-- Redshift-oriented reference DDL. This file is not executed by the DuckDB lab.
-- Choose distribution and sort keys only after understanding actual query and
-- table-size patterns; these examples support the dominant date/customer joins.

CREATE TABLE IF NOT EXISTS analytics.fact_order (
    order_id         VARCHAR(64)   NOT NULL,
    customer_id      VARCHAR(64)   NOT NULL,
    order_date       DATE          NOT NULL,
    status           VARCHAR(32),
    currency         VARCHAR(3),
    total_amount     DECIMAL(18,2),
    updated_at       TIMESTAMP
)
DISTSTYLE KEY
DISTKEY (customer_id)
SORTKEY (order_date, customer_id);

-- Typical S3 load shape:
-- COPY analytics.fact_order
-- FROM 's3://YOUR_BUCKET/gold/fact_order/'
-- IAM_ROLE 'arn:aws:iam::ACCOUNT_ID:role/YOUR_REDSHIFT_ROLE'
-- FORMAT AS PARQUET;

ANALYZE analytics.fact_order;

