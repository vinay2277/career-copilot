"""Password hashing.

Argon2id, which is the OWASP first recommendation and what `argon2-cffi`
defaults to. The parameters are the library's defaults deliberately — they
track current guidance, and hand-tuned values go stale silently.

Rehashing is handled here too: when the library's defaults tighten, a correct
password is transparently re-hashed at the next sign-in rather than leaving
old accounts on weaker parameters forever.
"""

from __future__ import annotations

import logging
import unicodedata

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

logger = logging.getLogger(__name__)

_hasher = PasswordHasher()

#: Long enough to resist guessing, short enough that people will comply.
MIN_PASSWORD_LENGTH = 10

#: Argon2 hashes the full input, but an unbounded password is a cheap denial of
#: service — the work factor is per-hash, and a megabyte of input is a megabyte
#: to hash.
MAX_PASSWORD_LENGTH = 256


class PasswordError(ValueError):
    """A password that cannot be accepted. The message is shown to the user."""


def normalize_password(password: str) -> str:
    """Normalize Unicode so the same typed password always hashes the same.

    An accented character can be encoded two ways that look identical; without
    this, a password typed on one keyboard can fail to match itself typed on
    another.
    """
    return unicodedata.normalize("NFKC", password)


def validate_password(password: str) -> None:
    """Raise `PasswordError` if the password is unusable.

    Length only. Composition rules — a digit, a symbol, mixed case — push people
    toward `Password1!` and are no longer recommended by NIST; length is what
    actually helps.
    """
    if len(password) < MIN_PASSWORD_LENGTH:
        raise PasswordError(
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
        )
    if len(password) > MAX_PASSWORD_LENGTH:
        raise PasswordError(
            f"Password must be at most {MAX_PASSWORD_LENGTH} characters."
        )


def hash_password(password: str) -> str:
    """Validate and hash. Raises `PasswordError` on an unusable password."""
    password = normalize_password(password)
    validate_password(password)
    return _hasher.hash(password)


def verify_password(password: str, stored_hash: str) -> bool:
    """Check a password against a stored hash.

    Returns False rather than raising on a mismatch, so a wrong password and a
    corrupt hash are handled the same way by the caller — neither should reveal
    anything different to whoever is trying.
    """
    try:
        _hasher.verify(stored_hash, normalize_password(password))
    except VerifyMismatchError:
        return False
    except InvalidHashError:
        logger.warning("Stored password hash is unreadable; treating as a failure.")
        return False
    return True


def needs_rehash(stored_hash: str) -> bool:
    """Whether the hash uses parameters weaker than today's defaults."""
    try:
        return _hasher.check_needs_rehash(stored_hash)
    except InvalidHashError:
        return True


def normalize_email(email: str) -> str:
    """Lowercase and strip.

    Addresses are matched on this form and stored in it, so `Vinay@X.com` and
    `vinay@x.com` cannot become two accounts. The local part is technically
    case-sensitive in the RFC; no mail provider anyone uses honours that, and
    duplicate accounts are the worse failure.
    """
    return email.strip().lower()
