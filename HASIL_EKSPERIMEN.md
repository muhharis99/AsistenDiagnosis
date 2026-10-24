# Hasil Eksperimen — Asisten Diagnosis

## Status sumber data saat eksperimen ini dijalankan

**PENTING: semua angka dalam dokumen ini adalah hasil eksperimen perangkat lunak pada DATA DEMO SINTETIS. Angka ini bukan hasil dari dataset Kaggle `Training.csv` atau Pima Indians Diabetes yang sebenarnya, dan sama sekali tidak membuktikan performa klinis.** Lingkungan eksekusi tidak memiliki CSV lokal dan koneksi OpenML gagal. Karena itu, generator sintetis digunakan untuk memastikan pipeline, evaluasi, visualisasi, model joblib, dan logika penjelasan dapat berjalan. Setelah dataset nyata diletakkan di `data/`, jalankan kembali training untuk mendapatkan angka yang sesuai sumber asli.

Tanggal metadata training: tersimpan dalam `models/symptom_metadata.json` dan `models/screening_metadata.json`.

## Modul A — Diagnosis gejala

Data demo: 224 baris sintetis dibuat → 9 baris duplikat dihapus → 215 baris unik; 32 fitur gejala; 8 kelas pola sintetis; split stratified 172 train / 43 test; 5-fold CV. Tidak ada baris identik lintas train/test. Dataset ini **tidak** memuat 132 gejala/41 penyakit versi Kaggle.

| Model | CV accuracy | CV macro-F1 | Test top-1 accuracy | Test macro-F1 | Test top-3 accuracy | Multiclass Brier (perbandingan model) |
|---|---:|---:|---:|---:|---:|---:|
| DummyClassifier | 0.116 | 0.026 | 0.116 | 0.026 | 0.395 | 1.767 |
| Bernoulli Naive Bayes | 0.925 | 0.925 | 0.837 | 0.830 | 1.000 | 0.178 |
| Logistic Regression | 0.913 | 0.908 | 0.837 | 0.829 | 1.000 | 0.429 |
| Gradient Boosting | 0.884 | 0.882 | 0.814 | 0.805 | 1.000 | 0.215 |
| Random Forest | 0.872 | 0.871 | 0.791 | 0.780 | 1.000 | 0.326 |

**Model aplikasi yang dipilih:** Bernoulli Naive Bayes karena macro-F1 cross-validation tertinggi di antara model non-baseline pada data demo. Model akhir dikalibrasi dengan `CalibratedClassifierCV` sigmoid; pada test holdout, top-1 accuracy = **0.837**, macro-F1 = **0.830**, top-3 accuracy = **1.000**, multiclass Brier = **0.227**. Ambang “Belum cukup informasi” = **0.483**, kuantil 10% maksimum probabilitas top-1 terkalibrasi dari prediksi out-of-fold pada data train. Ambang ini bukan batas diagnosis tervalidasi.

### Confusion matrix dan top-k

Test terdiri dari 43 baris sintetis. Pada matriks `outputs/symptom_confusion_matrix.csv`, kelas pola sintetis A tertukar menjadi B sebanyak 2 sampel; B tertukar menjadi F sebanyak 1; F tertukar menjadi C dan H masing-masing 1; H tertukar menjadi A dan B masing-masing 1. Recall per kelas: A 0.60 (n=5), B 0.80 (n=5), C 1.00 (n=5), D 1.00 (n=6), E 1.00 (n=5), F 0.60 (n=5), G 1.00 (n=6), H 0.667 (n=6).

Top-3 accuracy 100% di sini berarti kelas berlabel demo termasuk dalam tiga kelas dengan probabilitas tertinggi untuk semua 43 sampel test sintetis. Karena jumlah kelas hanya delapan dan fitur dibuat dari pola prototipe buatan, ini **bukan** bukti bahwa model akan mengusulkan diagnosis banding yang akurat pada pasien.

### Kalibrasi dan fitur terpenting

