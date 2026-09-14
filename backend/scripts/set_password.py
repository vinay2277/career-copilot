"""Set or reset an account's password from the command line.

Needed in two situations:

  * After the multi-tenancy migration, which adopts a pre-existing profile onto
    an account with no usable password — there was none to migrate, and
    inventing one would be worse than requiring this step.
  * Whenever someone is locked out and self-service reset isn't wired up.

    python scripts/set_password.py vinay@example.com
    python scripts/set_password.py vinay@example.com --role admin
    python scripts/set_password.py --list

The password is read from a prompt, not an argument, so it does not end up in
shell history or a process listing.
"""

from __future__ import annotations

import argparse
import getpass
import sys

from sqlalchemy import select

from app.core.passwords import PasswordError, hash_password, normalize_email
from app.db.session import SessionLocal
from app.models import Account, Role


def list_accounts() -> int:
    with SessionLocal() as db:
        accounts = db.execute(select(Account).order_by(Account.id)).scalars().all()

    if not accounts:
        print("No accounts yet.")
        return 0

    print(f"{'id':>4}  {'role':<8} {'password':<10} email")
    for a in accounts:
        # "!" is the unusable marker the migration writes.
        state = "unset" if a.password_hash == "!" else "set"
        suspended = "" if a.is_active else "  (suspended)"
        print(f"{a.id:>4}  {a.role.value:<8} {state:<10} {a.email}{suspended}")
    return 0


def set_password(email: str, role: str | None) -> int:
    normalized = normalize_email(email)

    with SessionLocal() as db:
        account = db.execute(
            select(Account).where(Account.email == normalized)
        ).scalar_one_or_none()

        if account is None:
            print(f"No account with email {normalized!r}.", file=sys.stderr)
            print("Run with --list to see what exists.", file=sys.stderr)
            return 1

        password = getpass.getpass(f"New password for {normalized}: ")
        confirm = getpass.getpass("Confirm: ")

        if password != confirm:
            print("Passwords did not match.", file=sys.stderr)
            return 1

        try:
            account.password_hash = hash_password(password)
        except PasswordError as e:
            print(str(e), file=sys.stderr)
            return 1

        if role is not None:
            try:
                account.role = Role(role)
            except ValueError:
                print(
                    f"Unknown role {role!r}. "
                    f"Choose from: {', '.join(r.value for r in Role)}",
                    file=sys.stderr,
                )
                return 1

        db.commit()
        print(f"Password set for {normalized} (role: {account.role.value}).")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("email", nargs="?", help="Account to update.")
    parser.add_argument(
        "--role",
        help="Also change the role (student, hr, admin).",
    )
    parser.add_argument(
        "--list", action="store_true", help="List accounts and exit."
    )
    args = parser.parse_args()

    if args.list:
        return list_accounts()
    if not args.email:
        parser.error("an email is required unless --list is given")

    return set_password(args.email, args.role)


if __name__ == "__main__":
    raise SystemExit(main())
