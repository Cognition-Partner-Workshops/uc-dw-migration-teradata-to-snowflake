{{ config(alias='DIM_CUSTOMER') }}

with changed as (
    select distinct t.CUSTOMER_ID
    from {{ source('td_source', 'DIM_CUSTOMER') }} t
    join {{ ref('stg_customer') }} s on t.CUSTOMER_ID = s.CUSTOMER_ID
    where t.CURRENT_FLAG = 'Y' and (s.CUSTOMER_SEGMENT <> t.CUSTOMER_SEGMENT
            or s.RISK_SCORE <> t.RISK_SCORE
            or s.CREDIT_RATING <> t.CREDIT_RATING
            or s.KYC_STATUS <> t.KYC_STATUS
            or s.ADDRESS_LINE_1 <> t.ADDRESS_LINE_1
            or s.CITY <> t.CITY
            or s.STATE_PROVINCE <> t.STATE_PROVINCE
            or s.POSTAL_CODE <> t.POSTAL_CODE
            or s.MARITAL_STATUS <> t.MARITAL_STATUS
            or coalesce(s.PHONE_NUMBER, '') <> coalesce(t.PHONE_NUMBER, '')
            or coalesce(s.EMAIL_ADDRESS, '') <> coalesce(t.EMAIL_ADDRESS, ''))
), expired as (
    select
    cast(t.CUSTOMER_ID as NUMBER(10,0)) as CUSTOMER_ID,
    cast(t.CUSTOMER_KEY as NUMBER(19,0)) as CUSTOMER_KEY,
    cast(t.FIRST_NAME as VARCHAR(50)) as FIRST_NAME,
    cast(t.LAST_NAME as VARCHAR(50)) as LAST_NAME,
    cast(t.DATE_OF_BIRTH as DATE) as DATE_OF_BIRTH,
    cast(t.GENDER as CHAR(1)) as GENDER,
    cast(t.MARITAL_STATUS as CHAR(1)) as MARITAL_STATUS,
    cast(t.EMAIL_ADDRESS as VARCHAR(100)) as EMAIL_ADDRESS,
    cast(t.PHONE_NUMBER as VARCHAR(20)) as PHONE_NUMBER,
    cast(t.ADDRESS_LINE_1 as VARCHAR(100)) as ADDRESS_LINE_1,
    cast(t.ADDRESS_LINE_2 as VARCHAR(100)) as ADDRESS_LINE_2,
    cast(t.CITY as VARCHAR(50)) as CITY,
    cast(t.STATE_PROVINCE as VARCHAR(50)) as STATE_PROVINCE,
    cast(t.POSTAL_CODE as VARCHAR(10)) as POSTAL_CODE,
    cast(t.COUNTRY_CODE as CHAR(3)) as COUNTRY_CODE,
    cast(t.CUSTOMER_SEGMENT as VARCHAR(20)) as CUSTOMER_SEGMENT,
    cast(t.RISK_SCORE as DECIMAL(5,2)) as RISK_SCORE,
    cast(t.CREDIT_RATING as CHAR(3)) as CREDIT_RATING,
    cast(t.KYC_STATUS as VARCHAR(15)) as KYC_STATUS,
    cast(t.ONBOARDING_DATE as DATE) as ONBOARDING_DATE,
    cast(t.LAST_REVIEW_DATE as DATE) as LAST_REVIEW_DATE,
    cast(t.IS_ACTIVE as NUMBER(5,0)) as IS_ACTIVE,
    cast(t.EFFECTIVE_FROM as TIMESTAMP_NTZ(0)) as EFFECTIVE_FROM,
    cast(case when ch.CUSTOMER_ID is not null and t.CURRENT_FLAG = 'Y' then {{ load_timestamp() }} else t.EFFECTIVE_TO end as TIMESTAMP_NTZ(0)) as EFFECTIVE_TO,
    cast(case when ch.CUSTOMER_ID is not null and t.CURRENT_FLAG = 'Y' then 'N' else t.CURRENT_FLAG end as CHAR(1)) as CURRENT_FLAG,
    cast(case when ch.CUSTOMER_ID is not null and t.CURRENT_FLAG = 'Y' then {{ batch_id() }} else t.ETL_BATCH_ID end as NUMBER(19,0)) as ETL_BATCH_ID,
    cast(t.ETL_INSERT_TS as TIMESTAMP_NTZ(0)) as ETL_INSERT_TS,
    cast(case when ch.CUSTOMER_ID is not null and t.CURRENT_FLAG = 'Y' then {{ load_timestamp() }} else t.ETL_UPDATE_TS end as TIMESTAMP_NTZ(0)) as ETL_UPDATE_TS
    from {{ source('td_source', 'DIM_CUSTOMER') }} t left join changed ch on t.CUSTOMER_ID = ch.CUSTOMER_ID
), candidates as (
    select s.*, coalesce(e.ONBOARDING_DATE, {{ run_day() }}) as ONBOARDING_DATE
    from {{ ref('stg_customer') }} s
    left join expired e on s.CUSTOMER_ID = e.CUSTOMER_ID and e.CURRENT_FLAG = 'N'
    where s.CUSTOMER_ID not in (select CUSTOMER_ID from expired where CURRENT_FLAG = 'Y')
    qualify row_number() over (partition by e.CUSTOMER_ID order by e.EFFECTIVE_TO desc nulls last, s.CUSTOMER_ID, e.CUSTOMER_KEY) = 1
)
select * from expired
union all
select
    cast(s.CUSTOMER_ID as NUMBER(10,0)) as CUSTOMER_ID,
    cast((select max(CUSTOMER_KEY) from {{ source('td_source', 'DIM_CUSTOMER') }}) + row_number() over (order by s.CUSTOMER_ID) as NUMBER(19,0)) as CUSTOMER_KEY,
    cast(s.FIRST_NAME as VARCHAR(50)) as FIRST_NAME,
    cast(s.LAST_NAME as VARCHAR(50)) as LAST_NAME,
    cast(s.DATE_OF_BIRTH as DATE) as DATE_OF_BIRTH,
    cast(s.GENDER as CHAR(1)) as GENDER,
    cast(s.MARITAL_STATUS as CHAR(1)) as MARITAL_STATUS,
    cast(s.EMAIL_ADDRESS as VARCHAR(100)) as EMAIL_ADDRESS,
    cast(s.PHONE_NUMBER as VARCHAR(20)) as PHONE_NUMBER,
    cast(s.ADDRESS_LINE_1 as VARCHAR(100)) as ADDRESS_LINE_1,
    cast(s.ADDRESS_LINE_2 as VARCHAR(100)) as ADDRESS_LINE_2,
    cast(s.CITY as VARCHAR(50)) as CITY,
    cast(s.STATE_PROVINCE as VARCHAR(50)) as STATE_PROVINCE,
    cast(s.POSTAL_CODE as VARCHAR(10)) as POSTAL_CODE,
    cast(coalesce(s.COUNTRY_CODE, 'NOR') as CHAR(3)) as COUNTRY_CODE,
    cast(s.CUSTOMER_SEGMENT as VARCHAR(20)) as CUSTOMER_SEGMENT,
    cast(s.RISK_SCORE as DECIMAL(5,2)) as RISK_SCORE,
    cast(s.CREDIT_RATING as CHAR(3)) as CREDIT_RATING,
    cast(s.KYC_STATUS as VARCHAR(15)) as KYC_STATUS,
    cast(s.ONBOARDING_DATE as DATE) as ONBOARDING_DATE,
    cast({{ run_day() }} as DATE) as LAST_REVIEW_DATE,
    cast(1 as NUMBER(5,0)) as IS_ACTIVE,
    cast({{ load_timestamp() }} as TIMESTAMP_NTZ(0)) as EFFECTIVE_FROM,
    cast(to_timestamp_ntz('9999-12-31 23:59:59') as TIMESTAMP_NTZ(0)) as EFFECTIVE_TO,
    cast('Y' as CHAR(1)) as CURRENT_FLAG,
    cast({{ batch_id() }} as NUMBER(19,0)) as ETL_BATCH_ID,
    cast({{ load_timestamp() }} as TIMESTAMP_NTZ(0)) as ETL_INSERT_TS,
    cast({{ load_timestamp() }} as TIMESTAMP_NTZ(0)) as ETL_UPDATE_TS
from candidates s
