"""Plain-text Telegram transport with sanitized outcomes and conservative retries."""

import logging
import re
from dataclasses import dataclass

import httpx


class RedactBotToken(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = re.sub(r"bot[0-9]+:[A-Za-z0-9_-]+", "bot[REDACTED]", record.getMessage())
        record.args = ()
        return True


@dataclass(frozen=True)
class DeliveryResult:
    outcome: str
    reason: str
    retry_after: int = 0


async def send_message(client: httpx.AsyncClient, token: str, chat_id: str, text: str) -> DeliveryResult:
    if not re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]+", token) or not chat_id:
        return DeliveryResult("failed", "invalid_configuration")
    # HTTPX logs request URLs at INFO; Telegram embeds its token in that URL.
    for name in ("httpx", "httpcore"):
        logger = logging.getLogger(name)
        if not any(isinstance(item, RedactBotToken) for item in logger.filters):
            logger.addFilter(RedactBotToken())
    try:
        response = await client.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "link_preview_options": {"is_disabled": True},
                  "allow_paid_broadcast": False},
            timeout=10,
        )
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
        return DeliveryResult("retry", "connection_unavailable", 60)
    except httpx.HTTPError:
        return DeliveryResult("uncertain", "transport_outcome_unknown")
    try:
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("invalid response")
    except ValueError:
        return DeliveryResult("uncertain", "invalid_provider_response")
    if response.status_code == 200 and data.get("ok") is True:
        result = data.get("result")
        message_id = result.get("message_id") if isinstance(result, dict) else None
        if isinstance(message_id, int) and not isinstance(message_id, bool) and message_id > 0:
            return DeliveryResult("sent", "provider_confirmed")
        return DeliveryResult("uncertain", "missing_confirmation")
    if response.status_code == 429 or data.get("error_code") == 429:
        params = data.get("parameters")
        delay = params.get("retry_after") if isinstance(params, dict) else None
        if not isinstance(delay, int) or isinstance(delay, bool) or delay < 1:
            delay = 60
        if delay > 86400:
            return DeliveryResult("uncertain", "unsupported_retry_delay")
        return DeliveryResult("retry", "provider_rate_limit", delay)
    if response.status_code in (400, 401, 403, 404) or data.get("error_code") in (400, 401, 403, 404):
        return DeliveryResult("failed", "provider_rejected")
    return DeliveryResult("uncertain", "provider_outcome_unknown")
