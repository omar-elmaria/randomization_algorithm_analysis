# Step 1: Import packages
from google.cloud import bigquery
from google.cloud import bigquery_storage
import pandas as pd
import numpy as np
import pingouin as pg
import subprocess
import datetime as dt
from datetime import timedelta
import uuid
import random
import warnings
import os
warnings.filterwarnings(action="ignore")
import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s  - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    filename="analysis_script_logs.log"
)

##-----------------------------------------------------END OF STEP 1-----------------------------------------------------##

# Step 2: Define some input parameters
sb_window_size = [2, 3, 4] # 2, 3, and 4 hours
num_variants = [2, 3, 4, 5, 6, 7] # 2, 3, 4, 5, 6, and 7 variants 
exp_length = [7, 14, 21, 28] # 7, 14, 21, and 28 days
col_list = [
    'actual_df_paid_by_customer', 'gfv_local', 'gmv_local', 'commission_local', 'joker_vendor_fee_local', # Customer KPIs (1)
    'sof_local', 'service_fee_local', 'revenue_local', 'delivery_costs_local', 'gross_profit_local', # Customer KPIs (2)
    'dps_mean_delay', 'delivery_distance_m', 'actual_DT' # Logistics KPIs
]
entity_asa_zone_dict = [ # Define a list of dictionaries containing the entity IDs, ASA IDs, and zone names that will be used in the analysis
    # SG
    {"entity_id": "FP_SG", "asa_id": 559, "zone_names": ["Bukitpanjang", "Jurongwest", "Woodlands"], "zone_group_identifier": "zg_1"},
    {"entity_id": "FP_SG", "asa_id": 560, "zone_names": ["Far_east", "Jurong east"], "zone_group_identifier": "zg_2"},

    # HK
    {"entity_id": "FP_HK", "asa_id": 402, "zone_names": ["To kwa wan rider", "Kowloon city rider", "Lai chi kok rider"], "zone_group_identifier": "zg_3"},
    {"entity_id": "FP_HK", "asa_id": 406, "zone_names": ["Ma liu shui rider", "Kwai chung rider", "Sai kung rider", "Sheung shui rider", "Tai po rider", "Tai wai rider", "Tin shui wai rider", "Tsing yi rider", "Tsuen wan rider", "Tuen mun rider", "Tun chung rider", "Yuen long rider"], "zone_group_identifier": "zg_4"},
    {"entity_id": "FP_HK", "asa_id": 398, "zone_names": ["Admiralty cwb rider", "Happy valley cwb rider", "Kennedy town rider", "Quarry bay rider"], "zone_group_identifier": "zg_5"},

    # PH
    {"entity_id": "FP_PH", "asa_id": 496, "zone_names": ["South alabang atc", "Paranaque", "North Ias pinas", "North alabang atc", "Bf homes"], "zone_group_identifier": "zg_6"},
    {"entity_id": "FP_PH", "asa_id": 525, "zone_names": ["Bacoor north", "Tagaytay", "Dasmarinas", "Imus"], "zone_group_identifier": "zg_7"},
    {"entity_id": "FP_PH", "asa_id": 528, "zone_names": ["Antipolo north", "Malabon", "Sjdm", "Valenzuela"], "zone_group_identifier": "zg_8"},
    {"entity_id": "FP_PH", "asa_id": 508, "zone_names": ["Makati", "Pasay"], "zone_group_identifier": "zg_9"}
]
zone_groups = [i["zone_group_identifier"] for i in entity_asa_zone_dict]
sig_level = 0.05

##-----------------------------------------------------END OF STEP 2-----------------------------------------------------##

# Step 3: Instantiate a BQ client and run the SQL query that pulls the historical data
client = bigquery.Client(project="logistics-data-staging-flat")
bqstorage_client = bigquery_storage.BigQueryReadClient()

# with open("sql_queries.sql", mode="r", encoding="utf-8") as f:
#     query = f.read()
#     f.close()

# client.query(query=query).result()

# Pull the data from the final table generated by the query
df = client.query("""SELECT * FROM `dh-logistics-product-ops.pricing.ab_test_individual_orders_augmented_randomization_algo_analysis`""")\
    .result()\
    .to_dataframe(bqstorage_client=bqstorage_client, progress_bar_type="tqdm")

##-----------------------------------------------------END OF STEP 3-----------------------------------------------------##

