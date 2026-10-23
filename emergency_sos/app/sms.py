import logging
from typing import List, Dict, Any, Optional
import httpx
from app.config import settings

logger = logging.getLogger("emergencysos.sms")


class SMSDispatcher:
    """Abstract SMS Dispatcher interface."""
    async def send_sms(self, to_phone: str, message: str) -> Dict[str, Any]:
        raise NotImplementedError

    async def broadcast_sos(
        self,
        contacts: List[Dict[str, Any]],
        victim_name: str,
        location: Dict[str, Any],
        tracking_url: str
    ) -> List[str]:
        """Broadcasts emergency SOS alert with live tracking radar to contacts."""
        lat = round(location.get("lat", 0.0), 5)
        lng = round(location.get("lng", 0.0), 5)
        name_upper = victim_name.upper() if victim_name else "JOHN WICK"
        msg = (
            f"SECURITY ALERT! "
            f"{name_upper} IS IN DANGER !!!! "
            f"Loc: {lat},{lng} | Live Radar: {tracking_url} | Call 112"
        )
        sent_to = []
        tier1 = [c for c in contacts if c.get("priority", 1) == 1] or contacts
        for contact in tier1:
            phone = contact.get("phone")
            if phone:
                await self.send_sms(phone, msg)
                sent_to.append(phone)
        return sent_to


class MockSMSDispatcher(SMSDispatcher):
    """Local zero-dependency mock SMS dispatcher that records and logs messages."""
    def __init__(self):
        self.sent_messages: List[Dict[str, Any]] = []

    async def send_sms(self, to_phone: str, message: str) -> Dict[str, Any]:
        record = {
            "to": to_phone,
            "message": message,
            "status": "delivered_mock",
            "provider": "mock"
        }
        self.sent_messages.append(record)
        logger.info(f"📱 [MOCK SMS DISPATCH] To: {to_phone}\nMessage: {message}\n" + "-" * 50)
        return record


class TwilioSMSDispatcher(SMSDispatcher):
    """Live Twilio SMS dispatcher using standard HTTP REST API via httpx."""
    def __init__(self):
        self.account_sid = settings.TWILIO_ACCOUNT_SID
        self.auth_token = settings.TWILIO_AUTH_TOKEN
        self.from_phone = settings.TWILIO_PHONE_NUMBER
        self.fallback = MockSMSDispatcher()

    async def send_sms(self, to_phone: str, message: str) -> Dict[str, Any]:
        if not self.account_sid or not self.auth_token or not self.from_phone:
            logger.warning("Twilio credentials incomplete; falling back to Mock SMS dispatcher.")
            return await self.fallback.send_sms(to_phone, message)

        url = f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}/Messages.json"
        data = {
            "From": self.from_phone,
            "To": to_phone,
            "Body": message
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(
                    url,
                    data=data,
                    auth=(self.account_sid, self.auth_token)
                )
                if res.status_code in (200, 201):
                    logger.info(f"✅ Twilio SMS dispatched successfully to {to_phone}")
                    return {
                        "to": to_phone,
                        "status": "sent",
                        "sid": res.json().get("sid"),
                        "provider": "twilio"
                    }
                else:
                    logger.error(f"❌ Twilio dispatch failed ({res.status_code}): {res.text}")
                    return await self.fallback.send_sms(to_phone, message)

        except Exception as e:
            logger.error(f"Twilio network error ({e}); using mock fallback.")
            return await self.fallback.send_sms(to_phone, message)


_mock_instance = MockSMSDispatcher()
_twilio_instance = None


def get_sms_dispatcher() -> SMSDispatcher:
    global _twilio_instance
    if settings.SMS_PROVIDER.lower().strip() == "twilio":
        if _twilio_instance is None:
            _twilio_instance = TwilioSMSDispatcher()
        return _twilio_instance
    return _mock_instance
