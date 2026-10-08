CREATE SET TABLE RETAIL_DW.PRODUCTS, NO FALLBACK, NO BEFORE JOURNAL, NO AFTER JOURNAL, CHECKSUM = DEFAULT
(
    product_id                  CHAR(32)    CHARACTER SET LATIN   NOT CASESPECIFIC NOT NULL,
    product_category_name       VARCHAR(60) CHARACTER SET UNICODE NOT CASESPECIFIC,
    product_name_lenght         SMALLINT,
    product_description_lenght  INTEGER,
    product_photos_qty          BYTEINT,
    product_weight_g            INTEGER,
    product_length_cm           SMALLINT,
    product_height_cm           SMALLINT,
    product_width_cm            SMALLINT,
    FOREIGN KEY (product_category_name) REFERENCES WITH NO CHECK OPTION RETAIL_DW.PRODUCT_CATEGORY_TRANSLATION (product_category_name)
)
UNIQUE PRIMARY INDEX UPI_PRODUCTS (product_id);
