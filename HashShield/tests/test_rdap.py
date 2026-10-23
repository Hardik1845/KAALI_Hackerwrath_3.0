import pytest
from unittest.mock import patch
from app.rdap import lookup_domain_rdap


@pytest.mark.asyncio
async def test_rdap_lookup_success():
    """
    Test 3a (Mandatory):
    RDAP lookup with mocked response extracting registrar, host, and abuse emails.
    """
    mock_rdap_data = {
        "asn_description": "CLOUDFLARENET - Cloudflare, Inc., US",
        "network": {"name": "CLOUDFLARE"},
        "objects": {
            "REG-1": {
                "roles": ["registrar"],
                "contact": {"name": "Cloudflare Registrar LLC"}
            },
            "ABUSE-1": {
                "roles": ["abuse"],
                "contact": {"email": [{"value": "abuse@cloudflare.com"}]}
            }
        }
    }

    with patch("app.rdap.validate_hostname_ssrf", return_value=(True, ["104.16.132.229"], "")):
        with patch("app.rdap._perform_sync_rdap", return_value=mock_rdap_data):
            res = await lookup_domain_rdap("https://example-infringing-site.com/media/leak.jpg")
            assert res.status == "found"
            assert "Cloudflare" in res.host
            assert res.registrar == "Cloudflare Registrar LLC"
            assert "abuse@cloudflare.com" in res.abuse_emails


@pytest.mark.asyncio
async def test_rdap_lookup_timeout_handled():
    """
    Test 3b (Mandatory):
    RDAP lookup timeout or network failure returns 'not_found' and never crashes.
    """
    with patch("app.rdap.validate_hostname_ssrf", return_value=(True, ["104.16.132.229"], "")):
        with patch("app.rdap._perform_sync_rdap", side_effect=TimeoutError("Connection timed out")):
            res = await lookup_domain_rdap("https://slow-unresponsive-site.xyz/photo.png")
            assert res.status == "not_found"
            assert "failed" in res.error_detail.lower()
