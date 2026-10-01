"""Encryption for everything that crosses the relay (ADR-0004).

- Between paired peers: `crypto_box` (X25519 + XSalsa20-Poly1305), which authenticates the
  sender. The answering Warden must know *who* asks to apply its owner's sharing rules, and an
  anonymous sealed box can't tell it (ADR-0004 amendment).
- Pairing accept: a sealed box to the offerer's key (the offerer doesn't know the joiner yet).
- Pairing offer: a SecretBox under a key derived from the one-time code with Argon2id, so a
  curious relay pays an Argon2id evaluation per guess of the 40-bit code.
"""

import hmac
from hashlib import blake2b

from nacl.exceptions import CryptoError
from nacl.public import Box, PrivateKey, PublicKey, SealedBox
from nacl.pwhash import argon2id
from nacl.secret import SecretBox

PAIRING_SALT = b"custody-pair-v1!"  # 16 bytes, fixed: both sides must derive the same material

__all__ = ["CryptoError"]


def seal_for_peer(my_key: PrivateKey, peer: PublicKey, plaintext: bytes) -> bytes:
    return bytes(Box(my_key, peer).encrypt(plaintext))


def open_from_peer(my_key: PrivateKey, peer: PublicKey, ciphertext: bytes) -> bytes:
    """Raises CryptoError unless `peer` really sent it to us, unmodified."""
    return Box(my_key, peer).decrypt(ciphertext)


def seal_anonymous(recipient: PublicKey, plaintext: bytes) -> bytes:
    return bytes(SealedBox(recipient).encrypt(plaintext))


def open_anonymous(my_key: PrivateKey, ciphertext: bytes) -> bytes:
    return SealedBox(my_key).decrypt(ciphertext)


def derive_pairing(code: str) -> tuple[str, bytes]:
    """One-time code → (relay mailbox id, SecretBox key). Slow on purpose (Argon2id)."""
    material = argon2id.kdf(
        16 + SecretBox.KEY_SIZE,
        code.encode("ascii"),
        PAIRING_SALT,
        opslimit=argon2id.OPSLIMIT_INTERACTIVE,
        memlimit=argon2id.MEMLIMIT_INTERACTIVE,
    )
    return material[:16].hex(), material[16:]


def seal_offer(key: bytes, plaintext: bytes) -> bytes:
    return bytes(SecretBox(key).encrypt(plaintext))


def open_offer(key: bytes, ciphertext: bytes) -> bytes:
    return SecretBox(key).decrypt(ciphertext)


def pairing_proof(key: bytes, offerer: bytes, joiner: bytes) -> str:
    """Proves the joiner knew the code and binds both public keys to this pairing."""
    return blake2b(offerer + joiner, key=key, digest_size=32, person=b"custody-pairprf").hexdigest()


def proof_matches(expected: str, given: str) -> bool:
    return hmac.compare_digest(expected.encode(), given.encode())
