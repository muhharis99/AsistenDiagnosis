# Fase 7G — Kesiapan operasional SATUSEHAT sandbox

## Tujuan

Menyediakan ringkasan operasional yang aman untuk konfigurasi sandbox, status agregat outbox/transmisi demo, dan integritas audit. Fitur ini menggabungkan pemeriksaan yang sudah ada; bukan penguji koneksi dan bukan tombol transmisi.

## Yang dilakukan

- Menampilkan hasil pemeriksaan konfigurasi yang sudah tersedia tanpa mengungkap client ID, secret, token, payload, atau data pasien.
- Menghitung status outbox demo dan transmisi demo secara agregat.
- Menandai status `sending` dan `uncertain` sebagai hal yang perlu ditinjau operator sebelum melanjutkan proses.
- Memverifikasi hash-chain audit, termasuk pemeriksaan ulang setelah event audit pemeriksaan dicatat.
- Menambahkan satu event audit ringkas untuk tindakan pemeriksaan.

## Interpretasi status

- `BLOCKED`: pemeriksaan konfigurasi gagal atau hash-chain audit tidak valid. Jangan lakukan pengiriman baru melalui alur operasional sampai masalah ditangani.
- `REVIEW_REQUIRED`: jaringan masih nonaktif, atau terdapat transmisi `sending`/`uncertain` yang perlu ditinjau. Jaringan yang nonaktif adalah default aman, bukan kesalahan deployment.
- `ELIGIBLE_FOR_OPERATOR_REVIEW`: konfigurasi lokal lolos, opt-in jaringan terpasang, tidak ditemukan status belum pasti/masih mengirim, dan audit valid pada saat pemeriksaan. Ini hanya prasyarat tinjauan operator; **bukan** otorisasi otomatis, bukti OAuth berhasil, bukti koneksi, atau bukti resource diterima server.

## Cara menggunakan

1. Buka menu **Integrasi SATUSEHAT** dengan akun yang memiliki izin baca integrasi.
2. Buka bagian **Fase 7G — Kesiapan operasional sandbox** dan jalankan pemeriksaan.
3. Tinjau ringkasan, daftar pemeriksaan konfigurasi, jumlah per status, dan hasil audit.
4. Jika ada status `uncertain` atau `sending`, ikuti proses rekonsiliasi/manual review yang sudah ada. Jangan mengulang POST/PUT berdasarkan ringkasan ini.
5. Jika hash-chain audit tidak valid, simpan waktu pemeriksaan dan ID entri pertama yang gagal dalam tiket terkontrol. Jangan perbaiki hash secara manual.

## Batasan dan keselamatan

- Pemeriksaan tidak membuat request jaringan, tidak memperoleh token OAuth, tidak mengirim POST/PUT, dan tidak mengubah outbox atau status transmisi.
- Saat dibuka, pemeriksaan menambahkan event audit yang hanya berisi status/angka agregat serta booleans, tanpa nilai secret, payload, NIK, atau respons mentah.
- Tidak ada perubahan skema database.
- Tes menggunakan SQLite in-memory, data demo sintetis, dan tidak mengakses SATUSEHAT.
- Lulus tes tidak membuktikan kesesuaian profil FHIR/SATUSEHAT, penerimaan staging, validasi klinis, kepatuhan hukum, atau kesiapan produksi.
