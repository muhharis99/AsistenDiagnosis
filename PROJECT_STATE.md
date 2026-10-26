# PROJECT_STATE — AsistenDiagnosis / SIMRS Blueprint

Last updated: 2026-10-26  
Current phase: **Fase 2 — Front Office, antrean, tarif, invoice dan kasir demo merged ke main pada 2026-10-26; CI main sukses**  
Repository: https://github.com/muhharis99/AsistenDiagnosis

## Current reality
- Repo tetap memuat prototipe diagnosis Python/Streamlit dan modul RME/SATUSEHAT sandbox/demo.
- SIMRS modular monolith di simrs_platform/ dibangun terpisah; repo belum menjadi SIMRS operasional.
- Jangan proses data pasien nyata atau gunakan hasil untuk keputusan klinis/finansial operasional tanpa validasi, kontrol keamanan independen, UAT dan persetujuan.
- Fase 0 adalah blueprint; Fase 1 menambahkan fondasi Python/Django, identitas/role, unit, terminologi berversi, MPI demo terenkripsi dan audit hash-chain.

## Architecture decisions
- ADR-0001: modular monolith sebelum microservices.
- ADR-0002: domain internal terpisah dari FHIR/vendor melalui adapter.
- ADR-0003: synthetic data di dev/test; default non-produksi dan network disabled by default.
- ADR-0004: data klinis/keuangan yang diposting dikoreksi melalui amendment/versioning, bukan hard delete.
- ADR-0005: Python 3.12+ dengan Django + DRF + PostgreSQL sebagai default SIMRS; prototipe diagnosis/Streamlit tetap terpisah.
- Blueprint: docs/FASE_0_SIMRS_BLUEPRINT.md.

## Roadmap
- Phase 0: blueprint arsitektur — drafted.
- Phase 1: fondasi platform, organisasi unit, RBAC dasar, terminologi, MPI sintetis dan audit.
- Phase 2: pendaftaran Front Office, antrean unit, katalog tarif, snapshot invoice dan pembayaran kasir idempoten — diimplementasikan di simrs_platform/frontoffice/ dan simrs_platform/cashier/; harus lulus CI dan merge review.
- Phase 3: RME, CPOE, farmasi, LIS/RIS, IGD dan ADT — belum dimulai.
- Phase 4: payer, claims, AR/COB — belum dimulai.
- Phase 5: adapter SATUSEHAT/BPJS/SISRUTE/reporting — modul demo bukan sertifikasi produksi.
- Phase 6: logistik, aset, HR, akuntansi dan mutu — belum dimulai.
- Phase 7: hardening, UAT, migrasi, parallel run, downtime dan rollback — belum dimulai.

## Fase 2 design notes
- Registrasi hanya merujuk pasien MPI aktif dan unit aktif. Kode registrasi serta antrean berscope per unit/tanggal.
- Transisi antrean dikontrol dan diaudit.
- Invoice menyimpan snapshot kode/nama/harga tarif. Baris invoice yang diterbitkan dan pembayaran bersifat append-only.
- Pembayaran membutuhkan idempotency key, referensi non-tunai dan guard sisa tagihan; audit tidak menyimpan nama/NIK atau isi request.
- Sisa pekerjaan: tes konkurensi PostgreSQL, ABAC per relasi layanan/encounter, refund/reversal, rekonsiliasi pembayaran, integrasi struk, kontrak eksternal, pentest independen, UAT, backup/restore dan sign-off.
- Status keselamatan: demo-only, data sintetis, belum siap produksi.

## Glossary
- MPI: Master Patient Index.
- MRN: Medical Record Number / Nomor Rekam Medis.
- RME: Rekam Medis Elektronik.
- ABAC/RBAC: attribute-/role-based access control.
- ADR: Architecture Decision Record.
- FHIR: Fast Healthcare Interoperability Resources.
- Outbox/DLQ: transactional outbox / dead-letter queue.
- NFR: non-functional requirement.
- RPO/RTO: recovery point/time objectives.
- [ASUMSI]: pending confirmation; [VERIFIKASI]: official/source validation required; [REVIEW KLINIS]: clinical sign-off required.
