# Fase 7D — Integritas Outbox dan Konsistensi Snapshot Klinis

## Tujuan

Mencegah payload antrean FHIR yang berubah, rusak, salah jenis, merujuk ke pasien/kunjungan lain, atau sudah kedaluwarsa terhadap sumber klinis agar tidak dikirim ke sandbox SATUSEHAT.

## Perubahan

- Verifikasi ulang SHA-256 dari byte teks `payload_json` sebelum persiapan payload.
- Fail closed jika payload bukan JSON-object, atau `resourceType` berbeda dari metadata outbox.
- Validasi ID lokal demo yang ditemukan secara rekursif di seluruh payload. Referensi Patient, Encounter, Observation, Condition, ClinicalImpression, dan Composition harus terhubung dengan pasien/kunjungan yang benar.
- Untuk item yang dibuat melalui antrean Fase 6, bangun ulang snapshot dari data klinis saat ini dan bandingkan representasi kanonisnya dengan snapshot yang disimpan. Perubahan diagnosis, tanda vital, anamnesis/resume, atau data Encounter/Composition setelah antrean dibuat akan memblokir persiapan/transmisi payload lama.
- Tambahkan tes regresi untuk hash tidak cocok, JSON rusak, ketidakcocokan jenis resource, referensi lintas pasien dengan hash yang dihitung ulang, dan perubahan sumber diagnosis setelah payload dibuat.

## Batasan dan cara pemulihan

Tidak ada perubahan struktur database dan tidak ada transmisi jaringan otomatis. Pemeriksaan ini bukan pengganti validator profil FHIR/SATUSEHAT atau persetujuan klinisi.

Jika payload Fase 6 sudah kedaluwarsa, item lama sengaja diblokir. Operator harus melakukan rekonsiliasi dan membuat snapshot antrean versi baru melalui alur aplikasi yang disetujui; sistem tidak mengirim ulang data lama atau mengubah catatan klinis otomatis. Pemeriksaan snapshot sumber hanya diterapkan pada item dengan kunci idempotensi `phase6:`; payload dari fase sebelumnya masih melewati pemeriksaan integritas, JSON, tipe resource, dan identitas lokal.

## Validasi

GitHub Actions harus menjalankan suite proyek pada Python yang dikonfigurasi oleh workflow. Merge hanya dilakukan setelah CI PR sukses.