# Step 4: Create a new data frame with the combinations stipulated in the dictionary above
df_reduced = []
for i in entity_asa_zone_dict:
    df_iter = df[(df["entity_id"] == i["entity_id"]) & (df["asa_id"] == i["asa_id"]) & (df["zone_name"].isin(i["zone_names"]))]
    df_iter["zone_group_identifier"] = i["zone_group_identifier"]
    df_reduced.append(df_iter)

# Convert df_reduced to a dataframe
df_reduced = pd.concat(df_reduced)

# Add a new field to df_reduced showing a different format of "dps_sessionid_created_at_utc". We want to display the format followed by DPS, which is "%Y-%m-%dT%H:%M:%SZ"
df_reduced["dps_sessionid_created_at_utc_formatted"] = df_reduced["dps_sessionid_created_at_utc"]\
    .apply(lambda x: dt.datetime.strftime(x, "%Y-%m-%dT%H:%M:%SZ"))

df_reduced.reset_index(drop=True, inplace=True)

##-----------------------------------------------------END OF STEP 4-----------------------------------------------------##

# Step 5: The shell script that runs the randomization algorithm needs the starting time of the experiment as one of its input
# We define that as the minimum dps_session_start_timestamp per zone_group_identifier
df_min_max_dps_session_start_ts = df_reduced.groupby(["entity_id", "zone_group_identifier"])["dps_sessionid_created_at_utc_formatted"]\
    .agg(["min", "max"])\
    .reset_index()\
    .rename(columns={"min": "min_dps_session_start_ts", "max": "max_dps_session_start_ts"})

##-----------------------------------------------------END OF STEP 5-----------------------------------------------------##

# Step 6: Define a function that allocates variants to orders based on some input parameters
def var_allocation_func(zg_id, sb_window_size, num_variants, exp_start_time, input_file_name):
    # Delete all output CSV files if they exist
    output_csv_file_list = [i for i in os.listdir() if i.startswith("output")]
    if len(output_csv_file_list) > 0:
        for i in output_csv_file_list:
            os.remove(i)

    # Create a function that takes the zone_group_identifier and creates a CSV file called input_{zg_identifier}
    # This file contains the details necessary to run the randomization algorithm
    def input_csv_func(zg_identifier):
        df_stg = df_reduced[df_reduced["zone_group_identifier"] == zg_identifier][["platform_order_code", "zone_id", "dps_sessionid_created_at_utc_formatted"]]\
            .sort_values("dps_sessionid_created_at_utc_formatted")\
            .reset_index(drop=True)
        df_stg["dps_sessionid_created_at_utc_formatted"] = df_stg["dps_sessionid_created_at_utc_formatted"].apply(lambda x: str(x))
        df_stg.to_csv(input_file_name, index=False, header=False, date_format="str")

    # Invoke the function that creates the input file. Keep in mind that this overwrites the already existing input.csv file
    input_csv_func(zg_identifier=zg_id)

    # Change the CSV file "input.csv" to unix format
    subprocess.run(["dos2unix", input_file_name])

    # Invoke the Javascript function that allocates variants to orders
    subprocess.run([
        "sh",
        "./run-allocation.sh",
        "-w",
        sb_window_size,
        "-v",
        num_variants,
        "-t",
        exp_start_time,
        "-k",
        str(random.randint(1000, 2000)),
        "-s",
        str(uuid.uuid4()),
        "-f",
        input_file_name
    ])

##-----------------------------------------------------END OF STEP 6-----------------------------------------------------##

