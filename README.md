# Asisten Diagnosis — Prototipe Riset Python

Satu aplikasi Streamlit dengan dua modul:

- **Modul A — Diagnosis banding dari gejala:** tiga kandidat statistik, probabilitas model, gejala pendukung, gejala yang belum dipilih tetapi sering muncul pada sampel kelas, pertanyaan lanjutan berbasis information gain, EDA, calibration/reliability curve, permutation importance, dan uji ketahanan.
- **Modul B — Skrining indikasi risiko diabetes:** pipeline imputasi median + scaling, perbandingan Logistic Regression / Random Forest / Gradient Boosting, class weighting, threshold dengan perhatian pada recall, confusion matrix, ROC-AUC, ROC curve, serta penjelasan skor individual.

> **Batas keselamatan:** Ini adalah prototipe edukasi/riset, bukan dokter, bukan diagnosis pasti, dan bukan alat kesehatan berizin. Setiap istilah terjemahan/penyakit dan pemetaan red flag ditandai untuk ditinjau tenaga medis. Jangan gunakan hasil untuk mengambil keputusan klinis tanpa dokter.

## 1. Persiapan lingkungan

Disarankan Python 3.10–3.12, lingkungan virtual, dan instalasi dependensi:

```bash
python3 -m venv .venv
source .venv/bin/activate   # Linux/macOS
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## 2. Dataset Modul A (Kaggle)

1. Masuk ke halaman Kaggle: https://www.kaggle.com/datasets/kaushil268/disease-prediction-using-machine-learning
2. Unduh dan ekstrak berkas `Training.csv` dan `Testing.csv` (akun Kaggle mungkin diperlukan).
3. Letakkan file sebagai:

```text
data/Training.csv
data/Testing.csv
```

`Training.csv` dipakai untuk EDA, deduplikasi, split 80/20 dan evaluasi utama. `Testing.csv` hanya dipakai untuk sanity check opsional dan **bukan** untuk memilih model atau melaporkan evaluasi utama.

Jika file `Training.csv` tidak ditemukan, aplikasi training membuat data kecil **DATA DEMO SINTETIS** agar dapat menguji jalannya program. Label dan metrik demo tidak mempunyai makna klinis. Jika data lokal tersedia, kode tidak menggunakan data demo.

Kode membersihkan kolom `Unnamed`, nama kolom ganda, kolom kosong, nilai gejala non-biner, serta menghitung dan membuang duplikat **sebelum split**. Kelas dengan kurang dari 3 baris unik tidak dipakai dalam split/CV utama dan dilaporkan karena evaluasi stratified tidak cukup didukung.

Pemetaan nama berada di `config/symptom_mapping_id.json` dan `config/disease_mapping_id.json`. Nama yang tidak memiliki terjemahan menggunakan fallback yang ditandai *perlu ditinjau tenaga medis*. Semua terjemahan saat ini juga masih membutuhkan review klinis.

## 3. Dataset Modul B (Pima)

Urutan pemuatan: CSV lokal (`data/diabetes.csv`, `data/pima.csv`, atau `data/pima-indians-diabetes.csv`) → OpenML data ID 37 → URL publik alternatif → **DATA DEMO SINTETIS** bila semuanya gagal. Bila ingin melarang fallback demo, ubah pemanggilan `load_pima_local_or_remote(allow_demo=False)` di `train_screening.py`.

Nilai nol pada `Glucose`, `BloodPressure`, `SkinThickness`, `Insulin`, dan `BMI` diganti menjadi nilai hilang sebelum pemodelan. Median imputer ditempatkan dalam `Pipeline`, sehingga statistik imputasi dipelajari di train/fold, bukan dari test.

## 4. Training, evaluasi, aplikasi, dan tes

Jalankan dari folder proyek:

```bash
python train_symptom.py
python train_screening.py
python evaluate.py
pytest -q
streamlit run app.py
```

Training bisa memerlukan waktu karena hyperparameter tuning, CV, kalibrasi, dan permutation importance. Setelah selesai, Streamlit akan dibuka pada URL lokal yang dicetak Streamlit. Jangan mengekspos aplikasi ini ke internet atau memasukkan identitas pasien.

## 5. Keluaran training

Folder `outputs/` berisi:

- `symptom_model_comparison.csv`, `symptom_selected_model_test_metrics.csv`, `symptom_confusion_matrix.csv`, `symptom_top_confusions.csv`, `symptom_recall_per_disease.csv`, `symptom_reliability_bins.csv`, `symptom_robustness_tests.csv`, `symptom_permutation_importance.csv`, dan grafik EDA/kalibrasi/importance.
- `screening_model_comparison.csv`, `screening_selected_test_metrics.csv`, `screening_confusion_matrix.csv`, `screening_permutation_importance.csv`, `screening_reliability_bins.csv`, serta grafik ROC/kalibrasi/importance.
- laporan EDA dan metadata sumber data.

Folder `models/` menyimpan joblib dan metadata versi library/waktu training. Model gejala menyimpan statistik training publik untuk menghitung prevalensi dan pertanyaan lanjut; input pasien aplikasi tidak disimpan.

## 6. Desain evaluasi dan interpretasi

- Modul A memilih model berdasar macro-F1 cross-validation; DummyClassifier adalah baseline saja. Top-1/top-3, recall per kelas, confusion matrix, Brier multi-class, reliability bins, dan top confusion pairs dihitung pada test holdout setelah deduplikasi.
- Ambang `Belum cukup informasi` dihitung dari kuantil 10% probabilitas maksimum pada prediksi out-of-fold train. Itu hanya ambang statistik internal, bukan ambang diagnosis tervalidasi. Kurang dari tiga gejala selalu memicu penahanan dugaan.
- Uji robustness menilai penghapusan 20%, 35%, 50% fitur, penambahan gejala acak, dan penyisaan 1–3 gejala positif. Dataset yang bersih dapat memberi hasil sangat tinggi; ini tidak membuktikan kinerja pada pasien nyata.
- Modul B memilih model berdasar recall CV dan ROC-AUC sebagai metrik tambahan. Threshold dipilih dari OOF train dengan sasaran recall 80% bila dapat dicapai, lalu dilaporkan precision/specificity. Penurunan threshold umumnya meningkatkan recall dengan trade-off lebih banyak false positive.
- Kategori Rendah/Sedang/Tinggi didasarkan pada tertil probabilitas OOF train, bukan batas klinis. Output `predict_proba` perlu validasi kalibrasi di data lokal.

## 7. Privasi dan lapisan keselamatan

- Input pasien hanya diproses di memori/session; kode aplikasi tidak menulis masukan pasien ke disk/database dan tidak mengirimkannya ke pihak ketiga. Jangan mengaktifkan logging input atau merekam sesi jika aplikasi dimodifikasi.
- Informasi kesehatan termasuk data pribadi spesifik menurut UU No. 27 Tahun 2022 tentang Pelindungan Data Pribadi. Pernyataan ini bukan sertifikasi kepatuhan hukum; pengoperasian nyata perlu kajian hukum, keamanan, dan tata kelola. Sumber resmi: https://peraturan.bpk.go.id/Details/229798/uu-no-27-tahun-2022
- Red flag pada `config/red_flags.json` diproses oleh `safety.py` **sebelum** inferensi hasil, sehingga skor ML tidak dapat menimpa peringatan. Pemetaan kolom aktual tergantung versi dataset; kontrol red flag manual tetap disediakan. Semua aturan perlu review klinis.
- Pesan darurat: segera ke IGD atau hubungi 112 / 119. 119 adalah PSC darurat kesehatan Kemenkes. Layanan 112 diselenggarakan pemerintah daerah; cek ketersediaannya di wilayah setempat.
- Peringatan statis untuk bayi/anak kecil, kehamilan, lansia, dan penyakit kronis ditampilkan sepanjang aplikasi.

## 8. Keterbatasan dan validasi sebelum penggunaan nyata

Dataset gejala yang banyak beredar mempunyai 4.920 baris, 132 gejala, 41 kelas, dan sering terlihat tepat 120 sampel per kelas; data ini tampak sangat terstruktur dan tidak memuat usia, jenis kelamin, lama/keparahan gejala, anamnesis, pemeriksaan fisik atau laboratorium. Dataset Pima hanya mencakup perempuan keturunan Pima berusia 21 tahun ke atas. Keduanya belum tentu representatif untuk populasi Indonesia.

Sebelum pemakaian klinis, diperlukan: validasi prospektif/eksternal oleh dokter, evaluasi bias per subkelompok, kalibrasi di data lokal, audit keselamatan dan usability, keamanan/privasi, serta kajian pemenuhan regulasi alat kesehatan dan UU Pelindungan Data Pribadi. Prototipe ini tidak mengeluarkan obat/dosis dan tidak menggantikan diagnosis dokter.

## 9. Sumber

- Kaggle dataset (kaushil268): https://www.kaggle.com/datasets/kaushil268/disease-prediction-using-machine-learning
- OpenML search: https://www.openml.org/search?type=data
- Kemenkes RI — tanda stroke & tindakan cepat: https://keslan.kemkes.go.id/view_artikel/4465/kenali-stroke-iskemik-dan-bertindak-cepat
- Kemenkes RI — PSC 119: https://kemkes.go.id/id/layanan/psc-119
- Komdigi — layanan 112: https://layanan112.komdigi.go.id/tentang
- WHO — diabetes: https://www.who.int/news-room/questions-and-answers/item/diabetes
- BPK RI — UU No. 27 Tahun 2022 tentang Pelindungan Data Pribadi: https://peraturan.bpk.go.id/Details/229798/uu-no-27-tahun-2022


## Fase 1 — Fondasi RME Rawat Jalan (prototipe)

Fase 1 menambahkan entry point RME terpisah di `rme_app.py` agar UI AI yang lama tetap tidak rusak sampai panel AI dipasang ke alur klinis pada Fase 2. Semua data pasien dan kunjungan yang dibuat lewat RME ini adalah fiktif. Aplikasi menolak `APP_MODE` selain `demo`.

### Jalankan RME demo

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/init_demo.py
streamlit run rme_app.py
```

