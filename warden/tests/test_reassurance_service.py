import base64
from datetime import timedelta
from typing import Any

import pytest
from l2_harness import Pair
from nacl.public import PrivateKey, PublicKey
from warden.models import SharingRule
from warden.reassurance import crypto
from warden.reassurance.keys import key_id
from warden.reassurance.messages import Query
from warden.reassurance.service import (
    AlreadyPaired,
    InvalidCode,
    NoAnswer,
    PairingNotFound,
    PeerNotFound,
    RelayUnavailable,
    SelfPairing,
    normalize_code,
)


async def test_pairing_gives_both_sides_a_peer_and_a_default_rule(pair: Pair) -> None:
    alice_id_for_bob, bob_id_for_alice = await pair.pair()

    [a_row] = await pair.alice.store.peers.query()
    [b_row] = await pair.bob.store.peers.query()
    assert a_row["peer"]["display_name"] == "Bob"
    assert b_row["peer"]["display_name"] == "Alice"
    assert base64.b64decode(a_row["peer"]["public_key"]) == bytes(pair.bob.key.public_key)
    assert base64.b64decode(b_row["peer"]["public_key"]) == bytes(pair.alice.key.public_key)
    rule = await pair.bob.store.sharing_rules.get(bob_id_for_alice)
    assert rule == {
        "peer_id": bob_id_for_alice,
        "allowed_questions": ["ok"],
        "allowed_levels": ["normal", "unusual", "help", "unknown"],
        "active": True,  # pair() confirms; see test_sharing_waits_for_the_fingerprint
    }
    assert await pair.alice.store.sharing_rules.get(alice_id_for_bob) is not None
    [pending] = await pair.alice.store.pairings.query()
    assert "key" not in pending  # consumed: the derived key is gone
    assert pending["peer_id"] == alice_id_for_bob


async def test_a_pairing_code_works_once(pair: Pair) -> None:
    started = await pair.alice.service.start_pairing("Bob")
    await pair.bob.service.join_pairing(started.code, "Alice")
    await pair.alice.service.poll_once()

    # A third Warden that overheard the code: its accept reaches Alice but is dropped.
    eve = pair.bob.service
    eve._key = PrivateKey.generate()
    await pair.bob.store.peers.delete((await pair.bob.store.peers.query())[0]["peer"]["id"])
    await eve.join_pairing(started.code, "Alice")
    await pair.alice.service.poll_once()
    assert len(await pair.alice.store.peers.query()) == 1


async def test_an_expired_code_is_refused(pair: Pair) -> None:
    started = await pair.alice.service.start_pairing("Bob")
    pair.clock.now += timedelta(minutes=11)
    with pytest.raises(PairingNotFound):
        await pair.bob.service.join_pairing(started.code, "Alice")


async def test_a_wrong_code_finds_nothing(pair: Pair) -> None:
    await pair.alice.service.start_pairing("Bob")
    with pytest.raises(PairingNotFound):
        await pair.bob.service.join_pairing("ZZZZZZZZ", "Alice")


async def test_pairing_with_yourself_is_refused(pair: Pair) -> None:
    started = await pair.alice.service.start_pairing("Me")
    with pytest.raises(SelfPairing):
        await pair.alice.service.join_pairing(started.code, "Me")


async def test_an_accept_with_a_bad_proof_is_dropped(pair: Pair) -> None:
    await pair.alice.service.start_pairing("Bob")
    forged = (
        '{"t":"pair_accept","public_key":"'
        + base64.b64encode(bytes(pair.bob.key.public_key)).decode()
        + '","proof":"'
        + "0" * 64
        + '"}'
    )
    sealed = crypto.seal_anonymous(pair.alice.key.public_key, forged.encode())
    await pair.bob.service._relay.post(  # type: ignore[union-attr]
        pair.alice.service.key_id, sealed, pair.bob.service.key_id
    )
    await pair.alice.service.poll_once()
    assert await pair.alice.store.peers.query() == []


@pytest.mark.parametrize(("raw", "normal"), [("abcd-efgh", "ABCDEFGH"), ("0OIL 1234", "00111234")])
def test_codes_are_normalised(raw: str, normal: str) -> None:
    assert normalize_code(raw) == normal


