import re
import secrets
import time
from typing import Optional, Tuple

class IdError(ValueError):
    """Raised when an identifier or slug is invalid or generation fails."""
    pass

CROCKFORD_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
CROCKFORD_REVERSE = {c: i for i, c in enumerate(CROCKFORD_ALPHABET)}

_VALID_ULID_RE = re.compile(r"^[0-7][0-9A-HJKMNP-TV-Z]{25}$")
_VALID_SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_NON_SLUG_CHARS_RE = re.compile(r"[^a-z0-9]+")
_FILENAME_RE = re.compile(r"(\d{3,})-([a-z0-9]+(?:-[a-z0-9]+)*)\.md")

#: Sequence numbers are display identity only. The stable identity is the
#: ULID in frontmatter ``id``; it is what digests, supersedes references, and
#: the journal bind to. Renumbering after a branch merge is therefore a pure
#: file rename and can never invalidate a content digest.
MAX_NUMBER = 10 ** 6

_last_timestamp_ms = -1
_last_random_int = 0

def _encode_base32(value: int, length: int) -> str:
    """Encode an integer to Crockford base32, padded to length."""
    res = []
    for _ in range(length):
        res.append(CROCKFORD_ALPHABET[value & 0x1F])
        value >>= 5
    return "".join(reversed(res))

def _decode_base32(value: str) -> int:
    """Decode a Crockford base32 string to an integer."""
    res = 0
    for char in value:
        res = (res << 5) | CROCKFORD_REVERSE[char]
    return res

def new_ulid(now_ms: Optional[int] = None) -> str:
    """Generate a new ULID."""
    global _last_timestamp_ms, _last_random_int
    
    if now_ms is None:
        now_ms = int(time.time() * 1000)
    
    if now_ms < 0 or now_ms > 0xFFFFFFFFFFFF:
        raise IdError(f"Timestamp out of 48-bit range: {now_ms}")
        
    if now_ms == _last_timestamp_ms:
        _last_random_int += 1
        if _last_random_int > 0xFFFFFFFFFFFFFFFFFFFF:
            raise IdError("Random component overflow in the same millisecond")
    else:
        _last_timestamp_ms = now_ms
        _last_random_int = int.from_bytes(secrets.token_bytes(10), 'big')
        
    total_int = (now_ms << 80) | _last_random_int
    return _encode_base32(total_int, 26)

def is_valid_ulid(value: str) -> bool:
    """Check if the string is a valid ULID.

    Uses ``fullmatch``: ``re.match`` with a trailing ``$`` also accepts a
    trailing newline, which would let a validated identifier smuggle a newline
    into a path or document.
    """
    if not isinstance(value, str):
        return False
    return bool(_VALID_ULID_RE.fullmatch(value))

def ulid_timestamp_ms(value: str) -> int:
    """Extract the timestamp from a ULID in milliseconds."""
    if not is_valid_ulid(value):
        raise IdError(f"Invalid ULID format: {value}")
    
    total_int = _decode_base32(value)
    timestamp_ms = total_int >> 80
    return timestamp_ms

def slugify(title: str) -> str:
    """Generate a slug from a title."""
    if not isinstance(title, str):
        raise IdError("Title must be a string")
        
    ascii_chars = []
    for char in title:
        if ord(char) < 128:
            ascii_chars.append(char)
            
    ascii_title = "".join(ascii_chars).lower()
    slug = _NON_SLUG_CHARS_RE.sub('-', ascii_title)
    slug = slug.strip('-')
    
    if len(slug) > 80:
        slug = slug[:80].rstrip('-')
        
    if not slug:
        raise IdError("Resulting slug is empty")
        
    return slug

def is_valid_slug(value: str) -> bool:
    """Check if the string is a valid slug.

    ``fullmatch`` for the same reason as :func:`is_valid_ulid`.
    """
    if not isinstance(value, str):
        return False
    if len(value) > 80:
        return False
    return bool(_VALID_SLUG_RE.fullmatch(value))

def format_number(number: int) -> str:
    """Zero-pad a sequence number to at least three digits (001, 002, 1000)."""
    if not isinstance(number, int) or isinstance(number, bool):
        raise IdError("Sequence number must be an int")
    if number < 1 or number > MAX_NUMBER:
        raise IdError(f"Sequence number out of range: {number}")
    return "%03d" % number

def adr_filename(number: int, slug: str) -> str:
    """Generate the ADR filename: ``NNN-<slug>.md``."""
    prefix = format_number(number)
    if not is_valid_slug(slug):
        raise IdError("Invalid slug")
    return f"{prefix}-{slug}.md"

def parse_filename(name: str) -> Optional[Tuple[int, str]]:
    """Parse ``NNN-<slug>.md`` into ``(number, slug)``; ``None`` if no match.

    ``fullmatch`` for the same reason as :func:`is_valid_ulid`: a trailing
    newline must not turn an unrelated string into a record filename.
    """
    if not isinstance(name, str):
        return None
    match = _FILENAME_RE.fullmatch(name)
    if match is None:
        return None
    number = int(match.group(1))
    if number < 1 or number > MAX_NUMBER:
        return None
    return number, match.group(2)
