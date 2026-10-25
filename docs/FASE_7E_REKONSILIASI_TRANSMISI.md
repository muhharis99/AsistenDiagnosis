# Fase 7E — Rekonsiliasi Transmisi Sandbox dan Dependensi Resource

## Tujuan

Mengatasi hasil tulis FHIR yang tidak pasti akibat timeout atau respons tidak lengkap tanpa mengirim ulang POST/PUT secara otomatis.

## Perubahan

- Tambah metode pembacaan resource sandbox secara terbatas: pencarian berbasis identifier untuk Condition, Composition, Observation, dan ClinicalImpression serta GET langsung hanya untuk Encounter dengan ID terpetakan yang aman.
- Tambah operasi eksplisit `reconcile_uncertain_transmission`, dibatasi pada data demo, izin SATUSEHAT, mode sandbox, dan opt-in jaringan.
- Jika hasil pencarian memberikan tepat satu resource bertipe benar, ID eksternal aman, dan identifier yang sama, status lokal dapat direkonsiliasi menjadi `succeeded`.
- Nol hasil, beberapa hasil, atau respons baca yang tidak meyakinkan tidak mengubah status menjadi sukses dan tidak memicu pengiriman ulang. Status tetap `uncertain` agar petugas melakukan pemeriksaan manual.
- ClinicalImpression memperoleh identifier deterministik agar dapat dicari secara aman setelah respons POST hilang.
- Tambah tes untuk kecocokan tunggal, tidak ada hasil, hasil ambigu, dan penolakan rekonsiliasi atas status selain `uncertain`.

## Batasan keamanan

Fitur ini hanya menyediakan alur rekonsiliasi eksplisit di sandbox. Tidak ada retry otomatis. Status `succeeded` hanya ditetapkan bila server mengembalikan satu hasil yang cocok. Jika snapshot Fase 6 sudah kedaluwarsa atau preflight tidak lagi terpenuhi, alur persiapan tetap memblokir rekonsiliasi otomatis dan perlu penanganan manual.

Tidak ada perubahan struktur database. Tidak ada pencatatan body FHIR mentah, token, NIK, atau diagnostik rahasia. Fitur ini tidak menggantikan uji integrasi SATUSEHAT resmi maupun validasi profil FHIR.

## Validasi

Perubahan harus melewati GitHub Actions untuk Python 3.11 dan 3.12 sebelum merge.