@pytest.mark.parametrize("raw", ["short", "ABCDEFGHJ", "ABCD-EFGU"])
def test_malformed_codes_are_refused(raw: str) -> None:
    with pytest.raises(InvalidCode):
        normalize_code(raw)


async def test_ask_ok_end_to_end_in_process(pair: Pair) -> None:
    alice_id_for_bob, bob_id_for_alice = await pair.pair()
    response = await pair.alice_asks(alice_id_for_bob)

    assert response.answer.level == "normal"
    assert response.answer.reason == "active_as_usual"
    assert response.receipt.fields_shared == ["level", "reason", "ts"]
    assert response.receipt.location_shared is False
    assert response.receipt.egress_log_ref.startswith("relay:")
    assert 0 < response.receipt.bytes_sent < 512

    [entry] = await pair.bob.store.questions_log.query()
    assert entry["peer_id"] == bob_id_for_alice
    assert entry["question"] == "ok"
    assert entry["answer_level"] == "normal"
    [row] = await pair.alice.store.peers.query()
    assert row["last_answer"]["level"] == "normal"


async def _set_rule(pair: Pair, bob_id_for_alice: str, **changes: Any) -> None:
    rule = SharingRule.model_validate(await pair.bob.store.sharing_rules.get(bob_id_for_alice))
    await pair.bob.store.sharing_rules.put(
        bob_id_for_alice, rule.model_copy(update=changes).model_dump(mode="json")
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"active": False},
        {"allowed_questions": []},
        {"allowed_levels": ["unknown"]},
    ],
)
async def test_the_owners_sharing_rule_withholds_and_still_logs(
    pair: Pair, changes: dict[str, Any]
) -> None:
    alice_id_for_bob, bob_id_for_alice = await pair.pair()
    await _set_rule(pair, bob_id_for_alice, **changes)

    response = await pair.alice_asks(alice_id_for_bob)

    assert (response.answer.level, response.answer.reason) == ("unknown", "not_enough_data")
    [entry] = await pair.bob.store.questions_log.query()
    assert entry["answer_level"] == "unknown"


async def test_home_is_unknown_in_v1(pair: Pair) -> None:
    alice_id_for_bob, bob_id_for_alice = await pair.pair()
    await _set_rule(pair, bob_id_for_alice, allowed_questions=["ok", "home"])
    response = await pair.alice_asks(alice_id_for_bob, "home")
    assert (response.answer.level, response.answer.reason) == ("unknown", "not_enough_data")


async def test_a_query_from_an_unpaired_key_is_dropped_and_not_answered(pair: Pair) -> None:
    await pair.pair()
    stranger = PrivateKey.generate()
    query = Query(t="query", q="ok", nonce="a" * 32, ts=pair.clock.now)
    sealed = crypto.seal_for_peer(
        stranger, pair.bob.key.public_key, query.model_dump_json().encode()
    )
    await pair.alice.service._relay.post(  # type: ignore[union-attr]
        pair.bob.service.key_id, sealed, key_id(stranger.public_key)
    )
    posts_before = len(pair.posts)
    await pair.bob.service.poll_once()
    assert len(pair.posts) == posts_before
    assert await pair.bob.store.questions_log.query() == []


async def test_a_spoofed_sender_key_id_fails_authentication(pair: Pair) -> None:
    """Claiming Alice's key id without Alice's private key gets nowhere."""
    await pair.pair()
    mallory = PrivateKey.generate()
    query = Query(t="query", q="ok", nonce="b" * 32, ts=pair.clock.now)
    sealed = crypto.seal_for_peer(
        mallory, pair.bob.key.public_key, query.model_dump_json().encode()
    )
    await pair.alice.service._relay.post(  # type: ignore[union-attr]
        pair.bob.service.key_id, sealed, pair.alice.service.key_id
    )
    posts_before = len(pair.posts)
    await pair.bob.service.poll_once()
    assert len(pair.posts) == posts_before
    assert await pair.bob.store.questions_log.query() == []


