# Paritas Aturan Routine Lama (WP1b)

> Chip **FINOPS-WP1b**. Kode dan analisis ini **perlu verifikasi manusia** sebelum dipakai di produksi. Seluruh *fixture* untuk aturan L2–L10 bersifat **sintetis** (`tests/fixtures/legacy_synthetic.py`, `tests/fixtures/legacy_history_v1.json`) dan tidak berasal dari *billing export*.

Tujuan: core deterministik dapat mereproduksi jendela waktu dan aturan routine lama untuk *parallel run* (kriteria keluar T1 "angka cocok dengan routine lama"), di samping mode baru (setengah bulan + MoM).

## Peta aturan → modul → test

Semua test ada di `tests/test_legacy_parity.py`.

| # | Aturan (ringkas) | Modul | Test |
|---|---|---|---|
| L1 | Mode `legacy14`: 14 hari berakhir kemarin vs 14 hari sebelumnya | `periods.legacy14_periods`, `resolve_periods`, `domain.Mode.LEGACY14` | `test_l1_legacy14_periods_as_of_2026_11_01`, `test_l1_legacy14_crosses_month_and_year`, `test_l1_legacy14_regression_totals_unchanged`, `test_l1_legacy14_run_id_differs_from_report_mode` |
| L2 | Naik ≥25%, kenaikan absolut besar relatif ke project, sumber biaya baru (≈0) | `classify.classify` (`spike`, `abs_rise_vs_project`, `new_cost_source`) | `test_l2_new_cost_source_and_abs_rise_vs_project`, `test_l2_near_zero_prior_counts_as_new_cost_source`, `test_l2_small_rise_not_flagged` |
| L3 | Biaya periodik/tahunan dan turun tepat menjadi pecahan → *lower-confidence* | `classify.exact_fraction`, `[classify] periodic_services`, `periodic_fractions` | `test_l3_periodic_service_is_lower_confidence`, `test_l3_drop_to_exact_half_is_lower_confidence`, `test_l3_periodic_alone_never_reaches_highest_status`, `test_l3_non_exact_drop_stays_normal` |
| L4 | *Recurring* ≥3 run, catatan "membaik/stabil", penurunan besar "sudah diketahui" | `history.apply_history`, `consecutive_runs` | `test_l4_recurring_below_threshold_still_flagged`, `test_l4_existing_finding_gets_recurring_count`, `test_l4_two_runs_is_not_recurring`, `test_l4_old_item_flat_gets_stable_note`, `test_l4_known_drop_still_low_not_reflagged`, `test_l4_known_drop_note_in_run` |
| L5 | Impor JSON histori skema v1 → baris `findings`; deteksi *gap* | `history.parse_legacy_history`, `load_legacy_history`, `to_findings_rows`, `gap_note` | `test_l5_import_synthetic_legacy_json`, `test_l5_fixture_is_labelled_synthetic`, `test_l5_rejects_invalid_documents`, `test_l5_rejects_unknown_item_type`, `test_l5_gap_detected`, `test_l5_gap_like_prototype_15_17_oct`, `test_l5_no_gap_when_contiguous_and_overlap_noted` |
| L6 | Ikhtisar ±12 project + "Lainnya (N project)", tetap rekonsiliasi | `analytics.project_overview`, `validator.check_reconciliation` | `test_l6_overview_folds_rest_and_reconciles`, `test_l6_no_fold_for_small_list`, `test_l6_broken_overview_fails_reconciliation` |
| L7 | Rincian per service top 3; *drill-down* SKU untuk sumber biaya baru dan penurunan besar | `analytics.service_breakdown`, `analytics.sku_drilldown`, `orchestrator.run` | `test_l7_service_breakdown_for_top3`, `test_l7_sku_drilldown_new_cost_and_drop` |
| L8 | Daftar pantau di luar top 3: *swing*, kategori biaya baru, storage tumbuh tanpa compute | `classify._watchlist` | `test_l8_watchlist_items`, `test_l8_storage_with_compute_growth_not_flagged`, `test_l8_watchlist_does_not_change_status` |
| L9 | `project.name` berubah → satu baris per `project.id` + satu catatan | `analytics.project_rename_note` | `test_l9_rename_one_row_one_note`, `test_l9_no_note_without_rename` |
| L10 | Project null berisi Vertex AI Search → catatan Gemini Enterprise | `analytics.null_project_hint_note`, `[methodology]` | `test_l10_null_project_vertex_ai_search_note`, `test_l10_no_note_for_other_null_rows` |
| L11 | Subjek `[GCP Billing Check] Status: … — {tgl} s.d. {tgl}` + *plain-text body* | `render.build_subject`, `render.build_plain_text`, `narrative.format_date_id` | `test_l11_subject_format`, `test_l11_plain_text_has_required_parts` |
| L12 | Self-check gagal → *review*, tidak pernah dipaksa kirim | `orchestrator.run`, `orchestrator.is_dispatchable`, `validator.validate_run` | `test_l12_failed_self_check_routes_to_review`, `test_l12_tampered_plain_text_fails_gate`, `test_l12_no_force_send_option`, `test_l12_valid_runs_are_dispatchable` |
| L13 | Setiap temuan menyebut "Project — Service" | `domain.Finding.label`, `validator.check_finding_labels`, `check_findings_named` | `test_l13_every_finding_names_project_and_service`, `test_l13_validator_rejects_missing_label`, `test_l13_narrative_must_name_each_counted_finding` |

