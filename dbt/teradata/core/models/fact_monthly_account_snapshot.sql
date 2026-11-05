{{ config(alias='FACT_MONTHLY_ACCOUNT_SNAPSHOT') }}

with aggregates as (
SELECT
            ft.ACCOUNT_KEY,
            SUM(CASE WHEN ft.TRANSACTION_TYPE IN ('DEBIT', 'FEE')
                     THEN ABS(ft.TRANSACTION_AMOUNT) ELSE 0 END) AS TOTAL_DEBITS,
            SUM(CASE WHEN ft.TRANSACTION_TYPE IN ('CREDIT', 'INTEREST')
                     THEN ft.TRANSACTION_AMOUNT ELSE 0 END) AS TOTAL_CREDITS,
            SUM(CASE WHEN ft.TRANSACTION_TYPE IN ('DEBIT', 'FEE') THEN 1 ELSE 0 END) AS DEBIT_COUNT,
            SUM(CASE WHEN ft.TRANSACTION_TYPE IN ('CREDIT', 'INTEREST') THEN 1 ELSE 0 END) AS CREDIT_COUNT,
            SUM(CASE WHEN ft.TRANSACTION_TYPE = 'INTEREST' AND ft.TRANSACTION_AMOUNT > 0
                     THEN ft.TRANSACTION_AMOUNT ELSE 0 END) AS INTEREST_EARNED,
            SUM(CASE WHEN ft.TRANSACTION_TYPE = 'INTEREST' AND ft.TRANSACTION_AMOUNT < 0
                     THEN ABS(ft.TRANSACTION_AMOUNT) ELSE 0 END) AS INTEREST_CHARGED,
            SUM(CASE WHEN ft.TRANSACTION_TYPE = 'FEE'
                     THEN ABS(ft.TRANSACTION_AMOUNT) ELSE 0 END) AS FEES_CHARGED,
            MIN(ft.RUNNING_BALANCE) AS MIN_BALANCE,
            MAX(ft.RUNNING_BALANCE) AS MAX_BALANCE,
            AVG(ft.RUNNING_BALANCE) AS AVG_BALANCE,
            SUM(CASE WHEN ft.RUNNING_BALANCE < 0 THEN 1 ELSE 0 END) AS OVERDRAFT_DAYS
        FROM {{ ref('fact_transaction') }} ft
        WHERE ft.TRANSACTION_DATE BETWEEN date_trunc('month', {{ run_day() }}) AND {{ run_day() }}
        GROUP BY ft.ACCOUNT_KEY

), incoming as (

        SELECT
            {{ run_day() }} AS SNAPSHOT_DATE,
            to_number(to_char({{ run_day() }}, 'YYYYMM')) AS SNAPSHOT_MONTH_KEY,
            a.ACCOUNT_KEY,
            c.CUSTOMER_KEY,
            a.PRODUCT_ID,
            a.BRANCH_ID,
            coalesce(prev.CLOSING_BALANCE, 0) AS OPENING_BALANCE,
            coalesce(prev.CLOSING_BALANCE, 0)
                + coalesce(agg.TOTAL_CREDITS, 0)
                - coalesce(agg.TOTAL_DEBITS, 0) AS CLOSING_BALANCE,
            coalesce(agg.AVG_BALANCE, 0) AS AVERAGE_BALANCE,
            coalesce(agg.MIN_BALANCE, 0) AS MINIMUM_BALANCE,
            coalesce(agg.MAX_BALANCE, 0) AS MAXIMUM_BALANCE,
            coalesce(agg.TOTAL_DEBITS, 0) AS TOTAL_DEBITS,
            coalesce(agg.TOTAL_CREDITS, 0) AS TOTAL_CREDITS,
            coalesce(agg.DEBIT_COUNT, 0) AS DEBIT_COUNT,
            coalesce(agg.CREDIT_COUNT, 0) AS CREDIT_COUNT,
            coalesce(agg.INTEREST_EARNED, 0) AS INTEREST_EARNED,
            coalesce(agg.INTEREST_CHARGED, 0) AS INTEREST_CHARGED,
            coalesce(agg.FEES_CHARGED, 0) AS FEES_CHARGED,
            coalesce(agg.OVERDRAFT_DAYS, 0) AS DAYS_IN_OVERDRAFT,
            CASE WHEN agg.ACCOUNT_KEY IS NULL
                 THEN (datediff(day, date_trunc('month', {{ run_day() }}), {{ run_day() }}) + 1)
                 ELSE 0
            END AS DAYS_DORMANT,
            a.CURRENCY_CODE,
            {{ batch_id() }} AS ETL_BATCH_ID
        FROM {{ ref('dim_account') }} a
        LEFT JOIN {{ ref('dim_customer') }} c
            ON a.CUSTOMER_ID = c.CUSTOMER_ID
           AND c.CURRENT_FLAG = 'Y'
        LEFT JOIN aggregates agg
            ON a.ACCOUNT_KEY = agg.ACCOUNT_KEY
        LEFT JOIN {{ source('td_source', 'FACT_MONTHLY_ACCOUNT_SNAPSHOT') }} prev
            ON a.ACCOUNT_KEY = prev.ACCOUNT_KEY
           AND prev.SNAPSHOT_DATE = dateadd(month, -1, date_trunc('month', {{ run_day() }}))
        WHERE a.CURRENT_FLAG = 'Y'
          AND a.ACCOUNT_STATUS IN ('ACTIVE', 'DORMANT')

)
select
    cast(t.SNAPSHOT_DATE as DATE) as SNAPSHOT_DATE,
    cast(t.SNAPSHOT_MONTH_KEY as NUMBER(10,0)) as SNAPSHOT_MONTH_KEY,
    cast(t.ACCOUNT_KEY as NUMBER(19,0)) as ACCOUNT_KEY,
    cast(t.CUSTOMER_KEY as NUMBER(19,0)) as CUSTOMER_KEY,
    cast(t.PRODUCT_ID as NUMBER(10,0)) as PRODUCT_ID,
    cast(t.BRANCH_ID as NUMBER(10,0)) as BRANCH_ID,
    cast(case when s.ACCOUNT_KEY is not null then s.OPENING_BALANCE else t.OPENING_BALANCE end as DECIMAL(15,2)) as OPENING_BALANCE,
    cast(case when s.ACCOUNT_KEY is not null then s.CLOSING_BALANCE else t.CLOSING_BALANCE end as DECIMAL(15,2)) as CLOSING_BALANCE,
    cast(case when s.ACCOUNT_KEY is not null then s.AVERAGE_BALANCE else t.AVERAGE_BALANCE end as DECIMAL(15,2)) as AVERAGE_BALANCE,
    cast(case when s.ACCOUNT_KEY is not null then s.MINIMUM_BALANCE else t.MINIMUM_BALANCE end as DECIMAL(15,2)) as MINIMUM_BALANCE,
    cast(case when s.ACCOUNT_KEY is not null then s.MAXIMUM_BALANCE else t.MAXIMUM_BALANCE end as DECIMAL(15,2)) as MAXIMUM_BALANCE,
    cast(case when s.ACCOUNT_KEY is not null then s.TOTAL_DEBITS else t.TOTAL_DEBITS end as DECIMAL(15,2)) as TOTAL_DEBITS,
    cast(case when s.ACCOUNT_KEY is not null then s.TOTAL_CREDITS else t.TOTAL_CREDITS end as DECIMAL(15,2)) as TOTAL_CREDITS,
    cast(case when s.ACCOUNT_KEY is not null then s.DEBIT_COUNT else t.DEBIT_COUNT end as NUMBER(10,0)) as DEBIT_COUNT,
    cast(case when s.ACCOUNT_KEY is not null then s.CREDIT_COUNT else t.CREDIT_COUNT end as NUMBER(10,0)) as CREDIT_COUNT,
    cast(case when s.ACCOUNT_KEY is not null then s.INTEREST_EARNED else t.INTEREST_EARNED end as DECIMAL(12,2)) as INTEREST_EARNED,
    cast(case when s.ACCOUNT_KEY is not null then s.INTEREST_CHARGED else t.INTEREST_CHARGED end as DECIMAL(12,2)) as INTEREST_CHARGED,
    cast(case when s.ACCOUNT_KEY is not null then s.FEES_CHARGED else t.FEES_CHARGED end as DECIMAL(12,2)) as FEES_CHARGED,
    cast(case when s.ACCOUNT_KEY is not null then s.DAYS_IN_OVERDRAFT else t.DAYS_IN_OVERDRAFT end as NUMBER(5,0)) as DAYS_IN_OVERDRAFT,
    cast(case when s.ACCOUNT_KEY is not null then s.DAYS_DORMANT else t.DAYS_DORMANT end as NUMBER(5,0)) as DAYS_DORMANT,
    cast(t.CURRENCY_CODE as CHAR(3)) as CURRENCY_CODE,
    cast(t.BASE_CURRENCY_CLOSING as DECIMAL(15,2)) as BASE_CURRENCY_CLOSING,
    cast(case when s.ACCOUNT_KEY is not null then s.ETL_BATCH_ID else t.ETL_BATCH_ID end as NUMBER(19,0)) as ETL_BATCH_ID,
    cast(case when s.ACCOUNT_KEY is not null then {{ load_timestamp() }} else t.ETL_INSERT_TS end as TIMESTAMP_NTZ(0)) as ETL_INSERT_TS
