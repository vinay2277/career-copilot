"""Every third-party import must be declared in requirements.txt.

Written after a deploy failed with `ModuleNotFoundError: No module named
'argon2'`. The package had been pip-installed into the development virtualenv
by hand and never added to requirements.txt, so every local check passed and
the container — which installs from that file alone — could not start.

A local environment accumulates packages; a built image does not. This test is
the difference between finding that out here and finding it out in a deploy
log.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
APP = BACKEND / "app"
REQUIREMENTS = BACKEND / "requirements.txt"

#: Import name -> distribution name, where they differ.
IMPORT_TO_PACKAGE = {
    "PIL": "pillow",
    "argon2": "argon2-cffi",
    "pydantic_settings": "pydantic-settings",
    "dotenv": "python-dotenv",
    "multipart": "python-multipart",
    "yaml": "pyyaml",
}

#: Imports that come from a declared package's own dependencies. Listed
#: explicitly rather than allowed by default, so relying on a new transitive
#: package is a deliberate decision someone has to write down here.
TRANSITIVE = {
    "starlette": "arrives with fastapi",
    "httpx2": "arrives with anthropic",
    "alembic": "declared, but also imported at runtime by main.py",
}


def declared_packages() -> set[str]:
    """Distribution names from requirements.txt, normalized."""
    names: set[str] = set()
    # utf-8-sig, not utf-8: a Windows editor can leave a byte-order mark, and
    # a dependency check that dies on an invisible character is worse than
    # useless — it fails loudly for a reason unrelated to dependencies.
    for raw in REQUIREMENTS.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # Strip version pins, extras and trailing comments.
        name = line.split("#")[0].split("==")[0].split(">=")[0].split("[")[0]
        names.add(name.strip().lower().replace("_", "-"))
    return names


def imported_modules() -> dict[str, set[Path]]:
    """Top-level module name -> the files importing it, across app/."""
    found: dict[str, set[Path]] = {}

    for path in APP.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                # `from . import x` has no module; relative imports are ours.
                if node.level or node.module is None:
                    continue
                names = [node.module.split(".")[0]]
            else:
                continue

            for name in names:
                found.setdefault(name, set()).add(path.relative_to(BACKEND))

    return found


def third_party(modules: dict[str, set[Path]]) -> dict[str, set[Path]]:
    """Drop the standard library and our own package."""
    return {
        name: files
        for name, files in modules.items()
        if name != "app"
        and name != "__future__"
        and name not in sys.stdlib_module_names
    }


def test_requirements_file_is_readable():
    assert REQUIREMENTS.is_file()
    assert declared_packages(), "requirements.txt declared nothing"


def test_every_import_is_declared():
    """The check that would have caught the failed deploy."""
    declared = declared_packages()
    missing: list[str] = []

    for module, files in sorted(third_party(imported_modules()).items()):
        if module in TRANSITIVE:
            continue
        package = IMPORT_TO_PACKAGE.get(module, module).lower().replace("_", "-")
        if package not in declared:
            where = ", ".join(str(f) for f in sorted(files)[:3])
            missing.append(f"{module!r} (package {package!r}) imported by {where}")

    assert not missing, (
        "Imported but not in requirements.txt — the container installs from "
        "that file alone and will fail to start:\n  " + "\n  ".join(missing)
    )


@pytest.mark.parametrize("module", sorted(TRANSITIVE))
def test_transitive_imports_still_resolve(module):
    """A transitive dependency can disappear when its parent is upgraded.

    These are relied on without being declared, so nothing but this test would
    notice them going away until the app failed to import.
    """
    __import__(module)


def test_argon2_specifically_is_declared():
    """The one that actually broke a deploy.

    Kept as its own named test so the regression is legible in the run output
    rather than buried in a general assertion.
    """
    assert "argon2-cffi" in declared_packages()


def test_email_validator_is_declared():
    """Pydantic's EmailStr needs it and does not pull it in.

    It appears in no import statement, so the general check above cannot catch
    it — the failure is at class-definition time in the auth schemas.
    """
    assert "email-validator" in declared_packages()
