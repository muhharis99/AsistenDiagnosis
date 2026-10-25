# Fase 6 — Resource lanjutan RME rawat jalan

**Status:** resource queue, validator lokal, dan jalur sandbox dengan fake transport. Ini bukan sertifikasi kesesuaian profil SATUSEHAT.

## Sumber use case
Playbook SATUSEHAT RME rawat jalan mengurutkan alur melalui pendaftaran Patient, kunjungan Encounter, anamnesis, pemeriksaan fisik memakai Observation, riwayat perjalanan penyakit menggunakan ClinicalImpression, dan resume Composition. Referensi teknis:
- https://satusehat.kemkes.go.id/platform/docs/id/interoperability/rme-rawat-jalan/
- https://satusehat.kemkes.go.id/platform/docs/id/fhir/resources/encounter/
- https://satusehat.kemkes.go.id/platform/docs/id/fhir/resources/observation/
- https://satusehat.kemkes.go.id/platform/docs/id/fhir/resources/clinical-impression/

## Yang diimplementasikan
- Builder Encounter update dengan identifier lokal, kelas AMB, statusHistory, classHistory, subject, DPJP, location, serviceProvider, period, serta diagnosis yang merujuk Condition berhasil.
- Builder Observation untuk tanda vital yang tersedia: panel tekanan darah dengan komponen sistolik/diastolik, denyut jantung, frekuensi napas, temperatur, SpO2, berat, tinggi, dan BMI. Nilai LOINC dan UCUM dimasukkan sebagai coding eksplisit sesuai use case tanda vital.
- Builder ClinicalImpression memakai anamnesis, subjektif, dan asesmen dokter yang telah dicatat. Tidak mengambil kandidat AI sebagai diagnosis atau prognosis.
- Antrean Phase 6 idempoten menggunakan outbox yang sudah ada. Kunci payload dan audit tetap aktif.
- Persiapan payload mengganti semua referensi placeholder dengan ID mapping yang verified. Observation membutuhkan mapping Practitioner pengukur; ClinicalImpression memerlukan Practitioner penandatangan; Encounter update harus mengacu ke Encounter sandbox yang sudah dipetakan.
- Composition hanya dapat dikirim setelah Condition, Observation, dan ClinicalImpression yang dirujuk memperoleh respons sukses. Referensi Observation ditambahkan ke section Pemeriksaan Fisik dan ClinicalImpression ke section Anamnesis.
- Klien dapat melakukan PUT pada Encounter yang telah dipetakan, dan POST pada Observation dan ClinicalImpression. ID remote harus sama dengan path PUT; TLS, URL staging, konfirmasi operator, dan network opt-in tetap diwajibkan.
- Status uncertain tetap memblokir retry otomatis.

## Urutan operator yang disarankan
1. Siapkan outbox Phase 6 dari kunjungan demo yang finished, resume final, consent data-sharing aktif, diagnosis confirmed serta kode terverifikasi, dan ada tanda vital.
2. Pastikan mapping sandbox verified untuk Patient, Encounter, Practitioner DPJP, Practitioner pengukur tanda vital, Organization, dan Location.
3. Kirim Condition (kecuali sudah dikirim berhasil), kemudian seluruh Observation, ClinicalImpression, Encounter update, terakhir Composition.
4. Periksa hasil dan kode masalah di ledger; jangan ulangi item dengan status uncertain sebelum rekonsiliasi manual.

Encounter pada fase ini adalah PUT untuk ID Encounter sandbox yang sudah dipetakan. Fase ini belum membuat Encounter baru dari kunjungan lokal tanpa mapping server lebih dahulu.

## Pengujian
    python -m compileall -q rme rme_app.py scripts tests
    pytest -q

Tes menggunakan fake HTTP transport. Tidak ada jaringan SATUSEHAT nyata pada CI; hasil tes tidak membuktikan kredensial atau payload diterima endpoint staging.

## Batasan
- Validasi adalah subset lokal untuk menghalangi placeholder dan field wajib yang relevan, bukan validator penuh profil SATUSEHAT.
- Mapping/LOINC/UCUM tetap harus dicocokkan dengan profil dan terminologi resmi terbaru serta aturan organisasi sebelum penggunaan.
- Hanya nilai tanda vital yang tersedia yang dibuat; belum ada ServiceRequest, DiagnosticReport, AllergyIntolerance, MedicationStatement, Goal, CarePlan, QuestionnaireResponse, atau resource rawat inap.
- Dataset aplikasi tetap sintetis dan APP_MODE=demo; jangan gunakan dalam pelayanan klinis atau kirim data pasien nyata.
