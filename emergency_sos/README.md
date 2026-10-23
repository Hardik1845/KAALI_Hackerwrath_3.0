# KAALI — Emergency SOS Matrix Microservice

Emergency SOS is the **Protect & Dispatch** core engine of **KAALI**, an AI-powered safety platform for women. When an individual is in imminent danger, Emergency SOS triggers immediate situational awareness, broadcasts live GPS tracking links to trusted guardians, activates a 60-second auto-escalation timer for police dispatch, and records tamper-evident ambient audio evidence sealed for court admissibility under Section 65B of the Indian Evidence Act / Bharatiya Sakshya Adhiniyam (BSA).

---

## ⚡ Core Architecture & Features

1. **One-Tap / Triple-Tap Instant SOS (`POST /api/v1/sos/trigger`)**:
   - Creates a unique encrypted session tracking ID.
   - Computes live radar tracking link (`/live/{session_id}`).
   - Dispatches emergency SMS to Tier 1 contacts (Twilio / Mock fallback).
   - Starts a strict **60-second auto-escalation timer** for Police Control Room (PCR 112) escalation.
2. **Spatial Safe Haven Routing (`app/havens.py`)**:
   - Real-time Haversine spatial calculation matching victim's GPS coordinates against verified 24/7 Police Stations, Apollo Pharmacies, Trauma Hospitals, and CISF-manned Metro stations.
3. **Real-Time GPS WebSocket Telemetry (`/ws/sos/{id}` & `/ws/guardian/{id}`)**:
   - Zero-latency pub/sub fanout broadcasting victim coordinates, speed, and accuracy to guardian dashboards.
4. **Secret Passphrase & Coercion / Duress Detection (`POST /api/v1/sos/cancel`)**:
   - Disarms the active session with the victim's secret passphrase.
   - **Duress Protection**: If forced by an attacker to cancel, entering trigger words like `help` or `danger` returns a deceptive "SOS Deactivated" screen while secretly escalating to Police PCR 112 in the background.
5. **Encrypted Ambient Audio Witness (`POST & GET /api/v1/sos/{session_id}/audio`)**:
   - Audio is encrypted at rest using AES-256 (Fernet symmetric cipher).
   - Tamper-evident cryptographic SHA-256 hash generated upon receipt.
6. **Forensic Court-Admissible Dossier (`GET /api/v1/sos/{session_id}/dossier`)**:
   - Generates a PDF containing complete GPS breadcrumb log, contact dispatch audit, and Section 65B electronic evidence certification.
7. **Guardian Tactical Live Radar (`/live/{session_id}`)**:
   - Dark-mode glassmorphism interface with Leaflet.js map, pulsing beacon, breadcrumb polyline, ambient audio player, and one-tap 112 calling.

---

## 📂 File Structure

```
emergency sos/
├── .env.example
├── .env
├── requirements.txt
├── demo.py                        # Interactive end-to-end verification demo
├── Dockerfile
├── app/
│   ├── __init__.py
│   ├── main.py                   # FastAPI routing & WebSockets
│   ├── config.py                 # Pydantic v2 environment settings
│   ├── models.py                 # Pydantic schemas (Request/Response)
│   ├── security.py               # AES-256 encryption & Duress logic
│   ├── sms.py                    # Mock & Twilio SMS dispatchers
│   ├── havens.py                 # Spatial Haversine safe havens locator
│   ├── storage.py                # Thread-safe persistent session store
│   ├── websocket_manager.py      # Pub/Sub connection manager
│   ├── escalation.py             # 60s auto-escalation background worker
│   └── dossier.py                # ReportLab Section 65B PDF generator
├── static/
│   └── live.html                 # Leaflet.js Guardian Tactical Radar
└── tests/
    ├── __init__.py
    ├── conftest.py
    ├── test_sos_api.py           # API trigger, cancel, audio, dossier tests
    ├── test_escalation.py        # 60s timer & auto-escalation tests
    └── test_websocket.py         # Real-time WebSocket fanout tests
```

---

## 🚀 Quickstart

### 1. Install Dependencies
```bash
cd "emergency sos"
pip install -r requirements.txt
```

### 2. Run the Automated Test Suite
```bash
python -m pytest tests -v
```

### 3. Run the End-to-End Demo Script
```bash
python demo.py
```

### 4. Launch the Microservice
```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
```

- **Interactive API Documentation (Swagger)**: [http://127.0.0.1:8001/docs](http://127.0.0.1:8001/docs)
- **Guardian Tactical Live Radar**: `http://127.0.0.1:8001/live/<session_id>`
