import ipaddress
import socket
from typing import List, Tuple, Optional
from fastapi import Header, HTTPException, status, Depends
from fastapi.security import APIKeyHeader
import dns.resolver
from slowapi import Limiter
from slowapi.util import get_remote_address
from app.config import settings

# SlowAPI Limiter instance
limiter = Limiter(key_func=get_remote_address, default_limits=[settings.RATE_LIMIT_DEFAULT])

# OpenAPI Security Scheme for X-API-Key
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False, description="Secret service API key for HashShield")


def verify_api_key(x_api_key: Optional[str] = Depends(api_key_header)) -> str:
    """Validate the service-to-service secret API key."""
    if not settings.API_KEY:
        return x_api_key or ""
    if not x_api_key or x_api_key != settings.API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-API-Key header. Provide 'X-API-Key: kaali-secret-key-12345' in headers or click Authorize in Swagger UI."
        )
    return x_api_key


def is_safe_ip(ip_str: str) -> bool:
    """
    Evaluate whether an IP address is a safe public routable address.
    Strictly reject private, loopback, link-local, multicast, and reserved addresses.
    """
    try:
        ip = ipaddress.ip_address(ip_str)

        # Check for IPv4-mapped IPv6 addresses (e.g., ::ffff:127.0.0.1)
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            ip = ip.ipv4_mapped

        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return False

        # Extra safety check for 0.0.0.0/8 and 100.64.0.0/10 (Carrier-grade NAT)
        if isinstance(ip, ipaddress.IPv4Address):
            octets = ip.exploded.split('.')
            if octets[0] == '0' or octets[0] == '127':
                return False
            if octets[0] == '100' and (64 <= int(octets[1]) <= 127):
                return False

        return True
    except ValueError:
        return False


def validate_hostname_ssrf(hostname: str) -> Tuple[bool, List[str], str]:
    """
    Resolve DNS for a given hostname and assert that all resolved IP addresses are safe.
    Returns (is_safe, resolved_ips, reason).
    """
    hostname = hostname.strip().lower()
    
    # Instant rejection for known internal names
    blocked_names = {"localhost", "localhost.localdomain", "127.0.0.1", "::1", "0.0.0.0"}
    if hostname in blocked_names or hostname.endswith(".local") or hostname.endswith(".internal"):
        return False, [], "Internal or loopback hostname blocked"

    # If hostname is already an IP address
    try:
        ipaddress.ip_address(hostname)
        if not is_safe_ip(hostname):
            return False, [hostname], "Direct IP falls into private/loopback range"
        return True, [hostname], ""
    except ValueError:
        pass

    # Resolve host IPs via OS getaddrinfo (handles local Windows DNS, VPN, and system hosts)
    resolved_ips: List[str] = []
    try:
        try:
            infos = socket.getaddrinfo(hostname, None)
            for item in infos:
                ip = item[4][0]
                if ip not in resolved_ips:
                    resolved_ips.append(ip)
        except socket.gaierror:
            pass

        # Fallback to dnspython if needed
        if not resolved_ips:
            try:
                resolver = dns.resolver.Resolver()
                resolver.timeout = 2.0
                resolver.lifetime = 2.0
                try:
                    for rdata in resolver.resolve(hostname, 'A'):
                        resolved_ips.append(str(rdata))
                except Exception:
                    pass
                try:
                    for rdata in resolver.resolve(hostname, 'AAAA'):
                        resolved_ips.append(str(rdata))
                except Exception:
                    pass
            except Exception:
                pass

        if not resolved_ips:
            return False, [], "DNS resolution failed (host not found)"

        # Verify every resolved IP against SSRF rules
        for ip in resolved_ips:
            if not is_safe_ip(ip):
                return False, resolved_ips, f"Hostname resolves to unsafe address: {ip}"

        return True, resolved_ips, ""

    except Exception as e:
        return False, [], f"DNS lookup error: {str(e)}"


def validate_image_bytes(data: bytes, max_mb: int = 10) -> Tuple[bool, str, str]:
    """
    Enforce file size limits and inspect true magic bytes.
    Returns (is_valid, mime_type, error_message).
    """
    if len(data) > max_mb * 1024 * 1024:
        return False, "", f"File exceeds maximum allowed size of {max_mb} MB"

    if len(data) < 12:
        return False, "", "File data too small to be a valid image"

    # JPEG: starts with FF D8 FF
    if data[:3] == b'\xff\xd8\xff':
        return True, "image/jpeg", ""

    # PNG: starts with 89 50 4E 47 0D 0A 1A 0A
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        return True, "image/png", ""

    # WebP: starts with RIFF, then 4 bytes of size, then WEBP
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return True, "image/webp", ""

    return False, "", "Invalid image file format. Only JPEG, PNG, and WebP are allowed."
