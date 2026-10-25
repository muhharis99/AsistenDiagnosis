# Fase 4 — Persiapan identitas dan sandbox SATUSEHAT

**Status:** preflight lokal; tidak ada koneksi OAuth/HTTP dan tidak ada data yang dikirim.

## Fitur
- Tabel mapping sandbox memisahkan kunci lokal dari ID Patient/IHS, Practitioner/IHS, Organization/IHS, Location dan Encounter yang berasal dari sumber SATUSEHAT.
- Mapping baru belum terverifikasi. Verifikasi memerlukan sumber dan catatan tertulis. Jika external ID berubah, status verifikasi otomatis direset.
- Identifier yang masih berupa placeholder demo, mengandung example/.invalid, atau berformat tidak aman ditolak.
- RBAC memisahkan pengelolaan mapping teknis dari akses ke data klinis dan payload outbox. Admin Sistem dapat mengelola mapping teknis, tetapi tidak mendapat izin membaca diagnosis atau outbox.
- Preflight konfigurasi memeriksa mode sandbox, ketersediaan client ID/secret tanpa memunculkan nilai, IHS organisasi induk, URL staging yang di-allowlist, dan TLS verification.
- Preflight per kunjungan memeriksa status finished, resume final, consent pembukaan/pemanfaatan data, diagnosis confirmed dan coding terverifikasi, serta mapping Patient/Encounter/Practitioner/Organization/Location.
- Guard FHIR untuk sandbox menolak reference demo dan domain placeholder yang digunakan builder mock Fase 3.

## Konfigurasi environment
Tambahkan konfigurasi privat di file .env lokal. Jangan mengisi nilai asli ke repository atau log:
- SATUSEHAT_MODE=sandbox
- SATUSEHAT_CLIENT_ID
- SATUSEHAT_CLIENT_SECRET
- SATUSEHAT_ORG_IHS_ID
- SATUSEHAT_BASE_URL=https://api-satusehat-stg.dto.kemkes.go.id/fhir-r4/v1
- SATUSEHAT_TOKEN_URL=https://api-satusehat-stg.dto.kemkes.go.id/oauth2/v1/accesstoken
- SATUSEHAT_TLS_VERIFY=true

Mode aplikasi tetap APP_MODE=demo. Fase 4 tidak mengirim request; variabel konfigurasi hanya dibaca untuk pemeriksaan kesiapan. Jangan mengisi credential produksi pada lingkungan ini.

## Kunci mapping
- Patient: nilai kunci lokal adalah ID internal pasien.
- Practitioner: ID pengguna DPJP internal.
- Organization: ID fasilitas internal.
- Encounter: ID kunjungan internal.
- Location: facility_id:slug-poli, dengan teks poli dinormalisasi ke huruf kecil. Contoh untuk fasilitas 1 dan Poli Umum: 1:poli umum.
Gunakan ID dari master atau respons sandbox yang berwenang dan catat sumbernya. ID di data dummy dokumentasi tidak menjamin cocok untuk organisasi di luar skenario sandbox.

## Pengujian
    python -m compileall -q rme rme_app.py scripts tests
    pytest -q

## Batasan
- Ini preflight konfigurasi dan mapping, bukan bukti sukses integrasi atau validasi profil resmi penuh.
- Tidak ada OAuth, GET MPI/MNI, POST resource, retry jaringan, atau pembacaan OperationOutcome.
- Belum ada implementasi pengiriman sandbox. Hasil preflight yang lulus tidak mengaktifkan jaringan.
- Payload mock fase 3 tetap hanya untuk demo dan tidak boleh dikirim ke sandbox.
- Seluruh pasien dan kunjungan tetap fiktif, APP_MODE=production tetap ditolak.

## Referensi resmi yang diperiksa
- SATUSEHAT Patient / MPI: https://satusehat.kemkes.go.id/platform/docs/id/fhir/resources/patient/
- SATUSEHAT Practitioner / MNI: https://satusehat.kemkes.go.id/platform/docs/id/fhir/resources/practitioner/
- SATUSEHAT Organization: https://satusehat.kemkes.go.id/platform/docs/id/fhir/resources/organization/
- SATUSEHAT Location: https://satusehat.kemkes.go.id/platform/docs/id/fhir/resources/location/
- SATUSEHAT Encounter: https://satusehat.kemkes.go.id/platform/docs/id/fhir/resources/encounter/
- SATUSEHAT OAuth access token: https://satusehat.kemkes.go.id/platform/docs/id/api-catalogue/authentication/apis/token/
