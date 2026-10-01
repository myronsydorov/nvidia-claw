"""This Warden's X25519 identity key. Kept in its own 0600 file, never in the DB or logs."""

import os
from hashlib import blake2b
from pathlib import Path

from nacl.public import PrivateKey, PublicKey


def load_or_create(path: Path) -> PrivateKey:
    if path.exists():
        if path.stat().st_mode & 0o077:
            raise PermissionError(f"{path} is readable by others; run: chmod 600 {path}")
        raw = path.read_bytes()
        if len(raw) != 32:
            raise ValueError(f"{path} is not a 32-byte X25519 private key")
        return PrivateKey(raw)
    key = PrivateKey.generate()
    # O_EXCL + 0600: never clobber an existing key, never world-readable even briefly.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(bytes(key))
    return key


def key_path_from_env() -> Path:
    return Path(os.environ.get("WARDEN_KEY_PATH", "warden.key"))


def key_id(public_key: PublicKey | bytes) -> str:
    """The relay mailbox address for a public key: BLAKE2b-128, hex (32 chars)."""
    return blake2b(bytes(public_key), digest_size=16, person=b"custody-keyid").hexdigest()
