"""Field descriptors, refs, unions, computed, and validators."""

from didactic.fields._computed import computed
from didactic.fields._derived import derived
from didactic.fields._fields import MISSING, Field, FieldSpec, field
from didactic.fields._refs import Backref, Embed, Ref
from didactic.fields._unions import TaggedUnion
from didactic.fields._validators import (
    ValidationError,
    ValidationErrorEntry,
    validates,
)

__all__ = [
    "MISSING",
    "Backref",
    "Embed",
    "Field",
    "FieldSpec",
    "Ref",
    "TaggedUnion",
    "ValidationError",
    "ValidationErrorEntry",
    "computed",
    "derived",
    "field",
    "validates",
]
