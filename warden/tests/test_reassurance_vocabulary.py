"""Acceptance (T-15): answers outside the fixed vocabulary are rejected, and rejected *before*
encryption: nothing reaches the relay."""

from datetime import UTC, datetime
from typing import Any

import pytest
from l2_harness import NOW, Pair, signal_returning
from warden.reassurance.vocabulary import VocabularyViolation, enforce

TS = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
OUT_OF_VOCABULARY: list[Any] = [
    {"level": "normal", "reason": "at the hospital on 5th street", "ts": TS},  # free text
    {"level": "fine", "reason": "active_as_usual", "ts": TS},  # unknown level
    {"level": "Normal", "reason": "active_as_usual", "ts": TS},  # case matters
    {"level": "normal ", "reason": "active_as_usual", "ts": TS},  # so does whitespace
    {"level": "normal", "reason": "active_as_usual", "ts": TS, "location": "52.52,13.40"},
    {"level": "normal", "reason": "active_as_usual", "ts": TS, "note": ""},  # any extra field
    {"level": "normal", "reason": "active_as_usual"},  # missing ts
    {"level": "normal", "reason": "active_as_usual", "ts": "2026-10-01T12:00:00Z"},  # str ts
    {"level": "normal", "reason": "active_as_usual", "ts": datetime(2026, 10, 1, 12)},  # naive
    {"level": ["normal"], "reason": "active_as_usual", "ts": TS},  # nested
    {"level": {"v": "normal"}, "reason": "active_as_usual", "ts": TS},
    {"level": 1, "reason": "active_as_usual", "ts": TS},
    "normal",
    None,
    ["normal", "active_as_usual", TS],
]


@pytest.mark.parametrize("candidate", OUT_OF_VOCABULARY)
def test_enforce_rejects_anything_outside_the_vocabulary(candidate: Any) -> None:
    with pytest.raises(VocabularyViolation):
        enforce(candidate)


def test_the_error_never_echoes_the_offending_value() -> None:
    with pytest.raises(VocabularyViolation) as caught:
        enforce({"level": "normal", "reason": "at the hospital on 5th street", "ts": TS})
    assert "hospital" not in str(caught.value)


@pytest.mark.parametrize(
    ("level", "reason"),
    [
        ("normal", "active_as_usual"),
        ("normal", "do_not_disturb"),
        ("unusual", "quieter_than_usual"),
        ("help", "asked_for_help"),
        ("unknown", "not_enough_data"),
        ("normal", "arrived"),
        ("unusual", "not_arrived"),
    ],
)
def test_enforce_accepts_the_vocabulary(level: str, reason: str) -> None:
    answer = enforce({"level": level, "reason": reason, "ts": TS})
    assert answer.model_dump() == {"level": level, "reason": reason, "ts": TS}


@pytest.mark.parametrize("candidate", OUT_OF_VOCABULARY[:6])
async def test_an_out_of_vocabulary_answer_is_never_encrypted_or_sent(
    pair: Pair, candidate: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    alice_id_for_bob, bob_id_for_alice = await pair.pair()
    pair.bob.service._signal_fn = signal_returning(candidate)

    sealed: list[bytes] = []
    from warden.reassurance import crypto

    real_seal = crypto.seal_for_peer

    def spy(*args: Any) -> bytes:
        sealed.append(args[2])
        return real_seal(*args)

    monkeypatch.setattr(crypto, "seal_for_peer", spy)
    pair.alice.service._ask_timeout_s = 0.2
    alice_query_posts = len(pair.posts) + 1

    with pytest.raises(Exception, match="didn't answer"):
        await pair.alice_asks(alice_id_for_bob)

    # Only Alice's query was ever sealed and posted; Bob encrypted and sent nothing.
    assert len(sealed) == 1 and b'"t":"query"' in sealed[0]
    assert len(pair.posts) == alice_query_posts
    # The question is still in Bob's log, with nothing shared.
    [entry] = await pair.bob.store.questions_log.query()
    assert entry["peer_id"] == bob_id_for_alice
    assert entry["answer_level"] == "unknown"


async def test_a_peer_sending_junk_is_rejected_by_the_asker_too(pair: Pair) -> None:
    """Defence in depth: a modified peer Warden that skips its own gate still can't get
    free text onto the asker's screen."""
    from nacl.public import PublicKey
    from warden.reassurance import crypto
    from warden.reassurance.service import BadAnswer

    alice_id_for_bob, _ = await pair.pair()
    alice = pair.alice.service
    original = alice._relay.post  # type: ignore[union-attr]

    async def post_then_inject(recipient: str, ciphertext: bytes, sender: str) -> int:
        sent = await original(recipient, ciphertext, sender)
        nonce = next(iter(alice._waiting))
        junk = (
            '{"t":"answer","re":"' + nonce + '","answer":{"level":"normal",'
            '"reason":"at the hospital","ts":"' + NOW.isoformat() + '"}}'
        )
        evil = crypto.seal_for_peer(
            pair.bob.key, PublicKey(bytes(pair.alice.key.public_key)), junk.encode()
        )
        await original(alice.key_id, evil, pair.bob.service.key_id)
        return sent

    alice._relay.post = post_then_inject  # type: ignore[union-attr, method-assign]
    with pytest.raises(BadAnswer):
        await alice.ask(alice_id_for_bob, "ok")
    [row] = await pair.alice.store.peers.query()
    assert row["last_answer"] is None
