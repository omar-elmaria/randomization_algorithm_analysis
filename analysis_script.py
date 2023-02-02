# Step 1: Import packages
from google.cloud import bigquery
from google.cloud import bigquery_storage
import pandas as pd
import numpy as np
import subprocess
import scipy.stats
import datetime as dt
from datetime import datetime, timedelta
import warnings
import datetime
warnings.filterwarnings(action="ignore")
import uuid
import random

# Step 2: Instantiate a BQ client and run the SQL query that pulls the historical data
client = bigquery.Client(project="logistics-data-staging-flat")
bqstorage_client = bigquery_storage.BigQueryReadClient()

with open("sql_queries.sql", mode="r", encoding="utf-8") as f:
    query = f.read()
    f.close()

client.query(query=query).result()

# Step 3: Pull the data from the final table generated by the query
df = client.query("""SELECT * FROM `dh-logistics-product-ops.pricing.ab_test_individual_orders_augmented_randomization_algo_analysis`""")\
    .result()\
    .to_dataframe(bqstorage_client=bqstorage_client, progress_bar_type="tqdm")

# Step 4: Define a list of dictionaries containing the entity IDs, ASA IDs, and zone names that will be used in the analysis
entity_asa_zone_dict = [
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

# Step 5: Create a new data frame with the combinations stipulated in the dictionary above
df_reduced = []
for i in entity_asa_zone_dict:
    df_iter = df[(df["entity_id"] == i["entity_id"]) & (df["asa_id"] == i["asa_id"]) & (df["zone_name"].isin(i["zone_names"]))]
    df_iter["zone_group_identifier"] = i["zone_group_identifier"]
    df_reduced.append(df_iter)

df_reduced = pd.concat(df_reduced)
# Add a new field to df_reduced showing a different format of "dps_sessionid_created_at_utc". We want to display the format followed by DPS, which is "%Y-%m-%dT%H:%M:%SZ"
df_reduced["dps_sessionid_created_at_utc_formatted"] = df_reduced["dps_sessionid_created_at_utc"]\
    .apply(lambda x: pd.to_datetime(dt.datetime.strftime(x, "%Y-%m-%dT%H:%M:%SZ")))

df_reduced.reset_index(drop=True, inplace=True)

# Step 6.1: The shell script that runs the randomization algorithm needs the starting time of the experiment as one of its input
# We define that as the minimum dps_session_start_timestamp per zone_group_identifier
df_min_max_dps_session_start_ts = df_reduced.groupby(["entity_id", "zone_group_identifier"])["dps_sessionid_created_at_utc_formatted"]\
    .agg(["min", "max"])\
    .reset_index()\
    .rename(columns={"min": "min_dps_session_start_ts", "max": "max_dps_session_start_ts"})

# Define a function that allocates variants to orders based on some input parameters
def var_allocation_func(zg_id, sb_window_size, num_variants, exp_start_time):
    # Create a function that takes the zone_group_identifier and creates a CSV file called input_{zg_identifier}
    # This file contains the details necessary to run the randomization algorithm
    def input_csv_func(zg_identifier):
        df_stg = df_reduced[df_reduced["zone_group_identifier"] == zg_identifier][["platform_order_code", "zone_id", "dps_sessionid_created_at_utc"]].reset_index(drop=True)
        df_stg["dps_sessionid_created_at_utc_formatted"] = df_stg["dps_sessionid_created_at_utc_formatted"].apply(lambda x: str(x))
        df_stg.to_csv(f"input.csv", index=False, header=False, date_format="str")
    
    # Invoke the function that creates the input file. Keep in mind that this overwrites the already existing input.csv file
    input_csv_func(zg_identifier=zg_id)

    # Change the CSV file "input.csv" to unix format
    subprocess.run(["dos2unix", "input.csv"])

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
        str(uuid.uuid4())    
    ])

