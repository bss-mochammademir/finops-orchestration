# finops-billing-sentinel `[SCAFFOLD — WP1]`

Core deterministik untuk *health check* billing GCP Bank Sahabat Sampoerna (pengganti routine pribadi, lihat `greed-is-good` doc 11 dan `docs/handoff/gcp-billing-alert/HANDOFF.md`). Repositori ini direncanakan menjadi submodule `components/finops-billing-sentinel` di `greed-is-good`.

> **Status: SCAFFOLD — WP1.** Kode ini **perlu review manusia** sebelum dipakai di produksi. Tidak ada koneksi ke GCP, BigQuery, Vertex AI, Google Chat, atau email. Query SQL di `sql/` **belum pernah dijalankan** terhadap billing export — wajib *dry-run* (`bq query --dry_run`) dan cek *bytes scanned* di WP2.

## Prinsip

- **Angka dihitung oleh kode** (D-1). Status, klasifikasi, dan (nanti) skor tidak pernah berasal dari model bahasa.
- **Quality gate wajib** (D-2): laporan yang gagal validasi diarahkan ke *review* internal (`route = "review"`), bukan ke penerima.
- **Graceful degradation** (D-3): bila penyedia narasi gagal, dipakai `TemplateNarrativeProvider`.
- **Status anomali terpisah dari rekomendasi approval invoice** (F-6): kode tidak pernah menghasilkan teks persetujuan invoice; validator menolak frasa semacam itu.
- **Tanpa secret di kode/config**: config hanya berisi *threshold*, warna, dan *routing key*; loader menolak key yang menyerupai *credential* dan nilai berisi URL.

## Cara menjalankan test

Prasyarat: Python 3.11+ (hanya *standard library*) dan `pytest` untuk pengembangan.

```bash
python -m pip install pytest        # atau: pip install -e ".[dev]"
python -m pytest -q
python -m compileall src
grep -rniE "password|secret=|token=|webhook.*https" src config   # harus kosong
```

## Struktur

```
src/billing_sentinel/
  domain.py        dataclass CostRow, Period, Finding, RunResult; enum Status, FindingType, Confidence
  periods.py       periode setengah bulan (1–15, 16–akhir bulan), pembanding MoM + prior-half
  sources.py       Protocol CostSource, InMemoryCostSource; BigQueryCostSource = stub (WP2)
  analytics.py     agregasi per project/service/app_category
  classify.py      klasifikasi temuan + status
  coverage.py      C_ADR003 ketat (UNMAPPED tidak dihitung attributed)
  money.py         format Rupiah + parser shorthand "ribu/juta/miliar"
  validator.py     quality gate
  config.py        loader TOML (tomllib)
  orchestrator.py  run(mode, as_of, source, config) -> RunResult, run_id deterministik
  narrative.py     Protocol NarrativeProvider + TemplateNarrativeProvider (tanpa model bahasa)
  render.py, dispatch.py, scoring.py   stub NotImplementedError (WP2–WP4)
sql/               fact_daily_cost.sql (scheduled query), ddl.sql
config/example.toml
tests/             pytest; fixture regresi di tests/fixtures/oct2026.py
infra/README.md    placeholder IaC (WP2)
```

## Peta ABB → modul

