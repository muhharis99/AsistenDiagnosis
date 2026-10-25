# Fase 7B — Perbaikan respons API dan klaim transmisi

**Status:** implementasi kode dan tes regresi pada branch fitur. Hasil CI harus diperiksa sebelum merge.

## Perubahan implementasi
- Klien sandbox menolak redirect sebelum mencoba membaca respons.
- Respons error non-JSON mempertahankan HTTP status tanpa membocorkan isi respons.
- Timeout/redirect pada POST dan PUT ditandai tidak pasti agar perlu rekonsiliasi.
- PUT Encounter dapat menerima pengakuan 204 No Content atau respons 2xx dengan body yang tidak dapat dibaca karena ID remote sudah dipastikan melalui mapping dan dicocokkan dengan path.
- POST 2xx dengan body tidak valid tetap berstatus uncertain; tidak dianggap berhasil tanpa ID resource dari body atau Location.
- Retry transmisi status failed menggunakan update compare-and-set dari failed ke sending. Hanya satu proses dapat memenangkan klaim.
- Pembuatan klaim pertama memiliki perlindungan unique constraint; proses yang kalah gagal tertutup sebelum request jaringan.

## Tes regresi
Tambahan tes fake transport meliputi:
- PUT 204 tanpa body dan PUT dengan body tidak bisa dibaca.
- POST sukses dengan JSON tidak valid.
- Redirect, HTTP 422/503 tanpa JSON, dan timeout PUT.
- Tidak mengirim ulang item yang sudah berstatus sending.
- Klaim retry failed dan peningkatan attempt count.

## Verifikasi
Jalankan:
```bash
python -m compileall -q rme rme_app.py scripts tests
pytest -q
```
CI memakai fake transport dan data sintetis. Lulus CI tidak membuktikan payload diterima SATUSEHAT staging atau memenuhi seluruh profil resmi.

## Batasan
Tidak ada perubahan skema database, default network-off, dan mode aplikasi tetap demo. Jangan mengirim data pasien nyata atau memakai prototipe untuk keputusan klinis.
