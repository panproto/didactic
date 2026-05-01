"""Tests for the PEP 727 ``Annotated[T, Doc(...)]`` reading.

PEP 727 is still in Draft as of Python 3.14, so ``typing.Doc`` is not in
stdlib yet. didactic's metadata reader duck-types on a ``.documentation``
attribute so any current or future Doc class works — including
``typing_extensions.Doc`` and user-defined helpers.
"""

from dataclasses import dataclass
from typing import Annotated

from annotated_types import Ge

import didactic.api as dx


@dataclass(frozen=True, slots=True)
class _Doc:
    """A minimal PEP 727-shaped Doc class used for testing."""

    documentation: str


class Documented(dx.Model):
    """Model whose fields carry inline documentation via Annotated metadata."""

    id: Annotated[str, _Doc("Primary identifier (project-unique).")]
    email: Annotated[str, _Doc("Contact email address.")] = ""


def test_doc_metadata_populates_field_description() -> None:
    specs = Documented.__field_specs__
    assert specs["id"].description == "Primary identifier (project-unique)."
    assert specs["email"].description == "Contact email address."


def test_explicit_dx_field_description_overrides_doc() -> None:
    class Override(dx.Model):
        bio: Annotated[str, _Doc("from Doc")] = dx.field(
            default="", description="from field()"
        )

    assert Override.__field_specs__["bio"].description == "from field()"


def test_doc_alongside_constraint() -> None:
    class WithBoth(dx.Model):
        age: Annotated[int, Ge(0), _Doc("A non-negative age in years.")]

    spec = WithBoth.__field_specs__["age"]
    assert spec.description == "A non-negative age in years."
    assert any("x >= 0" in a for a in spec.axioms)
