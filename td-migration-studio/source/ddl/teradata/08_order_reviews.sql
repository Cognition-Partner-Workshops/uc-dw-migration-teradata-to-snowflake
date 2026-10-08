/* review_id is NOT unique in the published Olist data (~800 duplicates): declared NUPI on purpose,
   logical key is (review_id, order_id). review_answer_timestamp is stored WITH TIME ZONE (America/Sao_Paulo, -03:00). */
CREATE MULTISET TABLE RETAIL_DW.ORDER_REVIEWS, NO FALLBACK, NO BEFORE JOURNAL, NO AFTER JOURNAL, CHECKSUM = DEFAULT
(
    review_id                CHAR(32)       CHARACTER SET LATIN   NOT CASESPECIFIC NOT NULL,
    order_id                 CHAR(32)       CHARACTER SET LATIN   NOT CASESPECIFIC NOT NULL,
    review_score             BYTEINT        NOT NULL,
    review_comment_title     VARCHAR(100)   CHARACTER SET UNICODE NOT CASESPECIFIC,
    review_comment_message   VARCHAR(5000)  CHARACTER SET UNICODE NOT CASESPECIFIC,
    review_creation_date     TIMESTAMP(0),
    review_answer_timestamp  TIMESTAMP(0) WITH TIME ZONE,
    FOREIGN KEY (order_id) REFERENCES WITH NO CHECK OPTION RETAIL_DW.ORDERS (order_id)
)
PRIMARY INDEX PI_ORDER_REVIEWS (review_id)
UNIQUE INDEX USI_ORDER_REVIEWS (review_id, order_id);
