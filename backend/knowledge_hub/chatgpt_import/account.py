"""Explicit ChatGPT account identity.

The alias is supplied by the caller. It is never inferred from a ZIP name,
a conversations file, or an email address.
"""

from __future__ import annotations

from dataclasses import dataclass
import re


_ALIAS = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class AccountError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class AccountIdentity:
    alias: str

    def to_dict(self) -> dict[str, str]:
        return {"alias": self.alias}


def resolve_account(alias: str) -> AccountIdentity:
    if not isinstance(alias, str) or alias.strip() == "":
        raise AccountError("ACCOUNT_ALIAS_REQUIRED")
    value = alias.strip()
    if "@" in value or not _ALIAS.fullmatch(value):
        raise AccountError("INVALID_ACCOUNT_ALIAS")
    return AccountIdentity(alias=value)
