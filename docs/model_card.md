# Kartu Model — Asisten Diagnosis (Fase 2)

**Versi prototipe:** 0.2.0-phase2  
**Status validasi:** BELUM TERVVALIDASI KLINIS  
**Tujuan penggunaan:** membantu dokter menyusun daftar dugaan statistik untuk ditinjau, bukan menetapkan diagnosis.  
**Lingkungan:** lokal, data fiktif, bukan alat kesehatan berizin.  
**Keputusan manusia:** dokter wajib menilai saran; diagnosis final dan kode ICD tidak dibuat oleh model.

## Modul A — dugaan diagnosis dari gejala

- **Sumber yang dikonfigurasi:** Kaggle kaushil268 / Disease Prediction Using Machine Learning; training harus memakai data/Training.csv bila tersedia.
- **Artefak model saat dokumentasi dibuat:** metadata menyebut DATA DEMO SINTETIS, 224 baris sumber, 215 baris setelah pembersihan, 9 baris duplikat dibuang, 32 fitur gejala, 8 label pola sintetis. Ini bukan dataset Kaggle asli.
- **Model terpilih menurut metadata demo:** Bernoulli Naive Bayes dengan kalibrasi untuk aplikasi.
- **Holdout demo:** top-1 accuracy 0,8372; macro-F1 0,8295; top-3 accuracy 1,0000; multiclass Brier score 0,2274.
- **Threshold penahanan:** sekitar 0,4827 pada artefak demo. Threshold didapat dari data validasi internal, bukan batas klinis.
- **Keterbatasan:** dataset/demo tidak memuat umur, jenis kelamin, durasi/keparahan, riwayat, pemeriksaan fisik, atau laboratorium. Distribusi yang sangat terstruktur dapat menghasilkan metrik menyesatkan. Akurasi tinggi bukan bukti performa klinis.
- **Penjelasan:** gejala pendukung/yang belum dipilih dan pertanyaan informasi-lanjutan dihitung dari statistik training. Ini bukan hubungan sebab-akibat.

## Modul B — skrining diabetes

- **Sumber yang dikonfigurasi:** Pima Indians Diabetes; letakkan CSV sumber di data/diabetes.csv untuk training atas data asli.
- **Artefak model saat dokumentasi dibuat:** metadata menyebut DATA DEMO SINTETIS, 768 baris sintetis, 8 fitur dan label 436/332. Angka ini bukan hasil Pima asli.
- **Model aplikasi demo:** Random Forest terkalibrasi.
- **Metrik holdout demo:** accuracy 0,5195; precision 0,4673; recall/sensitivity 0,7463; specificity 0,3448; F1 0,5747; ROC-AUC 0,6620; threshold 0,3702.
- **Keterbatasan sumber Pima:** data publik Pima asli hanya meliputi perempuan keturunan Pima berusia minimal 21 tahun, sehingga tidak otomatis mewakili populasi Indonesia.
- **Preprocessing:** nilai nol pada Glucose, BloodPressure, SkinThickness, Insulin, dan BMI dianggap missing; imputasi median berada di dalam Pipeline.

## Jejak saran dalam RME

Setiap permintaan yang menghasilkan prediksi menyimpan:
- ID internal kunjungan, dokter peminta, waktu UTC, dan status;
- ID fitur gejala yang dipilih—tanpa nama/NIK sebagai input model;
- keluaran kandidat dan penjelasan;
- versi kode/model, SHA-256 artefak, dan SHA-256 data fitur+label train yang tertanam dalam bundle;
- status demo/model registry.

SHA data latih dibuat dari serialisasi kanonis X_train dan y_train di bundle model saat inferensi. Karena bundle menyertakan statistik training, jangan membuka artefak model kepada pihak tidak berwenang. Log audit tidak menyimpan nama/NIK atau teks alasan tinjauan dalam payload audit; alasan tinjauan disimpan di catatan RME terpisah.

Keputusan dokter (accepted_as_working_hypothesis, modified, ignored) dicatat sebagai tinjauan saran terpisah. **Tidak ada aksi yang membuat atau mengubah diagnosis resmi.** Pemetaan ICD-10 dan alur diagnosis resmi adalah pekerjaan Fase 3.

## Pemantauan dan retraining

Sebelum dipertimbangkan untuk penggunaan klinis, wajib dilakukan validasi eksternal/klinis oleh dokter, pengujian pada data lokal yang representatif, kalibrasi probabilitas, analisis bias/subkelompok, penilaian sensitivitas/spesifisitas, uji ketahanan dengan data klinis yang sah, peninjauan privasi dan keamanan, serta kajian hukum/regulasi. Perubahan dataset, pipeline, pustaka, threshold, atau model harus menghasilkan versi dan hash baru. Artefak demo tidak boleh digunakan sebagai dasar keputusan pasien.