| ABB (HANDOFF §5) | Modul / artefak | Status WP1 |
|---|---|---|
| A01 Orkestrasi & Penjadwalan | `orchestrator.py` (`run`, `make_run_id`); Cloud Scheduler/Run Job di `infra/` | Core selesai; penjadwalan WP2 |
| A02 Analitik Biaya (deterministik) | `periods.py`, `analytics.py`, `classify.py`, `coverage.py` | Selesai (perlu review) |
| A03 Mesin Scoring | `scoring.py` | Stub — WP4 |
| A04 AI Inference (narasi) | `narrative.py` (`NarrativeProvider`) | Template saja; provider model — WP4 |
| A05 Validator / Quality Gate | `validator.py`, `money.py` | Selesai (perlu review) |
| A06 Renderer Dua View | `render.py` | Stub — WP3/WP4 |
| A07 Dispatcher Notifikasi | `dispatch.py` | Stub — WP2 |
| D01 Fakta Biaya Harian | `sql/fact_daily_cost.sql`, `sql/ddl.sql`, `domain.CostRow` | SQL belum dijalankan |
| D02 Referensi App Category | `ref_app_category`, `ref_project_routing` di `sql/ddl.sql` | DDL saja |
| D03 Histori Temuan | `findings`, `finding_events` di `sql/ddl.sql`; `validator.check_finding_events` | DDL + aturan validator; migrasi WP2 |
| D04 Penyimpanan Skor | `finops_score` di `sql/ddl.sql` | DDL saja |
| X02 Manajemen Secret | `config.py` (penolakan key *credential*) | Guard saja; Secret Manager WP2 |
| X03 Observability (*dead man's switch*) | `dispatch.heartbeat` | Stub — WP2 |
| X04 Konfigurasi & IaC | `config/example.toml`, `infra/` | Config selesai; IaC WP2 |

## Aturan bisnis yang ter-*encode*

| Aturan | Lokasi | Test |
|---|---|---|
| 0 temuan → `Normal` (#2e7d32); ≥3 temuan *normal-confidence* atau lonjakan besar (>100% **dan** selisih > Rp1.000.000) → `Ada Indikasi Anomali` (#c62828); selain itu → `Perlu Perhatian` (#f9a825) | `classify.derive_status` | `test_status_rules.py` |
| *Lower-confidence* = border #9aa5b1, tidak ikut hitungan "≥3" dan tidak bisa menjadi lonjakan besar | `classify` | `test_status_rules.py` |
| Hanya `temuan_naik` yang dihitung untuk status; `penurunan_besar` dan *watchlist* hanya konteks | `classify.counted_findings` | `test_status_rules.py` |
| Group by `project.id`; `null` → `(unattributed)`; tanpa label → `UNMAPPED` | `analytics.py` | `test_analytics_coverage.py` |
| Rekonsiliasi Σ app_category == Σ project == total, toleransi eksplisit `[reconciliation] tolerance_idr = 40` | `validator.check_reconciliation` | `test_validator.py`, `test_regression_oct2026.py` |
| `acknowledged_normal` tanpa `expires_on` ditolak | `validator.check_finding_events` | `test_validator.py` |
| Angka narasi ⊂ angka hitungan; shorthand harus cocok | `validator.check_narrative_numbers` | `test_validator.py` |
| Hari terakhir < 0,7 × median harian → catatan otomatis | `validator.last_day_lag_note` | `test_validator.py`, `test_orchestrator.py` |
| `run_id` sama untuk (mode, periode, versi config) yang sama | `orchestrator.make_run_id` | `test_orchestrator.py` |

## Data regresi

`tests/fixtures/oct2026.py` memuat `RAW_PROJ` (total per project, disalin apa adanya dari `prototype/build.py`) untuk run 18–31 Oktober 2026. Hasil yang diuji: total **Rp47.587.313** vs **Rp44.416.052** (**+7,14%**), top 3 `bss-prod-ekyc-2`, `bss-master-network-1`, `bss-prod-notification-1`, status **Ada Indikasi Anomali** (3 amber + 1 abu, lonjakan Maps API).

Catatan penting:

- Data per service (`data.tsv`) tidak tersedia. Seluruh angka level service/SKU di fixture adalah **sintetis** (diberi label di file), kecuali beberapa angka SKU yang dikutip dari teks prototype.
- Pemetaan `ac_xxx` di fixture **sintetis** dan hanya untuk project yang dicontohkan eksplisit di ADR-003 (doc 03 §2); project lain sengaja dibiarkan `UNMAPPED`.
- Σ per project (dibulatkan) berselisih +3 (berjalan) dan +1 (pembanding) dari total ROLLUP. Fixture merekonstruksi pecahan Rupiah sehingga total tidak dibulatkan tepat sama; selisih tampilan diterima oleh toleransi eksplisit 40 (warisan *assert* prototype; batas teoretis 0,5 × jumlah baris).

## Asumsi yang perlu diverifikasi manusia

1. Mode `triage` memakai periode *half-month-to-date* s.d. H-1, dibandingkan MoM dengan *offset* hari yang sama.
2. Ambang klasifikasi di `config/example.toml` (lonjakan ≥25% dan ≥Rp250.000, biaya baru ≥Rp100.000, dsb.) adalah usulan awal, bukan hasil kalibrasi.
3. Ambang *lag* 0,7: kasus riil 31 Oktober (Rp2.463.398 vs ~Rp3.500.000 = 70,4%) **tidak** tertangkap pada ambang ini — lihat test `test_legacy_31_oct_case_is_borderline_at_70pct`.
4. `charge_date` = `DATE(usage_start_time)` dalam UTC, sama dengan routine lama.
5. Aturan `ac_046` dan `null → ac_052` menunggu keputusan IT Finance (gate G3).

## Keamanan

- Data billing agregat bukan data pribadi, tetapi `ref_project_routing` dan `finding_events.actor_principal` wajib di dataset terbatas dan tidak pernah dikirim ke model bahasa.
- Endpoint Chat/email adalah secret dan hanya di-*resolve* dari Secret Manager saat runtime (WP2).
- Tidak ada aksi remediasi otomatis; seluruh keluaran adalah masukan bagi keputusan manusia.