# Step 7: Create a function that gets the p-value for one simulation run. One simulation run entails one zg_id, sb_window_size, number_of_variants, and experiment length
def df_analysis_creator_func(zg_id, exp_length):
    # Read get the name of the output csv file
    csv_output_file_name = [i for i in os.listdir() if i.startswith("output")][0]

    # After the output.csv file is created, retrieve the variants from the output.csv file and join them to df_reduced
    df_variants = pd.read_csv(f"{csv_output_file_name}")
    df_analysis = df_reduced[df_reduced["zone_group_identifier"] == zg_id].copy() # Create a copy of df_reduced just for the zg_id being analysed
    df_analysis = pd.merge(left=df_analysis, right=df_variants, how="left", left_on="platform_order_code", right_on="OrderID")
    df_analysis.drop("OrderID", axis=1, inplace=True)

    ##-----------------------------------------------------SEPARATOR-----------------------------------------------------##

    # Add a column indicating the week number
    df_analysis["dps_session_created_date"] = df_analysis["dps_sessionid_created_at_utc"].apply(lambda x: x.date())
    # Change the KPI columns to numeric
    df_analysis[col_list] = df_analysis[col_list].apply(lambda x: pd.to_numeric(x))
    # Rename the column slotUID to time_zone_unit_id
    df_analysis.rename({"SlotID": "time_zone_unit_id"}, axis=1, inplace=True)

    ##-----------------------------------------------------SEPARATOR-----------------------------------------------------##

    # Create a conditions list
    start_date = df_analysis["dps_session_created_date"].min()
    conditions = [
        (df_analysis["dps_session_created_date"] >= start_date) & (df_analysis["dps_session_created_date"] <= start_date + timedelta(days=6)),
        (df_analysis["dps_session_created_date"] >= start_date + timedelta(days=7)) & (df_analysis["dps_session_created_date"] <= start_date + timedelta(days=13)),
        (df_analysis["dps_session_created_date"] >= start_date + timedelta(days=14)) & (df_analysis["dps_session_created_date"] <= start_date + timedelta(days=20)),
        (df_analysis["dps_session_created_date"] >= start_date + timedelta(days=21)) & (df_analysis["dps_session_created_date"] <= start_date + timedelta(days=27)),
    ]

    df_analysis["week_num"] = np.select(condlist=conditions, choicelist=["week_1", "week_2", "week_3", "week_4"])

    ##-----------------------------------------------------SEPARATOR-----------------------------------------------------##

    # Filter df_analysis based on exp_length
    df_analysis = df_analysis[df_analysis["day_num"] <= exp_length]

    ##-----------------------------------------------------SEPARATOR-----------------------------------------------------##

    # Calculate the "total" metrics and rename the column label to "df_per_order_metrics"
    df_analysis_tot = round(df_analysis.groupby(["time_zone_unit_id", "Variant"])[col_list[:-3]].sum(), 2)
    df_analysis_tot['order_count'] = df_analysis.groupby(["time_zone_unit_id", "Variant"])['platform_order_code'].nunique()
    df_analysis_tot = df_analysis_tot.rename_axis(['df_tot_metrics'], axis = 1)

    # Calculate the "total" metrics and rename the column label to "df_per_order_metrics"
    df_analysis_per_order_cust_kpis = df_analysis_tot.copy()

    for iter_col in df_analysis_per_order_cust_kpis.columns[:-1]:
        df_analysis_per_order_cust_kpis[iter_col] = round(df_analysis_per_order_cust_kpis[iter_col] / df_analysis_per_order_cust_kpis['order_count'], 4)

    df_analysis_per_order_log_kpis = round(df_analysis.groupby(["time_zone_unit_id", "Variant"])[col_list[-3:]].mean(), 2) 
    df_analysis_per_order = pd.concat([df_analysis_per_order_cust_kpis, df_analysis_per_order_log_kpis], axis = 1)
    df_analysis_per_order = df_analysis_per_order.rename_axis(['df_per_order_metrics'], axis = 1)

    # Reset the indices of the 
    df_analysis_tot = df_analysis_tot.reset_index()
    df_analysis_per_order = df_analysis_per_order.reset_index()

    return df_analysis, df_analysis_tot, df_analysis_per_order
    ##-----------------------------------------------------SEPARATOR-----------------------------------------------------##