async def _send_query_as_alice(pair: Pair, nonce: str, ts_offset: timedelta) -> None:
    query = Query(t="query", q="ok", nonce=nonce, ts=pair.clock.now + ts_offset)
    sealed = crypto.seal_for_peer(
        pair.alice.key, PublicKey(bytes(pair.bob.key.public_key)), query.model_dump_json().encode()
    )
    await pair.alice.service._relay.post(  # type: ignore[union-attr]
        pair.bob.service.key_id, sealed, pair.alice.service.key_id
    )


async def test_replayed_and_stale_queries_are_not_answered(pair: Pair) -> None:
    await pair.pair()
    await _send_query_as_alice(pair, "c" * 32, timedelta(0))
    await _send_query_as_alice(pair, "c" * 32, timedelta(0))  # the relay replays it
    await _send_query_as_alice(pair, "d" * 32, -timedelta(minutes=6))  # stale
    posts_before = len(pair.posts)
    await pair.bob.service.poll_once()
    assert len(pair.posts) == posts_before + 1  # one answer, for the first query only
    assert len(await pair.bob.store.questions_log.query()) == 1


async def test_no_answer_is_a_timeout_not_a_made_up_answer(pair: Pair) -> None:
    alice_id_for_bob, _ = await pair.pair()
    pair.alice.service._ask_timeout_s = 0.2
    with pytest.raises(NoAnswer):
        await pair.alice.service.ask(alice_id_for_bob, "ok")  # Bob never polls
    [row] = await pair.alice.store.peers.query()
    assert row["last_answer"] is None


async def test_relay_down_is_relay_unavailable(pair: Pair) -> None:
    alice_id_for_bob, _ = await pair.pair()
    pair.alice.service._relay = type(pair.alice.service._relay)(  # type: ignore[misc]
        "http://127.0.0.1:9"  # nothing listens on the discard port
    )
    with pytest.raises(RelayUnavailable):
        await pair.alice.service.ask(alice_id_for_bob, "ok")


@pytest.mark.parametrize("payload", [b'["x"]', b'[{"id": 1}]', b'{"a": 1}', b"not json", b"[1, 2]"])
async def test_a_malformed_relay_reply_never_kills_the_poller(
    pair: Pair, payload: bytes
) -> None:
    import asyncio

    import httpx2 as httpx
    from warden.reassurance.relay_client import RelayClient

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=payload)

    service = pair.alice.service
    service._relay = RelayClient("http://relay", transport=httpx.MockTransport(handler))
    await service.poll_once()  # no exception escapes
    service._poll_s = 0.01
    task = asyncio.create_task(service.run_forever())
    await asyncio.sleep(0.05)
    assert not task.done()  # still polling
    task.cancel()


async def test_a_peer_flooding_queries_is_capped_per_hour(pair: Pair) -> None:
    from warden.reassurance.service import MAX_QUERIES_PER_PEER_PER_HOUR

    await pair.pair()
    for i in range(MAX_QUERIES_PER_PEER_PER_HOUR + 5):
        await _send_query_as_alice(pair, f"{i:032x}", timedelta(0))
    posts_before = len(pair.posts)
    await pair.bob.service.poll_once()
    assert len(pair.posts) == posts_before + MAX_QUERIES_PER_PEER_PER_HOUR
    assert len(await pair.bob.store.questions_log.query()) == MAX_QUERIES_PER_PEER_PER_HOUR
    # An hour later the peer can ask again.
    pair.clock.now += timedelta(hours=1, seconds=1)
    await _send_query_as_alice(pair, "f" * 32, timedelta(0))
    await pair.bob.service.poll_once()
    # Alice's new query plus Bob's answer to it.
    assert len(pair.posts) == posts_before + MAX_QUERIES_PER_PEER_PER_HOUR + 2


async def test_both_sides_show_the_same_fingerprint(pair: Pair) -> None:
    alice_id_for_bob, bob_id_for_alice = await pair.pair()
    [a_row] = await pair.alice.store.peers.query()
    [b_row] = await pair.bob.store.peers.query()
    a_fp = pair.alice.service.peer_from_row(a_row).fingerprint
    b_fp = pair.bob.service.peer_from_row(b_row).fingerprint
    assert a_fp == b_fp
    assert len(a_fp) == 9 and a_fp[4] == " "
    assert "fingerprint" not in a_row["peer"]  # computed on read, never stored


