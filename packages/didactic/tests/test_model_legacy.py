"""Verify Model works with ``from __future__ import annotations``.

The metaclass must transparently handle modules where annotations are
stringified (the legacy PEP 563 path) — many codebases still use that
import for forward-compat reasons. This module deliberately enables it
and re-runs a tiny smoke test.
"""

from __future__ import annotations

from typing import Annotated

from annotated_types import Ge

import didactic.api as dx


class LegacyUser(dx.Model):
    """A user model authored under the legacy stringified-annotation path."""

    id: str
    age: Annotated[int, Ge(0)]
    nickname: str | None = None


def test_legacy_field_specs_resolved() -> None:
    specs = LegacyUser.__field_specs__
    assert set(specs) == {"id", "age", "nickname"}
    assert specs["id"].translation.sort == "String"
    assert specs["age"].translation.sort == "Int"
    assert any("x >= 0" in a for a in specs["age"].axioms)
    assert specs["nickname"].translation.is_optional


def test_legacy_construct_and_access() -> None:
    u = LegacyUser(id="u1", age=33)
    assert u.id == "u1"
    assert u.age == 33
    assert u.nickname is None
    u2 = u.with_(nickname="primary")
    assert u2.nickname == "primary"