# Step 8: Loop through every zone group ID, SB window size, number of variants, and experiment length to calculate the ANOVA p-value
counter = 1
pval_list_tot = []
pval_list_per_order = []
for zn in zone_groups: # Loop through all the zone group IDs
    for sb in sb_window_size: # Loop through all switchback window sizes
        for var in num_variants: # Loop through all variants
            for exp in exp_length: # Loop through all experiment lengths
                logging.info(f"Allocating the variants with parameters --> zone: {zn}, SB window size: {sb}, number of variants: {var}, experiment_length: {exp}...")
                var_allocation_func(
                    zg_id=zn,
                    sb_window_size=str(sb),
                    num_variants=str(var),
                    exp_start_time=str(df_min_max_dps_session_start_ts[df_min_max_dps_session_start_ts["zone_group_identifier"] == zn].reset_index()["min_dps_session_start_ts"].iloc[0]),
                    input_file_name="input.csv"
                ) # Run the variant allocation function. The output is a CSV file containing the variant allocations
                logging.info("Applying the df_analysis_creator_func that reads from the output CSV file and creates the various df_analysis data frames...")
                df_analysis, df_analysis_tot, df_analysis_per_order = df_analysis_creator_func(zg_id=zn, exp_length=exp) # Run the function that returns the data frames that can be used to compute p-values

                # Calculate the ANOVA p-value
                logging.info("Calculating the p-values for the different KPIs")
                for iter_col in df_analysis_per_order.columns[2:]: # Pick the columns from the data frame that has more columns
                    anova_pval_per_order = pg.welch_anova(dv=iter_col, between="Variant", data=df_analysis_per_order)["p-unc"].iloc[0].round(4)
                    try:
                        anova_pval_tot = pg.welch_anova(dv=iter_col, between="Variant", data=df_analysis_tot)["p-unc"].iloc[0].round(4)
                    except KeyError: # df_analysis_tot does not have the logistics KPIs, so it will generate an error that we handle with this try-except block
                        logging.info(f"Trying to calculate a p-value for {iter_col} from df_analysis_tot, which is not possible. Bypassing to avoid an error...")

                    # Create significance flags based on the p-values
                    if anova_pval_tot <= sig_level:
                        anova_sig_tot = "significant"
                    else:
                        anova_sig_tot = "insignificant"

                    if anova_pval_per_order <= sig_level:
                        anova_sig_per_order = "significant"
                    else:
                        anova_sig_per_order = "insignificant"
                
                    # Create the output dictionaries
                    output_dict_base = {
                        "sim_run_id": zn + "-" + str(sb) + "-window_size-" + str(var) + "-var_num-" + str(exp) + "-exp_length",
                        "zone_group": zn,
                        "sb_window_size": sb,
                        "num_variants": var,
                        "exp_length": exp,
                        "kpi": iter_col
                    }
                    output_dict_tot = output_dict_base.copy()
                    output_dict_per_order = output_dict_base.copy()
                    output_dict_tot.update({
                        "anova_pval": anova_pval_tot,
                        "anova_sig": anova_sig_tot,
                        "kpi_type": "tot"
                    })
                    output_dict_per_order.update({
                        "anova_pval": anova_pval_per_order,
                        "anova_sig": anova_sig_per_order,
                        "kpi_type": "per_order"
                    })

                    # Append the results to the empty lists created above
                    pval_list_tot.append(output_dict_tot)
                    pval_list_per_order.append(output_dict_per_order)

                # Mark end of p-value calculation
                logging.info(f"Finished calculating the p-values for iteration {counter} with parameters --> zone: {zn}, SB window size: {sb}, number of variants: {var}, experiment_length: {exp}...\n")
                counter += 1

# Convert df_pval_tot and df_pval_per_order to data frames
df_pval_tot = pd.DataFrame(pval_list_tot)
df_pval_per_order = pd.DataFrame(pval_list_per_order)
df_pval = pd.concat([df_pval_tot, df_pval_per_order[df_pval_per_order["kpi"] != "order_count"]])

##-----------------------------------------------------END OF STEP 8-----------------------------------------------------##

# Upload the data frame to big query
logging.info("Uploading the data to bigquery...")
job_config = bigquery.LoadJobConfig(
    schema = [
        bigquery.SchemaField("sim_run_id", "STRING"),
        bigquery.SchemaField("zone_group", "STRING"),
        bigquery.SchemaField("sb_window_size", "INT64"),
        bigquery.SchemaField("num_variants", "INT64"),
        bigquery.SchemaField("exp_length", "INT64"),
        bigquery.SchemaField("kpi", "STRING"),
        bigquery.SchemaField("anova_pval", "FLOAT64"),
        bigquery.SchemaField("anova_sig", "STRING"),
        bigquery.SchemaField("kpi_type", "STRING"),
    ]
)

# Set the job_config to overwrite the data in the table
job_config.write_disposition = bigquery.WriteDisposition.WRITE_TRUNCATE

# Upload the p-values data frame to BQ
client.load_table_from_dataframe(
    dataframe=df_pval.reset_index(drop=True),
    destination="dh-logistics-product-ops.pricing.df_pval_switchback_randomization_algo_analysis",
    job_config=job_config
).result()