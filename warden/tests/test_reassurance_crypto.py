import os
import stat
from pathlib import Path

import pytest
from nacl.exceptions import CryptoError
from nacl.public import PrivateKey
from warden.reassurance import crypto
from warden.reassurance.keys import key_id, load_or_create


def test_box_round_trip_and_sender_authentication() -> None:
    alice, bob, mallory = PrivateKey.generate(), PrivateKey.generate(), PrivateKey.generate()
    sealed = crypto.seal_for_peer(alice, bob.public_key, b"hello")
    assert crypto.open_from_peer(bob, alice.public_key, sealed) == b"hello"
    with pytest.raises(CryptoError):
        crypto.open_from_peer(bob, mallory.public_key, sealed)  # not from mallory


def test_tampering_is_detected() -> None:
    alice, bob = PrivateKey.generate(), PrivateKey.generate()
    sealed = bytearray(crypto.seal_for_peer(alice, bob.public_key, b"hello"))
    sealed[-1] ^= 1
    with pytest.raises(CryptoError):
        crypto.open_from_peer(bob, alice.public_key, bytes(sealed))


def test_sealed_box_only_opens_for_the_recipient() -> None:
    bob, eve = PrivateKey.generate(), PrivateKey.generate()
    sealed = crypto.seal_anonymous(bob.public_key, b"accept")
    assert crypto.open_anonymous(bob, sealed) == b"accept"
    with pytest.raises(CryptoError):
        crypto.open_anonymous(eve, sealed)


def test_the_real_pairing_kdf_is_deterministic_and_code_bound() -> None:
    mailbox, key = crypto.derive_pairing("ABCDEFGH")
    assert (mailbox, key) == crypto.derive_pairing("ABCDEFGH")
    assert len(mailbox) == 32 and len(key) == 32
    other_mailbox, other_key = crypto.derive_pairing("ABCDEFGJ")
    assert other_mailbox != mailbox and other_key != key
    with pytest.raises(CryptoError):
        crypto.open_offer(other_key, crypto.seal_offer(key, b"offer"))


def test_proof_binds_both_keys() -> None:
    key = os.urandom(32)
    proof = crypto.pairing_proof(key, b"a" * 32, b"b" * 32)
    assert crypto.proof_matches(proof, crypto.pairing_proof(key, b"a" * 32, b"b" * 32))
    assert not crypto.proof_matches(proof, crypto.pairing_proof(key, b"a" * 32, b"c" * 32))
    assert not crypto.proof_matches(
        proof, crypto.pairing_proof(os.urandom(32), b"a" * 32, b"b" * 32)
    )


def test_identity_key_file_is_private_and_stable(tmp_path: Path) -> None:
    path = tmp_path / "warden.key"
    first = load_or_create(path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert bytes(load_or_create(path)) == bytes(first)


def test_a_corrupt_key_file_is_an_error_not_a_new_identity(tmp_path: Path) -> None:
    path = tmp_path / "warden.key"
    path.write_bytes(b"short")
    path.chmod(0o600)
    with pytest.raises(ValueError):
        load_or_create(path)


def test_key_id_is_32_hex_chars() -> None:
    kid = key_id(PrivateKey.generate().public_key)
    assert len(kid) == 32 and all(c in "0123456789abcdef" for c in kid)


def test_a_key_file_readable_by_others_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "warden.key"
    load_or_create(path)
    path.chmod(0o644)
    with pytest.raises(PermissionError):
        load_or_create(path)
