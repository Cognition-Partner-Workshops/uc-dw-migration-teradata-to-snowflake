-- Inferred contract; see docs/inferred_ddl.md.
CREATE OR REPLACE TABLE BANKING_DW.ETL_BATCH_CONTROL
(
    BATCH_ID               BIGINT              NOT NULL,
    BATCH_DATE             DATE                ,
    BATCH_STATUS           VARCHAR(20)         ,
    START_TS               TIMESTAMP_NTZ(0)    ,
    END_TS                 TIMESTAMP_NTZ(0)
);
