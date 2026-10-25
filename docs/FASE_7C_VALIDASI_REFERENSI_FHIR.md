# Fase 7C — Validasi referensi FHIR yang lebih ketat

**Status:** pengetatan validator lokal dan tes regresi di branch fitur. Ini bukan validator penuh FHIR R4 atau profil SATUSEHAT.

## Perubahan
- Referensi FHIR harus berbentuk relative reference `ResourceType/server-id`, bukan URL absolut, query, history path, atau bentuk bebas.
- Resource type referensi di-allowlist.
- ID referensi harus sesuai pola ID yang diizinkan serta menolak marker placeholder seperti `demo`, `example`, dan `.invalid`.
- Aturan ketat diterapkan pada reference yang diketahui di Condition, Composition, Encounter, Observation, dan ClinicalImpression.
- Pemeriksaan rekursif tambahan memeriksa seluruh elemen `reference`, termasuk bidang bertingkat yang belum tercakup oleh pemeriksaan per-resource.
- ID Encounter yang dipakai untuk update juga harus sesuai pola ID server yang diizinkan.

## Bukti tes
`tests/test_rme_phase7c.py` memuat fixture FHIR sintetis dan tes negatif untuk ID contoh, URL absolut, query string, history path, reference tipe resource salah, dan reference yang tersembunyi pada bidang bertingkat.

## Verifikasi
```bash
python -m compileall -q rme rme_app.py scripts tests
pytest -q
```

CI harus lulus pada Python yang didukung sebelum perubahan digabung. Semua fixture menggunakan ID dan data sintetis.

## Batasan
- Validator ini tetap hanya subset lokal, tidak memuat seluruh cardinality, terminology binding, profile slicing, invariants, atau referential integrity dari implementasi guide SATUSEHAT.
- Validator memeriksa bentuk ID/reference, bukan membuktikan bahwa ID tersebut benar-benar ada di server atau sesuai dengan pasien/kunjungan yang dimaksud.
- Tidak ada perubahan skema database dan tidak ada transmisi jaringan yang diaktifkan.