async def test_a_racing_joiner_shows_a_different_fingerprint(pair: Pair) -> None:
    """Eve joins first with an overheard code: Alice's screen shows fp(Alice, Eve), the real
    Bob's shows fp(Alice, Bob). The humans comparing screens see the mismatch."""
    started = await pair.alice.service.start_pairing("Bob")
    real_bob_key = pair.bob.key
    eve = pair.bob.service
    eve._key = PrivateKey.generate()
    await eve.join_pairing(started.code, "Alice")  # Eve first
    await pair.alice.service.poll_once()
    eve._key = real_bob_key
    await pair.bob.store.peers.delete((await pair.bob.store.peers.query())[0]["peer"]["id"])
    bob_view = await pair.bob.service.join_pairing(started.code, "Alice")  # Bob too late
    await pair.alice.service.poll_once()

    [alice_row] = await pair.alice.store.peers.query()  # paired with Eve only
    assert pair.alice.service.peer_from_row(alice_row).fingerprint != bob_view.fingerprint


async def test_pairing_status_waits_then_reports_the_peer(pair: Pair) -> None:
    started = await pair.alice.service.start_pairing("Bob")
    status = await pair.alice.service.pairing_status(started.pairing_id)
    assert (status.state, status.peer) == ("waiting", None)

    bob_view = await pair.bob.service.join_pairing(started.code, "Alice")
    await pair.alice.service.poll_once()
    status = await pair.alice.service.pairing_status(started.pairing_id)
    assert status.state == "paired" and status.peer is not None
    assert status.peer.display_name == "Bob"
    assert status.peer.fingerprint == bob_view.fingerprint

    # Still shown for a while after the code's 10 minutes, then forgotten.
    pair.clock.now += timedelta(minutes=30)
    assert (await pair.alice.service.pairing_status(started.pairing_id)).state == "paired"
    pair.clock.now += timedelta(hours=1)
    await pair.alice.service.start_pairing("someone else")  # prunes
    assert (await pair.alice.service.pairing_status(started.pairing_id)).state == "expired"


async def test_pairing_status_expires_and_unknown_ids_are_expired(pair: Pair) -> None:
    started = await pair.alice.service.start_pairing("Bob")
    pair.clock.now += timedelta(minutes=11)
    assert (await pair.alice.service.pairing_status(started.pairing_id)).state == "expired"
    assert (await pair.alice.service.pairing_status("pr_nope")).state == "expired"


async def test_unpair_forgets_the_peer_and_their_rule_but_keeps_the_log(pair: Pair) -> None:
    alice_id_for_bob, bob_id_for_alice = await pair.pair()
    await pair.alice_asks(alice_id_for_bob)
    await pair.bob.service.unpair(bob_id_for_alice)
    assert await pair.bob.store.peers.query() == []
    assert await pair.bob.store.sharing_rules.get(bob_id_for_alice) is None
    assert len(await pair.bob.store.questions_log.query()) == 1
    # Alice's next question now comes from an unknown key: dropped, not answered.
    pair.alice.service._ask_timeout_s = 0.2
    with pytest.raises(NoAnswer):
        await pair.alice_asks(alice_id_for_bob)
    with pytest.raises(PeerNotFound):
        await pair.bob.service.unpair(bob_id_for_alice)


async def test_asking_again_within_the_cooldown_is_refused(pair: Pair) -> None:
    from warden.reassurance.service import TooSoon

    alice_id_for_bob, _ = await pair.pair()
    pair.alice.service._ask_cooldown = timedelta(minutes=10)
    await pair.alice_asks(alice_id_for_bob)
    posts = len(pair.posts)
    pair.clock.now += timedelta(minutes=9)
    with pytest.raises(TooSoon):
        await pair.alice_asks(alice_id_for_bob)
    assert len(pair.posts) == posts  # nothing was sent
    pair.clock.now += timedelta(minutes=1, seconds=1)
    assert (await pair.alice_asks(alice_id_for_bob)).answer.level == "normal"


