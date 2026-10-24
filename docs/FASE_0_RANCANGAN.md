# Fase 0 — Rancangan prototipe RME rawat jalan dengan Asisten Diagnosis

**Status:** rancangan awal untuk ditinjau sebelum Fase 1.  
**Target runtime:** Python 3.10+, Streamlit, SQLAlchemy 2.x, SQLite untuk demo, PostgreSQL sebagai sasaran pengembangan.  
**Klasifikasi:** prototipe edukasi/riset dengan data fiktif; bukan untuk pelayanan klinis nyata dan bukan klaim kepatuhan/sertifikasi.

## 1. Prinsip rancangan

1. AI hanya membuat `SaranAI` berstatus saran/dugaan. Model tidak mempunyai jalur tulis ke diagnosis final. Dokter menetapkan diagnosis; Perekam Medis memverifikasi kode.
2. Semua layar dan database dalam mode demo menggunakan pasien serta data sintetis, `is_demo=true`, dan banner permanen `PROTOTIPE — DATA FIKTIF`. Aplikasi menolak `APP_MODE=production`.
3. Otorisasi dijalankan di service, bukan sekadar menyembunyikan tombol di UI.
4. Setiap akses baca dan perubahan klinis dicatat ke audit append-only berantai hash; data final tidak dihapus permanen. Koreksi awal dan addendum dipisahkan.
5. Input AI diproses hanya dari gejala/fitur klinis yang diperlukan. Persetujuan AI harus aktif sebelum inferensi. Hasil pasien tidak masuk log aplikasi.
6. SATUSEHAT default `mock`; `sandbox` hanya melalui kredensial .env dan data uji resmi. Tidak ada mode production.
7. Semua kode ICD-10/terminologi ditandai status verifikasi; yang tidak terverifikasi memakai `TODO-VERIFIKASI` dan tidak dikirim.

## 2. Arsitektur

```text
Streamlit multipage + CSS
    └── services (application/business use cases + RBAC + validasi)
          ├── domain (model SQLAlchemy, enum, schema Pydantic)
          ├── repositories (SQLAlchemy; SQLite demo / PostgreSQL target)
          ├── ml (adapter model gejala & skrining; hanya membuat saran)
          ├── terminology (ICD-10 edisi 2010, pemetaan kandidat, validator)
          ├── integrations/satusehat (FHIR R4, OAuth sandbox, mock, outbox)
          └── security (argon2, consent, audit chain, field encryption)
```

Aturan red flag dijalankan di `services/safety_service.py` sebelum pemanggilan model. Integrasi SATUSEHAT menerima hanya resource yang telah diverifikasi dan difinalisasi sesuai aturan domain; keluaran mentah AI tidak pernah dijadikan diagnosis/kondisi final atau dikirim sebagai diagnosis.

## 3. Skema entitas inti

- `Fasyankes`: id, nama fiktif, organization_id nullable, is_demo.
- `Pengguna`: id, username unik, password_hash Argon2, role_id, aktif, last_login_at.
- `Peran`: id, kode, nama; matriks permission eksplisit pada service.
- `Pasien`: id internal, no_rm unik, nama terenkripsi, NIK terenkripsi, NIK hash untuk pencarian yang dirancang aman, tanggal lahir, jenis kelamin, agama, pekerjaan, pendidikan, status perkawinan, alergi, is_demo.
- `Persetujuan`: pasien_id, jenis (umum/AI-assist/pembukaan data), status, pemberi/pihak keluarga, waktu UTC, versi teks.
- `Kunjungan`: id, pasien_id, nomor kunjungan, poli, DPJP, status arrived/in-progress/finished, waktu UTC, versi/finalized_at.
- `Anamnesis`: keluhan utama, gejala penyerta, riwayat pribadi/keluarga, alergi, obat yang digunakan, pembuat, waktu, revisi.
- `TandaVital`: sistolik/diastolik, nadi, napas, suhu, SpO2, berat, tinggi, IMT, UCUM/LOINC berstatus verifikasi.
- `SaranAI`: model_version, model/data hash, kode_version, created_at UTC, fitur gejala/fitur klinis tanpa identitas, kandidat dan skor, status; tidak mempunyai FK sebagai diagnosis final.
- `Diagnosis`: kode ICD-10, edisi, judul, primer/sekunder, status provisional/confirmed, asal dokter, pembuat, pengkode, waktu.
- `MasterICD10`, `PemetaanICD10`: sumber, edisi 2010, nama dataset, kandidat, status_verifikasi, sumber_verifikasi.
- `ResumeMedis`: ringkasan SOAP, penulis, waktu, status draft/final.
- `TandaTangan`: referensi dokumen, digest, signer, metode, waktu; demo menyatakan bukan TTE tersertifikasi.
- `OutboxSync`: resource type/id, status, idempotency key, attempt_count, next_attempt_at, response summary, last_error tanpa rahasia.
- `AuditLog`: actor, action, entity, entity_id, timestamp UTC, old/new redacted, previous_hash, entry_hash.
- `RegistriModel`: id, nama/version, sumber data, hash data, metrik, waktu train, versi pustaka, status demo/validated.

