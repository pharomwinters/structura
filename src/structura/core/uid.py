"""Document identity.

Decision 4 in the design: every document carries a UID that never changes,
and links resolve to UIDs rather than to titles or paths. That is what lets
`rename` be a file operation instead of a workspace-wide link rewrite.

The format is a ULID -- 48 bits of millisecond timestamp followed by 80 bits
of randomness, rendered in Crockford base32. Three properties earn it over a
UUID4:

- It sorts lexicographically by creation time, so `ORDER BY uid` is a
  usable tiebreak in the index without a second column.
- It is 26 characters of unambiguous uppercase, so it survives being pasted
  into a `.ics` UID property, a filename, and a YAML scalar unquoted.
- It has no dependency. iCalendar and vCard both mandate a UID field, and
  Structura must be able to mint one in every store without importing a
  different library per store.

Crockford base32 deliberately omits I, L, O and U, so a UID read aloud or
retyped cannot become a different valid UID by way of a confusable character.
"""

from __future__ import annotations

import os
import time

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_DECODE = {c: i for i, c in enumerate(_ALPHABET)}

UID_LENGTH = 26
_TIME_LENGTH = 10
_MAX_TIME = (1 << 48) - 1


def _encode(value: int, length: int) -> str:
    chars = []
    for _ in range(length):
        chars.append(_ALPHABET[value & 0x1F])
        value >>= 5
    return "".join(reversed(chars))


def new_uid(timestamp_ms: int | None = None) -> str:
    """Mint a new ULID. `timestamp_ms` is for tests; production passes None."""
    ms = int(time.time() * 1000) if timestamp_ms is None else timestamp_ms
    if not 0 <= ms <= _MAX_TIME:
        raise ValueError(f"timestamp out of ULID range: {ms}")
    randomness = int.from_bytes(os.urandom(10), "big")
    return _encode(ms, _TIME_LENGTH) + _encode(randomness, 16)


def is_uid(value: object) -> bool:
    """True for a well-formed ULID string.

    Deliberately strict about case: a lowercase ULID is not accepted, because
    accepting it would mean two spellings of one identity and the index would
    have to normalise on every comparison.
    """
    if not isinstance(value, str) or len(value) != UID_LENGTH:
        return False
    return all(c in _DECODE for c in value)


def uid_timestamp_ms(uid: str) -> int:
    """The creation time encoded in a ULID, in milliseconds since the epoch."""
    if not is_uid(uid):
        raise ValueError(f"not a ULID: {uid!r}")
    value = 0
    for char in uid[:_TIME_LENGTH]:
        value = (value << 5) | _DECODE[char]
    return value