Brier multiclass model akhir terkalibrasi pada holdout adalah 0.227. Kurva reliabilitas top-1 disimpan di `outputs/symptom_calibration_curve.png`; bin berisi sedikit data sehingga estimasi per bin tidak stabil.

Permutation importance global (penurunan macro-F1 saat fitur diacak) teratas pada demo: `itching` 0.0808, `polyuria` 0.0460, `chest_pain` 0.0374, `nausea` 0.0354, `runny_nose` 0.0250. Nilai ini hanya mencerminkan pola yang dibuat oleh generator demo, bukan faktor medis penting.

### Uji ketahanan wajib

| Skenario (test holdout sintetis) | Top-1 accuracy | Top-3 accuracy |
|---|---:|---:|
| Baseline tanpa gangguan | 0.837 | 1.000 |
| Hapus 20% fitur acak (rerata 3 ulangan) | 0.767 | 0.969 |
| Hapus 35% fitur acak (rerata 3 ulangan) | 0.690 | 0.953 |
| Hapus 50% fitur acak (rerata 3 ulangan) | 0.558 | 0.760 |
| Tambah 1–3 gejala positif acak | 0.814 | 1.000 |
| Hanya 1 gejala positif per baris | 0.488 | 0.814 |
| Hanya 2 gejala positif per baris | 0.512 | 0.698 |
| Hanya 3 gejala positif per baris | 0.698 | 0.930 |

Hasil memperlihatkan model demo sensitif terhadap kehilangan fitur. Uji ini adalah gangguan sintetis sederhana, bukan pengganti evaluasi klinis eksternal. Pada data Kaggle asli, akurasi dapat tinggi karena dataset sangat terstruktur dan berulang; itu tidak membuktikan generalisasi klinis.

## Modul B — Skrining indikasi risiko diabetes

Data demo numerik: 768 baris sintetis, 8 fitur; kelas sintetis 436 negatif dan 332 positif; split test 154 baris; 5-fold CV. Dataset demo dibangkitkan oleh generator berbasis fungsi matematis dan bukan data pasien.

### Perbandingan model (model dasar + threshold dari OOF train, hasil test)

| Model | Accuracy | Precision | Recall/sensitivity | Specificity | F1 | ROC-AUC | Threshold | TN | FP | FN | TP |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Logistic Regression | 0.597 | 0.523 | 0.836 | 0.414 | 0.644 | 0.700 | 0.407 | 36 | 51 | 11 | 56 |
| Random Forest | 0.545 | 0.487 | 0.821 | 0.333 | 0.611 | 0.634 | 0.371 | 29 | 58 | 12 | 55 |
| Gradient Boosting | 0.584 | 0.512 | 0.940 | 0.310 | 0.663 | 0.654 | 0.355 | 27 | 60 | 4 | 63 |

CV recall pada threshold default 0.5 dan ROC-AUC CV juga tersedia di `outputs/screening_model_comparison.csv`. Gradient Boosting memakai sample weight seimbang, sebab kelas tidak ditangani melalui parameter `class_weight` pada estimator itu.

**Model aplikasi yang dipilih:** Random Forest. Aturan seleksi mengutamakan recall out-of-fold pada threshold yang dipilih untuk mencapai sasaran 80%; Random Forest mencapai OOF recall **0.808**, sedikit di atas Logistic Regression dan Gradient Boosting pada 0.800, dengan OOF precision 0.476. Ini trade-off yang mengutamakan menemukan lebih banyak label positif pada demo, bukan model klinis terbaik.

Model akhir dikalibrasi dengan sigmoid dan threshold dipilih dari prediksi OOF terkalibrasi pada train. Hasil test model aplikasi: accuracy **0.519**, precision **0.467**, recall **0.746**, specificity **0.345**, F1 **0.575**, ROC-AUC **0.662**, threshold **0.370**. Recall test di bawah sasaran OOF 80% menunjukkan kinerja pada data yang tak dilihat bisa berbeda; threshold bukan jaminan sensitivitas. Kategori rendah/sedang/tinggi berasal dari tertil distribusi probabilitas OOF training (batas 0.386 dan 0.460), bukan batas klinis.

