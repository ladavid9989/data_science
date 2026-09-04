-- BigQuery-oriented reference DDL. Replace the project and dataset names.

CREATE TABLE IF NOT EXISTS `PROJECT.analytics.fact_order`
(
  order_id STRING NOT NULL,
  customer_id STRING NOT NULL,
  order_date DATE NOT NULL,
  status STRING,
  currency STRING,
  total_amount NUMERIC,
  updated_at TIMESTAMP
)
PARTITION BY order_date
CLUSTER BY customer_id, status;

-- Verify bytes processed in the BigQuery UI before running a query. Use a
-- partition predicate so the engine can prune unrelated dates.
SELECT order_date, SUM(total_amount) AS revenue
FROM `PROJECT.analytics.fact_order`
WHERE order_date BETWEEN DATE '2026-01-01' AND DATE '2026-01-07'
GROUP BY order_date;

