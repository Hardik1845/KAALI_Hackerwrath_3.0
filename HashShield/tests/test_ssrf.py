import pytest
from app.security import is_safe_ip, validate_hostname_ssrf
from app.rdap import lookup_domain_rdap


def test_ssrf_ip_classifier():
    """
    Test 4a (Mandatory):
    Direct validation of dangerous and private IP ranges.
    """
    unsafe_ips = [
        "127.0.0.1",          # Loopback
        "127.0.1.1",          # Loopback range
        "10.0.0.5",           # Private RFC 1918 Class A
        "172.16.0.10",        # Private RFC 1918 Class B
        "192.168.1.100",      # Private RFC 1918 Class C
        "169.254.169.254",    # Link-local / AWS instance metadata service
        "0.0.0.0",            # Unspecified
        "::1",                # IPv6 loopback
        "fe80::1",            # IPv6 link-local
        "::ffff:127.0.0.1"    # IPv4-mapped IPv6 loopback
    ]

    for ip in unsafe_ips:
        assert is_safe_ip(ip) is False, f"IP {ip} should be rejected as unsafe"

    safe_public_ips = [
        "8.8.8.8",
        "1.1.1.1",
        "104.16.132.229",
        "142.250.190.46"
    ]

    for ip in safe_public_ips:
        assert is_safe_ip(ip) is True, f"Public IP {ip} should be accepted"


def test_ssrf_hostname_rejection():
    """
    Test 4b (Mandatory):
    Hostname SSRF rejection for localhost, internal domains, and metadata endpoints.
    """
    unsafe_hosts = [
        "localhost",
        "localhost.localdomain",
        "internal.local",
        "127.0.0.1",
        "169.254.169.254"
    ]

    for host in unsafe_hosts:
        is_safe, ips, reason = validate_hostname_ssrf(host)
        assert is_safe is False, f"Host {host} should have failed SSRF verification"


@pytest.mark.asyncio
async def test_ssrf_rdap_lookup_rejected():
    """
    Test 4c (Mandatory):
    Attempting an RDAP lookup on a private/loopback URL returns 'not_found' with safety block.
    """
    res = await lookup_domain_rdap("http://127.0.0.1/admin/leak.png")
    assert res.status == "not_found"
    assert "ssrf" in res.error_detail.lower() or "blocked" in res.error_detail.lower()

    res_meta = await lookup_domain_rdap("http://169.254.169.254/latest/meta-data/")
    assert res_meta.status == "not_found"
    assert "ssrf" in res_meta.error_detail.lower() or "blocked" in res_meta.error_detail.lower()
