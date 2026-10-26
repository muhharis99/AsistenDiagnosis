# SIMRS Platform Foundation — Fase 1–3

Fondasi modular monolith Python/Django ini merupakan prototipe demo, bukan aplikasi rumah sakit operasional. Gunakan hanya data sintetis; jangan masukkan data pasien nyata.

## Ruang lingkup

- Fase 1: unit organisasi, role assignment, terminologi berversi, MPI demo terenkripsi, dan audit hash-chain append-only.
- Fase 2: registrasi pasien dari MPI, antrean harian per unit, katalog tarif bertanggal efektif, invoice dengan snapshot harga, serta pencatatan pembayaran idempoten.
- Fase 3: encounter klinis, catatan RME append-only berversi, diagnosis, order obat/laboratorium/radiologi/tindakan, penyerahan obat parsial, hasil diagnostik berversi, serta admisi dan pemulangan ADT.
- API memeriksa role dan penugasan unit. Audit tidak menyimpan nama pasien, NIK, password, instruksi medis, atau isi hasil.
- Mode demo dikunci ke APP_MODE=demo.

## Menjalankan lokal

Persyaratan Python 3.12+ dan uv.

    cp .env.example .env
    uv sync --all-groups
    uv run python manage.py migrate
    uv run python manage.py createsuperuser
    uv run python manage.py runserver 127.0.0.1:8000

Atur MPI_ENCRYPTION_KEY dan MPI_HMAC_KEY di .env untuk operasi MPI. Jangan commit secret ke Git.

## API utama

- Health: /api/health/
- OpenAPI: /api/docs/
- Registrasi dan antrean: /api/frontoffice/
- Tarif, invoice, pembayaran: /api/cashier/
- Encounter: POST/GET /api/clinical/encounters/ (GET membutuhkan unit_id).
- Catatan RME: GET/POST /api/clinical/encounters/{encounter_id}/notes/.
- Diagnosis: POST /api/clinical/encounters/{encounter_id}/diagnoses/.
- Order klinis: POST /api/orders/orders/; daftar order: GET /api/orders/orders/?encounter_id={uuid}.
- Pembatalan order: POST /api/orders/orders/{order_id}/cancel/.
- Penyerahan obat: GET/POST /api/pharmacy/orders/{order_id}/dispenses/.
- Hasil laboratorium/radiologi: GET/POST /api/diagnostics/orders/{order_id}/results/.
- ADT: GET/POST /api/adt/admissions/ (GET membutuhkan ward_unit_id).
- Pemulangan: POST /api/adt/admissions/{admission_id}/discharge/.

## Aturan klinis awal

Encounter hanya dapat dibuat dari registrasi yang sudah check-in atau sedang dilayani. Catatan RME dan hasil diagnostik tidak dapat ditimpa/dihapus melalui model; koreksi dibuat sebagai versi baru. Diagnosis utama kedua pada encounter ditolak. Order obat wajib berisi dosis, rute, frekuensi dan durasi; order laboratorium/radiologi membutuhkan indikasi. Order dibatalkan hanya dari status ORDERED. Penyerahan obat bisa parsial, tetapi jumlah total tidak boleh melebihi resep. Hasil final hanya dapat diperbaiki dengan amendemen baru. Admisi memerlukan ruang rawat aktif; pasien hanya dapat dipulangkan sekali melalui transisi status yang diaudit.

## Batasan dan tindak lanjut

Katalog order/obat belum terhubung ke formularium atau master pemeriksaan tervalidasi. Belum ada pengecekan alergi/interaksi, stok farmasi, validasi dosis, tanda tangan elektronik tersertifikasi, bed management, integrasi alat LIS/RIS, standar hasil terstruktur, maupun evaluasi klinis yang disetujui. Tidak ada integrasi BPJS/SATUSEHAT dalam fase ini. Konkurensi harus diuji pada PostgreSQL; SQLite hanya untuk demo lokal. Refund/pembalikan finansial, rekonsiliasi, pentest independen, UAT, backup/restore, dan persetujuan klinis/manajemen belum selesai. Belum layak produksi.
