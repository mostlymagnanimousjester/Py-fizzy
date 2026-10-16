"""Rails-compatible values for Fizzy's SQLite database.

Fizzy stores primary keys as 16-byte blobs. In Ruby they are UUIDv7 values
printed as 25-character base36 strings (see lib/rails_ext/active_record_uuid_type.rb).
Datetimes are UTC strings with a space separator, and booleans are 0/1.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone

BASE36 = "0123456789abcdefghijklmnopqrstuvwxyz"
BASE36_LENGTH = 25
BASE58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
BASE32 = "0123456789abcdefghijklmnopqrstuv"

JSON_COLUMNS = {
    "particulars",
    "fields",
    "subscribed_actions",
    "metadata",
    "transports",
    "request",
    "response",
}

BOOL_COLUMNS = {
    "all_access",
    "staff",
    "active",
    "backed_up",
    "completed",
    "watching",
}


def uuid7_bytes() -> bytes:
    unix_ms = int(time.time() * 1000) & 0xFFFFFFFFFFFF
    rand_a = int.from_bytes(os.urandom(2), "big") & 0x0FFF
    rand_b = int.from_bytes(os.urandom(8), "big") & 0x3FFFFFFFFFFFFFFF
    value = (unix_ms << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b
    return value.to_bytes(16, "big")


def to_base36(number: int) -> str:
    if number < 0:
        raise ValueError("base36 encoding expects a non-negative integer")
    if number == 0:
        return "0"
    chars = []
    while number:
        number, remainder = divmod(number, 36)
        chars.append(BASE36[remainder])
    return "".join(reversed(chars))


def bytes_to_base36(value: bytes) -> str:
    if len(value) != 16:
        raise ValueError(f"expected 16-byte uuid, got {len(value)}")
    return to_base36(int.from_bytes(value, "big")).rjust(BASE36_LENGTH, "0")


def base36_to_bytes(value: str) -> bytes:
    text = value.strip().lower()
    if len(text) != BASE36_LENGTH or any(ch not in BASE36 for ch in text):
        raise ValueError(f"not a fizzy id: {value!r}")
    return int(text, 36).to_bytes(16, "big")


def new_id() -> str:
    return bytes_to_base36(uuid7_bytes())


def is_fizzy_id(value: object) -> bool:
    if not isinstance(value, str) or len(value) != BASE36_LENGTH:
        return False
    return all(ch in BASE36 for ch in value)


def uuid_bytes(value):
    """16-byte id from a blob, a Fizzy base36 id, or a hex / dashed UUID.

    Ruby's SQLite adapter writes ``blob(16)``. A dump, a ``uuid`` column, or a
    membership id stored as text can hold the same value as hex or base36.
    Comparing those forms in SQL never matches, so the membership fold used to
    drop the only link between a user and their identity.
    """
    if isinstance(value, memoryview):
        value = value.tobytes()
    if isinstance(value, (bytes, bytearray)):
        raw = bytes(value)
        return raw if len(raw) == 16 else None
    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    if is_fizzy_id(text):
        return base36_to_bytes(text)
    hexed = text.replace("-", "")
    if len(hexed) == 32 and all(ch in "0123456789abcdef" for ch in hexed):
        return bytes.fromhex(hexed)
    return None


def decode_uuid(value):
    if value is None:
        return None
    if isinstance(value, memoryview):
        value = value.tobytes()
    if isinstance(value, (bytes, bytearray)):
        raw = bytes(value)
        if len(raw) == 16:
            return bytes_to_base36(raw)
        return raw
    if isinstance(value, str):
        converted = uuid_bytes(value)
        if converted is not None:
            return bytes_to_base36(converted)
        return value
    return value


def token(length: int = 24, alphabet: str = BASE58) -> str:
    size = len(alphabet)
    return "".join(alphabet[b % size] for b in os.urandom(length))


def magic_code(length: int = 6) -> str:
    return token(length, BASE32).upper()


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def dump_dt(value: datetime) -> str:
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value.strftime("%Y-%m-%d %H:%M:%S.%f")


def parse_dt(value):
    if value is None or isinstance(value, datetime):
        return value
    text = str(value).strip().replace("Z", "")
    if text.endswith("+00:00"):
        text = text[: -len("+00:00")]
    text = text.replace("T", " ")
    if "+" in text:
        text = text.split("+", 1)[0]
    for fmt, size in (
        ("%Y-%m-%d %H:%M:%S.%f", 26),
        ("%Y-%m-%d %H:%M:%S", 19),
        ("%Y-%m-%d", 10),
    ):
        try:
            return datetime.strptime(text[:size], fmt)
        except ValueError:
            continue
    return None


def iso(value) -> str | None:
    parsed = parse_dt(value)
    if parsed is None:
        return None
    return parsed.strftime("%Y-%m-%dT%H:%M:%S.") + f"{parsed.microsecond // 1000:03d}Z"


def as_bool(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.lower() in {"1", "true", "t", "yes"}
    return bool(value)
