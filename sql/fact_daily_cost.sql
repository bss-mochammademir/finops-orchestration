-- fact_daily_cost — scheduled query (SCAFFOLD — WP1). NOT YET EXECUTED.
--
-- HUMAN VERIFICATION REQUIRED before use (WP2):
--   * run with `bq query --dry_run` and check bytes scanned;
--   * confirm the partition column of the billing export table (standard export
--     tables are partitioned on _PARTITIONTIME; adjust if different);
--   * confirm the late-arrival window below (billing rows can be restated for
--     several days after usage).
--
-- Placeholders (substituted by deployment tooling in WP2, never hard-coded here):
--   {{billing_export_table}}  fully qualified billing export table
--   {{dataset}}               fully qualified FinOps dataset (project.dataset)
-- Parameters:
--   @start_date DATE, @end_date DATE   usage dates to (re)build, inclusive
--
-- Rules encoded (doc 11 §4, lessons §8.4–§8.6):
--   * charge_date = DATE(usage_start_time) (UTC, same as the legacy routine);
--   * group by project.id (never project.name); null project.id -> '(unattributed)';
--   * app_category_code = project label 'application_category' AT USAGE TIME,
--     taken from the row itself; missing -> 'UNMAPPED' (never defaults to ac_046);
--   * net_cost = cost + SUM(credits.amount);
--   * idempotent: the date range is deleted then re-inserted in one script.

DECLARE late_arrival_days INT64 DEFAULT 5;

BEGIN TRANSACTION;

DELETE FROM `{{dataset}}.fact_daily_cost`
WHERE charge_date BETWEEN @start_date AND @end_date;

INSERT INTO `{{dataset}}.fact_daily_cost`
  (charge_date, invoice_month, project_id, app_category_code,
   service_name, sku_name, gross_cost, credits, net_cost, currency)
WITH src AS (
  SELECT
    DATE(usage_start_time) AS charge_date,
    invoice.month AS invoice_month,
    IFNULL(project.id, '(unattributed)') AS project_id,
    IFNULL(
      NULLIF(TRIM((SELECT l.value FROM UNNEST(project.labels) l
                   WHERE l.key = 'application_category' LIMIT 1)), ''),
      'UNMAPPED') AS app_category_code,
    service.description AS service_name,
    sku.description AS sku_name,
    CAST(cost AS NUMERIC) AS gross_cost,
    CAST(IFNULL((SELECT SUM(c.amount) FROM UNNEST(credits) c), 0) AS NUMERIC) AS credits,
    currency
  FROM `{{billing_export_table}}`
  -- Partition pruning: only partitions that can contain the usage window.
  WHERE DATE(_PARTITIONTIME) BETWEEN @start_date
                                 AND DATE_ADD(@end_date, INTERVAL late_arrival_days DAY)
    AND DATE(usage_start_time) BETWEEN @start_date AND @end_date
)
SELECT
  charge_date, invoice_month, project_id, app_category_code,
  service_name, sku_name,
  SUM(gross_cost) AS gross_cost,
  SUM(credits) AS credits,
  SUM(gross_cost) + SUM(credits) AS net_cost,
  currency
FROM src
GROUP BY charge_date, invoice_month, project_id, app_category_code,
         service_name, sku_name, currency;

COMMIT TRANSACTION;
