-- Continue trying to get link the target groups to orders
-- Step 0: Declare inputs
DECLARE entity_id_var ARRAY <STRING>;
DECLARE start_date_var, end_date_var DATE;
DECLARE asa_ids ARRAY <INT64>;
SET entity_id_var = ['FP_SG', 'FP_PH', 'FP_HK'];
SET (start_date_var, end_date_var) = (DATE('2023-01-01'), DATE('2023-01-28')); 
SET asa_ids = [
  559, -- SG: Restaurants [IWD] - Tier 1 (3 zones --> Bukitpanjang, Jurongwest, Woodlands)
  560, -- SG: Restaurants [IWD] - Tier 2 (2 zones --> Far_east, Jurong east)

  402, -- HK: 20221103_Restaurants_KL3 (3 zones --> To kwa wan rider, Kowloon city rider, Lai chi kok rider)
  406, -- HK: 20221103_Restaurants_NT4 (12 zones --> Ma liu shui rider, Kwai chung rider, Sai kung rider, Sheung shui rider, Tai po rider, Tai wai rider, Tin shui wai rider, Tsing yi rider, Tsuen wan rider, Tuen mun rider, Tun chung rider, Yuen long rider)
  398, -- HK: 20221103_Restaurants_HK3 (4 zones --> Admiralty cwb rider, Happy valley cwb rider, Kennedy town rider, Quarry bay rider)

  496, -- PH: Resto - All - South alabang atc, Paranaque, North las pinas, North alabang atc, Bf homes MOV 129 (5 zones --> South alabang atc, Paranaque, North Ias pinas, North alabang atc, Bf homes)
  525, -- PH: Resto - All - Bacoor north, Dasma, Imus, Tagaytay (4 zones --> Bacoor north, Tagaytay, Dasmarinas, Imus)
  528, -- PH: Resto - All - Antipolo north, Malabon, Sjdm, Valenzuela (4 zones --> Antipolo north, Malabon, Sjdm, Valenzuela)
  508 -- PH: Resto - All - Makati, Pasay (2 zones --> Makati and Pasay)
];

-- Step 1: Extract the geo data 
CREATE OR REPLACE TABLE `dh-logistics-product-ops.pricing.ab_test_geo_data_randomization_algo_analysis` AS
SELECT
    p.entity_id,
    co.country_code,
    ci.name AS city_name,
    ci.id AS city_id,
    zo.shape AS zone_shape, 
    zo.name AS zone_name,
    zo.id AS zone_id
FROM `fulfillment-dwh-production.cl.countries` co
LEFT JOIN UNNEST(co.platforms) p
LEFT JOIN UNNEST(co.cities) ci
LEFT JOIN UNNEST(ci.zones) zo
WHERE TRUE 
    AND p.entity_id IN UNNEST(entity_id_var)
    AND co.country_code != 'dp-sg'
    AND zo.is_active -- Active city
    AND ci.is_active; -- Active zone

###----------------------------------------------------------END OF EXP SETUPS PART----------------------------------------------------------###

-- Step 2: Pull the business KPIs from dps_sessions_mapped_to_orders_v2
CREATE OR REPLACE TABLE `dh-logistics-product-ops.pricing.ab_test_individual_orders_randomization_algo_analysis` AS
WITH entities AS (
    SELECT
        ent.region,
        p.entity_id,
        ent.country_iso,
        ent.country_name,
FROM `fulfillment-dwh-production.cl.entities` ent
LEFT JOIN UNNEST(platforms) p
INNER JOIN (SELECT DISTINCT entity_id FROM `fulfillment-dwh-production.cl.dps_sessions_mapped_to_orders_v2`) dps ON p.entity_id = dps.entity_id 
WHERE p.entity_id IN UNNEST(entity_id_var)
)

