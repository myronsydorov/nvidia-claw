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
    PairingStatusResponse,
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
COMPLETED_PAIRING_KEPT = timedelta(hours=1)
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


class AlreadyPaired(ReassuranceError):
    pass


class TooSoon(ReassuranceError):
    pass


class NoAnswer(ReassuranceError):
    pass


class BadAnswer(ReassuranceError):
    """The peer's answer failed our own vocabulary check; it is discarded, never shown."""


def default_rule(peer_id: str) -> SharingRule:
    """What a new peer may ask once the owner confirms the fingerprint: "ok?" only, every
    level. Until then `active` is False, so a peer who raced the real joiner with an
    overheard code only ever gets `unknown` (security-reviewer, T-17 integration)."""
    return SharingRule(
        peer_id=peer_id,
        allowed_questions=["ok"],
        allowed_levels=["normal", "unusual", "help", "unknown"],
        active=False,
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
        ask_cooldown_s: float = 600.0,
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
        self._ask_cooldown = timedelta(seconds=ask_cooldown_s)
        self._ask_poll_s = ask_poll_s
        self._poll_s = poll_s
        self._waiting: dict[str, _Waiter] = {}
        self._poll_lock = asyncio.Lock()
        # Saving the peer and marking its pairing done are two writes; a status read between
        # them saw "waiting" with the peer already listed (flaky L2 test, 2026-10-01).
        self._pairing_lock = asyncio.Lock()
        self._ask_locks: dict[str, asyncio.Lock] = {}

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
        pairing_id = f"pr_{ULID()}"
        await self._store.pairings.put(
            mailbox_id,
            {
                "mailbox_id": mailbox_id,
                "pairing_id": pairing_id,
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
        return PairingStartResponse(pairing_id=pairing_id, code=code, expires_at=expires_at)

    async def pairing_status(self, pairing_id: str) -> PairingStatusResponse:
        async with self._pairing_lock:
            return await self._pairing_status(pairing_id)

    async def _pairing_status(self, pairing_id: str) -> PairingStatusResponse:
        now = self._now()
        for row in await self._store.pairings.query():
            if row.get("pairing_id") != pairing_id:
                continue
            if row.get("peer_id"):
                peer_row = await self._store.peers.get(row["peer_id"])
                if peer_row is not None:
                    return PairingStatusResponse(state="paired", peer=self.peer_from_row(peer_row))
                break  # paired, then un-paired
            if datetime.fromisoformat(row["expires_at"]) > now:
                return PairingStatusResponse(state="waiting", peer=None)
            break
        return PairingStatusResponse(state="expired", peer=None)

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
        if await self._peer_row_by_key_id(key_id(offerer)) is not None:
            # Re-pairing starts with un-pairing here, so both sides move to the new
            # fingerprint together (a replayed code can't desync them).
            raise AlreadyPaired("already paired with that Warden")
        pair_nonce = secrets.token_hex(16)  # fresh per pairing: no precomputed fingerprint
        accept = PairAccept(
            t="pair_accept",
            public_key=_b64(self.public_key),
            proof=crypto.pairing_proof(key, offerer, self.public_key),
            nonce=pair_nonce,
        )
        sealed = crypto.seal_anonymous(PublicKey(offerer), accept.model_dump_json().encode())
        try:
            await relay.post(key_id(offerer), sealed, self.key_id)
        except httpx.HTTPError as exc:
            raise RelayUnavailable("relay unreachable") from exc
        return await self._save_peer(offer.public_key, display_name, pair_nonce)

    async def _prune_pairings(self, now: datetime) -> None:
        # A completed pairing (no key left) stays an hour so its screen can show the result.
        for row in await self._store.pairings.query():
            keep_until = datetime.fromisoformat(row["expires_at"])
            if "key" not in row:
                keep_until += COMPLETED_PAIRING_KEPT
            if keep_until <= now:
                await self._store.pairings.delete(row["mailbox_id"])

    def peer_from_row(self, row: dict[str, Any]) -> Peer:
        stored = row["peer"]
        return Peer.model_validate(
            {
                **stored,
                "fingerprint": crypto.fingerprint(
                    self.public_key,
                    base64.b64decode(stored["public_key"]),
                    bytes.fromhex(row["pair_nonce"]),
                ),
            }
        )

    async def confirm(self, peer_id: str) -> None:
        """The person saw matching fingerprints: the peer's sharing rule takes effect."""
        if await self._store.peers.get(peer_id) is None:
            raise PeerNotFound(peer_id)
        stored = await self._store.sharing_rules.get(peer_id)
        rule = SharingRule.model_validate(stored) if stored else default_rule(peer_id)
        await self._store.sharing_rules.put(
            peer_id, rule.model_copy(update={"active": True}).model_dump(mode="json")
        )

    async def unpair(self, peer_id: str) -> None:
        """Forget a peer and their sharing rule. The question log stays: it's the owner's."""
        if await self._store.peers.get(peer_id) is None:
            raise PeerNotFound(peer_id)
        await self._store.peers.delete(peer_id)
        await self._store.sharing_rules.delete(peer_id)

    async def _save_peer(self, public_key_b64: str, display_name: str, pair_nonce: str) -> Peer:
        existing = await self._peer_row_by_key_id(key_id(base64.b64decode(public_key_b64)))
        if existing is not None:
            # Re-pairing: a new fingerprint to compare, and sharing waits for it again.
            existing["pair_nonce"] = pair_nonce
            peer_id = existing["peer"]["id"]
            await self._store.peers.put(peer_id, existing)
            stored = await self._store.sharing_rules.get(peer_id)
            rule = SharingRule.model_validate(stored) if stored else default_rule(peer_id)
            await self._store.sharing_rules.put(
                peer_id, rule.model_copy(update={"active": False}).model_dump(mode="json")
            )
            return self.peer_from_row(existing)
        peer_id = new_peer_id()
        row: dict[str, Any] = {
            "peer": {
                "id": peer_id,
                "display_name": display_name,
                "public_key": public_key_b64,
                "paired_at": self._now().isoformat(),
            },
            "last_answer": None,
            "last_answer_at": None,
            "last_asked_at": None,
            "pair_nonce": pair_nonce,
        }
        peer = self.peer_from_row(row)  # validates before anything is stored
        await self._store.peers.put(peer_id, row)
        if await self._store.sharing_rules.get(peer_id) is None:
            await self._store.sharing_rules.put(
                peer_id, default_rule(peer_id).model_dump(mode="json")
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
        await self._prune_pairings(now)
        for row in await self._store.pairings.query():
            if "key" not in row or datetime.fromisoformat(row["expires_at"]) <= now:
                continue  # already used, or expired
            expected = crypto.pairing_proof(bytes.fromhex(row["key"]), self.public_key, joiner)
            if crypto.proof_matches(expected, accept.proof):
                async with self._pairing_lock:
                    peer = await self._save_peer(
                        accept.public_key, row["display_name"], accept.nonce
                    )
                    # One-time: the key is dropped; the row only remembers the outcome.
                    done = {k: v for k, v in row.items() if k != "key"}
                    await self._store.pairings.put(row["mailbox_id"], {**done, "peer_id": peer.id})
                log.info("pairing completed")
                return
        log.info("dropped a pairing accept with no live pairing")

    # --- asking -----------------------------------------------------------------------------

    async def ask(self, peer_id: str, q: ReassuranceQuestion) -> AskPeerResponse:
        row = await self._store.peers.get(peer_id)
        if row is None:
            raise PeerNotFound(peer_id)
        relay = self._require_relay()
        peer = self.peer_from_row(row)
        async with self._ask_locks.setdefault(peer_id, asyncio.Lock()):
            row = await self._store.peers.get(peer_id) or row
            last = row.get("last_asked_at") or row.get("last_answer_at")
            if last and self._now() - datetime.fromisoformat(last) < self._ask_cooldown:
                # No "check again" loop (AGENTS #9, A11): they'll say if anything changes.
                raise TooSoon("asked less than the cooldown ago")
            # The clock starts when the question leaves, whatever comes back (or doesn't).
            row["last_asked_at"] = self._now().isoformat()
            await self._store.peers.put(peer_id, row)
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
        current = await self._store.peers.get(peer_id)
        if current is not None:  # un-paired while we waited: never bring the peer back
            current["last_answer"] = answer.model_dump(mode="json")
            current["last_answer_at"] = self._now().isoformat()
            await self._store.peers.put(peer_id, current)
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
        peer = self.peer_from_row(row)
        try:
            plaintext = crypto.open_from_peer(
                self._key, PublicKey(base64.b64decode(peer.public_key)), message.ciphertext
            )
        except crypto.CryptoError:
            # Not a Box from this peer: maybe they're re-pairing (a sealed accept).
            await self._handle_pair_accept(message)
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
