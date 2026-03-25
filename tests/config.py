"""
Configuration for Teradata-to-Snowflake migration data quality tests.

All credentials are read from environment variables. Never hardcode secrets.
"""

import os

# ---------------------------------------------------------------------------
# Snowflake connection settings
# ---------------------------------------------------------------------------
SNOWFLAKE_ACCOUNT = os.environ.get("SNOWFLAKE_ACCOUNT", "")
SNOWFLAKE_USER = os.environ.get("SNOWFLAKE_USER", "")
SNOWFLAKE_PASSWORD = os.environ.get("SNOWFLAKE_PASSWORD", "")
SNOWFLAKE_DATABASE = os.environ.get("SNOWFLAKE_DATABASE", "BANKING_DW")
SNOWFLAKE_WAREHOUSE = os.environ.get("SNOWFLAKE_WAREHOUSE", "COMPUTE_WH")
SNOWFLAKE_SCHEMA = os.environ.get("SNOWFLAKE_SCHEMA", "BANKING_DW")
SNOWFLAKE_ROLE = os.environ.get("SNOWFLAKE_ROLE", "")

# ---------------------------------------------------------------------------
# Teradata connection settings (optional, for source-to-target comparison)
# ---------------------------------------------------------------------------
TERADATA_HOST = os.environ.get("TERADATA_HOST", "")
TERADATA_USER = os.environ.get("TERADATA_USER", "")
TERADATA_PASSWORD = os.environ.get("TERADATA_PASSWORD", "")
TERADATA_DATABASE = os.environ.get("TERADATA_DATABASE", "BANKING_DW")

# ---------------------------------------------------------------------------
# Test configuration
# ---------------------------------------------------------------------------
# Tolerance for floating-point / DECIMAL comparisons
DECIMAL_TOLERANCE = float(os.environ.get("DECIMAL_TOLERANCE", "0.01"))

# Tolerance percentage for approximate row counts (FACT tables)
ROW_COUNT_TOLERANCE_PCT = float(os.environ.get("ROW_COUNT_TOLERANCE_PCT", "5.0"))

# Expected timestamp type in Snowflake after migration
EXPECTED_TIMESTAMP_TYPE = os.environ.get("EXPECTED_TIMESTAMP_TYPE", "TIMESTAMP_NTZ")

# ---------------------------------------------------------------------------
# Schema / object inventory
# ---------------------------------------------------------------------------
ALL_TABLES = [
    "DIM_CUSTOMER",
    "DIM_ACCOUNT",
    "DIM_PRODUCT",
    "DIM_BRANCH",
    "DIM_DATE",
    "FACT_TRANSACTION",
    "FACT_MONTHLY_ACCOUNT_SNAPSHOT",
]

ALL_VIEWS = [
    "VW_CUSTOMER_360",
    "VW_REGULATORY_LARGE_TRANSACTIONS",
    "VW_BRANCH_PERFORMANCE",
]

ALL_PROCEDURES = [
    "SP_CUSTOMER_SCD2",
    "SP_LOAD_DAILY_TRANSACTIONS",
    "SP_MONTHLY_SNAPSHOT",
]

ALL_MACROS_AS_PROCEDURES = [
    "AML_SCREENING",
    "CUSTOMER_TXN_HISTORY",
    "DAILY_BALANCE_CHECK",
]

# ---------------------------------------------------------------------------
# Expected column counts per table (derived from Teradata DDL)
# ---------------------------------------------------------------------------
EXPECTED_COLUMN_COUNTS = {
    "DIM_CUSTOMER": 28,
    "DIM_ACCOUNT": 23,
    "DIM_PRODUCT": 17,
    "DIM_BRANCH": 19,
    "DIM_DATE": 27,
    "FACT_TRANSACTION": 30,
    "FACT_MONTHLY_ACCOUNT_SNAPSHOT": 24,
}

# ---------------------------------------------------------------------------
# Expected row counts (from data/validation/expected_row_counts.csv)
# ---------------------------------------------------------------------------
EXPECTED_ROW_COUNTS = {
    "DIM_CUSTOMER": 15,
    "DIM_ACCOUNT": 20,
    "DIM_PRODUCT": 10,
    "DIM_BRANCH": 14,
    "DIM_DATE": 10958,
    "FACT_TRANSACTION": 50000,
    "FACT_MONTHLY_ACCOUNT_SNAPSHOT": 1920,
}