SELECT 
    -- Identifiers and supplementary fields     
    -- Date and time
    a.created_date AS created_date_utc,
    a.order_placed_at AS order_placed_at_utc,
    a.order_placed_at_local,
    FORMAT_DATE('%A', DATE(order_placed_at_local)) AS dow_local,
    a.dps_sessionid_created_at AS dps_sessionid_created_at_utc,
    DATE_DIFF(DATE(a.order_placed_at_local), DATE(start_date_var), DAY) + 1 AS day_num, -- We add "+1" so that the first day gets a "1" not a "0"

    -- Location of order
    a.region,
    a.entity_id,
    a.country_code,
    a.city_name,
    a.city_id,
    a.zone_name,
    a.zone_id,
    zn.zone_shape,
    ST_GEOGPOINT(dwh.delivery_location.longitude, dwh.delivery_location.latitude) AS customer_location,

    -- Order/customer identifiers and session data
    start_date_var,
    a.order_id,
    a.platform_order_code,
    a.vendor_price_scheme_type,	-- The assignment type of the scheme to the vendor during the time of the order, such as 'Automatic', 'Manual', 'Campaign', and 'Country Fallback'.
    CAST(a.assignment_id AS INT64) AS asa_id,
    
    -- Vendor data and information on the delivery
    a.vendor_id,
    a.vertical_type,
    a.exchange_rate,

    -- Business KPIs (These are the components of profit)
    a.dps_delivery_fee_local,
    a.dps_surge_fee_local,
    a.dps_travel_time_fee_local,
    a.delivery_fee_local,
    a.commission_local,
    a.joker_vendor_fee_local,
    COALESCE(a.service_fee_local, 0) AS service_fee_local,
    IF(a.gfv_local - a.dps_minimum_order_value_local >= 0, 0, COALESCE(a.mov_customer_fee_local, (a.dps_minimum_order_value_local - a.gfv_local))) AS sof_local,
    a.delivery_costs_local,
    CASE
        WHEN ent.region IN ('Europe', 'Asia') THEN COALESCE( -- Get the delivery fee data of Pandora countries from Pandata tables
            pd.delivery_fee_local, 
            -- In 99 pct of cases, we won't need to use that fallback logic as pd.delivery_fee_local is reliable
            IF(a.is_delivery_fee_covered_by_discount = TRUE OR a.is_delivery_fee_covered_by_voucher = TRUE, 0, a.delivery_fee_local)
        )
        -- If the order comes from a non-Pandora country, use delivery_fee_local
        WHEN ent.region NOT IN ('Europe', 'Asia') THEN (CASE WHEN a.is_delivery_fee_covered_by_discount = TRUE OR a.is_delivery_fee_covered_by_voucher = TRUE THEN 0 ELSE a.delivery_fee_local END)
    END AS actual_df_paid_by_customer,
    a.gfv_local,
    a.gmv_local,

    -- Logistics KPIs
    a.mean_delay, -- A.K.A Average fleet delay --> Average lateness in minutes of an order at session start time (Used by dashboard, das, dps). This data point is only available for OD orders
    a.dps_mean_delay, -- A.K.A DPS Average fleet delay --> Average lateness in minutes of an order placed at this time coming from DPS service
    a.travel_time, -- The time (min) it takes rider to travel from vendor location coordinates to the customers. This data point is only available for OD orders.
    a.dps_travel_time, -- The calculated travel time in minutes from the vendor to customer coming from DPS
    a.delivery_distance_m, -- This is the "Delivery Distance" field in the overview tab in the AB test dashboard. The Manhattan distance (km) between the vendor location coordinates and customer location coordinates
    -- This distance doesn't take into account potential stacked deliveries, and it's not the travelled distance. This data point is only available for OD orders.
    a.actual_DT, -- The time it took to deliver the order. Measured from order creation until rider at customer. This data point is only available for OD orders.
FROM `fulfillment-dwh-production.cl.dps_sessions_mapped_to_orders_v2` a
LEFT JOIN `fulfillment-dwh-production.curated_data_shared_central_dwh.orders` dwh 
  ON TRUE 
    AND a.entity_id = dwh.global_entity_id
    AND a.platform_order_code = dwh.order_id -- There is no country_code field in this table
LEFT JOIN `fulfillment-dwh-production.pandata_curated.pd_orders` pd -- Contains info on the orders in Pandora countries
  ON TRUE 
    AND a.entity_id = pd.global_entity_id
    AND a.platform_order_code = pd.code 
    AND a.created_date = pd.created_date_utc -- There is no country_code field in this table
LEFT JOIN `dh-logistics-product-ops.pricing.ab_test_geo_data_randomization_algo_analysis` zn 
  ON TRUE 
    AND a.entity_id = zn.entity_id 
    AND a.country_code = zn.country_code
    AND a.zone_id = zn.zone_id
INNER JOIN entities ent ON a.entity_id = ent.entity_id -- Get the region associated with every entity_id
WHERE TRUE
  AND a.entity_id IN (SELECT DISTINCT entity_id FROM `dh-logistics-product-ops.pricing.ab_test_geo_data_randomization_algo_analysis`)
  AND a.created_date BETWEEN start_date_var AND end_date_var
  AND a.vendor_price_scheme_type = 'Automatic scheme'
  AND CAST(a.assignment_id AS INT64) IN UNNEST(asa_ids)
  AND a.is_sent -- Successful orders
  AND ST_CONTAINS(zn.zone_shape, ST_GEOGPOINT(dwh.delivery_location.longitude, dwh.delivery_location.latitude)); -- Filter for orders coming from the target zones

###----------------------------------------------------------SEPARATOR----------------------------------------------------------###

-- Step 7: Add revenue and profit
CREATE OR REPLACE TABLE `dh-logistics-product-ops.pricing.ab_test_individual_orders_augmented_randomization_algo_analysis` AS
SELECT
  a.*,
  -- Revenue and profit formulas
  actual_df_paid_by_customer + commission_local + joker_vendor_fee_local + service_fee_local + sof_local AS revenue_local,
  actual_df_paid_by_customer + commission_local + joker_vendor_fee_local + service_fee_local + sof_local - delivery_costs_local AS gross_profit_local,
FROM `dh-logistics-product-ops.pricing.ab_test_individual_orders_randomization_algo_analysis` a;