Pada Windows PowerShell, gunakan `.venv\\Scripts\\Activate.ps1` untuk aktivasi venv.

Seeder akan membuat `.env` lokal berisi kunci enkripsi, database SQLite, akun demo, serta sejumlah pasien/kunjungan sintetis. File `.env` dan database tidak boleh masuk Git. Akun demo hanya untuk localhost:

- `pendaftaran_demo / DemoDaftar!2026`
- `perawat_demo / DemoPerawat!2026`
- `dokter_demo / DemoDokter!2026`
- `rekam_medis_demo / DemoRekam!2026`
- `pimpinan_demo / DemoPimpinan!2026`
- `admin_sistem_demo / DemoSistem!2026`

### Cakupan fase ini

Autentikasi Argon2, role-based access control (RBAC) di lapisan service, rate limit login dalam memori, timeout idle, enkripsi field nama/NIK, masking NIK, pencatatan consent, pendaftaran, antrean, anamnesis, validasi tanda vital, draft/finalisasi resume SOAP, tanda tangan simulasi, koreksi 48 jam/addendum, dan audit append-only berantai hash. Kamus data awal: `docs/kamus_data_fase1.csv`; rincian: [docs/FASE_1_IMPLEMENTASI.md](docs/FASE_1_IMPLEMENTASI.md).