# Tables that use approximate row count matching (5% tolerance)
APPROXIMATE_COUNT_TABLES = {
    "FACT_TRANSACTION",
    "FACT_MONTHLY_ACCOUNT_SNAPSHOT",
}

# ---------------------------------------------------------------------------
# Expected columns per table (from Teradata DDL definitions)
# ---------------------------------------------------------------------------
EXPECTED_COLUMNS = {
    "DIM_CUSTOMER": [
        "CUSTOMER_ID", "CUSTOMER_KEY", "FIRST_NAME", "LAST_NAME",
        "DATE_OF_BIRTH", "GENDER", "MARITAL_STATUS", "EMAIL_ADDRESS",
        "PHONE_NUMBER", "ADDRESS_LINE_1", "ADDRESS_LINE_2", "CITY",
        "STATE_PROVINCE", "POSTAL_CODE", "COUNTRY_CODE", "CUSTOMER_SEGMENT",
        "RISK_SCORE", "CREDIT_RATING", "KYC_STATUS", "ONBOARDING_DATE",
        "LAST_REVIEW_DATE", "IS_ACTIVE", "EFFECTIVE_FROM", "EFFECTIVE_TO",
        "CURRENT_FLAG", "ETL_BATCH_ID", "ETL_INSERT_TS", "ETL_UPDATE_TS",
    ],
    "DIM_ACCOUNT": [
        "ACCOUNT_KEY", "ACCOUNT_ID", "CUSTOMER_ID", "ACCOUNT_TYPE",
        "ACCOUNT_SUBTYPE", "CURRENCY_CODE", "OPENING_DATE", "CLOSING_DATE",
        "ACCOUNT_STATUS", "INTEREST_RATE", "CREDIT_LIMIT", "OVERDRAFT_LIMIT",
        "BRANCH_ID", "RELATIONSHIP_MGR_ID", "PRODUCT_ID", "IS_JOINT_ACCOUNT",
        "TAX_REPORTING_FLAG", "EFFECTIVE_FROM", "EFFECTIVE_TO", "CURRENT_FLAG",
        "ETL_BATCH_ID", "ETL_INSERT_TS", "ETL_UPDATE_TS",
    ],
    "DIM_PRODUCT": [
        "PRODUCT_ID", "PRODUCT_CODE", "PRODUCT_NAME", "PRODUCT_CATEGORY",
        "PRODUCT_SUBCATEGORY", "BASE_INTEREST_RATE", "MIN_BALANCE",
        "MAX_BALANCE", "FEE_STRUCTURE", "MONTHLY_FEE", "IS_REGULATED",
        "REGULATORY_CODE", "LAUNCH_DATE", "DISCONTINUE_DATE", "IS_ACTIVE",
        "ETL_BATCH_ID", "ETL_INSERT_TS",
    ],
    "DIM_BRANCH": [
        "BRANCH_ID", "BRANCH_CODE", "BRANCH_NAME", "BRANCH_TYPE",
        "ADDRESS_LINE_1", "CITY", "COUNTY", "REGION", "POSTAL_CODE",
        "COUNTRY_CODE", "LATITUDE", "LONGITUDE", "MANAGER_ID",
        "OPENING_DATE", "CLOSING_DATE", "IS_ACTIVE", "EMPLOYEE_COUNT",
        "ETL_BATCH_ID", "ETL_INSERT_TS",
    ],
    "DIM_DATE": [
        "DATE_KEY", "CALENDAR_DATE", "DAY_OF_WEEK", "DAY_NAME",
        "DAY_OF_MONTH", "DAY_OF_YEAR", "WEEK_OF_YEAR", "ISO_WEEK",
        "MONTH_NUM", "MONTH_NAME", "MONTH_SHORT", "QUARTER_NUM",
        "QUARTER_NAME", "HALF_YEAR", "CALENDAR_YEAR", "FISCAL_YEAR",
        "FISCAL_QUARTER", "IS_WEEKEND", "IS_NORWEGIAN_HOLIDAY",
        "HOLIDAY_NAME", "IS_BUSINESS_DAY", "IS_MONTH_END", "IS_QUARTER_END",
        "IS_YEAR_END", "PRIOR_DAY_DATE", "NEXT_DAY_DATE",
        "SAME_DAY_PREV_YEAR",
    ],
    "FACT_TRANSACTION": [
        "TRANSACTION_ID", "TRANSACTION_DATE", "TRANSACTION_TIME",
        "TRANSACTION_TS", "ACCOUNT_KEY", "CUSTOMER_KEY", "PRODUCT_ID",
        "BRANCH_ID", "DATE_KEY", "TRANSACTION_TYPE", "TRANSACTION_SUBTYPE",
        "CHANNEL", "TRANSACTION_AMOUNT", "TRANSACTION_CURRENCY",
        "BASE_CURRENCY_AMOUNT", "EXCHANGE_RATE", "RUNNING_BALANCE",
        "MERCHANT_ID", "MERCHANT_NAME", "MERCHANT_CATEGORY",
        "COUNTERPARTY_ACCT", "REFERENCE_NUMBER", "DESCRIPTION_TEXT",
        "IS_INTERNATIONAL", "IS_FLAGGED", "FLAG_REASON", "POSTING_DATE",
        "VALUE_DATE", "ETL_BATCH_ID", "ETL_INSERT_TS",
    ],
    "FACT_MONTHLY_ACCOUNT_SNAPSHOT": [
        "SNAPSHOT_DATE", "SNAPSHOT_MONTH_KEY", "ACCOUNT_KEY", "CUSTOMER_KEY",
        "PRODUCT_ID", "BRANCH_ID", "OPENING_BALANCE", "CLOSING_BALANCE",
        "AVERAGE_BALANCE", "MINIMUM_BALANCE", "MAXIMUM_BALANCE",
        "TOTAL_DEBITS", "TOTAL_CREDITS", "DEBIT_COUNT", "CREDIT_COUNT",
        "INTEREST_EARNED", "INTEREST_CHARGED", "FEES_CHARGED",
        "DAYS_IN_OVERDRAFT", "DAYS_DORMANT", "CURRENCY_CODE",
        "BASE_CURRENCY_CLOSING", "ETL_BATCH_ID", "ETL_INSERT_TS",
    ],
}

