"""Pin the dataclass-transform contract on ``ModelMeta``.

didactic Models are constructed by keyword only (the runtime
``Model.__init__`` rejects positional args). The metaclass must
therefore advertise ``kw_only_default=True`` to type checkers via
PEP 681's ``@dataclass_transform``. Without this, every subclass
that adds a non-default field after a parent's default-bearing field
trips ``reportGeneralTypeIssues`` -- a routine shape (Base with
auto-id / timestamps, domain-specific Subclass) under strict pyright.

This test pins the metaclass declaration so a later refactor can't
silently regress the kw-only contract.
"""

from __future__ import annotations

from typing import cast
from uuid import UUID, uuid4

import didactic.api as dx
from didactic.models._meta import ModelMeta


# -- the dataclass_transform metadata is set at module-decoration time
# and stored on the class as ``__dataclass_transform__``.


def test_modelmeta_dataclass_transform_kw_only_default_is_true() -> None:
    transform = cast("dict[str, object]", ModelMeta.__dataclass_transform__)  # type: ignore[attr-defined]
    assert transform.get("kw_only_default") is True


def test_modelmeta_dataclass_transform_frozen_default_is_true() -> None:
    """Sanity check: the frozen contract still travels alongside kw-only."""
    transform = cast("dict[str, object]", ModelMeta.__dataclass_transform__)  # type: ignore[attr-defined]
    assert transform.get("frozen_default") is True


# -- runtime regression: the issue's exact repro shape.


class _Base(dx.Model):
    id: UUID = dx.field(default_factory=uuid4)


class _Sub(_Base):
    name: str


def test_subclass_with_required_field_after_parent_default_constructs() -> None:
    """The shape pyright flagged at static-check time still works at runtime.

    The fix is purely a type-checker contract change; this test makes
    sure the runtime behaviour the contract describes hasn't drifted.
    """
    s = _Sub(name="x")
    assert s.name == "x"
    assert isinstance(s.id, UUID)


def test_subclass_passes_id_explicitly_too() -> None:
    """The default still applies when not overridden, and is overridable."""
    fixed = UUID("00000000-0000-0000-0000-000000000001")
    s = _Sub(id=fixed, name="y")
    assert s.id == fixed
