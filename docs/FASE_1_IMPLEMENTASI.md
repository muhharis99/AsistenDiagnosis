# Fase 1 — Fondasi RME rawat jalan

**Status:** implementasi prototipe demo. Semua identitas dan kunjungan adalah fiktif. Tidak ada klaim kepatuhan penuh, validasi klinis, atau status alat kesehatan berizin.

## Implementasi pada fase ini

- Login akun demo menggunakan Argon2, rate limit percobaan login dalam memori, timeout idle, serta hak akses peran yang diperiksa di layer service.
- Data pasien disimpan dengan nama dan NIK terenkripsi Fernet. NIK dicari menggunakan HMAC dan dimasking secara default. Nama/NIK plaintext tidak disimpan dalam audit.
- Pasien dan kunjungan dipaksa berstatus data demo lewat validasi dan constraint database.
- Persetujuan umum, pembukaan/pemanfaatan data, AI-assist dan persetujuan keluarga/wali dicatat terpisah. Pasien di bawah 18 tahun ditolak tanpa consent keluarga/wali.
- Alur status kunjungan: arrived → in-progress → finished. Kunjungan hanya dapat selesai setelah resume difinalisasi oleh dokter.
- SOAP: anamnesis, tanda vital dengan validasi rentang, BMI turunan, draf resume, finalisasi dan digest tanda tangan simulasi.
- Koreksi resume hanya untuk pembuat dalam 48 jam dengan revision history. Setelah batas, koreksi harus menjadi addendum agar konten final lama tidak ditimpa.
- Audit append-only dengan hash-chain, verifikasi hash, dan trigger database untuk menolak UPDATE/DELETE pada SQLite/PostgreSQL.
- Data dictionary awal tersedia di `docs/kamus_data_fase1.csv`. Kolom/terminologi yang belum diverifikasi masih ditandai `TODO-VERIFIKASI`.

## Menyiapkan demo

Jalankan dari root repository:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/init_demo.py
streamlit run rme_app.py
```

Pada Windows PowerShell, aktivasi venv adalah `.venv\\Scripts\\Activate.ps1`.

Akun demo:
- `pendaftaran_demo / DemoDaftar!2026`
- `perawat_demo / DemoPerawat!2026`
- `dokter_demo / DemoDokter!2026`
- `rekam_medis_demo / DemoRekam!2026`
- `pimpinan_demo / DemoPimpinan!2026`
- `admin_sistem_demo / DemoSistem!2026`

Kredensial itu hanya untuk localhost. Jangan buka aplikasi ke jaringan umum. `.env`, kunci enkripsi, file SQLite dan data runtime tidak boleh di-commit. Kehilangan kunci enkripsi akan membuat nama/NIK demo tidak bisa didekripsi.

## Tes dan batasan

```bash
python -m compileall -q rme rme_app.py scripts tests
pytest -q
```

Tes unit mencakup field sensitif terenkripsi, consent, RBAC, validasi tanda vital, state machine kunjungan, resume, aturan koreksi 48 jam dan audit append-only.

Mode selain `APP_MODE=demo` ditolak. Nama/NIK terenkripsi pada level field, tetapi kolom catatan klinis tidak dienkripsi aplikasi pada fase ini; lindungi file database/volume dan akses host. Audit hash-chain membutuhkan pengaturan transaksi yang sesuai jika kelak dijalankan pada multiworker. Backup terenkripsi di lokasi berbeda, manajemen kunci profesional, pemulihan bencana, TTE tersertifikasi, IAM produksi, uji penetrasi dan tinjauan kepatuhan masih di luar kode fase ini.

AI belum dihubungkan ke alur RME pada fase ini. SATUSEHAT belum mengirim data dan baru disiapkan sebagai placeholder pada UI; FHIR builder, OAuth, outbox, MPI dan sandbox akan dibuat pada fase berikutnya.

## Sumber awal

- JDIH Kemenkes, Permenkes 24/2022 tentang Rekam Medis: https://jdih.kemkes.go.id/documents/peraturan-menteri-kesehatan-nomor-24-tahun-2022
- BPK RI, UU 27/2022 tentang Pelindungan Data Pribadi: https://peraturan.bpk.go.id/Details/229798/uu-no-27-tahun-2022
- SATUSEHAT Platform, Resume Medis Rawat Jalan (riwayat versi terlihat pada dokumentasi): https://satusehat.kemkes.go.id/platform/docs/id/interoperability/rme-rawat-jalan/
- Kepmenkes/SKB/SEB lain yang tercantum di spesifikasi fase tidak dianggap terverifikasi sampai teks resmi primer dibaca dan dicocokkan.
