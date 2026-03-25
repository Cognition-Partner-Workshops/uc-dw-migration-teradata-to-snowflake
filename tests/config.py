"""
Configuration module for Teradata-to-Snowflake migration validation tests.

Reads connection parameters from environment variables.
"""

import os


# ---------------------------------------------------------------------------
# Snowflake connection settings (required)
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
# Validation thresholds
# ---------------------------------------------------------------------------
DECIMAL_TOLERANCE = float(os.environ.get("DECIMAL_TOLERANCE", "0.01"))
ROW_COUNT_TOLERANCE_PCT = float(os.environ.get("ROW_COUNT_TOLERANCE_PCT", "5.0"))

# ---------------------------------------------------------------------------
# Timestamp migration strategy
# ---------------------------------------------------------------------------
TIMESTAMP_VARIANT = os.environ.get("TIMESTAMP_VARIANT", "TIMESTAMP_NTZ")

# ---------------------------------------------------------------------------
# Schema under test
# ---------------------------------------------------------------------------
TARGET_SCHEMA = SNOWFLAKE_SCHEMA

# ---------------------------------------------------------------------------
# Expected tables and views in BANKING_DW
# ---------------------------------------------------------------------------
EXPECTED_TABLES = [
    "DIM_CUSTOMER",
    "DIM_ACCOUNT",
    "DIM_PRODUCT",
    "DIM_BRANCH",
    "DIM_DATE",
    "FACT_TRANSACTION",
    "FACT_MONTHLY_ACCOUNT_SNAPSHOT",
]