async def test_sharing_waits_for_the_fingerprint(pair: Pair) -> None:
    """A peer (maybe one who raced the real joiner) gets only `unknown` until the owner taps
    "It matches"."""
    started = await pair.alice.service.start_pairing("Bob")
    bob_view = await pair.bob.service.join_pairing(started.code, "Alice")
    await pair.alice.service.poll_once()
    [a_row] = await pair.alice.store.peers.query()
    alice_id_for_bob = a_row["peer"]["id"]
    rule = await pair.bob.store.sharing_rules.get(bob_view.id)
    assert rule is not None and rule["active"] is False

    response = await pair.alice_asks(alice_id_for_bob)
    assert (response.answer.level, response.answer.reason) == ("unknown", "not_enough_data")

    await pair.bob.service.confirm(bob_view.id)
    pair.clock.now += timedelta(minutes=11)
    pair.alice.service._ask_cooldown = timedelta(minutes=10)
    assert (await pair.alice_asks(alice_id_for_bob)).answer.level == "normal"


async def test_each_pairing_has_its_own_fingerprint(pair: Pair) -> None:
    """The joiner's fresh nonce: the same two keys never repeat a number, so a key ground
    offline against yesterday's number is useless today."""
    alice_id_for_bob, bob_id_for_alice = await pair.pair()
    first = pair.bob.service.peer_from_row(
        await pair.bob.store.peers.get(bob_id_for_alice)  # type: ignore[arg-type]
    ).fingerprint
    with pytest.raises(AlreadyPaired):  # a replayed or new code can't desync a pairing
        await pair.bob.service.join_pairing(
            (await pair.alice.service.start_pairing("Bob")).code, "Alice"
        )
    await pair.bob.service.unpair(bob_id_for_alice)  # re-pairing starts with un-pairing
    started = await pair.alice.service.start_pairing("Bob")
    again = await pair.bob.service.join_pairing(started.code, "Alice")
    await pair.alice.service.poll_once()
    status = await pair.alice.service.pairing_status(started.pairing_id)
    assert status.state == "paired" and status.peer is not None
    assert status.peer.fingerprint == again.fingerprint != first
    # Re-pairing asks for the fingerprint check again, on both sides.
    for store, peer_id in ((pair.alice.store, alice_id_for_bob), (pair.bob.store, again.id)):
        rule = await store.sharing_rules.get(peer_id)
        assert rule is not None and rule["active"] is False


async def test_the_cooldown_starts_when_the_question_is_sent(pair: Pair) -> None:
    from warden.reassurance.service import TooSoon

    alice_id_for_bob, _ = await pair.pair()
    alice = pair.alice.service
    alice._ask_cooldown = timedelta(minutes=10)
    alice._ask_timeout_s = 0.1
    with pytest.raises(NoAnswer):  # Bob is asleep
        await alice.ask(alice_id_for_bob, "ok")
    with pytest.raises(TooSoon):  # ...and asking again right away is not allowed
        await alice.ask(alice_id_for_bob, "home")
    [row] = await pair.alice.store.peers.query()
    assert row["last_asked_at"] is not None and row["last_answer"] is None


async def test_two_asks_at_once_send_one_question(pair: Pair) -> None:
    import asyncio

    from warden.reassurance.service import TooSoon

    alice_id_for_bob, _ = await pair.pair()
    alice = pair.alice.service
    alice._ask_cooldown = timedelta(minutes=10)
    alice._ask_timeout_s = 0.1
    results = await asyncio.gather(
        alice.ask(alice_id_for_bob, "ok"),
        alice.ask(alice_id_for_bob, "ok"),
        return_exceptions=True,
    )
    assert sorted(type(r).__name__ for r in results) == ["NoAnswer", "TooSoon"]
    assert any(isinstance(r, TooSoon) for r in results)


async def test_unpairing_during_an_ask_does_not_bring_the_peer_back(pair: Pair) -> None:
    import asyncio

    alice_id_for_bob, _ = await pair.pair()
    task = asyncio.create_task(pair.alice.service.ask(alice_id_for_bob, "ok"))
    await asyncio.sleep(0.02)
    await pair.alice.service.unpair(alice_id_for_bob)
    while not task.done():
        await pair.bob.service.poll_once()
        await asyncio.sleep(0.01)
    assert await pair.alice.store.peers.get(alice_id_for_bob) is None


async def test_confirm_an_unknown_peer_is_an_error(pair: Pair) -> None:
    with pytest.raises(PeerNotFound):
        await pair.alice.service.confirm("p_01K6C0NKNWN0000000000000099")
