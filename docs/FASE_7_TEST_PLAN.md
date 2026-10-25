# Fase 7 — Matriks pengujian

Seluruh data dan jawaban API pada tes otomatis wajib sintetis. Pengujian staging nyata, jika dilakukan kelak, memerlukan persetujuan operator dan credential staging yang sah.

| Area | Skenario positif | Skenario negatif / boundary | Bukti yang diharapkan |
|---|---|---|---|
| Konfigurasi | staging allowlist + TLS aktif | jaringan off, mode bukan sandbox, URL bukan allowlist, TLS off | permintaan ditolak sebelum transport dipanggil |
| Token | token bearer valid | token kosong, tipe salah, expiry invalid, 3xx/4xx/5xx, body malformed | token tidak tercatat; error aman |
| HTTP | GET/POST/PUT yang diizinkan | metode/path/resource terlarang, ID placeholder, redirect | transport tidak dipanggil atau hasil ditandai tidak pasti |
| Consent | consent terakhir aktif | consent dicabut sebelum kirim | outbox tidak ditransmisikan |
| RBAC | peran dengan permission | role tanpa permission | error otorisasi; tidak ada efek samping |
| Mapping | ID terverifikasi dari sumber | ID berubah, placeholder, organisasi tidak cocok | mapping ditolak atau kembali unverified |
| Outbox | antrean idem untuk payload sama | klik ganda, dua worker, perubahan payload | tidak ada duplikasi; status deterministik |
| Dependencies | Condition sukses dan punya ID eksternal | dependency gagal/uncertain/tanpa ID | Composition diblokir |
| Respons | FHIR resource valid dan ID aman | JSON malformed, body bukan object, 204 tanpa body, ID/tipe berbeda | tidak tercatat sukses secara palsu |
| Audit | event tanpa PII | NIK/token/secret pada error atau body | nilai rahasia tidak muncul di DB/log/UI |
| Diagnosis | red flag tertangani lebih dulu | consent AI off, gejala sedikit, model/threshold tidak tersedia | tidak ada saran diagnosis yang melanggar guard |
| FHIR profile | fixture valid per resource | referensi demo, coding/field wajib hilang | validator gagal tertutup |
| Model | evaluasi pada holdout | duplikasi/kebocoran data, kelas minim | laporan memperlihatkan keterbatasan dan sampel |

## Perintah verifikasi
```bash
python -m compileall -q rme rme_app.py scripts tests
pytest -q
```

Hasil harus dicatat dari workflow CI; jangan menyatakan seluruh skenario di atas sudah lulus sebelum tes spesifik diimplementasikan dan dijalankan.
