# PROJECT_STATE — AsistenDiagnosis / SIMRS Blueprint

Last updated: 2026-10-26  
Current phase: **Fase 0 — Discovery & Blueprint drafted; awaiting owner input**  
Repository: https://github.com/muhharis99/AsistenDiagnosis

## Current reality
- Repo sekarang merupakan prototipe diagnosis Python/Streamlit dengan modul RME dan SATUSEHAT sandbox/demo.
- Repo **belum** menjadi SIMRS rumah sakit siap produksi.
- Tidak boleh memproses data pasien nyata atau dipakai mengambil keputusan klinis tanpa validasi, kontrol keamanan independen, UAT dan persetujuan.
- Fase 0 ditambahkan sebagai blueprint dokumentasi. Belum ada perubahan kode runtime, skema database, secrets, atau endpoint jaringan.

## Decisions / ADRs
- ADR-0001: modular monolith sebelum microservices.
- ADR-0002: domain internal terpisah dari FHIR/vendor melalui adapter.
- ADR-0003: synthetic data di dev/test; default non-produksi dan network disabled by default.
- ADR-0004: data klinis/keuangan yang diposting dikoreksi melalui amendment/versioning, bukan hard delete.
- ADR-0005: SIMRS operasional berbasis Python 3.12+ dengan Django + Django REST Framework + drf-spectacular dan PostgreSQL sebagai modular monolith; prototipe diagnosis Python/Streamlit dipisahkan sampai integrasi disetujui. Ini menyelaraskan rancangan dengan persyaratan wajib Python pada master prompt.

See [docs/FASE_0_SIMRS_BLUEPRINT.md](docs/FASE_0_SIMRS_BLUEPRINT.md) for full rationale and diagrams.

## Assumptions pending confirmation
- Facility: one general hospital, public/private/type unknown.
- MVP: patient registration → outpatient RME → pharmacy → cashier; claims as mock/adapter until officially verified.
- Scale: provisional planning numbers only; not validated.
- Deployment: private cloud in Indonesia as default assumption, not approved.
- Integrations: SATUSEHAT/BPJS/SISRUTE via adapters, mock servers and contract tests; official specs must be checked.
- Time zone: WIB placeholder.
- Operating requirements: proposed 99.9% availability, RPO 15 min, RTO 1 hr, API p95 read <300 ms/write <500 ms; must be confirmed and load tested.

## Modules / roadmap
- Phase 0: blueprint — drafted, owner feedback needed.
- Phase 1: foundation/IAM/audit/master data/MPI — not started for the SIMRS target.
- Phase 2: registration, queue, tariff, billing/cashier — not started.
- Phase 3: clinical workflows/RME/CPOE/pharmacy/LIS/RIS/IGD/ADT — not started.
- Phase 4: payer/claims/AR/COB — not started.
- Phase 5: SATUSEHAT/BPJS/SISRUTE/reporting adapters — existing demo modules are not production certification.
- Phase 6: logistics/asset/HR/accounting/quality — not started.
- Phase 7: hardening/UAT/migration/parallel run/downtime/rollback — not started.

## Open questions
See Part 2 of [docs/FASE_0_SIMRS_BLUEPRINT.md](docs/FASE_0_SIMRS_BLUEPRINT.md); seven priority questions remain.

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


## Follow-up correction
- 2026-10-26: Menyelaraskan pilihan stack pada blueprint dengan master prompt: seluruh kode aplikasi dan logika bisnis SIMRS wajib Python; pilihan default Django + DRF + PostgreSQL. Dokumentasi saja; runtime/database tidak berubah.
