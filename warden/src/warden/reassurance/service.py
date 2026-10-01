"""Pairing, asking and answering over the relay mailbox (CONTRACTS §2, ADR-0004).

Pairing (one-time code, 10-minute expiry):
1. A: `start_pairing` derives (mailbox id, key) from a fresh code with Argon2id and posts a
   SecretBox'd `PairOffer{public_key, expires_at}` to that mailbox. A stores the derived key,
   never the code.
2. B: `join_pairing` derives the same material from the typed code, opens the offer, saves A
   as a peer, and posts a sealed `PairAccept{public_key, proof}` to A's mailbox. The proof
   (keyed BLAKE2b over both public keys) shows B knew the code.
3. A's poller checks the proof against its pending pairings, saves B, and deletes the pending
   entry, so the code works once. Display names are local; no name crosses the relay.

Asking (A asks B "ok?"): A posts a Box'd `Query{q, nonce, ts}` and polls its own mailbox for
the `Answer` carrying the same nonce. B's poller computes the local signal, runs it through
`vocabulary.enforce`, applies B's sharing rule for A, enforces again, and only then encrypts.
Every question is written to B's question log, whatever the outcome.
"""

import asyncio
import base64
import json
import logging
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx2 as httpx
from nacl.public import PrivateKey, PublicKey
from pydantic import ValidationError
from ulid import ULID

from warden.db import Store
from warden.events import EventBus
from warden.ids import new_peer_id
from warden.models import (
    AskPeerResponse,
    PairingStartResponse,
    Peer,
    PrivacyReceipt,
    QuestionLogEntry,
    ReassuranceAnswer,
    ReassuranceQuestion,
    SharingRule,
)
from warden.reassurance import crypto, signal
from warden.reassurance.keys import key_id
from warden.reassurance.messages import Answer, PairAccept, PairOffer, Query
from warden.reassurance.relay_client import RelayClient, RelayMessage
from warden.reassurance.sources import ActivityProbe, calendar_busy_now
from warden.reassurance.vocabulary import (
    FIELDS_SHARED,
    VocabularyViolation,
    WireAnswer,
    enforce,
    unknown,
)

log = logging.getLogger(__name__)

CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
CODE_LENGTH = 8
PAIRING_TTL = timedelta(minutes=10)
QUERY_MAX_AGE = timedelta(minutes=5)
SAMPLE_EVERY_S = 300.0
ACTIVE_IF_IDLE_BELOW_S = 300.0
SAMPLE_RETENTION = timedelta(days=28)
MAX_QUERIES_PER_PEER_PER_HOUR = 30


class ReassuranceError(Exception):
    """Base for the errors the routes map to HTTP statuses."""


class RelayUnavailable(ReassuranceError):
    pass


class PeerNotFound(ReassuranceError):
    pass


class InvalidCode(ReassuranceError):
    pass


class PairingNotFound(ReassuranceError):
    pass


class SelfPairing(ReassuranceError):
    pass


class NoAnswer(ReassuranceError):
    pass


class BadAnswer(ReassuranceError):
    """The peer's answer failed our own vocabulary check; it is discarded, never shown."""


def default_rule(peer_id: str) -> SharingRule:
    """What a new peer may ask: "ok?" only, every level. The owner can narrow or revoke it."""
    return SharingRule(
        peer_id=peer_id,
        allowed_questions=["ok"],
        allowed_levels=["normal", "unusual", "help", "unknown"],
        active=True,
    )


def apply_rule(
    rule: SharingRule | None, q: ReassuranceQuestion, answer: ReassuranceAnswer
) -> ReassuranceAnswer:
    """The owner's rule decides; anything it doesn't allow becomes the null answer."""
    if rule is None or not rule.active or q not in rule.allowed_questions:
        return unknown(answer.ts)
    if answer.level not in rule.allowed_levels:
        return unknown(answer.ts)
    return answer


def new_code() -> str:
    return "".join(secrets.choice(CROCKFORD) for _ in range(CODE_LENGTH))