Kolom nullable/indeks/constraint final dirinci dan diuji pada fase implementasi; penyimpanan NIK dan nama wajib mengenkripsi-at-rest dengan kunci dari environment. Jangan pernah menyimpan secret di database atau Git.

## 4. Peran dan kewenangan minimum

| Peran | Wewenang utama |
|---|---|
| Admin Pendaftaran | buat/ubah data demografis dalam batas kewenangan, consent, registrasi dan antrean |
| Perawat | input tanda vital dan bagian pengkajian keperawatan |
| Dokter (DPJP) | anamnesis, meninjau/menolak/mengubah saran AI dengan alasan, menetapkan diagnosis, finalisasi resume |
| Perekam Medis | verifikasi/pengkodean ICD-10, administrasi metadata dan koreksi administratif sesuai aturan |
| Pimpinan | lihat audit/laporan sesuai kebijakan, persetujuan perubahan administratif setelah batas koreksi |
| Admin Sistem | kelola pengguna/konfigurasi teknis; tidak otomatis mendapat kewenangan membaca data klinis |

Hak akses detail dibuat sebagai permission matrix dalam service. Tindakan sensitif memerlukan otorisasi dan audit server-side.

## 5. Halaman UI

1. Dasbor: antrean hari ini, tugas menunggu verifikasi, outbox gagal/menunggu, indikator mock/sandbox, waktu WIB.
2. Pendaftaran: pencarian No. RM/NIK/nama yang terotorisasi, pasien fiktif, data sosial, consent, penanda pasien tanpa NIK/bayi untuk penanganan khusus.
3. Antrean Kunjungan: filter status, poli, DPJP, mulai pemeriksaan.
4. Pemeriksaan: banner pasien, status kunjungan, SOAP tabs (Anamnesis; Fisik & Tanda Vital; Penunjang; Asesmen & Diagnosis; Rencana; Resume), panel AI lipat, red flag di bagian teratas.
5. Resume Medis: preview, cek kelengkapan, konfirmasi finalisasi, simulasi tanda tangan non-sertifikasi, kunci kunjungan.
6. Integrasi SATUSEHAT: status outbox, retry terotorisasi, detail OperationOutcome tanpa credential/PHI berlebih.
7. Evaluasi Model: data source/demo badge, model card, metrik, confusion matrix/ROC/reliability, robust tests, versi dan hash.
8. Administrasi: pengguna, roles/permissions, registri ICD-10 dan model, status backup (bukan menyatakan backup offsite sudah dilakukan).
9. Tentang: label perangkat lunak, tujuan/larangan, status prototipe, keterbatasan, versi dan sumber regulasi.

## 6. Alur kunjungan

