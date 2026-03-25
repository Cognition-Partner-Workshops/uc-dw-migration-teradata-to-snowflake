"""
Configuration for Teradata-to-Snowflake migration data quality tests.
All credentials are read from environment variables — never hardcode secrets.
"""

import os

# ---------------------------------------------------------------------------
# Snowflake connection parameters
# ---------------------------------------------------------------------------
SNOWFLAKE_CONFIG = {
    "account": os.environ.get("SNOWFLAKE_ACCOUNT", ""),
    "user": os.environ.get("SNOWFLAKE_USER", ""),
    "password": os.environ.get("SNOWFLAKE_PASSWORD", ""),
    "database": os.environ.get("SNOWFLAKE_DATABASE", "BANKING_DW"),
    "warehouse": os.environ.get("SNOWFLAKE_WAREHOUSE", "COMPUTE_WH"),
    "schema": os.environ.get("SNOWFLAKE_SCHEMA", "BANKING_DW"),
    "role": os.environ.get("SNOWFLAKE_ROLE", "SYSADMIN"),
}

# ---------------------------------------------------------------------------
# Optional Teradata connection parameters (for source-to-target comparison)
# ---------------------------------------------------------------------------
TERADATA_CONFIG = {
    "host": os.environ.get("TERADATA_HOST", ""),
    "user": os.environ.get("TERADATA_USER", ""),
    "password": os.environ.get("TERADATA_PASSWORD", ""),
    "database": os.environ.get("TERADATA_DATABASE", "BANKING_DW"),
}

TERADATA_AVAILABLE = bool(TERADATA_CONFIG["host"])

# ---------------------------------------------------------------------------
# Schema / object inventory
# ---------------------------------------------------------------------------
SCHEMA_NAME = SNOWFLAKE_CONFIG["schema"]

TABLES = [
    "DIM_CUSTOMER",
    "DIM_ACCOUNT",
    "DIM_PRODUCT",
    "DIM_BRANCH",
    "DIM_DATE",
    "FACT_TRANSACTION",
    "FACT_MONTHLY_ACCOUNT_SNAPSHOT",
]

VIEWS = [
    "VW_CUSTOMER_360",
    "VW_REGULATORY_LARGE_TRANSACTIONS",
    "VW_BRANCH_PERFORMANCE",
]

STORED_PROCEDURES = [
    "SP_CUSTOMER_SCD2",
    "SP_LOAD_DAILY_TRANSACTIONS",
    "SP_MONTHLY_SNAPSHOT",
]

MACROS_AS_PROCEDURES = [
    "AML_SCREENING",
    "CUSTOMER_TXN_HISTORY",
    "DAILY_BALANCE_CHECK",
]

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

# Tables that use approximate counts (5 % tolerance)
APPROXIMATE_COUNT_TABLES = {
    "FACT_TRANSACTION",
    "FACT_MONTHLY_ACCOUNT_SNAPSHOT",
}

ROW_COUNT_TOLERANCE = 0.05  # 5 %

# ---------------------------------------------------------------------------
# Expected column counts per table (from DDL inspection)
# ---------------------------------------------------------------------------
EXPECTED_COLUMN_COUNTS = {
    "DIM_CUSTOMER": 23,
    "DIM_ACCOUNT": 21,
    "DIM_PRODUCT": 17,
    "DIM_BRANCH": 18,
    "DIM_DATE": 24,
    "FACT_TRANSACTION": 27,
    "FACT_MONTHLY_ACCOUNT_SNAPSHOT": 24,
}

