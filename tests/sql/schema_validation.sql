-- ================================================================
-- Schema Validation Queries (Category 1: S-01 to S-09)
-- Run against Snowflake INFORMATION_SCHEMA
-- ================================================================

-- S-01: Verify all 7 tables exist
SELECT TABLE_NAME
FROM INFORMATION_SCHEMA.TABLES
WHERE TABLE_SCHEMA = '{schema}'
  AND TABLE_TYPE = 'BASE TABLE'
ORDER BY TABLE_NAME;

-- S-02: Verify all 3 views exist
SELECT TABLE_NAME
FROM INFORMATION_SCHEMA.VIEWS
WHERE TABLE_SCHEMA = '{schema}'
ORDER BY TABLE_NAME;

-- S-03: Verify column count per table
SELECT TABLE_NAME, COUNT(*) AS COLUMN_COUNT
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = '{schema}'
GROUP BY TABLE_NAME
ORDER BY TABLE_NAME;

-- S-04: Verify column names for a given table
SELECT COLUMN_NAME
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = '{schema}'
  AND TABLE_NAME = '{table_name}'
ORDER BY ORDINAL_POSITION;

-- S-05: Verify column data types
SELECT COLUMN_NAME, DATA_TYPE, NUMERIC_PRECISION, NUMERIC_SCALE
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = '{schema}'
  AND TABLE_NAME = '{table_name}'
  AND COLUMN_NAME = '{column_name}';

-- S-06: Verify NOT NULL constraints
SELECT COLUMN_NAME, IS_NULLABLE
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = '{schema}'
  AND TABLE_NAME = '{table_name}'
  AND COLUMN_NAME = '{column_name}';

-- S-07: Verify DEFAULT values
SELECT COLUMN_NAME, COLUMN_DEFAULT
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = '{schema}'
  AND TABLE_NAME = '{table_name}'
  AND COLUMN_NAME = '{column_name}';

-- S-08: Verify IDENTITY columns
SELECT COLUMN_NAME, IS_IDENTITY
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = '{schema}'
  AND TABLE_NAME = '{table_name}'
  AND COLUMN_NAME = '{column_name}';

-- S-09: Verify TIMESTAMP column types
SELECT COLUMN_NAME, DATA_TYPE
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = '{schema}'
  AND TABLE_NAME = '{table_name}'
  AND COLUMN_NAME = '{column_name}';
