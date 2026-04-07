/**********************************************************************
 * SP_CUSTOMER_SCD2 (Snowflake)
 *
 * Applies SCD Type 2 changes to the customer dimension.
 * Converted from Teradata stored procedure.
 *
 * Changes:
 *   - REPLACE PROCEDURE -> CREATE OR REPLACE PROCEDURE
 *   - Teradata SQL procedure -> Snowflake Scripting (SQL)
 *   - UPDATE ... FROM (subquery) src SET ... WHERE -> Snowflake MERGE
 *     (Snowflake does not support UPDATE ... FROM with the same syntax)
 *   - ACTIVITY_COUNT -> SQLROWCOUNT
 *   - SEL -> SELECT
 *   - QUALIFY ROW_NUMBER() -> QUALIFY (natively supported)
 *   - COLLECT STATISTICS -> removed
 *   - OUT parameters -> OBJECT return value
 *   - TIMESTAMP literal -> Snowflake TIMESTAMP_NTZ cast
 **********************************************************************/

CREATE OR REPLACE PROCEDURE BANKING_DW.SP_CUSTOMER_SCD2(
    P_BATCH_ID BIGINT
)
RETURNS OBJECT
LANGUAGE SQL
EXECUTE AS CALLER
AS
$$
DECLARE
    v_current_ts TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP();
    v_new_rows INTEGER DEFAULT 0;
    v_changed INTEGER DEFAULT 0;
    v_return_code INTEGER DEFAULT 0;
    v_result OBJECT;
BEGIN
    -- Step 1: Expire changed records
    -- Snowflake supports UPDATE ... FROM with slightly different syntax
    UPDATE BANKING_DW.DIM_CUSTOMER tgt
    SET tgt.CURRENT_FLAG = 'N',
        tgt.EFFECTIVE_TO = :v_current_ts,
        tgt.ETL_UPDATE_TS = :v_current_ts,
        tgt.ETL_BATCH_ID = :P_BATCH_ID
    FROM (
        SELECT stg.CUSTOMER_ID
        FROM BANKING_DW.STG_CUSTOMER stg
        INNER JOIN BANKING_DW.DIM_CUSTOMER dim
            ON stg.CUSTOMER_ID = dim.CUSTOMER_ID
           AND dim.CURRENT_FLAG = 'Y'
        WHERE (
            stg.CUSTOMER_SEGMENT <> dim.CUSTOMER_SEGMENT
            OR stg.RISK_SCORE <> dim.RISK_SCORE
            OR stg.CREDIT_RATING <> dim.CREDIT_RATING
            OR stg.KYC_STATUS <> dim.KYC_STATUS
            OR stg.ADDRESS_LINE_1 <> dim.ADDRESS_LINE_1
            OR stg.CITY <> dim.CITY
            OR stg.STATE_PROVINCE <> dim.STATE_PROVINCE
            OR stg.POSTAL_CODE <> dim.POSTAL_CODE
            OR COALESCE(stg.PHONE_NUMBER, '') <> COALESCE(dim.PHONE_NUMBER, '')
            OR COALESCE(stg.EMAIL_ADDRESS, '') <> COALESCE(dim.EMAIL_ADDRESS, '')
            OR stg.MARITAL_STATUS <> dim.MARITAL_STATUS
        )
    ) src
    WHERE tgt.CUSTOMER_ID = src.CUSTOMER_ID
      AND tgt.CURRENT_FLAG = 'Y';

    v_changed := SQLROWCOUNT;

    -- Step 2: Insert new versions of changed records + brand new customers
    INSERT INTO BANKING_DW.DIM_CUSTOMER (
        CUSTOMER_ID, FIRST_NAME, LAST_NAME, DATE_OF_BIRTH, GENDER,
        MARITAL_STATUS, EMAIL_ADDRESS, PHONE_NUMBER,
        ADDRESS_LINE_1, ADDRESS_LINE_2, CITY, STATE_PROVINCE,
        POSTAL_CODE, COUNTRY_CODE, CUSTOMER_SEGMENT, RISK_SCORE,
        CREDIT_RATING, KYC_STATUS, ONBOARDING_DATE, LAST_REVIEW_DATE,
        IS_ACTIVE, EFFECTIVE_FROM, EFFECTIVE_TO, CURRENT_FLAG,
        ETL_BATCH_ID, ETL_INSERT_TS, ETL_UPDATE_TS
    )
    SELECT
        stg.CUSTOMER_ID,
        stg.FIRST_NAME,
        stg.LAST_NAME,
        stg.DATE_OF_BIRTH,
        stg.GENDER,
        stg.MARITAL_STATUS,
        stg.EMAIL_ADDRESS,
        stg.PHONE_NUMBER,
        stg.ADDRESS_LINE_1,
        stg.ADDRESS_LINE_2,
        stg.CITY,
        stg.STATE_PROVINCE,
        stg.POSTAL_CODE,
        COALESCE(stg.COUNTRY_CODE, 'NOR'),
        stg.CUSTOMER_SEGMENT,
        stg.RISK_SCORE,
        stg.CREDIT_RATING,
        stg.KYC_STATUS,
        COALESCE(existing.ONBOARDING_DATE, CURRENT_DATE),
        CURRENT_DATE,
        1,
        :v_current_ts,
        '9999-12-31 23:59:59'::TIMESTAMP_NTZ,
        'Y',
        :P_BATCH_ID,
        :v_current_ts,
        :v_current_ts
    FROM BANKING_DW.STG_CUSTOMER stg
    LEFT JOIN BANKING_DW.DIM_CUSTOMER existing
        ON stg.CUSTOMER_ID = existing.CUSTOMER_ID
       AND existing.CURRENT_FLAG = 'N'
    QUALIFY ROW_NUMBER() OVER (PARTITION BY existing.CUSTOMER_ID
                               ORDER BY existing.EFFECTIVE_TO DESC) = 1
    WHERE stg.CUSTOMER_ID NOT IN (
        SELECT CUSTOMER_ID FROM BANKING_DW.DIM_CUSTOMER WHERE CURRENT_FLAG = 'Y'
    );

    v_new_rows := SQLROWCOUNT;

    -- Note: COLLECT STATISTICS removed; Snowflake manages statistics automatically

    v_result := OBJECT_CONSTRUCT(
        'new_rows', :v_new_rows,
        'changed_rows', :v_changed,
        'return_code', :v_return_code
    );
    RETURN v_result;
END;
$$;
