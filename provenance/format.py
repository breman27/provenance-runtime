"""Version 0.1's restricted JSON domain and UTC timestamp encoding."""
import json
from datetime import datetime, timezone

from .errors import fail


def _domain(value):
    if value is None or type(value) is bool:
        return
    if type(value) is int:
        if abs(value) > 2**53 - 1:
            fail("FORMAT", "integer is outside the interoperable range")
    elif type(value) is str:
        if any(0xD800 <= ord(c) <= 0xDFFF for c in value):
            fail("FORMAT", "string contains an unpaired surrogate")
    elif type(value) is list:
        for item in value:
            _domain(item)
    elif type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                fail("FORMAT", "object keys must be strings")
            _domain(key)
            _domain(item)
    else:
        fail("FORMAT", f"unsupported JSON value: {type(value).__name__}")


def canonical_json(value: object) -> bytes:
    try:
        _domain(value)
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False).encode("utf-8")
    except RecursionError:
        fail("FORMAT", "cyclic or excessively nested JSON value")


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            fail("FORMAT", f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _unsupported_number(value):
    fail("FORMAT", f"unsupported JSON number: {value}")


def parse_json(data: bytes) -> object:
    if not isinstance(data, bytes) or data.startswith(b"\xef\xbb\xbf"):
        fail("FORMAT", "JSON must be UTF-8 bytes without a BOM")
    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=_pairs,
                           parse_float=_unsupported_number, parse_constant=_unsupported_number)
        _domain(value)
        return value
    except (UnicodeError, json.JSONDecodeError, RecursionError, ValueError) as error:
        from .errors import ProvenanceError
        if isinstance(error, ProvenanceError):
            raise
        fail("FORMAT", f"invalid JSON: {error}")


def utc_timestamp(value: datetime | str) -> str:
    try:
        instant = datetime.fromisoformat(value) if isinstance(value, str) else value
        if not isinstance(instant, datetime) or instant.tzinfo is None or instant.utcoffset() is None:
            fail("FORMAT", "timestamp must identify an instant with a timezone")
        instant = instant.astimezone(timezone.utc)
        return (f"{instant.year:04d}-{instant.month:02d}-{instant.day:02d}T"
                f"{instant.hour:02d}:{instant.minute:02d}:{instant.second:02d}."
                f"{instant.microsecond:06d}Z")
    except (ValueError, OverflowError) as error:
        from .errors import ProvenanceError
        if isinstance(error, ProvenanceError):
            raise
        fail("FORMAT", f"invalid timestamp: {error}")