## Regresi 18–31 Oktober 2026 dalam mode `legacy14`

`run("legacy14", as_of=2026-11-01)` menghasilkan periode 18–31 Oktober 2026 vs 4–17 Oktober 2026 tanpa *override* periode, dengan total **Rp47.587.313** / **Rp44.416.052** (+7,14%), top 3 dan status **Ada Indikasi Anomali** yang sama dengan WP1.

## Interpretasi yang dipilih (perlu dikonfirmasi)

1. **L2 "tipikal project"** ditafsirkan sebagai total project pada periode pembanding: kenaikan service ≥ `abs_rise_project_share_pct` (10%) dari total itu **dan** ≥ `spike_delta_min_idr`. Aturan L2 diterapkan ke semua project, bukan hanya top 3, sejalan dengan prototype yang memasukkan `bss-prod-pdaja-1` di luar top 3.
2. **L2 "≈0"**: biaya periode pembanding ≤ `new_cost_prior_max_idr` (Rp1.000).
3. **L3**: daftar service periodik (`Cloud Domains`, `Certificate Manager`, `Support`) dan pecahan (1/2, 1/3, 1/4, 2/3, 3/4, toleransi Rp1) adalah **usulan**; nama service harus dicocokkan dengan *billing export*.
4. **L4**: temuan *recurring* yang di bawah ambang ditandai sebagai `temuan_naik` *lower-confidence* (abu-abu). Ia membuat status minimal "Perlu Perhatian", tetapi tidak menaikkan status ke tingkat tertinggi sendirian. Syaratnya biaya masih naik pada run ini. "Berturut-turut" dihitung per entri histori, tanpa memperhitungkan *gap* tanggal.
5. **L4 "datar"**: |perubahan| ≤ `stable_pct_max` (10%) → "stabil". Bila turun lebih dari itu → "membaik". "Tetap rendah" berarti biaya kini ≤ biaya entri terakhir × (1 + 10%).
6. **L5**: dokumen dengan lebih dari 6 entri, urutan yang bukan *newest-last*, `schema_version` ≠ 1, atau `type` di luar empat nilai **ditolak** (tidak dipotong diam-diam). Kolom `confidence`, `app_category_code`, `driver_sku`, `recurring_count` pada baris migrasi diisi `NULL` karena tidak ada di skema lama. *Overlap* periode juga diberi catatan.
7. **L6**: tidak dilipat bila jumlah project ≤ 13 (baris "Lainnya (1 project)" tidak berguna).
8. **L8**: *swing* = |perubahan total project| ≥ 50% dan ≥ Rp100.000, dinamai dengan service pendorongnya. Kategori biaya baru = service baru ≥ Rp10.000 tetapi di bawah `new_cost_min_idr`. Storage tumbuh ≥ 20% dan ≥ Rp50.000 sementara compute ≤ +5%.
9. **L13**: temuan project baru kini dinamai dengan service terbesarnya, bukan `*`. Akibatnya `finding_key` temuan project baru berubah dibanding WP1. Hal ini belum berdampak karena belum ada data tersimpan.
10. **L11**: hanya subjek dan *plain-text body* yang diimplementasikan. *Plain-text body* ikut divalidasi oleh *quality gate*: angka, frasa approval, dan nama "Project — Service". HTML penuh dan PDF tetap WP3/WP4.

## Di luar lingkup

Tidak ada panggilan GCP/Drive/Gmail. Histori JSON dibaca dari berkas lokal yang ditunjuk pemanggil. Penerima tetap berupa *config key*. Tidak ada nama orang atau alamat email.
