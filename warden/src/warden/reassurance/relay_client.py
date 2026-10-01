"""The Warden's only client for the relay mailbox (CONTRACTS §2 "Relay API")."""

import base64
import json
from dataclasses import dataclass

import httpx2 as httpx
from pydantic import BaseModel, Field, TypeAdapter, ValidationError

MAX_CIPHERTEXT_BYTES = 4096  # the relay's own cap; anything bigger in a mailbox is skipped


class _Item(BaseModel):
    id: int = Field(ge=1)
    ciphertext: str = Field(max_length=4 * MAX_CIPHERTEXT_BYTES)
    sender_key_id: str = Field(pattern=r"^[0-9a-f]{32}$")


_MAILBOX = TypeAdapter(list[_Item])


@dataclass(frozen=True, slots=True)
class RelayMessage:
    id: int
    ciphertext: bytes
    sender_key_id: str

    @property
    def body_bytes(self) -> int:
        """The exact size of the POST body the sender sent (see `envelope_body`)."""
        return len(envelope_body(base64.b64encode(self.ciphertext).decode(), self.sender_key_id))


def envelope_body(ciphertext_b64: str, sender_key_id: str) -> bytes:
    """Canonical POST body, so sender and recipient agree on `bytes_sent` to the byte."""
    return json.dumps(
        {"ciphertext": ciphertext_b64, "sender_key_id": sender_key_id}, separators=(",", ":")
    ).encode()


class RelayClient:
    def __init__(self, base_url: str, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._client = httpx.AsyncClient(base_url=base_url, transport=transport, timeout=10)

    async def post(self, recipient_key_id: str, ciphertext: bytes, sender_key_id: str) -> int:
        """Returns the number of bytes sent (the request body)."""
        body = envelope_body(base64.b64encode(ciphertext).decode(), sender_key_id)
        response = await self._client.post(
            f"/v1/mailbox/{recipient_key_id}",
            content=body,
            headers={"content-type": "application/json"},
        )
        response.raise_for_status()
        return len(body)

    async def fetch(self, key_id: str, since: int = 0) -> list[RelayMessage]:
        response = await self._client.get(f"/v1/mailbox/{key_id}", params={"since": since})
        response.raise_for_status()
        try:
            items = _MAILBOX.validate_json(response.content)
        except ValidationError as exc:  # a broken or hostile relay must never crash the poller
            raise ValueError("malformed relay response") from exc
        messages = []
        for item in items:
            try:
                raw = base64.b64decode(item.ciphertext, validate=True)
            except ValueError:
                continue
            if len(raw) > MAX_CIPHERTEXT_BYTES:
                continue
            messages.append(
                RelayMessage(id=item.id, ciphertext=raw, sender_key_id=item.sender_key_id)
            )
        return messages

    async def aclose(self) -> None:
        await self._client.aclose()
