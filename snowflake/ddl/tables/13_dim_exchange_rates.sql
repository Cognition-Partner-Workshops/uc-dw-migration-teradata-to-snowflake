-- Inferred contract; see docs/inferred_ddl.md.
CREATE OR REPLACE TABLE BANKING_DW.DIM_EXCHANGE_RATES
(
    FROM_CURRENCY          CHAR(3)             COLLATE 'en-ci' NOT NULL,
    TO_CURRENCY            CHAR(3)             COLLATE 'en-ci' NOT NULL,
    RATE_DATE              DATE                NOT NULL,
    EXCHANGE_RATE          DECIMAL(12,6)
);
