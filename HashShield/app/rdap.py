import asyncio
import logging
import time
from typing import Dict, List, Optional, Set, Any
from urllib.parse import urlparse
import tldextract
from ipwhois import IPWhois
from app.models import LookupResultItem
from app.security import validate_hostname_ssrf

logger = logging.getLogger("hashshield.rdap")


def extract_domain_from_url(url: str) -> str:
    """
    Safely extract the domain or FQDN from a user-supplied URL.
    Does NOT connect to or fetch the URL.
    """
    clean_url = url.strip()
    if not clean_url.startswith(("http://", "https://")):
        clean_url = "http://" + clean_url

    parsed = urlparse(clean_url)
    hostname = parsed.hostname or parsed.netloc

    if not hostname:
        return ""

    # Clean port if present
    if ":" in hostname:
        hostname = hostname.split(":")[0]

    ext = tldextract.extract(hostname)
    # Use fqdn or domain.suffix
    if ext.suffix:
        return ext.fqdn if ext.fqdn else f"{ext.domain}.{ext.suffix}"
    return hostname.lower()


def _perform_sync_rdap(ip: str, timeout: int = 4) -> Dict[str, Any]:
    """Execute sync IPWhois RDAP query with error catching."""
    ipw = IPWhois(ip, timeout=timeout)
    return ipw.lookup_rdap(depth=1)


async def lookup_domain_rdap(url: str, max_retries: int = 2) -> LookupResultItem:
    """
    Safely look up registrar, hosting network, and abuse contacts for a URL.
    SSRF-safe: Only resolves public IPs; rejects private/loopback/link-local addresses.
    Never crashes; returns 'not_found' or error details gracefully.
    """
    domain = extract_domain_from_url(url)
    if not domain:
        return LookupResultItem(
            url=url,
            domain="",
            status="not_found",
            error_detail="Invalid URL or missing domain"
        )

    # SSRF verification on the domain
    is_safe, resolved_ips, ssrf_reason = validate_hostname_ssrf(domain)
    if not is_safe or not resolved_ips:
        logger.warning(f"SSRF check failed for domain '{domain}': {ssrf_reason}")
        return LookupResultItem(
            url=url,
            domain=domain,
            status="not_found",
            error_detail=f"SSRF Safety block or unresolvable domain: {ssrf_reason}"
        )

    primary_ip = resolved_ips[0]
    rdap_result = None
    last_err = None

    # Retry loop with backoff
    for attempt in range(max_retries + 1):
        try:
            # Run IPWhois in thread pool to prevent blocking the event loop
            rdap_result = await asyncio.to_thread(_perform_sync_rdap, primary_ip, timeout=3)
            break
        except Exception as e:
            last_err = e
            if attempt < max_retries:
                await asyncio.sleep(0.5 * (2 ** attempt))

    if not rdap_result:
        return LookupResultItem(
            url=url,
            domain=domain,
            status="not_found",
            error_detail=f"RDAP lookup failed: {str(last_err)}"
        )

    # Extract Host / ASN
    asn_desc = rdap_result.get("asn_description")
    network = rdap_result.get("network") or {}
    net_name = network.get("name")
    host = asn_desc or net_name or "Unknown Host"

    # Extract Registrar & Abuse Emails
    abuse_emails: Set[str] = set()
    registrar = None

    objects = rdap_result.get("objects") or {}
    for obj_key, obj_val in objects.items():
        if not isinstance(obj_val, dict):
            continue
        
        # Check roles
        roles = obj_val.get("roles") or []
        contact = obj_val.get("contact") or {}

        # Look for registrar name
        if "registrar" in roles and not registrar:
            registrar = contact.get("name") or obj_key

        # Collect email addresses
        email_data = contact.get("email") or []
        if isinstance(email_data, list):
            for item in email_data:
                if isinstance(item, dict) and "value" in item:
                    abuse_emails.add(str(item["value"]).strip().lower())
                elif isinstance(item, str):
                    abuse_emails.add(item.strip().lower())
        elif isinstance(email_data, str):
            abuse_emails.add(email_data.strip().lower())

    # Check if host is behind Cloudflare
    cf_abuse_url = None
    combined_info = f"{host} {registrar or ''}".lower()
    if "cloudflare" in combined_info:
        cf_abuse_url = "https://abuse.cloudflare.com"

    return LookupResultItem(
        url=url,
        domain=domain,
        registrar=registrar or "Unspecified Registrar",
        host=host,
        abuse_emails=sorted(list(abuse_emails)),
        cloudflare_abuse_url=cf_abuse_url,
        status="found"
    )
