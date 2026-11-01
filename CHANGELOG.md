# Changelog

Format mengikuti [Keep a Changelog](https://keepachangelog.com/) dan versi mengikuti SemVer.

## [0.1.0] — 2026-11-01 — `[SCAFFOLD — WP1]`

### Added
- Core deterministik `billing_sentinel`: domain, periode setengah bulan + MoM, agregasi (net = cost + credits, group by `project.id`, `(unattributed)`, `UNMAPPED`), klasifikasi temuan + status, coverage `C_ADR003` ketat, format/parser Rupiah, validator (*quality gate*), config TOML, orchestrator dengan `run_id` deterministik, narasi template.
- Stub `render`, `dispatch`, `scoring`, `BigQueryCostSource` (`NotImplementedError`, rujukan WP2–WP4).
- `sql/fact_daily_cost.sql` dan `sql/ddl.sql` (belum dijalankan).
- Test regresi run 18–31 Oktober 2026, test validator, periode, status, idempotency.
