"""
Project KAALI — Hash Shield End-to-End Demonstration Script
Walks through the complete recovery pipeline from scratch:
1. Microservice Liveness & Health Probe (/health)
2. In-Memory Perceptual Hashing (/v1/hash)
3. StopNCII Intimate Image Hand-off Safeguard (/v1/scan intimate=true)
4. Web Image Discovery & Safe Verification (/v1/scan intimate=false)
5. Case Initialization from Scanned Candidates (/v1/cases)
6. SSRF-Safe Host RDAP Intelligence Lookup (/v1/cases/{id}/lookup)
7. Statutory Takedown Notice & Court PDF Generation (/v1/cases/{id}/notices)
8. Victim Notice Dispatch & 24-Hour SLA Timer (/v1/cases/{id}/sent)
9. Live Web Removal Status Probe (/v1/cases/{id}/check)
10. SLA Cron Expiry Monitor (/v1/jobs/due)
11. Case Resolution & Escalation Packet (/v1/cases/{id}/resolve)
"""

import io
import os
import sys
import base64
from datetime import datetime, timezone, timedelta
from PIL import Image, ImageDraw
from fastapi.testclient import TestClient

# Ensure current directory is on python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Windows console unicode protection
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from app.main import app
from app.config import settings
from app.storage import storage


def generate_benign_samples():
    """Generates three in-memory synthetic images for testing."""
    # 1. Original Image (Geometric shapes on steel-blue canvas)
    img_orig = Image.new("RGB", (300, 300), color=(70, 130, 180))
    draw_orig = ImageDraw.Draw(img_orig)
    draw_orig.rectangle([60, 60, 240, 240], fill=(220, 20, 60))
    draw_orig.ellipse([90, 90, 210, 210], fill=(255, 215, 0))
    
    buf_orig = io.BytesIO()
    img_orig.save(buf_orig, format="JPEG", quality=95)
    orig_bytes = buf_orig.getvalue()

    # 2. Recompressed Copy (Quality 70, resized to 200x200)
    img_recomp = img_orig.resize((200, 200))
    buf_recomp = io.BytesIO()
    img_recomp.save(buf_recomp, format="JPEG", quality=70)
    recomp_bytes = buf_recomp.getvalue()

    # 3. Unrelated Image (Forest-green canvas with purple triangle)
    img_unrel = Image.new("RGB", (300, 300), color=(34, 139, 34))
    draw_unrel = ImageDraw.Draw(img_unrel)
    draw_unrel.polygon([(40, 260), (150, 40), (260, 260)], fill=(138, 43, 226))
    
    buf_unrel = io.BytesIO()
    img_unrel.save(buf_unrel, format="JPEG", quality=95)
    unrel_bytes = buf_unrel.getvalue()

    return orig_bytes, recomp_bytes, unrel_bytes


