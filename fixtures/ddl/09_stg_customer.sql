-- Inferred contract; see docs/inferred_ddl.md.
CREATE MULTISET TABLE BANKING_DW.STG_CUSTOMER
(
    CUSTOMER_ID            INTEGER           NOT NULL,
    FIRST_NAME             VARCHAR(50)       NOT CASESPECIFIC NOT NULL,
    LAST_NAME              VARCHAR(50)       NOT CASESPECIFIC NOT NULL,
    DATE_OF_BIRTH          DATE              ,
    GENDER                 CHAR(1)           ,
    MARITAL_STATUS         CHAR(1)           ,
    EMAIL_ADDRESS          VARCHAR(100)      NOT CASESPECIFIC ,
    PHONE_NUMBER           VARCHAR(20)       ,
    ADDRESS_LINE_1         VARCHAR(100)      NOT CASESPECIFIC ,
    ADDRESS_LINE_2         VARCHAR(100)      NOT CASESPECIFIC ,
    CITY                   VARCHAR(50)       NOT CASESPECIFIC ,
    STATE_PROVINCE         VARCHAR(50)       NOT CASESPECIFIC ,
    POSTAL_CODE            VARCHAR(10)       ,
    COUNTRY_CODE           CHAR(3)           NOT CASESPECIFIC ,
    CUSTOMER_SEGMENT       VARCHAR(20)       NOT CASESPECIFIC ,
    RISK_SCORE             DECIMAL(5,2)      ,
    CREDIT_RATING          CHAR(3)           ,
    KYC_STATUS             VARCHAR(15)       NOT CASESPECIFIC
)
PRIMARY INDEX (CUSTOMER_ID);