# ---------------------------------------------------------------------------
# Expected data-type translations (Teradata -> Snowflake)
# Key columns to verify; format: (TABLE, COLUMN, SF_DATA_TYPE, precision, scale)
# precision/scale = None when not applicable
# ---------------------------------------------------------------------------
EXPECTED_TYPE_MAPPINGS = [
    # INTEGER -> NUMBER
    ("DIM_CUSTOMER", "CUSTOMER_ID", "NUMBER", 38, 0),
    # BIGINT -> NUMBER
    ("DIM_CUSTOMER", "CUSTOMER_KEY", "NUMBER", 38, 0),
    # VARCHAR -> VARCHAR (TEXT)
    ("DIM_CUSTOMER", "FIRST_NAME", "TEXT", None, None),
    # DECIMAL(5,2) -> NUMBER(5,2)
    ("DIM_CUSTOMER", "RISK_SCORE", "NUMBER", 5, 2),
    # DECIMAL(15,2) -> NUMBER(15,2)
    ("FACT_TRANSACTION", "TRANSACTION_AMOUNT", "NUMBER", 15, 2),
    # DECIMAL(12,6) -> NUMBER(12,6)
    ("FACT_TRANSACTION", "EXCHANGE_RATE", "NUMBER", 12, 6),
    # DECIMAL(7,4) -> NUMBER(7,4)
    ("DIM_ACCOUNT", "INTEREST_RATE", "NUMBER", 7, 4),
    # BYTEINT -> NUMBER
    ("DIM_CUSTOMER", "IS_ACTIVE", "NUMBER", 38, 0),
    # CHAR -> VARCHAR (TEXT) in Snowflake
    ("DIM_CUSTOMER", "GENDER", "TEXT", None, None),
    # SMALLINT -> NUMBER
    ("DIM_DATE", "DAY_OF_YEAR", "NUMBER", 38, 0),
    # DECIMAL(10,7) -> NUMBER(10,7)
    ("DIM_BRANCH", "LATITUDE", "NUMBER", 10, 7),
    # DATE -> DATE
    ("DIM_CUSTOMER", "DATE_OF_BIRTH", "DATE", None, None),
    ("DIM_CUSTOMER", "ONBOARDING_DATE", "DATE", None, None),
    # TIME(0) -> TIME
    ("FACT_TRANSACTION", "TRANSACTION_TIME", "TIME", None, None),
]

