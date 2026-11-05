SELECT
        'NEW_CUSTOMER_INTL' AS PATTERN_TYPE,
        c.CUSTOMER_ID,
        c.FIRST_NAME || ' ' || c.LAST_NAME AS CUSTOMER_NAME,
        c.ONBOARDING_DATE,
        (DATE '{{ var("as_of_date") }}' - c.ONBOARDING_DATE) AS DAYS_SINCE_ONBOARD,
        c.KYC_STATUS,
        COUNT(*) AS INTL_TXN_COUNT,
        SUM(ft.BASE_CURRENCY_AMOUNT) AS TOTAL_INTL_AMOUNT
    FROM {{ source('core', 'FACT_TRANSACTION') }} ft
    INNER JOIN {{ source('core', 'DIM_CUSTOMER') }} c
        ON ft.CUSTOMER_KEY = c.CUSTOMER_KEY AND c.CURRENT_FLAG = 'Y'
    WHERE ft.IS_INTERNATIONAL = 1
      AND ft.TRANSACTION_DATE BETWEEN (DATE '{{ var("as_of_date") }}' - 30) AND DATE '{{ var("as_of_date") }}'
      AND c.ONBOARDING_DATE >= (DATE '{{ var("as_of_date") }}' - 90)
    GROUP BY c.CUSTOMER_ID, c.FIRST_NAME, c.LAST_NAME,
             c.ONBOARDING_DATE, c.KYC_STATUS
    HAVING SUM(ft.BASE_CURRENCY_AMOUNT) >= 50000.00
    ORDER BY SUM(ft.BASE_CURRENCY_AMOUNT) DESC