### Interpretasi confusion matrix dan ROC

Pada test sintetis: TN=30, FP=57, FN=17, TP=50. Model menandai 107 sampel sebagai positif, tetapi hanya 50 di antaranya positif menurut label demo (precision 46.7%). Ada 17 kasus positif sintetis yang terlewat. ROC-AUC 0.662 menunjukkan diskriminasi terbatas pada data demo. Untuk skrining nyata, false negative maupun false positive harus dinilai bersama tenaga kesehatan dan data lokal. Threshold yang diturunkan dapat menaikkan recall, tetapi biasanya menambah false positive dan menurunkan precision/specificity.

### Kalibrasi dan fitur terpenting

Kurva reliabilitas ada di `outputs/screening_calibration_curve.png`; reliabilitas dievaluasi per bin pada holdout, dengan ukuran bin terbatas dan data sintetis. Permutation importance ROC-AUC tertinggi: Glucose 0.0881, DiabetesPedigreeFunction 0.0432, Age 0.0083. Fitur lainnya memiliki importance dekat nol atau negatif—mengacaknya kebetulan memperbaiki skor pada split ini. Ini adalah pola generator demo, **bukan kesimpulan klinis**.

## Contoh kasus fiktif — semua keluaran model di bawah berasal dari DATA DEMO

### Modul A

1. **Pola gejala sintetis (empat pilihan):** `itching`, `skin_rash`, `nodal_skin_eruptions`, `fatigue`. Skor teratas: `DATA DEMO — pola sintetis A` 78.24%, B 3.55%, G 3.21%. Aplikasi menampilkan keyakinan statistik “Sedang” menurut aturan prototipe. Label ini tidak mewakili penyakit nyata; hanya contoh aliran top-3.
2. **Informasi belum cukup:** pengguna hanya memilih `cough` dan `fatigue`. Sistem tidak memunculkan dugaan, karena kurang dari tiga gejala; ia meminta gejala tambahan yang benar-benar dialami.
3. **Red flag:** pengguna menandai nyeri dada (`chest_pain`) dan gejala lain. Aturan keselamatan memunculkan peringatan merah: jangan menunggu model, segera ke IGD atau hubungi 112/119. Modul tidak memunculkan diagnosis banding pada pengajuan tersebut, apa pun probabilitas model. Pemetaan red flag perlu review medis; 112 dijalankan oleh pemerintah daerah sehingga ketersediaannya bergantung wilayah.

### Modul B

| Kasus fiktif | Nilai input penting | Skor probabilitas demo | Kategori relatif | Interpretasi yang aman |
|---|---|---:|---|---|
| A | Glukosa 92 mg/dL; BMI 22.5; usia 25; kehamilan 0 | 24.97% | Rendah | Di bawah threshold demo 37.02%; ini tidak menyingkirkan diabetes dan tidak boleh dianggap skor klinis. |
| B | Glukosa 178 mg/dL; BMI 36.5; usia 58; kehamilan 6; pedigree 1.2 | 64.48% | Tinggi | Melewati threshold demo; faktor komparatif teratas: DiabetesPedigreeFunction (+11.97 poin), Glucose (+5.24), BMI (+2.87) pada analisis satu fitur. Ini hanya perilaku model sintetis, bukan kesimpulan medis. |

**Kesimpulan eksperimen:** seluruh pipeline berhasil dijalankan dan file keluaran dibuat pada data demo. Belum ada dasar yang sah untuk menyatakan model ini memiliki akurasi tertentu pada dataset Kaggle asli, dataset Pima asli, atau pasien Indonesia. Jalankan training ulang dengan file sumber asli sebelum menafsirkan hasil evaluasi; tetap perlukan validasi klinis dan data lokal.
