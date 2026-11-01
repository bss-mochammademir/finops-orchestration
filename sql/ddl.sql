-- DDL for the FinOps billing sentinel (SCAFFOLD — WP1). NOT YET EXECUTED.
-- Source: doc 11 §4 (delta on HANDOFF §6). Placeholder {{dataset}} = project.dataset.
-- Access: ref_project_routing and finding_events hold team/service identities and
-- must live in a restricted dataset; never sent to a language model.
-- HUMAN VERIFICATION REQUIRED (dry-run, IAM, retention) before WP2 deployment.

-- (1) Daily fact (D01). Column names chosen to map easily to FOCUS (doc 05).
CREATE TABLE IF NOT EXISTS `{{dataset}}.fact_daily_cost` (
  charge_date       DATE    NOT NULL,
  invoice_month     STRING,
  project_id        STRING  NOT NULL,   -- project.id; null -> '(unattributed)'
  app_category_code STRING  NOT NULL,   -- label at usage time; missing -> 'UNMAPPED'
  service_name      STRING,
  sku_name          STRING,
  gross_cost        NUMERIC,
  credits           NUMERIC,
  net_cost          NUMERIC,            -- gross_cost + credits
  currency          STRING
)
PARTITION BY charge_date
CLUSTER BY project_id, app_category_code, service_name
OPTIONS (require_partition_filter = TRUE);

-- (2) ADR-003 reference: code -> name. The ONLY source of category names (AMB-14).
CREATE TABLE IF NOT EXISTS `{{dataset}}.ref_app_category` (
  code       STRING NOT NULL,   -- ac_001 .. ac_052
  name       STRING NOT NULL,
  valid_from DATE   NOT NULL,
  valid_to   DATE,
  source_ref STRING             -- e.g. path/commit of application_category_mapping.csv
);

-- (3) Technical routing — team / space KEY only, never personal names (restricted dataset).
CREATE TABLE IF NOT EXISTS `{{dataset}}.ref_project_routing` (
  project_id      STRING NOT NULL,
  tech_owner_team STRING,
  chat_space_key  STRING,       -- resolved to an endpoint via Secret Manager at runtime
  valid_from      DATE   NOT NULL,
  valid_to        DATE
);

-- (4) Findings history (D03), append-only.
CREATE TABLE IF NOT EXISTS `{{dataset}}.findings` (
  run_id            STRING    NOT NULL,   -- deterministic idempotency key
  run_ts            TIMESTAMP NOT NULL,
  mode              STRING    NOT NULL,   -- triage | report
  period_start      DATE      NOT NULL,
  period_end        DATE      NOT NULL,
  level             STRING,               -- category | project | service
  app_category_code STRING,
  project_id        STRING,
  service           STRING,
  finding_key       STRING,               -- hash(project_id, service, type)
  type              STRING,               -- temuan_naik | penurunan_besar | watchlist | watchlist_new_cost
  confidence        STRING,               -- normal | lower
  cur               NUMERIC,
  prior             NUMERIC,
  pct_change        NUMERIC,
  driver_sku        STRING,
  recurring_count   INT64,
  note              STRING
)
PARTITION BY period_start;

-- (5) Human state of findings (closes doc 11 F-7), append-only.
-- Validator rule: state = 'acknowledged_normal' requires expires_on (enforced in code).
CREATE TABLE IF NOT EXISTS `{{dataset}}.finding_events` (
  finding_key     STRING    NOT NULL,
  event_ts        TIMESTAMP NOT NULL,
  state           STRING    NOT NULL,   -- new | investigating | acknowledged_normal | resolved | escalated
  actor_principal STRING,               -- system / service identity (restricted dataset)
  reason          STRING,
  expires_on      DATE
);

-- (6) FinOps score (D04). Closed periods are immutable; formula_version mandatory.
CREATE TABLE IF NOT EXISTS `{{dataset}}.finops_score` (
  period_start      DATE    NOT NULL,
  period_end        DATE    NOT NULL,
  app_category_code STRING  NOT NULL,
  score             NUMERIC,
  components        JSON,
  formula_version   STRING  NOT NULL    -- e.g. 'v0-coverage'
);
