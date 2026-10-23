# 🛡️ Hash Shield Microservice — Project KAALI

> **Zero-Knowledge Evidence Collection, Perceptual Hashing, Host Intelligence & Statutory 24-Hour Takedown Notice Engine for Women's Digital Safety.**

---

## 1. System Overview

Hash Shield is a privacy-first backend microservice designed for Project KAALI. It allows victims of image-based abuse, non-consensual intimate imagery (NCII), and deepfake morphs to:
- **Hash on Device / In-Memory**: Compute cryptographic (`SHA-256`) and perceptual (`pHash`, `dHash`) fingerprints without raw image bytes ever touching disk or database.
- **Match Against Vault**: Register authentic photos and identify matches across suspected links using bitwise Hamming distance (threshold: 10 bits).
- **SSRF-Safe Host Discovery**: Conduct RDAP and DNS queries on target domains without ever scraping, crawling, or fetching the infringing URLs.
- **Statutory Notice Generation**: Auto-compile formal Cease & Desist notices (IT Rules 2021, Rule 3(2)(b) and DMCA) as plain-text templates and court-admissible PDF dossiers.
- **24-Hour SLA Timer**: Track remediation countdowns and provide instant escalation paths to `cybercrime.gov.in` and national helpline `1930`.
- **StopNCII.org Link-Out**: Provide direct links and instructions for registering hashes with the StopNCII coalition.

---

## 2. Hard Security Rules Enforced

1. **Zero Raw Image Persistence**: Images are parsed exclusively in memory via `io.BytesIO`. Once dimensions and hashes are computed, buffers are immediately discarded.
2. **Never Fetch / Crawl User URLs**: Only domains are extracted using `tldextract` for network RDAP queries. The microservice never connects to the target content path.
3. **SSRF Rejection**: All hostname lookups are validated against loopback (`127.0.0.0/8`), private (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`), and link-local (`169.254.169.254`) IP spaces.
4. **Minor Protection Mandate**: If any request or notes indicate a person under 18, processing halts immediately with status `422`, providing direct guidance to Childline `1098` and `cybercrime.gov.in`.
5. **No Automatic Notice Dispatch**: All notices are generated as drafts for the victim to send personally.
6. **No Biometric Profiling**: No face recognition or individual identity extraction.

---

## 3. Quickstart & Local Setup

### Prerequisites
- Python 3.11+
- Virtual environment (recommended)

### Installation
From PowerShell at the project root:
```powershell
cd HashShield
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```
Set `API_KEY` in `HashShield/.env` and use the same value for `HASH_SHIELD_API_KEY` in the project root `.env`. Choose `DISCOVER_PROVIDER=serpapi_lens` and set `SERPAPI_API_KEY`, or choose `google_vision` and configure Google Cloud credentials. `mock` returns synthetic fixtures and is only for development checks.

`ENABLE_SSCD` is off by default. Its optional MobileNet descriptor downloads pretrained torchvision weights on first use, so keep it off for a predictable local setup; perceptual hash verification remains available.

### Running Locally
```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8002 --reload
```
Interactive OpenAPI documentation will be accessible at:
- **Swagger UI**: `http://localhost:8002/docs`
- **ReDoc**: `http://localhost:8002/redoc`
- **Health Check**: `http://localhost:8002/health`

### Running Test Suite
```bash
pytest -v tests/
```

### Running the End-to-End Demo
```bash
python demo.py
```

---

## 4. API Endpoints Reference

All API routes require the `X-API-Key` header (except `/health`). The Kaali browser uses the same-origin Node proxy, which adds the service key server-side; the browser never receives it.

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/health` | Liveness and health check |
| `POST` | `/v1/scan` | Hash original photo, run web discovery & verification; StopNCII hand-off if `intimate=true` |
| `POST` | `/v1/hash` | Multipart image upload → computes pHash, dHash, SHA-256; image bytes discarded |
| `POST` | `/v1/vault` | Register authentic reference image fingerprint for a `user_id` |
| `POST` | `/v1/match` | Suspect image or hash → Hamming distance matching against user vault |
| `POST` | `/v1/cases` | Create an evidence recovery case with target URLs or candidate IDs |
| `POST` | `/v1/cases/{id}/lookup` | SSRF-safe RDAP host & registrar lookup for each URL (incl. Cloudflare abuse link) |
| `POST` | `/v1/cases/{id}/notices` | Generate plain-text templates & ReportLab PDF evidence document with `TODO` review marker |
| `POST` | `/v1/cases/{id}/sent` | Mark notice dispatched; initiates statutory 24-hour SLA timer |
| `POST` | `/v1/cases/{id}/check` | Non-destructive HEAD/GET live status probe (404/410 vs 200/403) |
| `GET` | `/v1/cases/{id}` | Inspect case status, evidence log, and SLA seconds remaining evaluated on read |
| `GET` | `/v1/jobs/due` | Cron endpoint for inspecting cases where the 24-hour SLA has expired |
| `POST` | `/v1/cases/{id}/resolve` | Close case if removed, or escalate to `cybercrime.gov.in` and `1930` |

---

### Discovery Providers (`DISCOVER_PROVIDER`)
- **`mock`**: Synthetic exact, cropped, and unrelated candidates for development checks only; never use it as actual web search.
- **`google_vision`**: Google Cloud Vision API `WEB_DETECTION` with free tier (first 1,000 requests/month free).
- **24-Hour Cache**: Discovery results cached in memory by pHash. Never stores image bytes.
- **Daily Quota Cap**: Configurable via `DISCOVER_DAILY_LIMIT` (default 50).

---

## 5. Docker Deployment

### Build Image
```bash
docker build -t hashshield:latest .
```

### Run Container
```bash
docker run -p 8000:8000 --env-file .env hashshield:latest
```

---

## 6. Cloud Deployment Targets

### Render
1. Push repo to GitHub.
2. Create a new **Web Service** on Render.
3. Select **Docker** environment or Python 3.11 with start command:
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port $PORT
   ```
4. Set Environment Variables:
   - `API_KEY`
   - `SLA_HOURS=24`
   - `HASH_THRESHOLD=10`

### Hugging Face Spaces (Docker Space)
1. Create a new Space with **Docker** SDK.
2. Push `HashShield/` files.
3. Expose port `7860` (or update `PORT=7860` in Dockerfile).