from {{ source('td_source', 'FACT_MONTHLY_ACCOUNT_SNAPSHOT') }} t
left join incoming s on t.ACCOUNT_KEY = s.ACCOUNT_KEY and t.SNAPSHOT_MONTH_KEY = s.SNAPSHOT_MONTH_KEY
union all
select
    cast(s.SNAPSHOT_DATE as DATE) as SNAPSHOT_DATE,
    cast(s.SNAPSHOT_MONTH_KEY as NUMBER(10,0)) as SNAPSHOT_MONTH_KEY,
    cast(s.ACCOUNT_KEY as NUMBER(19,0)) as ACCOUNT_KEY,
    cast(s.CUSTOMER_KEY as NUMBER(19,0)) as CUSTOMER_KEY,
    cast(s.PRODUCT_ID as NUMBER(10,0)) as PRODUCT_ID,
    cast(s.BRANCH_ID as NUMBER(10,0)) as BRANCH_ID,
    cast(s.OPENING_BALANCE as DECIMAL(15,2)) as OPENING_BALANCE,
    cast(s.CLOSING_BALANCE as DECIMAL(15,2)) as CLOSING_BALANCE,
    cast(s.AVERAGE_BALANCE as DECIMAL(15,2)) as AVERAGE_BALANCE,
    cast(s.MINIMUM_BALANCE as DECIMAL(15,2)) as MINIMUM_BALANCE,
    cast(s.MAXIMUM_BALANCE as DECIMAL(15,2)) as MAXIMUM_BALANCE,
    cast(s.TOTAL_DEBITS as DECIMAL(15,2)) as TOTAL_DEBITS,
    cast(s.TOTAL_CREDITS as DECIMAL(15,2)) as TOTAL_CREDITS,
    cast(s.DEBIT_COUNT as NUMBER(10,0)) as DEBIT_COUNT,
    cast(s.CREDIT_COUNT as NUMBER(10,0)) as CREDIT_COUNT,
    cast(s.INTEREST_EARNED as DECIMAL(12,2)) as INTEREST_EARNED,
    cast(s.INTEREST_CHARGED as DECIMAL(12,2)) as INTEREST_CHARGED,
    cast(s.FEES_CHARGED as DECIMAL(12,2)) as FEES_CHARGED,
    cast(s.DAYS_IN_OVERDRAFT as NUMBER(5,0)) as DAYS_IN_OVERDRAFT,
    cast(s.DAYS_DORMANT as NUMBER(5,0)) as DAYS_DORMANT,
    cast(s.CURRENCY_CODE as CHAR(3)) as CURRENCY_CODE,
    cast(null as DECIMAL(15,2)) as BASE_CURRENCY_CLOSING,
    cast(s.ETL_BATCH_ID as NUMBER(19,0)) as ETL_BATCH_ID,
    cast({{ load_timestamp() }} as TIMESTAMP_NTZ(0)) as ETL_INSERT_TS
from incoming s
where not exists (
    select 1 from {{ source('td_source', 'FACT_MONTHLY_ACCOUNT_SNAPSHOT') }} t
    where t.ACCOUNT_KEY = s.ACCOUNT_KEY and t.SNAPSHOT_MONTH_KEY = s.SNAPSHOT_MONTH_KEY
)