```bash
python -m compileall -q rme rme_app.py scripts tests
pytest -q
```

**Penting:** RME Fase 1 adalah prototipe edukasi/riset, bukan penggunaan klinis. AI belum dihubungkan di fase ini, diagnosis tidak diisi otomatis, SATUSEHAT belum mengirim data, dan tanda tangan elektronik hanya simulasi bukan TTE tersertifikasi. Nama/NIK dienkripsi pada level field; catatan klinis belum mendapat enkripsi field-level. Amankan file database/host dan jangan expose ke jaringan publik. Belum ada klaim kepatuhan penuh atau sertifikasi.


## Fase 2 — Asisten Diagnosis di alur dokter

Panel AI kini tersedia pada tab **Pemeriksaan → Asesmen & Diagnosis** pada entry point RME, yaitu file rme_app.py. AI hanya mengeluarkan sampai tiga dugaan statistik untuk ditinjau dokter. Aksi "Catat sebagai kandidat hipotesis kerja", "Ubah saran", dan "Abaikan saran" masuk ke tabel tinjauan dan audit; tidak satu pun membuat diagnosis final atau mengisi diagnosis ICD-10.

### Consent, red flag, dan kelompok khusus

- Service memeriksa peran Dokter (DPJP), status kunjungan, penugasan DPJP dan consent ai_assist sebelum inferensi.
- Pemeriksaan red flag tersedia terpisah dari tombol AI agar tetap berfungsi meskipun consent AI belum aktif. Red flag memblokir inferensi dan menampilkan peringatan darurat.
- Kurang dari tiga gejala, usia di bawah 18/65 ke atas, kehamilan atau penyakit kronis yang ditandai, serta skor top-1 di bawah threshold akan menahan dugaan atau memblokir inferensi.
- Bila skor tertinggi di bawah threshold, aplikasi menyembunyikan daftar kandidat dan menampilkan "Belum cukup informasi".
- Nama/NIK tidak dikirim ke model. Saran menyimpan ID gejala, keluaran, penjelasan, versi model/kode, hash SHA-256 artefak dan data latih, waktu UTC serta status demo.
- Model demo saat ini bersumber dari generator sintetis. Skor dan metriknya bukan bukti performa klinis. Dokter tetap menetapkan diagnosis; pemetaan ICD-10 adalah fase selanjutnya.

