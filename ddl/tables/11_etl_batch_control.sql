-- Inferred contract; see docs/inferred_ddl.md.
CREATE MULTISET TABLE BANKING_DW.ETL_BATCH_CONTROL
(
    BATCH_ID               BIGINT            NOT NULL,
    BATCH_DATE             DATE              ,
    BATCH_STATUS           VARCHAR(20)       ,
    START_TS               TIMESTAMP(0)      ,
    END_TS                 TIMESTAMP(0)
)
PRIMARY INDEX (BATCH_ID);
