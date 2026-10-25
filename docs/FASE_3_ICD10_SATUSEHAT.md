# Fase 3 — Diagnosis terverifikasi dan SATUSEHAT mock

**Status:** prototipe lokal/demo. Semua pasien, kunjungan, dan data klinis harus fiktif.

## Yang diterapkan
- Entitas diagnosis manual dokter terpisah dari saran AI. Hanya dokter berizin yang dapat membuat diagnosis pada kunjungan aktif; dokter memilih apakah diagnosis masih provisional atau telah dikonfirmasi secara mandiri.
- Registry terminologi ICD-10 edisi 2010 dibaca dari CSV. Kode yang tidak ada atau tidak berstatus source-verified ditolak. CSV awal hanya memuat contoh resmi, bukan master lengkap.
- Peran Perekam Medis memverifikasi kode dan dokumentasi melalui catatan verifikasi wajib. Diagnosis provisional atau diagnosis tanpa verifikasi tidak dapat masuk outbox.
- Payload FHIR R4 lokal dibangun untuk Condition dan Composition. Bentuk dasar diperiksa di kode; pemeriksaan ini bukan validasi profil SATUSEHAT lengkap.
- Outbox menyimpan payload kanonis, hash SHA-256, status, jumlah percobaan, dan idempotency key. Antrean hanya dibuat jika kunjungan selesai, resume final, consent pembukaan/pemanfaatan data aktif, dan diagnosis/kode memenuhi prasyarat.
- Tindakan simulator mengubah status menjadi MOCK_ACCEPTED, menyimpan ringkasan respons dan audit; tidak membuat request jaringan.

## Prasyarat
1. Dokter menetapkan diagnosis manual dan mengonfirmasikannya; kandidat AI tidak disalin ke diagnosis resmi.
2. Perekam Medis memeriksa kecocokan kode terhadap dokumentasi klinis.
3. Persetujuan pembukaan/pemanfaatan data demo terakhir harus aktif.
4. Resume telah final dan status kunjungan sudah finished.
5. Barulah resource masuk outbox mock untuk inspeksi.

## Menjalankan pemeriksaan
    python -m compileall -q rme rme_app.py scripts tests
    pytest -q

## Referensi terminologi/interoperabilitas
- https://satusehat.kemkes.go.id/platform/docs/id/terminology/icd/icd-10/
- https://satusehat.kemkes.go.id/platform/docs/id/fhir/resources/condition/
- https://satusehat.kemkes.go.id/platform/docs/id/fhir/resources/composition/
- https://satusehat.kemkes.go.id/platform/docs/id/interoperability/rme-rawat-jalan/

## Belum termasuk
Master ICD-10 lengkap, import berlisensi yang diverifikasi, MPI/IHS lookup, mapping ID organisasi/tenaga kesehatan/lokasi, OAuth sandbox, transmisi resource, validasi profil resmi lengkap, handling OperationOutcome live, dan uji kesesuaian organisasi. Payload menggunakan reference demo dan domain .invalid; ini bukan payload untuk sandbox/production. APP_MODE=production tetap ditolak.
