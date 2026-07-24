import logging
import httpx

logger = logging.getLogger(__name__)

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"
EXPO_BATCH_SIZE = 100


async def send_push_to_tokens(tokens: list[str], title: str, body: str, data: dict | None = None) -> None:
    """Send an Expo push to a list of tokens. Never raises — logs and swallows all errors
    so a push failure can never break the caller's underlying operation."""
    if not tokens:
        return
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            for i in range(0, len(tokens), EXPO_BATCH_SIZE):
                batch = tokens[i:i + EXPO_BATCH_SIZE]
                messages = [
                    {"to": token, "title": title, "body": body, "data": data or {}, "sound": "default"}
                    for token in batch
                ]
                response = await client.post(EXPO_PUSH_URL, json=messages)
                if response.status_code != 200:
                    logger.warning(f"Expo push send returned {response.status_code}: {response.text}")
    except Exception as e:
        logger.error(f"Push send failed: {e}")


async def send_push_to_user(user: dict, title: str, body: str, data: dict | None = None) -> None:
    tokens = [t["token"] for t in user.get("push_tokens", []) if t.get("token")]
    await send_push_to_tokens(tokens, title, body, data)
