-- Inferred contract; see docs/inferred_ddl.md.
CREATE OR REPLACE TABLE BANKING_DW.STG_CUSTOMER
(
    CUSTOMER_ID            INTEGER             NOT NULL,
    FIRST_NAME             VARCHAR(50)         COLLATE 'en-ci' NOT NULL,
    LAST_NAME              VARCHAR(50)         COLLATE 'en-ci' NOT NULL,
    DATE_OF_BIRTH          DATE                ,
    GENDER                 CHAR(1)             ,
    MARITAL_STATUS         CHAR(1)             ,
    EMAIL_ADDRESS          VARCHAR(100)        COLLATE 'en-ci' ,
    PHONE_NUMBER           VARCHAR(20)         ,
    ADDRESS_LINE_1         VARCHAR(100)        COLLATE 'en-ci' ,
    ADDRESS_LINE_2         VARCHAR(100)        COLLATE 'en-ci' ,
    CITY                   VARCHAR(50)         COLLATE 'en-ci' ,
    STATE_PROVINCE         VARCHAR(50)         COLLATE 'en-ci' ,
    POSTAL_CODE            VARCHAR(10)         ,
    COUNTRY_CODE           CHAR(3)             COLLATE 'en-ci' ,
    CUSTOMER_SEGMENT       VARCHAR(20)         COLLATE 'en-ci' ,
    RISK_SCORE             DECIMAL(5,2)        ,
    CREDIT_RATING          CHAR(3)             ,
    KYC_STATUS             VARCHAR(15)         COLLATE 'en-ci'
);
