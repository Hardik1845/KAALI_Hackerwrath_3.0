import logging
from typing import List, Dict, Any, Optional
import urllib.parse
import httpx
from app.config import settings

logger = logging.getLogger("emergencysos.voice")


class VoiceDispatcher:
    """Abstract interface for automated emergency voice phone calls."""
    async def make_call(self, to_phone: str, spoken_text: str) -> Dict[str, Any]:
        raise NotImplementedError

    async def broadcast_voice_alerts(
        self,
        contacts: List[Dict[str, Any]],
        victim_name: str,
        location: Dict[str, Any]
    ) -> List[str]:
        """Places automated emergency voice calls to registered contacts."""
        lat = location.get("lat", 0.0)
        lng = location.get("lng", 0.0)
        speech = (
            f"Emergency SOS alert. This is an urgent automated alert from Project KAALI. "
            f"{victim_name} has triggered an emergency distress call. "
            f"Last known coordinates are latitude {lat:.4f}, longitude {lng:.4f}. "
            f"An SMS with the live tracking link has been sent to your phone. "
            f"Please take immediate action or contact emergency police services at 112. "
            f"Repeating: {victim_name} needs urgent assistance."
        )

        placed_calls = []
        # Call priority 1 contacts or all contacts
        tier1 = [c for c in contacts if c.get("priority", 1) == 1] or contacts
        for contact in tier1:
            phone = contact.get("phone")
            if phone:
                res = await self.make_call(phone, speech)
                if res.get("status") in ("queued", "in-progress", "initiated", "delivered_mock"):
                    placed_calls.append(phone)
        return placed_calls


class MockVoiceDispatcher(VoiceDispatcher):
    """Local zero-dependency mock voice caller for offline development and tests."""
    def __init__(self):
        self.call_history: List[Dict[str, Any]] = []

    async def make_call(self, to_phone: str, spoken_text: str) -> Dict[str, Any]:
        record = {
            "to": to_phone,
            "spoken_text": spoken_text,
            "status": "delivered_mock",
            "provider": "mock_voice"
        }
        self.call_history.append(record)
        logger.info(f"📞 [MOCK PHONE CALL PLACED] To: {to_phone}\nVoice Speech: \"{spoken_text}\"\n" + "-" * 50)
        return record


class TwilioVoiceDispatcher(VoiceDispatcher):
    """
    Live Twilio Voice Call dispatcher.
    Places real automated phone calls using Twilio Programmable Voice REST API and TwiML.
    """
    def __init__(self):
        self.account_sid = settings.TWILIO_ACCOUNT_SID
        self.auth_token = settings.TWILIO_AUTH_TOKEN
        self.from_phone = settings.TWILIO_PHONE_NUMBER
        self.fallback = MockVoiceDispatcher()

    async def make_call(self, to_phone: str, spoken_text: str) -> Dict[str, Any]:
        if not self.account_sid or not self.auth_token or not self.from_phone:
            logger.warning("Twilio credentials missing; falling back to Mock Voice caller.")
            return await self.fallback.make_call(to_phone, spoken_text)

        url = f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}/Calls.json"

        # TwiML payload using Polly.Aditi (Indian English) or Alice fallback
        twiml = (
            f"<Response>"
            f"<Pause length=\"1\"/>"
            f"<Say voice=\"alice\" language=\"en-IN\">{spoken_text}</Say>"
            f"<Pause length=\"1\"/>"
            f"<Say voice=\"alice\" language=\"en-IN\">{spoken_text}</Say>"
            f"</Response>"
        )

        data = {
            "To": to_phone,
            "From": self.from_phone,
            "Twiml": twiml
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                res = await client.post(
                    url,
                    data=data,
                    auth=(self.account_sid, self.auth_token)
                )

                if res.status_code in (200, 201):
                    call_data = res.json()
                    logger.info(f"📞 ✅ Twilio Voice Call placed to {to_phone} (Call SID: {call_data.get('sid')})")
                    return {
                        "to": to_phone,
                        "status": "initiated",
                        "sid": call_data.get("sid"),
                        "provider": "twilio"
                    }
                else:
                    logger.error(f"❌ Twilio Voice Call error ({res.status_code}): {res.text}")
                    return await self.fallback.make_call(to_phone, spoken_text)

        except Exception as e:
            logger.error(f"Twilio Voice network exception ({e}); fallback to mock.")
            return await self.fallback.make_call(to_phone, spoken_text)


_mock_voice = MockVoiceDispatcher()
_twilio_voice = None


def get_voice_dispatcher() -> VoiceDispatcher:
    global _twilio_voice
    # If credentials are provided or SMS_PROVIDER is twilio, use TwilioVoiceDispatcher
    if settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN and settings.TWILIO_PHONE_NUMBER:
        if _twilio_voice is None:
            _twilio_voice = TwilioVoiceDispatcher()
        return _twilio_voice
    elif settings.SMS_PROVIDER.lower().strip() == "twilio":
        if _twilio_voice is None:
            _twilio_voice = TwilioVoiceDispatcher()
        return _twilio_voice
    return _mock_voice
