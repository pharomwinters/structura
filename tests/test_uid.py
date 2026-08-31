"""Document identity."""

import re

import pytest

from structura.core.uid import UID_LENGTH, is_uid, new_uid, uid_timestamp_ms

CROCKFORD = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")


def test_a_new_uid_is_a_well_formed_ulid():
    uid = new_uid()
    assert len(uid) == UID_LENGTH
    assert CROCKFORD.match(uid)
    assert is_uid(uid)


def test_uids_are_unique():
    assert len({new_uid() for _ in range(2000)}) == 2000


def test_uids_sort_by_creation_time():
    """The property that earns a ULID over a UUID4: `ORDER BY uid` is a usable
    creation-order tiebreak in the index without a second column."""
    earlier = new_uid(timestamp_ms=1_700_000_000_000)
    later = new_uid(timestamp_ms=1_700_000_001_000)
    assert earlier < later


def test_timestamp_round_trips():
    assert uid_timestamp_ms(new_uid(timestamp_ms=1_756_000_000_000)) == 1_756_000_000_000


@pytest.mark.parametrize(
    "value",
    [
        "",
        None,
        123,
        "01J8",
        "01J8" + "X" * 30,
        "01arz3ndektsv4rrffq69g5fav",  # lowercase
        "01ARZ3NDEKTSV4RRFFQ69G5FAI",  # I is not in Crockford base32
        "01ARZ3NDEKTSV4RRFFQ69G5FAU",  # nor is U
    ],
)
def test_rejects_things_that_are_not_uids(value):
    assert not is_uid(value)


def test_lowercase_is_rejected_rather_than_normalised():
    """Accepting both cases would mean two spellings of one identity, and every
    index comparison would have to normalise."""
    uid = new_uid()
    assert is_uid(uid)
    assert not is_uid(uid.lower())