# ---------------------------------------------------------------------------
# Expected columns per table (uppercase — Snowflake stores unquoted as upper)
# ---------------------------------------------------------------------------
EXPECTED_COLUMNS: dict[str, list[str]] = {
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
        "HOLIDAY_NAME", "IS_BUSINESS_DAY", "IS_MONTH_END",
        "IS_QUARTER_END", "IS_YEAR_END", "PRIOR_DAY_DATE",
        "NEXT_DAY_DATE", "SAME_DAY_PREV_YEAR",
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
# Data type translation map: Teradata -> Snowflake
# ---------------------------------------------------------------------------
TYPE_TRANSLATION = {
    "INTEGER": "NUMBER",
    "BIGINT": "NUMBER",
    "SMALLINT": "NUMBER",
    "BYTEINT": "NUMBER",
    "DECIMAL": "NUMBER",
    "VARCHAR": "VARCHAR",
    "CHAR": "VARCHAR",
    "DATE": "DATE",
    "TIMESTAMP": "TIMESTAMP_NTZ",
    "TIME": "TIME",
}

# ---------------------------------------------------------------------------
# NOT NULL constraints to verify
# ---------------------------------------------------------------------------
NOT_NULL_COLUMNS = {
    "DIM_CUSTOMER": [
        "CUSTOMER_ID", "CUSTOMER_KEY", "FIRST_NAME", "LAST_NAME",
        "ONBOARDING_DATE",
    ],
    "DIM_ACCOUNT": [
        "ACCOUNT_KEY", "ACCOUNT_ID", "CUSTOMER_ID", "ACCOUNT_TYPE",
        "OPENING_DATE", "PRODUCT_ID",
    ],
    "DIM_PRODUCT": [
        "PRODUCT_ID", "PRODUCT_CODE", "PRODUCT_NAME", "PRODUCT_CATEGORY",
    ],
    "DIM_BRANCH": [
        "BRANCH_ID", "BRANCH_CODE", "BRANCH_NAME",
    ],
    "DIM_DATE": [
        "DATE_KEY", "CALENDAR_DATE", "DAY_OF_WEEK", "DAY_NAME",
        "DAY_OF_MONTH", "DAY_OF_YEAR", "WEEK_OF_YEAR", "ISO_WEEK",
        "MONTH_NUM", "MONTH_NAME", "MONTH_SHORT", "QUARTER_NUM",
        "QUARTER_NAME", "HALF_YEAR", "CALENDAR_YEAR", "FISCAL_YEAR",
        "FISCAL_QUARTER", "IS_WEEKEND", "IS_BUSINESS_DAY", "IS_MONTH_END",
        "IS_QUARTER_END", "IS_YEAR_END",
    ],
    "FACT_TRANSACTION": [
        "TRANSACTION_ID", "TRANSACTION_DATE", "ACCOUNT_KEY", "CUSTOMER_KEY",
        "PRODUCT_ID", "DATE_KEY", "TRANSACTION_TYPE", "TRANSACTION_AMOUNT",
    ],
    "FACT_MONTHLY_ACCOUNT_SNAPSHOT": [
        "SNAPSHOT_DATE", "SNAPSHOT_MONTH_KEY", "ACCOUNT_KEY", "CUSTOMER_KEY",
        "PRODUCT_ID", "OPENING_BALANCE", "CLOSING_BALANCE",
    ],
}

# ---------------------------------------------------------------------------
# Default values to verify
# ---------------------------------------------------------------------------
EXPECTED_DEFAULTS = {
    "DIM_CUSTOMER": {
        "IS_ACTIVE": "1",
        "COUNTRY_CODE": "'NOR'",
        "CURRENT_FLAG": "'Y'",
    },
    "DIM_ACCOUNT": {
        "CURRENT_FLAG": "'Y'",
    },
}

# ---------------------------------------------------------------------------
# Domain value sets for business logic validation
# ---------------------------------------------------------------------------
DOMAIN_VALUES = {
    "CUSTOMER_SEGMENT": {"RETAIL", "PREMIUM", "PRIVATE", "CORPORATE"},
    "ACCOUNT_TYPE": {
        "CHECKING", "SAVINGS", "LOAN", "CREDIT_CARD",
        "MORTGAGE", "DEPOSIT", "INVESTMENT",
    },
    "ACCOUNT_STATUS": {"ACTIVE", "DORMANT", "CLOSED", "FROZEN", "SUSPENDED"},
    "TRANSACTION_TYPE": {
        "DEBIT", "CREDIT", "TRANSFER", "FEE",
        "INTEREST", "REVERSAL", "ADJUSTMENT",
    },
    "CHANNEL": {"BRANCH", "ATM", "ONLINE", "MOBILE", "POS", "API"},
    "KYC_STATUS": {"VERIFIED", "PENDING", "REVIEW", "EXPIRED"},
    "GENDER": {"M", "F", "O"},
    "CURRENCY_CODE": {"NOK", "EUR", "USD", "GBP", "SEK", "DKK"},
    "BRANCH_TYPE": {"FULL_SERVICE", "DIGITAL", "KIOSK", "REGIONAL_HQ"},
    "REGION": {"OSTLANDET", "VESTLANDET", "SORLANDET", "TRONDELAG", "NORD-NORGE"},
}

# ---------------------------------------------------------------------------
# Decimal tolerance for floating-point comparisons
# ---------------------------------------------------------------------------
DECIMAL_TOLERANCE = 0.01

# ---------------------------------------------------------------------------
# Seed CSV paths (relative to repo root)
# ---------------------------------------------------------------------------
SEED_CSV_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "seed",
)

SEED_FILES = {
    "DIM_CUSTOMER": os.path.join(SEED_CSV_DIR, "dim_customer_sample.csv"),
    "DIM_ACCOUNT": os.path.join(SEED_CSV_DIR, "dim_account_sample.csv"),
    "DIM_BRANCH": os.path.join(SEED_CSV_DIR, "dim_branch_sample.csv"),
    "DIM_PRODUCT": os.path.join(SEED_CSV_DIR, "dim_product_sample.csv"),
}

# ---------------------------------------------------------------------------
# Timestamp strategy — default TIMESTAMP_NTZ
# ---------------------------------------------------------------------------
TIMESTAMP_TYPE = os.environ.get("SNOWFLAKE_TIMESTAMP_TYPE", "TIMESTAMP_NTZ")

# ---------------------------------------------------------------------------
# Clone schema name for negative / destructive tests
# ---------------------------------------------------------------------------
CLONE_SCHEMA = "BANKING_DW_TEST_CLONE"
