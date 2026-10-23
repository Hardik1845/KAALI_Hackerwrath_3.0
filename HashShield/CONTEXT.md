# Hash Shield: Continuous Context & Architecture Specification

> **Purpose**: This file serves as the canonical context document for artificial intelligence agents and human engineers working on the `HashShield` microservice. It details the operational workflows, security boundaries, database schemas, and state transitions.

---

## 1. System Overview

**Hash Shield** is a standalone Python/FastAPI microservice engineered for Project KAALI. It operates as the "Recover" pillar of a comprehensive women's cyber-physical safety platform. Its primary function is to empower victims of non-consensual intimate imagery (NCII), deepfake manipulation, and image-based abuse to:
1. Register authentic reference images in a private perceptual hash vault.
2. Verify suspected online infringing images against the vault using Hamming distance matching.
3. Conduct SSRF-safe RDAP lookups to trace host registrars and abuse desks from URLs.
4. Draft formal statutory Cease & Desist notices (under IT Rules 2021 Rule 3(2)(b) and DMCA) as plain text and cryptographic PDF evidence dossiers.
5. Track statutory 24-hour SLA remediation timers and provide instant escalation paths (e.g., cybercrime.gov.in, Helpline 1930).
6. Provide link-out guidance for StopNCII.org (without mocking or simulating an unauthorized API).

---

## 2. Hard Security Constraints & Invariants

All AI agents and developers modifying this codebase MUST uphold these non-negotiable invariants:

| Constraint | Enforcement Mechanism |
| :--- | :--- |
| **No Raw Image Persistence** | Uploaded images are strictly read in memory via `io.BytesIO`. Once hashes (`pHash`, `dHash`, `SHA-256`) and dimensions are extracted, the buffer is closed and garbage collected. No bytes are written to disk or database. |
| **No URL Crawling or Scraping** | The service never initiates HTTP GET/POST to suspect URLs. Only the domain is extracted using `tldextract` for DNS and RDAP network queries. |
| **Strict SSRF Mitigation** | All domain resolutions validate that target IPs do not fall into private, loopback, link-local, multicast, or reserved ranges (`127.0.0.0/8`, `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `169.254.0.0/16`, `::1`, `fc00::/7`). |
| **Under-18 Absolute Safety Valve** | If any request or user notes indicate the involvement of a minor (<18), processing halts immediately with status code `422 Unprocessable Entity` or `400 Bad Request`, directing to specialized child protection authorities (Childline 1098, cybercrime.gov.in). |
| **No Automated Notice Dispatch** | The system solely generates drafts (PDF & email text). The user retains sovereign control over dispatching legal notices. |
| **No Face Recognition** | No facial embedding, identity classification, or biometric profiling is performed. Matching relies solely on holistic perceptual image geometry (DCT/pHash/dHash). |

---

## 3. Workflow State Machine

```
[ User provides URL(s) + Image/Hash ]
                  │
                  ▼
         [ 1. In-Memory Hasher ] ──► Returns pHash, dHash, sha256
                  │
                  ▼
         [ 2. Vault Matcher ] ─────► Hamming Distance ≤ Threshold (10)
                  │
                  ▼
         [ 3. Case Creation ] ─────► Status: "created"
                  │
                  ▼
         [ 4. Host RDAP Lookup ] ──► Registrar, Hosting Org, Abuse Emails
                  │
                  ▼
         [ 5. Notice Generator ] ──► PDF Dossier & Text Drafts
                  │
                  ▼
         [ 6. Mark Sent ] ─────────► Status: "sent", SLA Timer (24h) starts
                  │
         ┌────────┴────────┐
         ▼                 ▼
   [ Removed: YES ]   [ Removed: NO ]
         │                 │
         ▼                 ▼
  Status: "closed"    Status: "escalated"
                      (Show CyberCrime / 1930)
```

---

## 4. Endpoints Reference

All endpoints are mounted with prefix `/v1` (and root `/health`).

- `GET /health`: Liveness probe.
- `POST /v1/hash`: Accepts multipart image file (`image/jpeg`, `image/png`, `image/webp` ≤ 10MB). Checks magic bytes. Returns hashes & dimensions. Discards image bytes.
- `POST /v1/vault`: Registers an original image hash for a `user_id`.
- `POST /v1/match`: Compares a suspect image or hash against a user's vault hashes using Hamming distance. Returns match list and threshold.
- `POST /v1/cases`: Initializes a case (`user_id`, `urls`, `evidence_hashes`, `notes`, `is_minor`).
- `POST /v1/cases/{id}/lookup`: Performs SSRF-safe RDAP resolution for each URL in the case.
- `POST /v1/cases/{id}/notices`: Compiles Jinja2 text templates and generates a ReportLab PDF evidence document.
- `POST /v1/cases/{id}/sent`: Marks notices as dispatched by user and calculates statutory SLA deadline timestamp.
- `GET /v1/cases/{id}`: Returns complete case status, remaining SLA timer in seconds, and evidence index.
- `POST /v1/cases/{id}/resolve`: Closes the case if content was removed, or transitions to escalated state with helpline guidance.

---

## 5. Storage Layer Abstraction

The storage layer (`app/storage.py`) implements a unified interface:
- If `MONGO_URL` is configured in environment, utilizes `motor.motor_asyncio` (MongoDB).
- If `MONGO_URL` is empty or unset, automatically falls back to an in-memory repository (`InMemoryStore`).

Both implementations share identical async semantics:
- `save_vault_item(item)` / `get_vault_items(user_id)`
- `save_case(case)` / `get_case(case_id)` / `update_case(case_id, update_dict)`