Dokumentasi lengkap: [docs/FASE_2_AI.md](docs/FASE_2_AI.md) dan [docs/model_card.md](docs/model_card.md).

Akun demo RME pada database baru dibuat oleh scripts/init_demo.py; seeder menyiapkan satu pasien fiktif dengan consent AI-assist aktif untuk demonstrasi lokal. Jika database demo lama sudah mempunyai pasien, seeder tidak mengubah consent yang sudah ada. Buat pasien demo baru melalui menu Pendaftaran dan catat persetujuannya secara terpisah.

Jalankan tes:

    python -m compileall -q rme rme_app.py scripts tests
    pytest -q

Fase ini masih prototipe lokal dengan data fiktif; tidak ada klaim validasi klinis, kepatuhan penuh regulasi, atau integrasi SATUSEHAT.


## 7. Fase 3 — ICD-10 dan SATUSEHAT mock

RME Fase 3 menambahkan diagnosis manual dokter yang terpisah dari tabel saran AI, registry terminologi ICD-10 edisi 2010 dengan status sumber, verifikasi kode oleh Perekam Medis, pembangun resource FHIR R4 Condition dan Composition, serta outbox idempoten untuk simulator lokal.

Sebelum masuk outbox, sistem meminta kunjungan finished, resume final, persetujuan pembukaan/pemanfaatan data aktif, diagnosis dokter berstatus confirmed, dan kode yang diverifikasi Perekam Medis. Payload tersimpan bersama SHA-256 untuk inspeksi lokal. Respons MOCK_ACCEPTED hanyalah simulasi perangkat lunak; **tidak ada OAuth, HTTP, atau transmisi ke SATUSEHAT pada fase ini**.

Registry awal data/icd10_seed_2010.csv hanyalah contoh kecil yang sumbernya dirujuk, **bukan katalog ICD-10 lengkap**. Gunakan daftar ICD-10 edisi 2010 yang diperoleh dari sumber resmi dan proses review organisasi sebelum menambahkannya. Tidak ada pemetaan otomatis dari kandidat AI ke diagnosis atau kode.

Dokumentasi rujukan yang diperiksa:
- SATUSEHAT — ICD-10 versi 2010: https://satusehat.kemkes.go.id/platform/docs/id/terminology/icd/icd-10/
- SATUSEHAT — resource Condition: https://satusehat.kemkes.go.id/platform/docs/id/fhir/resources/condition/
- SATUSEHAT — Composition: https://satusehat.kemkes.go.id/platform/docs/id/fhir/resources/composition/
- SATUSEHAT — Playbook Resume Medis Rawat Jalan: https://satusehat.kemkes.go.id/platform/docs/id/interoperability/rme-rawat-jalan/

Keterbatasan: ini belum validator profil SATUSEHAT lengkap, belum menyelesaikan identitas IHS/MPI, mapping organization/practitioner/location, OAuth sandbox, OperationOutcome, atau transmisi nyata. Reference bertanda demo- serta URL domain .invalid sengaja menjadi placeholder. Jangan mengubah mock menjadi sandbox/production tanpa telaah playbook dan pengujian profil resmi terbaru.


## 8. Fase 4 — Persiapan mapping dan sandbox SATUSEHAT

Fase 4 menambahkan mapping ID sandbox yang diverifikasi secara terpisah untuk Patient, Practitioner, Organization, Location, dan Encounter; preflight lokal; daftar URL staging yang diizinkan; pemeriksaan TLS; serta guard yang menolak payload dengan placeholder demo. Perubahan mapping external ID membatalkan status verifikasi lama.

Fase ini tidak melakukan OAuth, GET MPI/MNI, POST resource, maupun transmisi jaringan. Bahkan ketika preflight lengkap, pengiriman belum tersedia. Semua payload Fase 3 tetap payload mock, bukan payload untuk sandbox.

Dokumentasi rinci: docs/FASE_4_SATUSEHAT_READINESS.md


## 9. Fase 5 — OAuth sandbox, MPI search, dan transmisi resource

