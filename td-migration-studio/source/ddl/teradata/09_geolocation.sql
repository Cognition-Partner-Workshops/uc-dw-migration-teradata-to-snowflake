/* ~1M rows. Latitude/longitude kept as unbounded NUMBER (floating decimal) — a classic lossy-mapping case. */
CREATE MULTISET TABLE RETAIL_DW.GEOLOCATION, NO FALLBACK, NO BEFORE JOURNAL, NO AFTER JOURNAL, CHECKSUM = DEFAULT
(
    geolocation_zip_code_prefix  CHAR(5)      CHARACTER SET LATIN   NOT CASESPECIFIC NOT NULL,
    geolocation_lat              NUMBER,
    geolocation_lng              NUMBER,
    geolocation_city             VARCHAR(60)  CHARACTER SET UNICODE NOT CASESPECIFIC,
    geolocation_state            CHAR(2)      CHARACTER SET LATIN   NOT CASESPECIFIC
)
PRIMARY INDEX PI_GEOLOCATION (geolocation_zip_code_prefix);
