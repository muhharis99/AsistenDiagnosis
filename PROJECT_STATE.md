# PROJECT_STATE — AsistenDiagnosis / SIMRS Blueprint

Last updated: 2026-10-26
Current phase: Fase 4 — payer, claims, AR/COB demo workflow.
Repository: https://github.com/muhharis99/AsistenDiagnosis

## Current reality
- Repo tetap memuat prototipe diagnosis Python/Streamlit dan modul RME/SATUSEHAT sandbox/demo.
- SIMRS modular monolith di simrs_platform/ dibangun terpisah; repo belum menjadi SIMRS operasional.
- Jangan proses data pasien nyata atau gunakan hasil untuk keputusan klinis/finansial operasional tanpa validasi, kontrol keamanan independen, UAT dan persetujuan.
- Fase 1 memberi fondasi Python/Django, unit, role, terminologi berversi, MPI demo terenkripsi dan audit hash-chain.
- Fase 2 menambahkan pendaftaran, antrean, tarif, invoice dan pembayaran demo.
- Fase 3 menambahkan encounter, catatan RME berversi, diagnosis, order klinis, farmasi, hasil diagnostik berversi, dan ADT.
- Fase 4 menambahkan master penjamin/paket, kepesertaan COB, alur klaim, adjudikasi demo, koleksi penjamin/pasien, dan subledger piutang.

## Architecture decisions
- ADR-0001: modular monolith sebelum microservices.
- ADR-0002: domain internal terpisah dari FHIR/vendor melalui adapter.
- ADR-0003: synthetic data di dev/test; default non-produksi dan network disabled by default.
- ADR-0004: data klinis/keuangan yang diposting dikoreksi melalui amendment/versioning, bukan hard delete.
- ADR-0005: Python 3.12+ dengan Django + DRF + PostgreSQL sebagai default SIMRS; prototipe diagnosis/Streamlit tetap terpisah.
- Blueprint: docs/FASE_0_SIMRS_BLUEPRINT.md.

## Roadmap
- Phase 0: blueprint arsitektur — drafted.
- Phase 1: fondasi platform, organisasi unit, RBAC, terminologi, MPI sintetis dan audit.
- Phase 2: front office, antrean, katalog tarif, invoice dan pembayaran idempoten — PR #19 merged.
- Phase 3: encounter, RME, diagnosis, CPOE, farmasi, diagnostik dan ADT — PR #20 merged.
- Phase 4: payer, claims, receivables, coordination of benefits (COB) — fase demo ini.
- Phase 5: adapter SATUSEHAT/BPJS/SISRUTE/reporting — bukan sertifikasi produksi.
- Phase 6: logistik, aset, HR, akuntansi dan mutu.
- Phase 7: hardening, UAT, migrasi, parallel run, downtime dan rollback.

## Fase 4 design notes
- Coverage terkait pasien MPI dan tanggal kunjungan, dengan prioritas COB 1–3.
- Klaim primer menggunakan nilai invoice terbit; klaim berikutnya mengambil sisa piutang pasien dari penjamin sebelumnya.
- Pengajuan klaim mencatat piutang penjamin; adjudikasi mendistribusikan nilai allowed, denied, dan tanggung jawab pasien.
- Koleksi penjamin dan pasien idempoten; saldo tidak boleh negatif karena kelebihan penerimaan ditolak.
- Ledger append-only dengan audit event; role baru INSURANCE_BILLING dan PAYER_REVIEWER.
- Status keselamatan: demo-only, data sintetis, belum siap produksi; subledger piutang belum terintegrasi dengan pembayaran kasir Fase 2.

## Fase 3 design notes
- Encounter merujuk registrasi yang sudah check-in dan unit layanan terotorisasi.
- Catatan klinis dan hasil diagnostik append-only/versioned; hasil final dikoreksi dengan amendemen.
- Order klinis berisi snapshot kode/nama, status transisi dikontrol, dan belum merupakan katalog resmi atau formularium tervalidasi.
- Penyerahan obat dapat parsial dengan jumlah total tidak melebihi resep.
- ADT mensyaratkan unit rawat aktif dan merekam admisi/pemulangan melalui transisi status.

## Fase 2 design notes
- Registrasi hanya merujuk pasien MPI aktif dan unit aktif. Kode registrasi serta antrean berscope per unit/tanggal.
- Transisi antrean dikontrol dan diaudit.
- Invoice menyimpan snapshot kode/nama/harga tarif. Baris invoice yang diterbitkan dan pembayaran bersifat append-only.
- Pembayaran membutuhkan idempotency key, referensi non-tunai, dan guard sisa tagihan.
- Sisa pekerjaan: refund/reversal, rekonsiliasi pembayaran, integrasi struk, pentest independen, UAT, backup/restore, dan sign-off.

## Glossary
- MPI: Master Patient Index.
- MRN: Medical Record Number / Nomor Rekam Medis.
- RME: Rekam Medis Elektronik.
- COB: Coordination of Benefits.
- ABAC/RBAC: attribute-/role-based access control.
- ADR: Architecture Decision Record.
- FHIR: Fast Healthcare Interoperability Resources.
- Outbox/DLQ: transactional outbox / dead-letter queue.
- NFR: non-functional requirement.
- RPO/RTO: recovery point/time objectives.
- [ASUMSI]: pending confirmation; [VERIFIKASI]: official/source validation required; [REVIEW KLINIS]: clinical sign-off required.
