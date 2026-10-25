# Fase 7 — Audit keamanan, konsistensi integrasi, dan kesiapan validasi

**Status:** rencana audit dan kriteria penerimaan. Dokumen ini bukan hasil audit independen, validasi klinis, atau sertifikasi SATUSEHAT.

## Tujuan
Sebelum menambahkan koneksi/resource klinis baru, periksa jalur yang sudah tersedia pada Fase 1–6. Semua pengujian otomatis harus menggunakan pasien, NIK, nilai klinis, credential, dan respons server sintetis atau fake transport.

## Kriteria penerimaan

### A. Keamanan integrasi
- [ ] Jaringan nonaktif secara default dan konfigurasi produksi ditolak.
- [ ] TLS selalu diverifikasi; redirect tidak diikuti.
- [ ] Secret, token, NIK, dan payload klinis mentah tidak ditulis ke log/audit.
- [ ] Path dan metode HTTP hanya menerima allowlist resource yang eksplisit.
- [ ] POST/PUT dengan respons tidak lengkap, timeout, atau redirect tidak dianggap sukses.
- [ ] Status uncertain tidak dapat dikirim ulang secara otomatis.
- [ ] Token tidak dikembalikan ke antarmuka, log, atau ledger.
- [ ] Kesalahan transport tetap memiliki pesan aman dan tidak menyertakan exception/response mentah.

### B. Otorisasi dan consent
- [ ] Semua operasi integrasi memeriksa permission di service, bukan hanya menyembunyikan tombol UI.
- [ ] Pemeriksaan consent dilakukan saat mencari MPI dan sesaat sebelum menyiapkan/mengirim payload.
- [ ] Akses NIK dibatasi pada dataset demo dan dicatat tanpa nilai NIK.
- [ ] Mapping ID hanya dapat diverifikasi dengan permission yang tepat, sumber, dan catatan verifikasi.
- [ ] Perubahan ID mapping membatalkan status verified.

### C. Integritas workflow
- [ ] Diagnosis formal harus ditetapkan dokter dan kode diverifikasi sebelum Condition disiapkan.
- [ ] Resume harus final sebelum Composition disiapkan.
- [ ] Condition, Observation, dan ClinicalImpression harus memiliki transmisi sukses dan ID server sebelum direferensikan oleh Composition.
- [ ] Kunjungan dan resource lokal harus sesuai satu sama lain.
- [ ] Idempotency key stabil untuk satu kunjungan dan satu versi data; perubahan payload harus menimbulkan konflik/versi baru yang jelas.
- [ ] Pengiriman paralel atau klik ganda tidak boleh membuat dua operasi untuk satu outbox.
- [ ] Respons server yang malformed dan status ambigu memerlukan rekonsiliasi operator.

### D. Validasi FHIR
- [ ] Resource memenuhi struktur FHIR R4 serta profil dan terminologi SATUSEHAT yang relevan.
- [ ] ID placeholder tidak pernah lolos ke payload staging.
- [ ] Referensi resource menggunakan ID server yang terverifikasi, bukan ID lokal.
- [ ] Validator lokal tidak diklaim sebagai validator profil lengkap.
- [ ] Contoh positif/negatif tiap resource disediakan sebagai fixture sintetis.

### E. Validasi model diagnosis
- [ ] Evaluasi hanya memakai split yang bebas kebocoran pasien/baris duplikat.
- [ ] Laporkan sensitivitas/recall, spesifisitas, precision, F1, kalibrasi, interval ketidakpastian, serta jumlah sampel tiap kelas.
- [ ] Nilai ambang tidak disebut ambang klinis tanpa validasi klinis.
- [ ] Periksa performa kelompok yang relevan; jangan menyimpulkan aman/akurat pada populasi Indonesia dari dataset publik terbatas.
- [ ] Red flag harus dites mandiri dan selalu mengalahkan tampilan kandidat ML.
- [ ] Saran AI tidak pernah membuat diagnosis formal secara otomatis.

## Urutan kerja
1. Tambahkan tes negatif untuk jalur integrasi dan otorisasi.
2. Review hasil tes dan temuan oleh pengembang serta tenaga klinis yang berwenang.
3. Jalankan seluruh CI pada Python yang didukung.
4. Lakukan uji staging manual dengan data sintetis dan credential staging yang sah hanya setelah checklist keamanan lulus.
5. Catat temuan, tingkat risiko, pemilik perbaikan, dan bukti verifikasi sebelum mempertimbangkan penggunaan yang lebih luas.

## Batasan
- Tidak ada tes di dokumen ini yang menyatakan kepatuhan hukum, kelayakan klinis, atau kesesuaian resmi SATUSEHAT.
- CI dengan fake transport tidak membuktikan credential, jaringan, atau payload diterima server sebenarnya.
- Jangan kirim data pasien nyata atau mengaktifkan penggunaan klinis dalam fase ini.
