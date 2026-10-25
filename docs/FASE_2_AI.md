# Fase 2 — Integrasi Asisten Diagnosis ke alur dokter

**Status:** prototipe implementasi; semua pasien/kunjungan yang dibuat aplikasi RME tetap fiktif.

## Alur panel

1. Dokter (DPJP) membuka kunjungan berstatus in-progress dan tab Asesmen & Diagnosis.
2. Pemeriksaan keselamatan red flag terpisah tersedia kapan pun di panel, termasuk saat consent AI belum aktif. Red flag memblokir inferensi dan menampilkan pesan darurat; tidak menunggu model.
3. Untuk menjalankan inferensi, pasien harus mempunyai persetujuan ai_assist aktif; service memeriksa ulang di server. Model tidak dijalankan bila consent tidak aktif, usia di bawah 18/65 ke atas, kelompok hamil/penyakit kronis ditandai, atau gejala kurang dari tiga.
4. Model membentuk paling banyak tiga kandidat. Bila skor top-1 di bawah threshold empiris, antarmuka hanya menampilkan **Belum cukup informasi** dan pertanyaan lanjutan; daftar kandidat disembunyikan.
5. Dokter dapat mencatat kandidat sebagai hipotesis kerja, mengubah saran dengan alasan, atau mengabaikannya dengan alasan. Keputusan dicatat pada tabel tinjauan dan audit.
6. Tindakan panel hanya memengaruhi catatan saran/tinjauan. **Tidak dibuat tabel Diagnosis atau diagnosis resmi otomatis.** Diagnosis dan pemetaan ICD-10 menjadi bagian Fase 3.

## Persistensi dan audit

Tabel ai_suggestions menyimpan ID gejala, top-k, penjelasan, threshold, hash SHA-256 artefak dan data train, versi model/kode, waktu, serta status demo. Tabel ai_suggestion_reviews menyimpan aksi dokter dan alasan. AuditLog mencatat pembuatan saran, blokir red flag/kelompok khusus/consent, dan aksi tinjauan tanpa merekam nama/NIK ke payload log.

Hash training dihasilkan dari serialisasi fitur+label train yang tertanam dalam bundle model. Input model tidak mencakup identitas pasien; hanya ID fitur gejala. Data klinis tidak dikirim ke layanan pihak ketiga.

## Menyiapkan demo

Pada database baru, python scripts/init_demo.py membuat akun demo dan pasien sintetis; satu pasien fiktif awal diberi consent AI-assist agar panel bisa diperagakan. Untuk database lama yang sudah memiliki pasien, seeder tidak mengubah consent lama. Buat pasien demo baru melalui menu Pendaftaran dan centang persetujuan AI-assist yang sesuai. Jangan mengaktifkan consent palsu pada pasien nyata.

Jalankan perintah berikut dari root repository:

    python -m pip install -r requirements.txt
    python scripts/init_demo.py
    streamlit run rme_app.py

## Pengujian fase 2

    python -m compileall -q rme rme_app.py scripts tests
    pytest -q

Tes mencakup red flag sebelum model/consent, tidak adanya inferensi tanpa consent, penahanan input kurang dari tiga gejala, penahanan lansia, hash model/data train, tinjauan dokter, dan bukti bahwa aksi tinjauan tidak membuat diagnosis formal.

## Batasan

Model yang tersimpan pada repository saat fase ini menggunakan DATA DEMO SINTETIS. Metrik pada halaman Evaluasi Model hanya memeriksa jalur software. Kaggle/Pima asli harus dipasang dan training ulang dilakukan sebelum penilaian model yang bermakna. Tidak ada klaim validasi klinis, kepatuhan penuh regulasi, atau izin edar alat kesehatan.