Fase 5 menambah klien OAuth2 client_credentials dan API FHIR SATUSEHAT staging, pencarian MPI berdasarkan NIK dari pasien demo yang memiliki consent aktif, transformasi payload mock menjadi payload create-ready berbasis mapping terverifikasi, serta transmisi satu resource Condition/Composition dengan konfirmasi operator. Jaringan tetap nonaktif secara default (SATUSEHAT_ENABLE_NETWORK=false) dan tidak ada URL produksi diizinkan.

Ledger transmisi tidak menyimpan token, secret, NIK, payload klinis mentah, atau body OperationOutcome. Jika POST timeout atau penerimaannya tidak dapat dipastikan, status menjadi uncertain dan pengulangan otomatis diblokir untuk menghindari duplikasi.

Pengujian fase ini memakai fake transport; ia memverifikasi alur kode dan keamanan, bukan keberhasilan koneksi credential SATUSEHAT. Data aplikasi harus tetap sintetis dan mode tetap APP_MODE=demo.

Dokumentasi: docs/FASE_5_SATUSEHAT_SANDBOX_CLIENT.md


## 10. Fase 6 — Resource lanjutan FHIR R4 rawat jalan

Fase 6 menambah builder dan outbox untuk resource Observation (tanda vital), ClinicalImpression (riwayat perjalanan penyakit dari dokumentasi dokter), dan update Encounter yang sudah memiliki mapping verified. FHIR Composition menautkan Observation pada section Pemeriksaan Fisik dan ClinicalImpression pada section Anamnesis. Validasi lokal menolak placeholder demo dan mengharuskan referensi remote terverifikasi.

Urutan pengiriman disarankan: Condition → Observation → ClinicalImpression → Encounter update → Composition. Update Encounter memakai PUT ke ID sandbox yang sudah dipetakan; fase ini belum membuat Encounter baru. Klien tetap dibatasi staging, TLS, operator confirmation, dan network opt-in.

Tes menggunakan fake transport, bukan koneksi nyata. Validator bukan validator lengkap profil SATUSEHAT, dan dataset tetap fiktif. Dokumentasi: docs/FASE_6_RME_FHIR_RESOURCES.md


## Fase 7F — Integritas audit transmisi

Fase 7F menambah tes regresi untuk verifikasi hash-chain audit: rantai kosong/utuh, perubahan detail event, perubahan hash, dan pemutusan tautan predecessor. Panduan operator ada di [docs/FASE_7F_INTEGRITAS_AUDIT.md](docs/FASE_7F_INTEGRITAS_AUDIT.md).

Pemeriksaan ini menggunakan helper audit yang sudah ada, tidak mengubah skema database, tidak mengubah status transmisi, dan tidak mengirim ulang resource. Hash-chain lokal membantu mendeteksi inkonsistensi, tetapi bukan pengganti penyimpanan audit eksternal append-only. Semua tes memakai data demo sintetis; hasil CI bukan bukti penerimaan resource oleh SATUSEHAT atau kesiapan produksi.


## Fase 7G — Kesiapan operasional sandbox

Menu Integrasi SATUSEHAT kini memiliki pemeriksaan operasional lokal yang menyajikan hasil konfigurasi teredaksi, jumlah status outbox/transmisi demo, dan integritas audit. Pemeriksaan tidak memanggil jaringan, tidak mengubah status transaksi, dan menandai status `sending`/`uncertain` untuk tinjauan. Detail ada di [docs/FASE_7G_KESIAPAN_OPERASIONAL.md](docs/FASE_7G_KESIAPAN_OPERASIONAL.md). Status yang lolos tidak membuktikan OAuth/koneksi atau penerimaan resource oleh SATUSEHAT.


## Fase 7H — Kontrak FHIR dan skenario kegagalan

Menambahkan tes kontrak lokal untuk Condition, Composition, Observation, ClinicalImpression, dan Encounter, serta simulasi HTTP 201 tanpa ID resource dan HTTP 5xx. Hasil tulis yang tidak dapat dipastikan tetap `uncertain` dan tidak di-POST ulang otomatis. Lihat [docs/FASE_7H_KONTRAK_FHIR_DAN_KEGAGALAN.md](docs/FASE_7H_KONTRAK_FHIR_DAN_KEGAGALAN.md). Tes memakai fake transport dan data sintetis; ini bukan validator penuh profil FHIR/SATUSEHAT dan tidak membuktikan koneksi staging.
