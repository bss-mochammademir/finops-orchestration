# infra — placeholder `[SCAFFOLD — WP1]`

Folder ini sengaja belum berisi *Infrastructure as Code*. IaC (Terraform) dijadwalkan pada **WP2** dan wajib melalui *change management* formal BSS karena menyentuh project `bss-prod-mgmt-1`.

Rencana komponen (draf, perlu verifikasi manusia):

| Komponen | Tujuan | Catatan keamanan |
|---|---|---|
| Cloud Scheduler | Pemicu mingguan (`mode=triage`) dan dua mingguan (`mode=report`) | Jadwal di *version control* (X04) |
| Cloud Run Job | Menjalankan `billing_sentinel.orchestrator.run` | Tanpa server dikelola (T01) |
| Service account khusus | Akses *read-only* ke billing export dan `fact_daily_cost` (`bigquery.dataViewer` + `bigquery.jobUser`) | Tanpa *static key*; *least privilege* (X01) |
| Secret Manager | Endpoint Chat/email | Tidak pernah di config atau kode (X02) |
| Dataset terbatas | `ref_project_routing`, `finding_events` | Berisi identitas tim/layanan; tidak dikirim ke model bahasa |

Setiap perubahan produksi memerlukan langkah verifikasi dan *rollback* (rollback awal: *disable* job di Cloud Scheduler; routine lama tetap aktif selama *parallel run*).
