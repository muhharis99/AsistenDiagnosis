# PROJECT_STATE — AsistenDiagnosis / SIMRS Blueprint

Last updated: 2026-10-26  
Current phase: **Fase 1 — Platform foundation implemented in demo scope; validation and owner feedback pending**  
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
- Phase 1: Python/Django foundation, role assignment + active unit scoping, append-only audit hash-chain, organization units, versioned terminology and encrypted demo MPI — implemented in isolated `simrs_platform/`; CI tests and generated migrations are part of the Phase 1 branch/PR.
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


## Fase 1 status (2026-10-26)
- Added Python 3.12+, Django/DRF, OpenAPI, uv project tooling and a dedicated CI workflow.
- Added organization units and active user-unit assignments; role assignments have effective dates and optional unit scope.
- Added a write-once audit event table with a SHA-256 hash chain and metadata checks rejecting common PHI/secret keys.
- Added terminology tables with system/version provenance; no clinical code catalog was invented or seeded.
- Added MPI service that encrypts name/NIK using an environment-provided Fernet key and HMAC fingerprints for conservative matching. Duplicate candidates are returned for manual review; there is no automatic merge. An explicit merge service records actor/reason and preserves the source patient.
- Remaining before Phase 2: unit/encounter-specific ABAC, merge reversal/unmerge workflow, external append-only audit sink, broader API contracts, full security review, clinical/legal sign-off, UAT, backup/restore, and independent penetration testing.
- Safety status: demo-only; no real patient data, production connectivity, or clinical use.