# ---------------------------------------------------------------------------
# NOT NULL constraints to verify
# ---------------------------------------------------------------------------
NOT_NULL_COLUMNS = [
    ("DIM_CUSTOMER", "CUSTOMER_ID"),
    ("DIM_CUSTOMER", "CUSTOMER_KEY"),
    ("DIM_CUSTOMER", "FIRST_NAME"),
    ("DIM_CUSTOMER", "LAST_NAME"),
    ("DIM_CUSTOMER", "ONBOARDING_DATE"),
    ("DIM_ACCOUNT", "ACCOUNT_KEY"),
    ("DIM_ACCOUNT", "ACCOUNT_ID"),
    ("DIM_ACCOUNT", "CUSTOMER_ID"),
    ("DIM_ACCOUNT", "ACCOUNT_TYPE"),
    ("DIM_ACCOUNT", "OPENING_DATE"),
    ("DIM_ACCOUNT", "PRODUCT_ID"),
    ("DIM_PRODUCT", "PRODUCT_ID"),
    ("DIM_PRODUCT", "PRODUCT_CODE"),
    ("DIM_PRODUCT", "PRODUCT_NAME"),
    ("DIM_PRODUCT", "PRODUCT_CATEGORY"),
    ("DIM_BRANCH", "BRANCH_ID"),
    ("DIM_BRANCH", "BRANCH_CODE"),
    ("DIM_BRANCH", "BRANCH_NAME"),
    ("DIM_DATE", "DATE_KEY"),
    ("DIM_DATE", "CALENDAR_DATE"),
    ("FACT_TRANSACTION", "TRANSACTION_ID"),
    ("FACT_TRANSACTION", "TRANSACTION_DATE"),
    ("FACT_TRANSACTION", "ACCOUNT_KEY"),
    ("FACT_TRANSACTION", "CUSTOMER_KEY"),
    ("FACT_TRANSACTION", "PRODUCT_ID"),
    ("FACT_TRANSACTION", "DATE_KEY"),
    ("FACT_TRANSACTION", "TRANSACTION_TYPE"),
    ("FACT_TRANSACTION", "TRANSACTION_AMOUNT"),
    ("FACT_MONTHLY_ACCOUNT_SNAPSHOT", "SNAPSHOT_DATE"),
    ("FACT_MONTHLY_ACCOUNT_SNAPSHOT", "SNAPSHOT_MONTH_KEY"),
    ("FACT_MONTHLY_ACCOUNT_SNAPSHOT", "ACCOUNT_KEY"),
    ("FACT_MONTHLY_ACCOUNT_SNAPSHOT", "CUSTOMER_KEY"),
    ("FACT_MONTHLY_ACCOUNT_SNAPSHOT", "PRODUCT_ID"),
    ("FACT_MONTHLY_ACCOUNT_SNAPSHOT", "OPENING_BALANCE"),
    ("FACT_MONTHLY_ACCOUNT_SNAPSHOT", "CLOSING_BALANCE"),
]

# ---------------------------------------------------------------------------
# DEFAULT value checks
# ---------------------------------------------------------------------------
DEFAULT_VALUE_CHECKS = [
    ("DIM_CUSTOMER", "IS_ACTIVE", "1"),
    ("DIM_CUSTOMER", "COUNTRY_CODE", "'NOR'"),
    ("DIM_CUSTOMER", "CURRENT_FLAG", "'Y'"),
    ("DIM_ACCOUNT", "CURRENCY_CODE", "'NOK'"),
    ("DIM_ACCOUNT", "ACCOUNT_STATUS", "'ACTIVE'"),
    ("DIM_ACCOUNT", "CURRENT_FLAG", "'Y'"),
]

# ---------------------------------------------------------------------------
# IDENTITY / AUTOINCREMENT columns
# ---------------------------------------------------------------------------
IDENTITY_COLUMNS = [
    ("DIM_CUSTOMER", "CUSTOMER_KEY"),
    ("DIM_ACCOUNT", "ACCOUNT_KEY"),
]

