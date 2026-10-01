"""Plaintext envelopes inside the relay ciphertext (CONTRACTS §2). Strict: unknown fields fail.

Nothing here names or locates a person: an offer/accept carries a public key, a query carries
the question and a random nonce, and an answer carries the vocabulary-checked answer plus the
query's nonce so the asker can match it.
"""

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from warden.models import ReassuranceQuestion
from warden.reassurance.vocabulary import WireAnswer

B64_KEY = r"^[A-Za-z0-9+/]{43}=$"  # 32 bytes, standard base64
NONCE = r"^[0-9a-f]{32}$"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class PairOffer(_Strict):
    t: Literal["pair_offer"]
    public_key: str = Field(pattern=B64_KEY)
    expires_at: AwareDatetime


class PairAccept(_Strict):
    t: Literal["pair_accept"]
    public_key: str = Field(pattern=B64_KEY)
    proof: str = Field(pattern=r"^[0-9a-f]{64}$")


class Query(_Strict):
    t: Literal["query"]
    q: ReassuranceQuestion
    nonce: str = Field(pattern=NONCE)
    ts: AwareDatetime


class Answer(_Strict):
    t: Literal["answer"]
    re: str = Field(pattern=NONCE)
    answer: WireAnswer

