CREATE MULTISET TABLE RETAIL_DW.ORDER_PAYMENTS, NO FALLBACK, NO BEFORE JOURNAL, NO AFTER JOURNAL, CHECKSUM = DEFAULT
(
    order_id              CHAR(32)      CHARACTER SET LATIN NOT CASESPECIFIC NOT NULL,
    payment_sequential    SMALLINT      NOT NULL,
    payment_type          VARCHAR(20)   CHARACTER SET LATIN NOT CASESPECIFIC
                                        COMPRESS ('credit_card','boleto','voucher','debit_card','not_defined'),
    payment_installments  BYTEINT,
    payment_value         DECIMAL(12,2) NOT NULL,
    FOREIGN KEY (order_id) REFERENCES WITH NO CHECK OPTION RETAIL_DW.ORDERS (order_id)
)
PRIMARY INDEX PI_ORDER_PAYMENTS (order_id)
UNIQUE INDEX USI_ORDER_PAYMENTS (order_id, payment_sequential);
