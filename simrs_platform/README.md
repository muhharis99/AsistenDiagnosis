# SIMRS Platform Foundation — Fase 1–4

Fondasi modular monolith Python/Django ini merupakan prototipe demo, bukan aplikasi rumah sakit operasional. Gunakan hanya data sintetis; jangan masukkan data pasien nyata.

## Ruang lingkup

- Fase 1: unit organisasi, role assignment, terminologi berversi, MPI demo terenkripsi, dan audit hash-chain append-only.
- Fase 2: registrasi pasien dari MPI, antrean harian per unit, katalog tarif bertanggal efektif, invoice dengan snapshot harga, serta pencatatan pembayaran idempoten.
- Fase 3: encounter klinis, catatan RME append-only berversi, diagnosis, order obat/laboratorium/radiologi/tindakan, penyerahan obat parsial, hasil diagnostik berversi, serta admisi dan pemulangan ADT.
- Fase 4: master penjamin/paket, kepesertaan dan koordinasi penjamin (COB), alur klaim, adjudikasi demo, penerimaan penjamin/pasien, dan buku besar piutang append-only.
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
- Encounter, RME, diagnosis: /api/clinical/
- Order klinis: /api/orders/
- Penyerahan obat: /api/pharmacy/
- Hasil laboratorium/radiologi: /api/diagnostics/
- ADT admisi dan pemulangan: /api/adt/
- Master penjamin: GET/POST /api/payers/payers/.
- Paket penjamin: GET/POST /api/payers/plans/.
- Kepesertaan: GET/POST /api/payers/coverages/.
- Penetapan urutan COB: GET/POST /api/payers/registration-coverages/.
- Klaim per registrasi: GET /api/claims/claims/?registration_id={uuid}; klaim baru: POST /api/claims/claims/.
- Pengajuan klaim: POST /api/claims/claims/{claim_id}/submit/.
- Adjudikasi sintetis: POST /api/claims/claims/{claim_id}/adjudicate/.
- Penerimaan penjamin: POST /api/claims/claims/{claim_id}/remittances/.
- Pembayaran tanggung jawab pasien: POST /api/claims/claims/{claim_id}/patient-payments/.
- Ringkasan piutang per registrasi: GET /api/claims/receivables/?registration_id={uuid}.

## Aturan penjamin dan piutang

Kepesertaan harus aktif dan terverifikasi pada tanggal kunjungan. Penjamin diletakkan berurutan pada prioritas COB 1–3. Klaim pertama menggunakan total invoice yang terbit; klaim penjamin berikutnya hanya menggunakan sisa piutang pasien yang belum tertagih dari adjudikasi penjamin sebelumnya. Pengajuan membukukan piutang penjamin; adjudikasi membagi nominal ke nilai yang disetujui, ditolak, dan tanggung jawab pasien, yang harus tepat sama dengan nilai klaim. Penerimaan wajib memiliki referensi dan idempotency key, dan tidak boleh melebihi saldo terkait. Entri ledger, adjudikasi, baris klaim, dan penerimaan tidak boleh ditimpa atau dihapus.

## Batasan dan tindak lanjut

Adjudikasi di sini adalah input demo manual, bukan koneksi penjamin eksternal. Koreksi adjudikasi, reversal/refund, rekonsiliasi remittance, standar kode klaim, aturan manfaat plan, COB komersial yang sesungguhnya, pemetaan ke tarif/DRG, integrasi BPJS atau asuransi, dan perlakuan pajak/akuntansi belum diimplementasikan atau disertifikasi. Saldo klaim ini merupakan subledger demo terpisah dari pembayaran kasir Fase 2; integrasi posting silang perlu dirancang dan diuji sebelum operasional. Konkurensi wajib diuji pada PostgreSQL; SQLite hanya untuk demo lokal. Belum ada pentest independen, UAT, backup/restore, atau persetujuan hukum, klinis dan manajemen. Belum layak produksi.
