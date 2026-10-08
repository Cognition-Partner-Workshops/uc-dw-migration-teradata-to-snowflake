CREATE MULTISET TABLE RETAIL_DW.ORDERS, NO FALLBACK, NO BEFORE JOURNAL, NO AFTER JOURNAL, CHECKSUM = DEFAULT
(
    order_id                       CHAR(32)     CHARACTER SET LATIN NOT CASESPECIFIC NOT NULL,
    customer_id                    CHAR(32)     CHARACTER SET LATIN NOT CASESPECIFIC NOT NULL,
    order_status                   VARCHAR(20)  CHARACTER SET LATIN NOT CASESPECIFIC
                                                COMPRESS ('delivered','shipped','canceled','invoiced','processing','unavailable','approved','created'),
    order_purchase_timestamp       TIMESTAMP(0) NOT NULL,
    order_approved_at              TIMESTAMP(0),
    order_delivered_carrier_date   TIMESTAMP(0),
    order_delivered_customer_date  TIMESTAMP(0),
    order_estimated_delivery_date  DATE FORMAT 'YYYY-MM-DD',
    FOREIGN KEY (customer_id) REFERENCES WITH NO CHECK OPTION RETAIL_DW.CUSTOMERS (customer_id)
)
PRIMARY INDEX PI_ORDERS (order_id)
PARTITION BY RANGE_N(CAST(order_purchase_timestamp AS DATE) BETWEEN DATE '2016-01-01' AND DATE '2018-12-31' EACH INTERVAL '1' MONTH, NO RANGE)
UNIQUE INDEX USI_ORDERS (order_id);
