"""Skill-name canonicalization.

Alignment scoring must be reproducible: the same profile and the same job must
produce the same number today and next month. That rules out fuzzy string
similarity, whose thresholds drift. Instead every skill name is normalized and
then resolved through an explicit alias table.

An unknown spelling resolves to itself, so a missing alias shows up as a
`MISSING` requirement the user can correct — never as a silently wrong score.
"""

from __future__ import annotations

import re
import unicodedata

#: Built-in aliases. The `skill_aliases` table extends this at runtime; entries
#: there win, so a deployment can correct a mapping without a code change.
BUILTIN_ALIASES: dict[str, str] = {
    "postgres": "postgresql",
    "psql": "postgresql",
    "js": "javascript",
    "ts": "typescript",
    "py": "python",
    "golang": "go",
    "node": "node.js",
    "nodejs": "node.js",
    "react.js": "react",
    "reactjs": "react",
    "k8s": "kubernetes",
    "gcp": "google cloud platform",
    "aws lambda": "aws",
    "amazon web services": "aws",
    "ml": "machine learning",
    "dl": "deep learning",
    "nlp": "natural language processing",
    "ci/cd": "ci-cd",
    "cicd": "ci-cd",
    "rest api": "rest",
    "restful": "rest",
    "tf": "terraform",
    "sklearn": "scikit-learn",
    "tensorflow2": "tensorflow",
}

_PUNCT = re.compile(r"[^a-z0-9+#./\- ]+")
_SPACE = re.compile(r"\s+")


def normalize(name: str) -> str:
    """Lowercase, strip accents and stray punctuation, collapse whitespace.

    Kept deliberately conservative: `+`, `#`, `.`, `/` and `-` survive, because
    they carry meaning in skill names (c++, c#, node.js, ci/cd, scikit-learn).
    """
    decomposed = unicodedata.normalize("NFKD", name)
    ascii_only = decomposed.encode("ascii", "ignore").decode("ascii")
    lowered = ascii_only.lower().strip()
    cleaned = _PUNCT.sub(" ", lowered)
    return _SPACE.sub(" ", cleaned).strip()


def canonicalize(name: str, aliases: dict[str, str] | None = None) -> str:
    """Normalize `name`, then resolve it through the alias map.

    Resolution is single-hop on purpose. Chained aliases (a -> b -> c) would let
    a bad row create a cycle, and a cycle in a scoring path is worse than an
    alias that needs writing twice.
    """
    normalized = normalize(name)
    if not normalized:
        return ""
    table = {**BUILTIN_ALIASES, **(aliases or {})}
    return table.get(normalized, normalized)


def canonical_set(names: list[str], aliases: dict[str, str] | None = None) -> set[str]:
    """Canonicalize a list, dropping blanks."""
    return {c for c in (canonicalize(n, aliases) for n in names) if c}