# Create a function that gives a random UUID to each time interval. Note: This part will be removed once the UUID functionality is incorporated in the JS function
def hr_interval_date_func_random(test_start, test_length, sb_interval):
    def hr_interval_func_random(sb_interval_2):
        bins = int(24 / sb_interval_2) # The number of bins by which we will divide the range from 0 to 24. A 2-hour switchback interval will have 12 bin --> [0, 2), [2, 4), [4, 6), ... [22, 24)
        if sb_interval_2 >= 1:
            end_of_range = 25
        elif sb_interval_2 == 0.5:
            end_of_range = 24.5
        elif sb_interval_2 == 0.25:
            end_of_range = 24.25
        df_mapping = pd.DataFrame(data = {
                'hr_interval': list(pd.cut(np.arange(0, end_of_range, sb_interval_2), bins = bins, right = False)) # The bins should be closed from the left
            }
        )

        # Drop duplicates
        df_mapping.drop_duplicates(inplace = True)

        unique_intervals = df_mapping['hr_interval'].unique()

        rnd_id_list = [] # Create the full list that the rng.choice would choose from
        for i in range(1, len(unique_intervals) + 1):
            rnd_id_list.append(uuid.uuid4())

        rng = np.random.default_rng()
        df_mapping['treatment_status_by_time'] = rng.choice(rnd_id_list, replace = False, axis = 0, size = len(df_mapping))
        return df_mapping
        
    m = []
    date_iter = test_start # Start date of the test in datetime format
    for i in range(0, test_length): # The length of a test in days
        y = hr_interval_func_random(sb_interval_2=sb_interval) # The switchback window size
        y['sim_run'] = i + 1
        y['created_date_local'] = date_iter
        date_iter = date_iter + timedelta(days = 1)
        m.append(y)

    m = pd.concat(m)
    m.reset_index(inplace = True, drop = True)
    return m

# Create a function that gets the p-value for one simulation run. One simulation run entails one zg_id, sb_window_size, number_of_variants, and experiment length
def p_val_func(zg_id, exp_length, sb_window_size):
    # After the output.csv file is created, retrieve the variants from the output.csv file and join them to df_reduced
    df_variants = pd.read_csv("output.csv")
    df_analysis = df_reduced["zone_group_identifier" == zg_id].copy() # Create a copy of df_reduced just for the zg_id being analysed
    df_analysis = pd.merge(left=df_analysis, right=df_variants, how="left", left_on="platform_order_code", right_on="OrderID")
    df_analysis.drop("OrderID", axis=1, inplace=True)

    # Add a column indicating the week number
    df_analysis["created_date_local"] = df_analysis["order_placed_at_local"].apply(lambda x: pd.to_datetime(datetime.date(x)))

    conditions = [
        (df_analysis["created_date_local"] >= "2023-01-01") & (df_analysis["created_date_local"] <= "2023-01-07"),
        (df_analysis["created_date_local"] >= "2023-01-08") & (df_analysis["created_date_local"] <= "2023-01-14"),
        (df_analysis["created_date_local"] >= "2023-01-15") & (df_analysis["created_date_local"] <= "2023-01-21"),
        (df_analysis["created_date_local"] >= "2023-01-22") & (df_analysis["created_date_local"] <= "2023-01-28"),
    ]

    df_analysis["week_num"] = np.select(condlist=conditions, choicelist=["week_1", "week_2", "week_3", "week_4"])

    # Filter df_analysis based on exp_length
    df_analysis = df_analysis[df_analysis["day_num"] <= exp_length]

    # Create the data frame containing the random UUIDs for each time interval
    df_mapping = hr_interval_date_func_random(test_start=df_analysis["order_placed_at_local"].min().date(), test_length=exp_length, sb_interval=sb_window_size)

    # Merge the random UUIDs with df_analysis. Note: This part will be removed once the UUID functionality is incorporated in the JS function
    df_analysis = pd.merge(left = df_analysis, right = df_mapping, how = 'left', on = ['hr_interval', 'created_date_local'])