`arrived → in-progress → finished`. Pendaftaran membuat/mencari pasien dan consent. Perawat input tanda vital. Dokter mengisi anamnesis, memilih minimal tiga gejala jika ingin AI, melihat red flag, lalu memilih terima/ubah/abaikan saran (alasan wajib untuk ubah/abaikan). Hanya dokter menetapkan diagnosis. Perekam Medis memverifikasi kode. Dokter memeriksa resume, mengunci/finalisasi dan menandatangani simulasi. Data terverifikasi dimasukkan outbox; sinkronisasi mock diverifikasi dulu sebelum sandbox.

Koreksi biasa hanya oleh pembuat dalam jangka 2x24 jam yang dihitung dari waktu pencatatan yang disimpan UTC. Setelahnya perubahan klinis memakai addendum baru, mempertahankan versi sebelumnya. Perubahan administratif melewati approval yang diotorisasi.

## 7. TODO-VERIFIKASI sebelum implementasi / integrasi nyata

- Cocokkan tiap pasal Permenkes 24/2022 dengan teks JDIH dan nasihat hukum; prototipe tidak menyatakan telah memenuhi kewajiban retensi, akses, backup, keterhubungan, tanda tangan, atau registrasi.
- Import lampiran variabel/metadata KMK HK.01.07/MENKES/1423/2022; bila tidak tersedia, kamus data ditandai perlu dicocokkan.
- Verifikasi status/isi Kepmenkes HK.01.07/MENKES/951/2026 dan SEB 30 Juli 2026 dengan dokumen resmi, termasuk lingkup berlaku dan implikasi tanda tangan/izin edar.
- Verifikasi endpoint SATUSEHAT, token OAuth, FHIR R4 profile, MPI search, identifier, kode `Composition`, status Encounter, batas tanggal, terminologi dan versioning langsung di dokumentasi resmi yang berlaku pada saat uji.
- Import master ICD-10 edisi 2010 yang lisensinya sah; jangan menyimpulkan kode hanya dari nama penyakit. Lengkapi `terminology/icd10_mapping.csv` untuk seluruh 41 kelas dengan sumber dan status, `TODO-VERIFIKASI` bila belum yakin.
- Verifikasi SNOMED CT dan LOINC/UCUM yang akan digunakan; gejala yang belum diverifikasi tidak dikirim.
- Tinjauan klinis semua red flag, teks pesan, batas rentang tanda vital, terjemahan gejala dan saran umum.
- Threat model, manajemen kunci/enkripsi, kebijakan akses RM, retention, backup terenkripsi di lokasi berbeda, uji pemulihan, uji penetrasi, dan review UU PDP.
- Pastikan apakah prototype dimaksudkan untuk local single-user demo atau multi-user deployment; sampai ada keputusan, targetnya demo lokal dengan data sintetis.

## 8. Sumber awal yang telah ditemukan

- JDIH Kemenkes, Permenkes 24/2022: https://jdih.kemkes.go.id/documents/peraturan-menteri-kesehatan-nomor-24-tahun-2022
- SATUSEHAT Platform, Resume Medis Rawat Jalan: https://satusehat.kemkes.go.id/platform/docs/id/interoperability/rme-rawat-jalan/
- SATUSEHAT Platform, Composition: https://satusehat.kemkes.go.id/platform/docs/id/fhir/resources/composition/
- BPK RI, UU 27/2022 PDP: https://peraturan.bpk.go.id/Details/229798/uu-no-27-tahun-2022
- Kemenkes, informasi SEB integrasi RME–SATUSEHAT untuk tata kelola klaim JKN (terbit 2026; teks SEB primer masih perlu diambil dan dibandingkan): https://keslan.kemkes.go.id/read/4087/kemenkes-perkuat-tata-kelola-klaim-jkn-melalui-integrasi-rekam-medis-elektronik-dengan-satusehat

**Catatan tanggal:** Kepmenkes HK.01.07/MENKES/951/2026 yang disebut bertanggal 7 September 2026 dan teks lengkap SEB 30 Juli 2026 belum dianggap terverifikasi hanya berdasarkan ringkasan. Periksa dokumen primer sebelum matriks kepatuhan dipastikan.
