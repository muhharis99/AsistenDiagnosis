# Fase 7H — Pengujian kontrak FHIR dan kegagalan end-to-end

## Tujuan

Memperkuat tes atas kontrak payload sandbox serta perilaku aplikasi ketika hasil transmisi tidak pasti. Semua skenario menggunakan data sintetis dan fake transport; tidak ada request jaringan nyata.

## Cakupan tes

- Struktur minimum dan referensi untuk Condition, Composition, Observation, ClinicalImpression, serta Encounter update.
- Penolakan placeholder demo/mock, referensi lintas tipe resource yang keliru, dan ID lokal pada operasi create.
- Simulasi respons HTTP 201 tanpa ID resource yang dapat dipercaya.
- Simulasi HTTP 5xx, yang dapat terjadi setelah server memproses sebagian permintaan.
- Jaminan bahwa kedua kondisi di atas tetap `uncertain` dan tidak memicu pengiriman POST ulang otomatis.

## Makna hasil

- Tes kontrak lokal adalah subset structural guard yang ada di aplikasi. Itu bukan validator lengkap FHIR R4 atau profil resmi SATUSEHAT.
- HTTP 201 tanpa ID resource tidak cukup untuk menandai transmisi berhasil; perlu rekonsiliasi eksplisit.
- HTTP 5xx atau timeout setelah operasi tulis tidak membuktikan bahwa server belum menerima resource. Status tetap tidak pasti dan POST/PUT tidak boleh diulang tanpa proses rekonsiliasi.
- Lulus CI hanya menunjukkan perilaku kode yang diuji dengan fixture sintetis; bukan bukti keberhasilan OAuth, koneksi staging, penerimaan resource, kepatuhan, atau kesiapan produksi.

## Batas perubahan

- Tidak ada perubahan struktur database.
- Tidak ada perubahan kredensial, endpoint, atau default jaringan nonaktif.
- Tidak ada koneksi jaringan nyata dari tes.