def run_demo():
    print("=" * 80)
    print(" 🛡️  PROJECT KAALI — HASH SHIELD RECOVERY PIPELINE DEMONSTRATION")
    print("=" * 80)

    client = TestClient(app, headers={"X-API-Key": settings.API_KEY})

    # Step 0: Liveness
    print("\n[STEP 0] Checking Microservice Liveness Probe...")
    res_health = client.get("/health")
    assert res_health.status_code == 200
    print(f" -> Service Status: {res_health.json()['status']} | Version: {res_health.json()['version']}")

    # Step 1: Generate benign test images
    print("\n[STEP 1] Generating Synthetic In-Memory Images...")
    orig_bytes, recomp_bytes, unrel_bytes = generate_benign_samples()
    print(" -> 1. Original Master Image (300x300, Q95)")
    print(" -> 2. Recompressed/Resized Derivative (200x200, Q70)")
    print(" -> 3. Unrelated Independent Image (300x300)")

    # Step 2: In-Memory Perceptual Hashing
    print("\n[STEP 2] Computing In-Memory Perceptual & Cryptographic Hashes...")
    res_hash_orig = client.post("/v1/hash", files={"file": ("master.jpg", orig_bytes, "image/jpeg")})
    assert res_hash_orig.status_code == 200
    orig_data = res_hash_orig.json()
    print(f" -> Master pHash  : {orig_data['phash']}")
    print(f" -> Master dHash  : {orig_data['dhash']}")
    print(f" -> Master SHA-256: {orig_data['sha256'][:32]}...")

    # Step 3: Test StopNCII Intimate Image Privacy Safeguard
    print("\n[STEP 3] Testing Intimate Image Safeguard (StopNCII Hand-Off)...")
    res_intimate = client.post(
        "/v1/scan",
        files={"file": ("intimate_sample.jpg", orig_bytes, "image/jpeg")},
        data={"consent": "true", "intimate": "true", "is_minor": "false"}
    )
    assert res_intimate.status_code == 200
    intimate_data = res_intimate.json()
    print(f" -> Intimate Flagged: {intimate_data['intimate']}")
    print(f" -> StopNCII Portal : {intimate_data['stop_ncii']['url']}")
    print(f" -> External Web Scan Bypassed: {len(intimate_data['candidates'])} external queries dispatched (Strict Privacy Preserved)")

    # Step 4: Web Image Discovery & Verification (Non-Intimate)
    print("\n[STEP 4] Executing Web Discovery & Candidate Image Verification...")
    res_scan = client.post(
        "/v1/scan",
        files={"file": ("master.jpg", orig_bytes, "image/jpeg")},
        data={"consent": "true", "intimate": "false", "is_minor": "false"}
    )
    assert res_scan.status_code == 200
    scan_data = res_scan.json()
    scan_orig_id = scan_data["original_id"]
    candidates = scan_data["candidates"]
    print(f" -> Discovery Scan ID: {scan_orig_id}")
    print(f" -> Discovered Candidates: {len(candidates)}")
    for idx, c in enumerate(candidates, 1):
        print(f"    [{idx}] Domain: {c['domain']:<22} | Type: {c['match_type']:<7} | Verified: {str(c['verified']):<5} | Dist: {c['distance']}")

    # Step 5: Case Creation from Discovered Candidates
    print("\n[STEP 5] Initializing Takedown Case from Discovered Candidates...")
    user_id = "victim_ananya_sharma"
    selected_candidate_ids = [candidates[0]["candidate_id"], candidates[1]["candidate_id"]]
    res_case = client.post("/v1/cases", json={
        "user_id": user_id,
        "original_id": scan_orig_id,
        "candidate_ids": selected_candidate_ids,
        "notes": "Targeted candidates confirmed infringing personal photo"
    })
    assert res_case.status_code == 200
    case_data = res_case.json()
    case_id = case_data["case_id"]
    print(f" -> Case Created: ID={case_id} | Status={case_data['status']} | URLs Under Action: {len(case_data['urls'])}")

    # Step 6: Host & Registrar Intelligence (SSRF-Safe RDAP)
    print("\n[STEP 6] Executing SSRF-Safe Host Intelligence Lookup...")
    res_lookup = client.post(f"/v1/cases/{case_id}/lookup")
    assert res_lookup.status_code == 200
    lookups = res_lookup.json()["lookups"]
    for lk in lookups:
        print(f" -> Domain: {lk['domain']:<20} | Host: {lk['host'] or 'Unknown':<18} | Abuse: {lk['abuse_emails']}")
        if lk.get("cloudflare_abuse_url"):
            print(f"    ↳ Cloudflare Abuse Link: {lk['cloudflare_abuse_url']}")

    # Step 7: Statutory Notice Generation
    print("\n[STEP 7] Generating Statutory Takedown Notices (Jinja2 & ReportLab PDF)...")
    res_notices = client.post(f"/v1/cases/{case_id}/notices")
    assert res_notices.status_code == 200
    notices_data = res_notices.json()
    print(f" -> Legal Review Marker Verified: '{notices_data['todo_marker']}'")
    
    # Save court-admissible PDF evidence
    pdf_bytes = base64.b64decode(notices_data["pdf_base64"])
    pdf_path = os.path.join(os.path.dirname(__file__), "demo_evidence_dossier.pdf")
    with open(pdf_path, "wb") as f:
        f.write(pdf_bytes)
    print(f" -> Evidence PDF Dossier Persisted to: {pdf_path} ({len(pdf_bytes)} bytes)")

    # Step 8: Mark Sent & SLA Timer Initiation
    print(f"\n[STEP 8] Victim Dispatches Notice & Starts Statutory {settings.SLA_HOURS}-Hour SLA Timer...")
    res_sent = client.post(f"/v1/cases/{case_id}/sent")
    assert res_sent.status_code == 200
    sent_data = res_sent.json()
    print(f" -> Case Status       : {sent_data['status']}")
    print(f" -> Dispatched At(UTC): {sent_data['sent_at']}")
    print(f" -> Statutory Deadline: {sent_data['deadline']} ({sent_data['sla_hours']} Hours SLA)")

    # Step 9: Live Web Removal Status Check
    print("\n[STEP 9] Checking Live Web Status for Takedown Verification...")
    res_check = client.post(f"/v1/cases/{case_id}/check")
    assert res_check.status_code == 200
    check_data = res_check.json()
    print(f" -> Advisory: {check_data['advice']}")
    for r in check_data["results"]:
        print(f" -> Target: {r['url'][:45]}... | Status: {r['status_code']} | Assessment: {r['removed_assessment']}")

    # Step 10: SLA Cron Monitoring
    print("\n[STEP 10] External Cron Inspection for Expired SLA Cases...")
    res_jobs = client.get("/v1/jobs/due")
    assert res_jobs.status_code == 200
    print(f" -> Overdue SLA Cases Detected: {res_jobs.json()['count']}")

    # Step 11: Case Resolution & Escalation Packet
    print("\n[STEP 11] Case Resolution & Statutory Escalation Packet...")
    res_escalate = client.post(f"/v1/cases/{case_id}/resolve", json={"removed": False})
    assert res_escalate.status_code == 200
    esc = res_escalate.json()["escalation"]
    print(f" -> Status: {res_escalate.json()['status']}")
    print(f" -> National Cyber Crime Reporting Portal: {esc['portal']}")
    print(f" -> Helpline                             : {esc['helpline']}")
    print(f" -> StopNCII Portal                      : {esc['stop_ncii']['url']}")

    print("\n" + "=" * 80)
    print(" ✅ COMPLETE HASH SHIELD RECOVERY PIPELINE DEMO SUCCEEDED (EXIT CODE 0)!")
    print("=" * 80)


if __name__ == "__main__":
    run_demo()