EXPECTED_VIEWS = [
    "VW_CUSTOMER_360",
    "VW_REGULATORY_LARGE_TRANSACTIONS",
    "VW_BRANCH_PERFORMANCE",
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
# Expected columns per table (derived from Teradata DDL, uppercase)
# ---------------------------------------------------------------------------
EXPECTED_COLUMNS = {
    "DIM_CUSTOMER": [
        "CUSTOMER_ID",
        "CUSTOMER_KEY",
        "FIRST_NAME",
        "LAST_NAME",
        "DATE_OF_BIRTH",
        "GENDER",
        "MARITAL_STATUS",
        "EMAIL_ADDRESS",
        "PHONE_NUMBER",
        "ADDRESS_LINE_1",
        "ADDRESS_LINE_2",
        "CITY",
        "STATE_PROVINCE",
        "POSTAL_CODE",
        "COUNTRY_CODE",
        "CUSTOMER_SEGMENT",
        "RISK_SCORE",
        "CREDIT_RATING",
        "KYC_STATUS",
        "ONBOARDING_DATE",
        "LAST_REVIEW_DATE",
        "IS_ACTIVE",
        "EFFECTIVE_FROM",
        "EFFECTIVE_TO",
        "CURRENT_FLAG",
        "ETL_BATCH_ID",
        "ETL_INSERT_TS",
        "ETL_UPDATE_TS",
    ],
    "DIM_ACCOUNT": [
        "ACCOUNT_KEY",
        "ACCOUNT_ID",
        "CUSTOMER_ID",
        "ACCOUNT_TYPE",
        "ACCOUNT_SUBTYPE",
        "CURRENCY_CODE",
        "OPENING_DATE",
        "CLOSING_DATE",
        "ACCOUNT_STATUS",
        "INTEREST_RATE",
        "CREDIT_LIMIT",
        "OVERDRAFT_LIMIT",
        "BRANCH_ID",
        "RELATIONSHIP_MGR_ID",
        "PRODUCT_ID",
        "IS_JOINT_ACCOUNT",
        "TAX_REPORTING_FLAG",
        "EFFECTIVE_FROM",
        "EFFECTIVE_TO",
        "CURRENT_FLAG",
        "ETL_BATCH_ID",
        "ETL_INSERT_TS",
        "ETL_UPDATE_TS",
    ],
    "DIM_PRODUCT": [
        "PRODUCT_ID",
        "PRODUCT_CODE",
        "PRODUCT_NAME",
        "PRODUCT_CATEGORY",
        "PRODUCT_SUBCATEGORY",
        "BASE_INTEREST_RATE",
        "MIN_BALANCE",
        "MAX_BALANCE",
        "FEE_STRUCTURE",
        "MONTHLY_FEE",
        "IS_REGULATED",
        "REGULATORY_CODE",
        "LAUNCH_DATE",
        "DISCONTINUE_DATE",
        "IS_ACTIVE",
        "ETL_BATCH_ID",
        "ETL_INSERT_TS",
    ],
    "DIM_BRANCH": [
        "BRANCH_ID",
        "BRANCH_CODE",
        "BRANCH_NAME",
        "BRANCH_TYPE",
        "ADDRESS_LINE_1",
        "CITY",
        "COUNTY",
        "REGION",
        "POSTAL_CODE",
        "COUNTRY_CODE",
        "LATITUDE",
        "LONGITUDE",
        "MANAGER_ID",
        "OPENING_DATE",
        "CLOSING_DATE",
        "IS_ACTIVE",
        "EMPLOYEE_COUNT",
        "ETL_BATCH_ID",
        "ETL_INSERT_TS",
    ],
    "DIM_DATE": [
        "DATE_KEY",
        "CALENDAR_DATE",
        "DAY_OF_WEEK",
        "DAY_NAME",
        "DAY_OF_MONTH",
        "DAY_OF_YEAR",
        "WEEK_OF_YEAR",
        "ISO_WEEK",
        "MONTH_NUM",
        "MONTH_NAME",
        "MONTH_SHORT",
        "QUARTER_NUM",
        "QUARTER_NAME",
        "HALF_YEAR",
        "CALENDAR_YEAR",
        "FISCAL_YEAR",
        "FISCAL_QUARTER",
        "IS_WEEKEND",
        "IS_NORWEGIAN_HOLIDAY",
        "HOLIDAY_NAME",
        "IS_BUSINESS_DAY",
        "IS_MONTH_END",
        "IS_QUARTER_END",
        "IS_YEAR_END",
        "PRIOR_DAY_DATE",
        "NEXT_DAY_DATE",
        "SAME_DAY_PREV_YEAR",
    ],
    "FACT_TRANSACTION": [
        "TRANSACTION_ID",
        "TRANSACTION_DATE",
        "TRANSACTION_TIME",
        "TRANSACTION_TS",
        "ACCOUNT_KEY",
        "CUSTOMER_KEY",
        "PRODUCT_ID",
        "BRANCH_ID",
        "DATE_KEY",
        "TRANSACTION_TYPE",
        "TRANSACTION_SUBTYPE",
        "CHANNEL",
        "TRANSACTION_AMOUNT",
        "TRANSACTION_CURRENCY",
        "BASE_CURRENCY_AMOUNT",
        "EXCHANGE_RATE",
        "RUNNING_BALANCE",
        "MERCHANT_ID",
        "MERCHANT_NAME",
        "MERCHANT_CATEGORY",
        "COUNTERPARTY_ACCT",
        "REFERENCE_NUMBER",
        "DESCRIPTION_TEXT",
        "IS_INTERNATIONAL",
        "IS_FLAGGED",
        "FLAG_REASON",
        "POSTING_DATE",
        "VALUE_DATE",
        "ETL_BATCH_ID",
        "ETL_INSERT_TS",
    ],
    "FACT_MONTHLY_ACCOUNT_SNAPSHOT": [
        "SNAPSHOT_DATE",
        "SNAPSHOT_MONTH_KEY",
        "ACCOUNT_KEY",
        "CUSTOMER_KEY",
        "PRODUCT_ID",
        "BRANCH_ID",
        "OPENING_BALANCE",
        "CLOSING_BALANCE",
        "AVERAGE_BALANCE",
        "MINIMUM_BALANCE",
        "MAXIMUM_BALANCE",
        "TOTAL_DEBITS",
        "TOTAL_CREDITS",
        "DEBIT_COUNT",
        "CREDIT_COUNT",
        "INTEREST_EARNED",
        "INTEREST_CHARGED",
        "FEES_CHARGED",
        "DAYS_IN_OVERDRAFT",
        "DAYS_DORMANT",
        "CURRENCY_CODE",
        "BASE_CURRENCY_CLOSING",
        "ETL_BATCH_ID",
        "ETL_INSERT_TS",
    ],
}

# ---------------------------------------------------------------------------
# Expected data type mappings (Teradata -> Snowflake)
# Key: (TABLE_NAME, COLUMN_NAME)
# Value: dict with expected Snowflake INFORMATION_SCHEMA metadata
#
# Common Teradata-to-Snowflake type translations:
#   INTEGER       -> NUMBER (precision 38, scale 0)
#   BIGINT        -> NUMBER (precision 38, scale 0)
#   SMALLINT      -> NUMBER (precision 38, scale 0)
#   BYTEINT       -> NUMBER (precision 38, scale 0)
#   DECIMAL(p,s)  -> NUMBER (precision p, scale s)
#   VARCHAR(n)    -> VARCHAR / TEXT (max_length n * 4 for UTF-8 or n)
#   CHAR(n)       -> VARCHAR / TEXT (Snowflake treats CHAR as VARCHAR)
#   DATE          -> DATE
#   TIMESTAMP(0)  -> TIMESTAMP_NTZ (or configured variant)
#   TIMESTAMP(6)  -> TIMESTAMP_NTZ (or configured variant)
#   TIME(0)       -> TIME
# ---------------------------------------------------------------------------
EXPECTED_DATA_TYPES = {
    # DIM_CUSTOMER
    ("DIM_CUSTOMER", "CUSTOMER_ID"): {"DATA_TYPE": "NUMBER", "NUMERIC_PRECISION": 38, "NUMERIC_SCALE": 0},
    ("DIM_CUSTOMER", "CUSTOMER_KEY"): {"DATA_TYPE": "NUMBER", "NUMERIC_PRECISION": 38, "NUMERIC_SCALE": 0},
    ("DIM_CUSTOMER", "FIRST_NAME"): {"DATA_TYPE": "TEXT"},
    ("DIM_CUSTOMER", "LAST_NAME"): {"DATA_TYPE": "TEXT"},
    ("DIM_CUSTOMER", "DATE_OF_BIRTH"): {"DATA_TYPE": "DATE"},
    ("DIM_CUSTOMER", "GENDER"): {"DATA_TYPE": "TEXT"},
    ("DIM_CUSTOMER", "MARITAL_STATUS"): {"DATA_TYPE": "TEXT"},
    ("DIM_CUSTOMER", "EMAIL_ADDRESS"): {"DATA_TYPE": "TEXT"},
    ("DIM_CUSTOMER", "RISK_SCORE"): {"DATA_TYPE": "NUMBER", "NUMERIC_PRECISION": 5, "NUMERIC_SCALE": 2},
    ("DIM_CUSTOMER", "CREDIT_RATING"): {"DATA_TYPE": "TEXT"},
    ("DIM_CUSTOMER", "IS_ACTIVE"): {"DATA_TYPE": "NUMBER"},
    ("DIM_CUSTOMER", "EFFECTIVE_FROM"): {"DATA_TYPE": TIMESTAMP_VARIANT},
    ("DIM_CUSTOMER", "EFFECTIVE_TO"): {"DATA_TYPE": TIMESTAMP_VARIANT},
    ("DIM_CUSTOMER", "ETL_INSERT_TS"): {"DATA_TYPE": TIMESTAMP_VARIANT},
    ("DIM_CUSTOMER", "ETL_UPDATE_TS"): {"DATA_TYPE": TIMESTAMP_VARIANT},
    ("DIM_CUSTOMER", "ONBOARDING_DATE"): {"DATA_TYPE": "DATE"},
    ("DIM_CUSTOMER", "COUNTRY_CODE"): {"DATA_TYPE": "TEXT"},
    # DIM_ACCOUNT
    ("DIM_ACCOUNT", "ACCOUNT_KEY"): {"DATA_TYPE": "NUMBER", "NUMERIC_PRECISION": 38, "NUMERIC_SCALE": 0},
    ("DIM_ACCOUNT", "ACCOUNT_ID"): {"DATA_TYPE": "TEXT"},
    ("DIM_ACCOUNT", "CUSTOMER_ID"): {"DATA_TYPE": "NUMBER", "NUMERIC_PRECISION": 38, "NUMERIC_SCALE": 0},
    ("DIM_ACCOUNT", "INTEREST_RATE"): {"DATA_TYPE": "NUMBER", "NUMERIC_PRECISION": 7, "NUMERIC_SCALE": 4},
    ("DIM_ACCOUNT", "CREDIT_LIMIT"): {"DATA_TYPE": "NUMBER", "NUMERIC_PRECISION": 15, "NUMERIC_SCALE": 2},
    ("DIM_ACCOUNT", "OVERDRAFT_LIMIT"): {"DATA_TYPE": "NUMBER", "NUMERIC_PRECISION": 15, "NUMERIC_SCALE": 2},
    ("DIM_ACCOUNT", "EFFECTIVE_FROM"): {"DATA_TYPE": TIMESTAMP_VARIANT},
    ("DIM_ACCOUNT", "EFFECTIVE_TO"): {"DATA_TYPE": TIMESTAMP_VARIANT},
    ("DIM_ACCOUNT", "ETL_INSERT_TS"): {"DATA_TYPE": TIMESTAMP_VARIANT},
    ("DIM_ACCOUNT", "ETL_UPDATE_TS"): {"DATA_TYPE": TIMESTAMP_VARIANT},
    # DIM_PRODUCT
    ("DIM_PRODUCT", "PRODUCT_ID"): {"DATA_TYPE": "NUMBER", "NUMERIC_PRECISION": 38, "NUMERIC_SCALE": 0},
    ("DIM_PRODUCT", "BASE_INTEREST_RATE"): {"DATA_TYPE": "NUMBER", "NUMERIC_PRECISION": 7, "NUMERIC_SCALE": 4},
    ("DIM_PRODUCT", "MIN_BALANCE"): {"DATA_TYPE": "NUMBER", "NUMERIC_PRECISION": 15, "NUMERIC_SCALE": 2},
    ("DIM_PRODUCT", "MAX_BALANCE"): {"DATA_TYPE": "NUMBER", "NUMERIC_PRECISION": 15, "NUMERIC_SCALE": 2},
    ("DIM_PRODUCT", "MONTHLY_FEE"): {"DATA_TYPE": "NUMBER", "NUMERIC_PRECISION": 10, "NUMERIC_SCALE": 2},
    ("DIM_PRODUCT", "ETL_INSERT_TS"): {"DATA_TYPE": TIMESTAMP_VARIANT},
    # DIM_BRANCH
    ("DIM_BRANCH", "BRANCH_ID"): {"DATA_TYPE": "NUMBER", "NUMERIC_PRECISION": 38, "NUMERIC_SCALE": 0},
    ("DIM_BRANCH", "LATITUDE"): {"DATA_TYPE": "NUMBER", "NUMERIC_PRECISION": 10, "NUMERIC_SCALE": 7},
    ("DIM_BRANCH", "LONGITUDE"): {"DATA_TYPE": "NUMBER", "NUMERIC_PRECISION": 10, "NUMERIC_SCALE": 7},
    ("DIM_BRANCH", "ETL_INSERT_TS"): {"DATA_TYPE": TIMESTAMP_VARIANT},
    # DIM_DATE
    ("DIM_DATE", "DATE_KEY"): {"DATA_TYPE": "NUMBER", "NUMERIC_PRECISION": 38, "NUMERIC_SCALE": 0},
    ("DIM_DATE", "CALENDAR_DATE"): {"DATA_TYPE": "DATE"},
    ("DIM_DATE", "DAY_OF_WEEK"): {"DATA_TYPE": "NUMBER"},
    ("DIM_DATE", "CALENDAR_YEAR"): {"DATA_TYPE": "NUMBER"},
    # FACT_TRANSACTION
    ("FACT_TRANSACTION", "TRANSACTION_ID"): {"DATA_TYPE": "NUMBER", "NUMERIC_PRECISION": 38, "NUMERIC_SCALE": 0},
    ("FACT_TRANSACTION", "TRANSACTION_DATE"): {"DATA_TYPE": "DATE"},
    ("FACT_TRANSACTION", "TRANSACTION_TIME"): {"DATA_TYPE": "TIME"},
    ("FACT_TRANSACTION", "TRANSACTION_TS"): {"DATA_TYPE": TIMESTAMP_VARIANT},
    ("FACT_TRANSACTION", "TRANSACTION_AMOUNT"): {"DATA_TYPE": "NUMBER", "NUMERIC_PRECISION": 15, "NUMERIC_SCALE": 2},
    ("FACT_TRANSACTION", "BASE_CURRENCY_AMOUNT"): {"DATA_TYPE": "NUMBER", "NUMERIC_PRECISION": 15, "NUMERIC_SCALE": 2},
    ("FACT_TRANSACTION", "EXCHANGE_RATE"): {"DATA_TYPE": "NUMBER", "NUMERIC_PRECISION": 12, "NUMERIC_SCALE": 6},
    ("FACT_TRANSACTION", "ETL_INSERT_TS"): {"DATA_TYPE": TIMESTAMP_VARIANT},
    # FACT_MONTHLY_ACCOUNT_SNAPSHOT
    ("FACT_MONTHLY_ACCOUNT_SNAPSHOT", "SNAPSHOT_DATE"): {"DATA_TYPE": "DATE"},
    ("FACT_MONTHLY_ACCOUNT_SNAPSHOT", "OPENING_BALANCE"): {"DATA_TYPE": "NUMBER", "NUMERIC_PRECISION": 15, "NUMERIC_SCALE": 2},
    ("FACT_MONTHLY_ACCOUNT_SNAPSHOT", "CLOSING_BALANCE"): {"DATA_TYPE": "NUMBER", "NUMERIC_PRECISION": 15, "NUMERIC_SCALE": 2},
    ("FACT_MONTHLY_ACCOUNT_SNAPSHOT", "ETL_INSERT_TS"): {"DATA_TYPE": TIMESTAMP_VARIANT},
}

# ---------------------------------------------------------------------------
# NOT NULL constraints expected in Snowflake (derived from Teradata DDL)
# Key: TABLE_NAME, Value: list of columns that must be NOT NULL
# ---------------------------------------------------------------------------
EXPECTED_NOT_NULL_COLUMNS = {
    "DIM_CUSTOMER": [
        "CUSTOMER_ID",
        "CUSTOMER_KEY",
        "FIRST_NAME",
        "LAST_NAME",
        "ONBOARDING_DATE",
    ],
    "DIM_ACCOUNT": [
        "ACCOUNT_KEY",
        "ACCOUNT_ID",
        "CUSTOMER_ID",
        "ACCOUNT_TYPE",
        "OPENING_DATE",
        "PRODUCT_ID",
    ],
    "DIM_PRODUCT": [
        "PRODUCT_ID",
        "PRODUCT_CODE",
        "PRODUCT_NAME",
        "PRODUCT_CATEGORY",
    ],
    "DIM_BRANCH": [
        "BRANCH_ID",
        "BRANCH_CODE",
        "BRANCH_NAME",
    ],
    "DIM_DATE": [
        "DATE_KEY",
        "CALENDAR_DATE",
        "DAY_OF_WEEK",
        "DAY_NAME",
        "DAY_OF_MONTH",
        "DAY_OF_YEAR",
        "WEEK_OF_YEAR",
        "ISO_WEEK",
        "MONTH_NUM",
        "MONTH_NAME",
        "MONTH_SHORT",
        "QUARTER_NUM",
        "QUARTER_NAME",
        "HALF_YEAR",
        "CALENDAR_YEAR",
        "FISCAL_YEAR",
        "FISCAL_QUARTER",
        "IS_WEEKEND",
        "IS_BUSINESS_DAY",
        "IS_MONTH_END",
        "IS_QUARTER_END",
        "IS_YEAR_END",
    ],
    "FACT_TRANSACTION": [
        "TRANSACTION_ID",
        "TRANSACTION_DATE",
        "ACCOUNT_KEY",
        "CUSTOMER_KEY",
        "PRODUCT_ID",
        "DATE_KEY",
        "TRANSACTION_TYPE",
        "TRANSACTION_AMOUNT",
    ],
    "FACT_MONTHLY_ACCOUNT_SNAPSHOT": [
        "SNAPSHOT_DATE",
        "SNAPSHOT_MONTH_KEY",
        "ACCOUNT_KEY",
        "CUSTOMER_KEY",
        "PRODUCT_ID",
        "OPENING_BALANCE",
        "CLOSING_BALANCE",
    ],
}

# ---------------------------------------------------------------------------
# Expected DEFAULT values (column -> default expression substring)
# Snowflake stores defaults as expressions; we check for substring match.
# ---------------------------------------------------------------------------
EXPECTED_DEFAULTS = {
    ("DIM_CUSTOMER", "IS_ACTIVE"): "1",
    ("DIM_CUSTOMER", "COUNTRY_CODE"): "'NOR'",
    ("DIM_CUSTOMER", "CURRENT_FLAG"): "'Y'",
    ("DIM_CUSTOMER", "KYC_STATUS"): "'PENDING'",
    ("DIM_ACCOUNT", "CURRENCY_CODE"): "'NOK'",
    ("DIM_ACCOUNT", "ACCOUNT_STATUS"): "'ACTIVE'",
    ("DIM_ACCOUNT", "CURRENT_FLAG"): "'Y'",
    ("DIM_ACCOUNT", "OVERDRAFT_LIMIT"): "0",
    ("DIM_ACCOUNT", "IS_JOINT_ACCOUNT"): "0",
    ("DIM_ACCOUNT", "TAX_REPORTING_FLAG"): "1",
    ("DIM_PRODUCT", "MIN_BALANCE"): "0",
    ("DIM_PRODUCT", "MONTHLY_FEE"): "0",
    ("DIM_PRODUCT", "IS_REGULATED"): "1",
    ("DIM_PRODUCT", "IS_ACTIVE"): "1",
    ("DIM_BRANCH", "COUNTRY_CODE"): "'NOR'",
    ("DIM_BRANCH", "IS_ACTIVE"): "1",
    ("DIM_DATE", "IS_NORWEGIAN_HOLIDAY"): "0",
    ("FACT_TRANSACTION", "TRANSACTION_CURRENCY"): "'NOK'",
    ("FACT_TRANSACTION", "EXCHANGE_RATE"): "1.000000",
    ("FACT_TRANSACTION", "IS_INTERNATIONAL"): "0",
    ("FACT_TRANSACTION", "IS_FLAGGED"): "0",
    ("FACT_MONTHLY_ACCOUNT_SNAPSHOT", "TOTAL_DEBITS"): "0",
    ("FACT_MONTHLY_ACCOUNT_SNAPSHOT", "TOTAL_CREDITS"): "0",
    ("FACT_MONTHLY_ACCOUNT_SNAPSHOT", "DEBIT_COUNT"): "0",
    ("FACT_MONTHLY_ACCOUNT_SNAPSHOT", "CREDIT_COUNT"): "0",
    ("FACT_MONTHLY_ACCOUNT_SNAPSHOT", "INTEREST_EARNED"): "0",
    ("FACT_MONTHLY_ACCOUNT_SNAPSHOT", "INTEREST_CHARGED"): "0",
    ("FACT_MONTHLY_ACCOUNT_SNAPSHOT", "FEES_CHARGED"): "0",
    ("FACT_MONTHLY_ACCOUNT_SNAPSHOT", "DAYS_IN_OVERDRAFT"): "0",
    ("FACT_MONTHLY_ACCOUNT_SNAPSHOT", "DAYS_DORMANT"): "0",
    ("FACT_MONTHLY_ACCOUNT_SNAPSHOT", "CURRENCY_CODE"): "'NOK'",
}

# ---------------------------------------------------------------------------
# IDENTITY / AUTOINCREMENT columns
# ---------------------------------------------------------------------------
EXPECTED_IDENTITY_COLUMNS = {
    "DIM_CUSTOMER": ["CUSTOMER_KEY"],
    "DIM_ACCOUNT": ["ACCOUNT_KEY"],
}

# ---------------------------------------------------------------------------
# TIMESTAMP columns to validate against the configured variant
# ---------------------------------------------------------------------------
EXPECTED_TIMESTAMP_COLUMNS = {
    "DIM_CUSTOMER": ["EFFECTIVE_FROM", "EFFECTIVE_TO", "ETL_INSERT_TS", "ETL_UPDATE_TS"],
    "DIM_ACCOUNT": ["EFFECTIVE_FROM", "EFFECTIVE_TO", "ETL_INSERT_TS", "ETL_UPDATE_TS"],
    "DIM_PRODUCT": ["ETL_INSERT_TS"],
    "DIM_BRANCH": ["ETL_INSERT_TS"],
    "FACT_TRANSACTION": ["TRANSACTION_TS", "ETL_INSERT_TS"],
    "FACT_MONTHLY_ACCOUNT_SNAPSHOT": ["ETL_INSERT_TS"],
}