def normalize_code(raw: str) -> str:
    code = raw.upper().replace("-", "").replace(" ", "")
    code = code.translate(str.maketrans("ILO", "110"))
    if len(code) != CODE_LENGTH or any(c not in CROCKFORD for c in code):
        raise InvalidCode("a pairing code is 8 characters")
    return code


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(slots=True)
class _Waiter:
    peer_key_id: str
    future: "asyncio.Future[tuple[ReassuranceAnswer, RelayMessage]]"


class Reassurance:
    def __init__(
        self,
        store: Store,
        events: EventBus,
        key: PrivateKey,
        relay: RelayClient | None,
        probe: ActivityProbe,
        *,
        now: Callable[[], datetime] = _utcnow,
        signal_fn: Callable[[datetime, signal.SignalInputs], object] = signal.compute,
        busy_fn: Callable[[datetime], bool] = calendar_busy_now,
        ask_timeout_s: float = 20.0,
        ask_poll_s: float = 0.25,
        poll_s: float = 2.0,
    ) -> None:
        self._store = store
        self._events = events
        self._key = key
        self._relay = relay
        self._probe = probe
        self._now = now
        self._signal_fn = signal_fn
        self._busy_fn = busy_fn
        self._ask_timeout_s = ask_timeout_s
        self._ask_poll_s = ask_poll_s
        self._poll_s = poll_s
        self._waiting: dict[str, _Waiter] = {}
        self._poll_lock = asyncio.Lock()

    @property
    def public_key(self) -> bytes:
        return bytes(self._key.public_key)

    @property
    def key_id(self) -> str:
        return key_id(self.public_key)

    def _require_relay(self) -> RelayClient:
        if self._relay is None:
            raise RelayUnavailable("RELAY_URL is not configured")
        return self._relay

    # --- my own state: check-ins, "I need help", activity -----------------------------------

    async def _me(self) -> dict[str, Any]:
        return await self._store.me.get("me") or {"help": False, "last_check_in": None}

    async def check_in(self) -> None:
        """ "I'm OK": refreshes the signal and clears an earlier "I need help"."""
        me = await self._me()
        me.update(help=False, last_check_in=self._now().isoformat())
        await self._store.me.put("me", me)

    async def set_help(self, needed: bool) -> None:
        me = await self._me()
        me["help"] = needed
        await self._store.me.put("me", me)

    async def record_activity_sample(self) -> None:
        idle = await asyncio.to_thread(self._probe.idle_seconds)
        if idle is None:
            return
        now = self._now()
        await self._store.activity_samples.put(
            now.isoformat(), {"ts": now.isoformat(), "active": idle < ACTIVE_IF_IDLE_BELOW_S}
        )
        await self._store.activity_samples.delete_below("ts", (now - SAMPLE_RETENTION).isoformat())

    async def gather_inputs(self, now: datetime) -> signal.SignalInputs:
        me = await self._me()
        samples = [
            signal.ActivitySample(ts=datetime.fromisoformat(r["ts"]), active=bool(r["active"]))
            for r in await self._store.activity_samples.query()
        ]
        last = me.get("last_check_in")
        return signal.SignalInputs(
            help_requested=bool(me.get("help")),
            last_check_in=datetime.fromisoformat(last) if last else None,
            busy_now=await asyncio.to_thread(self._busy_fn, now),
            samples=samples,
            idle_s=await asyncio.to_thread(self._probe.idle_seconds),
        )

    async def current_signal(self) -> ReassuranceAnswer:
        """What an allowed peer asking "ok?" would get right now (before sharing rules)."""
        now = self._now()
        return enforce(self._signal_fn(now, await self.gather_inputs(now)))

    # --- pairing ----------------------------------------------------------------------------

    async def start_pairing(self, display_name: str) -> PairingStartResponse:
        relay = self._require_relay()
        code = new_code()
        mailbox_id, key = await asyncio.to_thread(crypto.derive_pairing, code)
        now = self._now()
        expires_at = now + PAIRING_TTL
        await self._prune_pairings(now)
        # Stored before the offer is posted, so an accept can never beat it.
        await self._store.pairings.put(
            mailbox_id,
            {
                "mailbox_id": mailbox_id,
                "key": key.hex(),
                "expires_at": expires_at.isoformat(),
                "display_name": display_name,
            },
        )
        offer = PairOffer(t="pair_offer", public_key=_b64(self.public_key), expires_at=expires_at)
        try:
            await relay.post(
                mailbox_id, crypto.seal_offer(key, offer.model_dump_json().encode()), mailbox_id
            )
        except httpx.HTTPError as exc:
            await self._store.pairings.delete(mailbox_id)
            raise RelayUnavailable("relay unreachable") from exc
        return PairingStartResponse(code=code, expires_at=expires_at)

    async def join_pairing(self, raw_code: str, display_name: str) -> Peer:
        code = normalize_code(raw_code)
        relay = self._require_relay()
        mailbox_id, key = await asyncio.to_thread(crypto.derive_pairing, code)
        try:
            messages = await relay.fetch(mailbox_id)
        except (httpx.HTTPError, ValueError) as exc:
            raise RelayUnavailable("relay unreachable") from exc
        offer: PairOffer | None = None
        for message in messages:
            try:
                offer = PairOffer.model_validate_json(crypto.open_offer(key, message.ciphertext))
                break
            except (crypto.CryptoError, ValidationError):
                continue
        if offer is None or offer.expires_at <= self._now():
            raise PairingNotFound("no live pairing for that code")
        offerer = base64.b64decode(offer.public_key)
        if offerer == self.public_key:
            raise SelfPairing("that code is this Warden's own")
        accept = PairAccept(
            t="pair_accept",
            public_key=_b64(self.public_key),
            proof=crypto.pairing_proof(key, offerer, self.public_key),
        )
        sealed = crypto.seal_anonymous(PublicKey(offerer), accept.model_dump_json().encode())
        try:
            await relay.post(key_id(offerer), sealed, self.key_id)
        except httpx.HTTPError as exc:
            raise RelayUnavailable("relay unreachable") from exc
        return await self._save_peer(offer.public_key, display_name)

    async def _prune_pairings(self, now: datetime) -> None:
        for row in await self._store.pairings.query():
            if datetime.fromisoformat(row["expires_at"]) <= now:
                await self._store.pairings.delete(row["mailbox_id"])

    async def _save_peer(self, public_key_b64: str, display_name: str) -> Peer:
        existing = await self._peer_row_by_key_id(key_id(base64.b64decode(public_key_b64)))
        if existing is not None:
            return Peer.model_validate(existing["peer"])
        peer = Peer(
            id=new_peer_id(),
            display_name=display_name,
            public_key=public_key_b64,
            paired_at=self._now(),
        )
        await self._store.peers.put(
            peer.id,
            {"peer": peer.model_dump(mode="json"), "last_answer": None, "last_answer_at": None},
        )
        if await self._store.sharing_rules.get(peer.id) is None:
            await self._store.sharing_rules.put(
                peer.id, default_rule(peer.id).model_dump(mode="json")
            )
        return peer

    async def _peer_row_by_key_id(self, sender_key_id: str) -> dict[str, Any] | None:
        for row in await self._store.peers.query():
            if key_id(base64.b64decode(row["peer"]["public_key"])) == sender_key_id:
                return row
        return None

    async def _handle_pair_accept(self, message: RelayMessage) -> None:
        try:
            accept = PairAccept.model_validate_json(
                crypto.open_anonymous(self._key, message.ciphertext)
            )
        except (crypto.CryptoError, ValidationError):
            log.info("dropped a message from an unknown sender")
            return
        joiner = base64.b64decode(accept.public_key)
        if key_id(joiner) != message.sender_key_id:
            return
        now = self._now()
        for row in await self._store.pairings.query():
            if datetime.fromisoformat(row["expires_at"]) <= now:
                await self._store.pairings.delete(row["mailbox_id"])
                continue
            expected = crypto.pairing_proof(bytes.fromhex(row["key"]), self.public_key, joiner)
            if crypto.proof_matches(expected, accept.proof):
                await self._store.pairings.delete(row["mailbox_id"])  # one-time
                await self._save_peer(accept.public_key, row["display_name"])
                log.info("pairing completed")
                return
        log.info("dropped a pairing accept with no live pairing")

    # --- asking -----------------------------------------------------------------------------

    async def ask(self, peer_id: str, q: ReassuranceQuestion) -> AskPeerResponse:
        row = await self._store.peers.get(peer_id)
        if row is None:
            raise PeerNotFound(peer_id)
        relay = self._require_relay()
        peer = Peer.model_validate(row["peer"])
        peer_key = PublicKey(base64.b64decode(peer.public_key))
        peer_key_id = key_id(peer_key)

        loop = asyncio.get_running_loop()
        nonce = secrets.token_hex(16)
        future: asyncio.Future[tuple[ReassuranceAnswer, RelayMessage]] = loop.create_future()
        self._waiting[nonce] = _Waiter(peer_key_id, future)
        try:
            query = Query(t="query", q=q, nonce=nonce, ts=self._now())
            sealed = crypto.seal_for_peer(self._key, peer_key, query.model_dump_json().encode())
            try:
                await relay.post(peer_key_id, sealed, self.key_id)
            except httpx.HTTPError as exc:
                raise RelayUnavailable("relay unreachable") from exc
            deadline = loop.time() + self._ask_timeout_s
            while not future.done():
                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise NoAnswer("the peer didn't answer in time")
                await self.poll_once()
                if not future.done():
                    await asyncio.wait([future], timeout=min(self._ask_poll_s, remaining))
            answer, message = future.result()
        finally:
            self._waiting.pop(nonce, None)

        receipt = PrivacyReceipt(
            bytes_sent=message.body_bytes,
            fields_shared=list(FIELDS_SHARED),
            location_shared=False,
            egress_log_ref=f"relay:{message.id}",
        )
        row["last_answer"] = answer.model_dump(mode="json")
        row["last_answer_at"] = self._now().isoformat()
        await self._store.peers.put(peer_id, row)
        await self._events.publish("peer.answer", {"peer_id": peer_id, "q": q})
        return AskPeerResponse(answer=answer, receipt=receipt)

    # --- the mailbox ------------------------------------------------------------------------

    async def poll_once(self) -> None:
        relay = self._relay
        if relay is None:
            return
        async with self._poll_lock:
            state = await self._store.relay_state.get("cursor") or {"since": 0}
            since = int(state["since"])
            try:
                messages = await relay.fetch(self.key_id, since)
            except (httpx.HTTPError, ValueError) as exc:
                log.warning("relay poll failed: %s", type(exc).__name__)
                return
            await self._prune_pairings(self._now())
            for message in messages:
                try:
                    await self._handle(message)
                except Exception as exc:  # one bad message must not wedge the mailbox
                    log.warning("message %d dropped: %s", message.id, type(exc).__name__)
                since = max(since, message.id)
            if messages:
                await self._store.relay_state.put("cursor", {"since": since})

    async def run_forever(self) -> None:
        while True:
            try:
                await self.poll_once()
            except Exception as exc:  # e.g. a SQLite hiccup: log it, never let the poller die
                log.warning("mailbox poll failed: %s", type(exc).__name__)
            await asyncio.sleep(self._poll_s)

    async def run_sampler_forever(self) -> None:
        while True:
            try:
                await self.record_activity_sample()
            except Exception as exc:
                log.warning("activity sample failed: %s", type(exc).__name__)
            await asyncio.sleep(SAMPLE_EVERY_S)

    async def _handle(self, message: RelayMessage) -> None:
        row = await self._peer_row_by_key_id(message.sender_key_id)
        if row is None:
            await self._handle_pair_accept(message)
            return
        peer = Peer.model_validate(row["peer"])
        try:
            plaintext = crypto.open_from_peer(
                self._key, PublicKey(base64.b64decode(peer.public_key)), message.ciphertext
            )
        except crypto.CryptoError:
            log.info("dropped a message that failed authentication")
            return
        try:
            raw = json.loads(plaintext)
        except ValueError:
            return
        if not isinstance(raw, dict):
            return
        if raw.get("t") == "answer":
            self._deliver_answer(message, raw, plaintext)
        elif raw.get("t") == "query":
            try:
                query = Query.model_validate_json(plaintext)
            except ValidationError:
                log.info("dropped a malformed query")
                return
            await self._answer(peer, message.sender_key_id, query)

    def _deliver_answer(self, message: RelayMessage, raw: dict[str, Any], plaintext: bytes) -> None:
        waiter = self._waiting.get(str(raw.get("re")))
        if waiter is None or waiter.peer_key_id != message.sender_key_id or waiter.future.done():
            return
        try:
            answer = enforce(Answer.model_validate_json(plaintext).answer)
        except (ValidationError, VocabularyViolation):
            waiter.future.set_exception(BadAnswer("the peer's answer was outside the vocabulary"))
            return
        waiter.future.set_result((answer, message))

    async def _asked_in_last_hour(self, peer_id: str, now: datetime) -> int:
        cutoff = now - timedelta(hours=1)
        return sum(
            1
            for row in await self._store.questions_log.query()
            if row["peer_id"] == peer_id and datetime.fromisoformat(row["asked_at"]) > cutoff
        )

    async def _answer(self, peer: Peer, sender_key_id: str, query: Query) -> None:
        relay = self._require_relay()
        now = self._now()
        if abs(now - query.ts) > QUERY_MAX_AGE:
            log.info("dropped a stale query")
            return
        if await self._store.seen_nonces.get(query.nonce) is not None:
            log.info("dropped a replayed query")
            return
        await self._store.seen_nonces.put(query.nonce, {}, ts=now.isoformat())
        await self._store.seen_nonces.delete_below("ts", (now - 2 * QUERY_MAX_AGE).isoformat())
        if await self._asked_in_last_hour(peer.id, now) >= MAX_QUERIES_PER_PEER_PER_HOUR:
            # A hostile or compulsive asker (A7/A11) can't burn CPU or bury the owner's log.
            log.warning("dropped a query over the per-peer hourly limit")
            return

        sent_level = "unknown"
        try:
            if query.q == "ok":
                candidate = self._signal_fn(now, await self.gather_inputs(now))
            else:  # "home": v1 has no arrival signal, and location is never collected
                candidate = unknown(now)
            rule_row = await self._store.sharing_rules.get(peer.id)
            rule = SharingRule.model_validate(rule_row) if rule_row else None
            # The vocabulary gate runs before and after the rule, and always before encryption.
            answer = enforce(apply_rule(rule, query.q, enforce(candidate)))
            envelope = Answer(
                t="answer",
                re=query.nonce,
                answer=WireAnswer.model_validate(answer.model_dump()),
            )
            sealed = crypto.seal_for_peer(
                self._key,
                PublicKey(base64.b64decode(peer.public_key)),
                envelope.model_dump_json().encode(),
            )
            await relay.post(sender_key_id, sealed, self.key_id)
            sent_level = answer.level
        except VocabularyViolation as exc:
            log.warning("answer rejected before encryption; nothing sent: %s", exc)
        except httpx.HTTPError as exc:
            log.warning("answer not delivered: %s", type(exc).__name__)
        finally:
            entry = QuestionLogEntry.model_validate(
                {
                    "id": f"q_{ULID()}",
                    "peer_id": peer.id,
                    "question": query.q,
                    "asked_at": now,
                    "answer_level": sent_level,
                }
            )
            await self._store.questions_log.put(
                entry.id, entry.model_dump(mode="json"), asked_at=entry.asked_at.isoformat()
            )
