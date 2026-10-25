# Fase 5 — Klien API SATUSEHAT sandbox (opt-in)

**Status:** implementasi klien dan jalur kirim satu-resource untuk data uji sintetis. Credential sandbox tidak disediakan oleh repository. Pengiriman hanya terjadi ketika operator mengaktifkan jaringan dengan sengaja.

## Yang diimplementasikan
- Klien OAuth2 client_credentials ke endpoint token resmi SATUSEHAT staging.
- HTTP client hanya mengizinkan host staging resmi, path resource yang di-allowlist, TLS verification, timeout eksplisit, dan penolakan redirect. Tidak ada opsi URL produksi.
- Token hanya disimpan sementara dalam memori proses. Token, client secret, NIK, payload klinis mentah, dan body OperationOutcome tidak masuk audit/log.
- Pencarian Patient MPI menggunakan query identifier=https://fhir.kemkes.go.id/id/nik|... berdasarkan dokumentasi resmi. Antarmuka hanya mengizinkan pencarian memakai NIK dari pasien demo lokal dengan consent aktif dan konfirmasi operator; respons ditampilkan sebagai ID pasien saja.
- Pengiriman hanya satu resource FHIR Condition atau Composition per aksi operator. Mapping Patient, Encounter, Practitioner, Organization, serta Location wajib verified.
- Composition baru boleh dikirim setelah Condition yang dirujuk memiliki respons sukses dan ID eksternal yang tercatat.
- Resource mock Fase 3 diubah menjadi payload create-ready: hapus ID lokal, ganti placeholder menjadi ID mapping verified, hilangkan extension .invalid, gunakan identifier lokal dengan Organization IHS, dan kode LOINC 88645-7 / kategori LP173421-1 untuk Resume Medis Rawat Jalan sebagaimana playbook.
- Ledger transmisi terpisah menyimpan status, HTTP status, external resource ID, jumlah percobaan, serta kode issue OperationOutcome yang aman; tidak menyimpan body respons mentah.
- Request yang timeout atau hasilnya tidak pasti menjadi uncertain. Sistem mencegah retry otomatis untuk menghindari duplikasi; operator perlu rekonsiliasi manual terlebih dahulu. Error HTTP 4xx yang jelas dapat diperiksa lalu dicoba ulang setelah penyebab diperbaiki.

## Aktivasi eksplisit pada environment lokal
Jangan taruh rahasia di repository, tiket, screenshot, atau log. Simpan kredensial sandbox yang sah di .env lokal yang tidak di-commit:

    APP_MODE=demo
    SATUSEHAT_MODE=sandbox
    SATUSEHAT_ENABLE_NETWORK=true
    SATUSEHAT_CLIENT_ID=<client id sandbox>
    SATUSEHAT_CLIENT_SECRET=<client secret sandbox>
    SATUSEHAT_ORG_IHS_ID=<organization IHS yang terikat pada credential>
    SATUSEHAT_BASE_URL=https://api-satusehat-stg.dto.kemkes.go.id/fhir-r4/v1
    SATUSEHAT_TOKEN_URL=https://api-satusehat-stg.dto.kemkes.go.id/oauth2/v1/accesstoken
    SATUSEHAT_TLS_VERIFY=true

SATUSEHAT_ENABLE_NETWORK=false adalah default. APP_MODE harus tetap demo; aplikasi belum mengizinkan mode produksi. Klien menolak URL selain staging dan tidak mengikuti redirect.

## Cara uji lokal
    python -m compileall -q rme rme_app.py scripts tests
    pytest -q

Semua tes memakai fake transport, bukan jaringan SATUSEHAT. Sebelum menyalakan jaringan, pastikan credential dan Organization IHS berasal dari portal sandbox yang berwenang; gunakan data sintetis, set mapping dengan sumber terpercaya, periksa preflight, dan kirim hanya satu resource pada satu waktu.

## Batasan
- CI menggunakan fake transport; keberhasilan tes tidak membuktikan bahwa credential atau payload diterima server staging sebenarnya.
- Ini bukan validasi penuh seluruh profil/terminologi SATUSEHAT. Tinjau playbook yang tepat, validasi resmi, resource identifier, master Patient/Practitioner/Organization/Location, dan aturan operasional fasilitas sebelum memakai hasil.
- Pencarian MPI tidak melakukan auto-match atau auto-save mapping; ID kandidat harus diverifikasi manusia sebelum disimpan.
- Tidak ada pencarian otomatis MNI, registrasi Patient/Encounter/Practitioner/Organization, batch Bundle/transaction, atau pengiriman data pasien nyata.
- Tidak ada retry otomatis untuk hasil POST yang tidak pasti. Rekonsiliasi manual dibutuhkan.
- Seluruh basis data aplikasi tetap dipaksa berisi data demo. Jangan memasukkan data pasien sungguhan atau memakai aplikasi ini dalam layanan klinis.

## Dokumentasi resmi yang digunakan
- Autentikasi OAuth client_credentials: https://satusehat.kemkes.go.id/platform/docs/id/api-catalogue/authentication/apis/token/
- API MPI dan endpoint resmi staging: https://satusehat.kemkes.go.id/platform/docs/id/master-data/master-patient-index/rest-api-mpi/
- Parameter pencarian Patient berdasarkan NIK: https://satusehat.kemkes.go.id/platform/docs/id/api-catalogue/onboardings/apis/patient/
- Resource Condition: https://satusehat.kemkes.go.id/platform/docs/id/fhir/resources/condition/
- Resource Composition: https://satusehat.kemkes.go.id/platform/docs/id/fhir/resources/composition/
- Playbook Resume Medis Rawat Jalan: https://satusehat.kemkes.go.id/platform/docs/id/interoperability/rme-rawat-jalan/
