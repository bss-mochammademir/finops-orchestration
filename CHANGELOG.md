# Changelog

Format mengikuti [Keep a Changelog](https://keepachangelog.com/) dan versi mengikuti SemVer.

## [Unreleased] — WP1b paritas routine lama

### Added
- Mode `legacy14` (L1); modul `history.py`: impor JSON histori skema v1 → baris `findings`, deteksi *gap*, aturan *recurring* / membaik-stabil / sudah diketahui (L4, L5).
- Aturan klasifikasi: kenaikan absolut relatif ke project, sumber biaya baru ≈0 (L2), biaya periodik/pecahan *lower-confidence* (L3), daftar pantau di luar top 3 (L8).
- Ikhtisar project + "Lainnya (N project)" (L6), rincian service top 3 dan *drill-down* SKU (L7), catatan metodologi untuk perubahan `project.name` dan Vertex AI Search pada project null (L9, L10).
- `render.build_subject` dan `render.build_plain_text` (L11); *plain-text body* ikut divalidasi; `orchestrator.is_dispatchable` (L12); label wajib "Project — Service" (L13).
- `docs/legacy-routine-parity.md`, fixture sintetis `tests/fixtures/legacy_synthetic.py` dan `legacy_history_v1.json`.

### Changed
- Temuan project baru dinamai dengan service terbesarnya (bukan `*`), sehingga `finding_key`-nya berubah.

## [0.1.0] — 2026-11-01 — `[SCAFFOLD — WP1]`

### Added
- Core deterministik `billing_sentinel`: domain, periode setengah bulan + MoM, agregasi (net = cost + credits, group by `project.id`, `(unattributed)`, `UNMAPPED`), klasifikasi temuan + status, coverage `C_ADR003` ketat, format/parser Rupiah, validator (*quality gate*), config TOML, orchestrator dengan `run_id` deterministik, narasi template.
- Stub `render`, `dispatch`, `scoring`, `BigQueryCostSource` (`NotImplementedError`, rujukan WP2–WP4).
- `sql/fact_daily_cost.sql` dan `sql/ddl.sql` (belum dijalankan).
- Test regresi run 18–31 Oktober 2026, test validator, periode, status, idempotency.
