select 'dim_customer' as model_name from {{ ref('dim_customer') }} group by CUSTOMER_KEY having count(*) > 1
union all
select 'dim_account' as model_name from {{ ref('dim_account') }} group by ACCOUNT_KEY having count(*) > 1
union all
select 'dim_product' as model_name from {{ ref('dim_product') }} group by PRODUCT_ID having count(*) > 1
union all
select 'dim_branch' as model_name from {{ ref('dim_branch') }} group by BRANCH_ID having count(*) > 1
union all
select 'dim_date' as model_name from {{ ref('dim_date') }} group by DATE_KEY having count(*) > 1
union all
select 'fact_transaction' as model_name from {{ ref('fact_transaction') }} group by TRANSACTION_ID, ETL_BATCH_ID having count(*) > 1
union all
select 'fact_monthly_account_snapshot' as model_name from {{ ref('fact_monthly_account_snapshot') }} group by ACCOUNT_KEY, SNAPSHOT_MONTH_KEY having count(*) > 1
union all
select 'stg_transactions' as model_name from {{ ref('stg_transactions') }} group by TRANSACTION_ID having count(*) > 1
union all
select 'stg_customer' as model_name from {{ ref('stg_customer') }} group by CUSTOMER_ID having count(*) > 1
union all
select 'stg_transaction_errors' as model_name from {{ ref('stg_transaction_errors') }} group by TRANSACTION_ID, BATCH_ID having count(*) > 1
union all
select 'etl_batch_control' as model_name from {{ ref('etl_batch_control') }} group by BATCH_ID having count(*) > 1
union all
select 'etl_log' as model_name from {{ ref('etl_log') }} group by BATCH_ID, PROCEDURE_NAME, LOG_LEVEL, LOG_TS, LOG_MESSAGE having count(*) > 1
union all
select 'dim_exchange_rates' as model_name from {{ ref('dim_exchange_rates') }} group by FROM_CURRENCY, TO_CURRENCY, RATE_DATE having count(*) > 1
