# Hash Shield: Technical & Legal Limitations

This document explicitly outlines the technical, cryptographic, operational, and legal boundaries of the **Hash Shield** microservice.

---

## 1. Perceptual Hash Resilience & Evasion

- **Heuristic Nature**: Perceptual hashing algorithms (`pHash`, `dHash`, `PDQ`) map high-dimensional visual content into compact 64-bit or 256-bit binary descriptors.
- **Tolerant To**: Minor resizing, moderate JPEG compression (quality ≥ 60%), slight cropping (≤ 10%), and subtle color balance shifts.
- **Vulnerable To**: Adversarial manipulation, severe cropping, rotations (> 5°), heavy artistic filters, deep face morphing, synthetic background replacement, and collage insertion.
- **Core Principle**: **Absence of a perceptual hash match is NOT conclusive proof that an image is absent or authentic.** A false-negative does not negate victim testimony.

---

## 2. RDAP & WHOIS Intelligence Discrepancies

- **Privacy Proxies**: Many commercial hosting services, bulletproof hosters, and domain registrars implement WHOIS Privacy Guard services (e.g., Withheld for Privacy, Domains By Proxy, Cloudflare reverse proxies).
- **Missing Abuse Records**: RDAP queries for decentralized, offshore, or bulletproof networks may return partial or redacted contact information.
- **Fail-Safe Policy**: When RDAP lookups fail or time out, the microservice gracefully returns `status="not_found"` without crashing.

---

## 3. Human-in-the-Loop Sovereign Notice Dispatch

- **Drafts Only**: Hash Shield strictly generates **drafts** (plain-text and cryptographic PDF dossiers).
- **No Automated Transmission**: The microservice never automatically transmits emails or submits web forms to third parties on the victim's behalf. The user must personally inspect, approve, and send the notice from her own authenticated email client.

---

## 4. Legal Review & Statutory Evolution

- **Placeholder Warning**: All generated text templates and PDF files feature a prominent visual disclaimer: `[TODO: verify legal wording]`.
- **Jurisdictional Variations**: The default templates cite Rule 3(2)(b) of the Indian Information Technology (Intermediary Guidelines and Digital Media Ethics Code) Rules, 2021 (which stipulates a 24-hour statutory remediation window) alongside IPC/BNS and Section 66E/67A provisions.
- **Review Requirement**: Because statutory rules, court precedents, and ministerial gazettes evolve over time, all generated notices must be verified by certified legal counsel or victim advocacy organizations prior to formal litigation.

---

## 5. StopNCII.org Link-Out Notice

- **No Public API**: StopNCII.org operates an independent, closed platform coalition for hashes shared between participating platforms (e.g., Meta, TikTok, OnlyFans).
- **No Simulation**: StopNCII does **not** provide a public REST API for third-party automated submission. Hash Shield explicitly provides link-outs and user instructions directly to [https://stopncii.org](https://stopncii.org), rather than simulating an unauthorized integration.
