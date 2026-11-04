-- Inferred contract; see docs/inferred_ddl.md.
CREATE OR REPLACE TABLE BANKING_DW.ETL_LOG
(
    PROCEDURE_NAME         VARCHAR(128)        ,
    BATCH_ID               BIGINT              ,
    LOG_LEVEL              VARCHAR(10)         ,
    LOG_MESSAGE            VARCHAR(2000)       ,
    LOG_TS                 TIMESTAMP_NTZ(0)
);
