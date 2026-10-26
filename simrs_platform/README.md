# SIMRS Platform Foundation — Fase 1–2

Fondasi modular monolith Python/Django. Ini prototipe demo, bukan aplikasi rumah sakit operasional. Jangan masukkan data pasien nyata.

## Ruang lingkup
- Fase 1: unit organisasi, role assignment, terminologi berversi, MPI demo terenkripsi, dan audit hash-chain append-only.
- Fase 2: registrasi pasien dari MPI, antrean harian per unit, katalog tarif bertanggal efektif, invoice dengan snapshot harga, serta pencatatan pembayaran idempoten.
- API memeriksa role dan penugasan unit aktif. Audit tidak menyimpan nama pasien, NIK, password atau isi request.
- Mode demo dikunci ke APP_MODE=demo; gunakan hanya data sintetis.

## Menjalankan lokal
Persyaratan Python 3.12+ dan uv.

    cp .env.example .env
    uv sync --all-groups
    uv run python manage.py migrate
    uv run python manage.py createsuperuser
    uv run python manage.py runserver 127.0.0.1:8000

Atur MPI_ENCRYPTION_KEY dan MPI_HMAC_KEY di .env untuk operasi MPI. Jangan commit secret ke Git.

- Health: /api/health/
- OpenAPI: /api/docs/
- Registrasi pasien: POST/GET /api/frontoffice/registrations/
- Check-in antrean: POST /api/frontoffice/registrations/{id}/arrive/
- Antrean per unit: GET /api/frontoffice/queue/?unit_id={uuid}
- Aksi antrean: POST /api/frontoffice/queue/{ticket_id}/call/, /start/, /complete/, /cancel/
- Tarif: GET /api/cashier/tariffs/
- Invoice: POST/GET /api/cashier/invoices/ (GET wajib registration_id atau invoice_no)
- Terbitkan invoice: POST /api/cashier/invoices/{id}/issue/
- Catat pembayaran: POST /api/cashier/invoices/{id}/payments/

## Aturan transaksi
Registrasi hanya untuk pasien MPI aktif dan unit aktif. Nomor registrasi dan antrean dihitung per unit/tanggal. Transisi antrean terkontrol: WAITING → CALLED → SERVING → DONE; pembatalan hanya saat WAITING. Invoice memilih tarif yang berlaku pada tanggal kunjungan, lalu menyimpan snapshot kode, nama, harga dan kuantitas. Invoice harus diterbitkan sebelum pembayaran. Metode demo: tunai, transfer, debit, QRIS. Uang diterima tunai dihitung kembalian; pembayaran non-tunai wajib memiliki referensi; overpayment ditolak; idempotency_key mencegah pembayaran ganda saat request diulang.

## Validasi dan keterbatasan
CI membuat migrasi Django, menjalankan system checks, migrasi, pytest, lint dan compileall. Konkurensi penomoran/pembayaran perlu diuji lagi pada PostgreSQL; SQLite hanya untuk demo lokal. Refund/pembalikan finansial, rekonsiliasi bank, struk fiskal, klaim, integrasi resmi, pentest independen, UAT, serta persetujuan hukum/klinis/manajemen belum dikerjakan. Belum layak produksi.