# ---------------------------------------------------------------------------
# TIMESTAMP columns to verify against expected type
# ---------------------------------------------------------------------------
TIMESTAMP_COLUMNS = [
    ("DIM_CUSTOMER", "EFFECTIVE_FROM"),
    ("DIM_CUSTOMER", "EFFECTIVE_TO"),
    ("DIM_CUSTOMER", "ETL_INSERT_TS"),
    ("DIM_CUSTOMER", "ETL_UPDATE_TS"),
    ("DIM_ACCOUNT", "EFFECTIVE_FROM"),
    ("DIM_ACCOUNT", "EFFECTIVE_TO"),
    ("DIM_ACCOUNT", "ETL_INSERT_TS"),
    ("DIM_ACCOUNT", "ETL_UPDATE_TS"),
    ("DIM_PRODUCT", "ETL_INSERT_TS"),
    ("DIM_BRANCH", "ETL_INSERT_TS"),
    ("FACT_TRANSACTION", "ETL_INSERT_TS"),
    ("FACT_MONTHLY_ACCOUNT_SNAPSHOT", "ETL_INSERT_TS"),
]

# TIMESTAMP(6) columns (higher precision)
TIMESTAMP6_COLUMNS = [
    ("FACT_TRANSACTION", "TRANSACTION_TS"),
]

# ---------------------------------------------------------------------------
# Primary / unique key columns per table (for duplicate checks)
# ---------------------------------------------------------------------------
PRIMARY_KEY_COLUMNS = {
    "DIM_CUSTOMER": "CUSTOMER_KEY",
    "DIM_ACCOUNT": "ACCOUNT_KEY",
    "DIM_PRODUCT": "PRODUCT_ID",
    "DIM_BRANCH": "BRANCH_ID",
    "DIM_DATE": "DATE_KEY",
    "FACT_TRANSACTION": "TRANSACTION_ID",
}

# Natural key for SCD2 tables
SCD2_NATURAL_KEYS = {
    "DIM_CUSTOMER": "CUSTOMER_ID",
    "DIM_ACCOUNT": "ACCOUNT_ID",
}

# ---------------------------------------------------------------------------
# Referential integrity relationships
# Format: (child_table, child_column, parent_table, parent_column)
# ---------------------------------------------------------------------------
REFERENTIAL_INTEGRITY_CHECKS = [
    ("FACT_TRANSACTION", "ACCOUNT_KEY", "DIM_ACCOUNT", "ACCOUNT_KEY"),
    ("FACT_TRANSACTION", "CUSTOMER_KEY", "DIM_CUSTOMER", "CUSTOMER_KEY"),
    ("FACT_TRANSACTION", "DATE_KEY", "DIM_DATE", "DATE_KEY"),
    ("FACT_TRANSACTION", "PRODUCT_ID", "DIM_PRODUCT", "PRODUCT_ID"),
    ("FACT_MONTHLY_ACCOUNT_SNAPSHOT", "ACCOUNT_KEY", "DIM_ACCOUNT", "ACCOUNT_KEY"),
    ("FACT_MONTHLY_ACCOUNT_SNAPSHOT", "CUSTOMER_KEY", "DIM_CUSTOMER", "CUSTOMER_KEY"),
    ("DIM_ACCOUNT", "CUSTOMER_ID", "DIM_CUSTOMER", "CUSTOMER_ID"),
    ("DIM_ACCOUNT", "PRODUCT_ID", "DIM_PRODUCT", "PRODUCT_ID"),
]

# Nullable FK (LEFT JOIN pattern — BRANCH_ID can be NULL for online/mobile)
NULLABLE_FK_CHECKS = [
    ("DIM_ACCOUNT", "BRANCH_ID", "DIM_BRANCH", "BRANCH_ID"),
]

# ---------------------------------------------------------------------------
# Seed CSV file paths (relative to repo root)
# ---------------------------------------------------------------------------
SEED_CSV_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "seed",
)
SEED_CSV_FILES = {
    "DIM_CUSTOMER": "dim_customer_sample.csv",
    "DIM_ACCOUNT": "dim_account_sample.csv",
    "DIM_BRANCH": "dim_branch_sample.csv",
    "DIM_PRODUCT": "dim_product_sample.csv",
}
SEED_CSV_DELIMITER = "|"
