"""Aggregator module for the didactic API.

`didactic` lets you author class-based, declarative data models the way
[Pydantic][pydantic] does, while the underlying values are
[panproto][panproto] [Theory][panproto.Theory] and
[Schema][panproto.Schema] instances rather than ad hoc Python objects with
bolt-on validation. The selling point is everything you get *for free*
once your data is panproto-native: lenses, dependent optics, theory
colimits, schema migrations as data, vertex-level VCS, and cross-language
semantic export.

[pydantic]: https://docs.pydantic.dev/
[panproto]: https://github.com/panproto/panproto

Notes
-----
The conventional alias for this module is ``dx``::

    import didactic.api as dx


    class User(dx.Model):
        id: str
        email: str

The ``didactic`` namespace itself is a PEP 420 implicit namespace
package; the four distributions (``didactic`` / ``didactic-pydantic`` /
``didactic-settings`` / ``didactic-fastapi``) each contribute a
sub-package (``didactic.api``, ``didactic.pydantic``,
``didactic.settings``, ``didactic.fastapi``) without an
``__init__.py`` at the namespace root. This lets static type checkers
resolve cross-distribution imports without a ``pkgutil`` workaround.
"""

from didactic import codegen
from didactic._self_describing import (
    FingerprintRegistry,
    embed_schema_uri,
    schema_uri,
    validate_with_uri_lookup,
)
from didactic.axioms._axioms import Axiom, axiom
from didactic.fields._computed import computed
from didactic.fields._derived import derived
from didactic.fields._fields import Field, FieldSpec, field
from didactic.fields._refs import Backref, Embed, Ref
from didactic.fields._unions import TaggedUnion
from didactic.fields._validators import (
    ValidationError,
    ValidationErrorEntry,
    validates,
)
from didactic.lenses import _testing as testing
from didactic.lenses._dependent_lens import DependentLens
from didactic.lenses._lens import Iso, Lens, Mapping, lens
from didactic.migrations._diff import classify_change, diff, is_breaking_change
from didactic.migrations._migrations import (
    load_registry,
    migrate,
    register_migration,
    save_registry,
)
from didactic.migrations._synthesis import SynthesisResult, synthesise_migration
from didactic.models._config import DEFAULT_CONFIG, ExtraPolicy, ModelConfig
from didactic.models._model import BaseModel, Model
from didactic.models._root import RootModel, TypeAdapter
from didactic.types import _types_lib as types
from didactic.vcs._backref import ModelPool, resolve_backrefs
from didactic.vcs._repo import Repository

__version__ = "0.4.3"

#: Conventional namespace for lens utilities (`dx.lens.identity(...)`,
#: `dx.lens.Lens`, etc.). The ``lens`` name doubles as a decorator
#: (``@dx.lens(A, B)``) and as a module-style namespace. The attributes
#: are bound by ``_LensNamespace.__init__`` in :mod:`didactic.lenses._lens`.

__all__ = [
    "DEFAULT_CONFIG",
    "Axiom",
    "Backref",
    "BaseModel",
    "DependentLens",
    "Embed",
    "ExtraPolicy",
    "Field",
    "FieldSpec",
    "FingerprintRegistry",
    "Iso",
    "Lens",
    "Mapping",
    "Model",
    "ModelConfig",
    "ModelPool",
    "Ref",
    "Repository",
    "RootModel",
    "SynthesisResult",
    "TaggedUnion",
    "TypeAdapter",
    "ValidationError",
    "ValidationErrorEntry",
    "__version__",
    "axiom",
    "classify_change",
    "codegen",
    "computed",
    "derived",
    "diff",
    "embed_schema_uri",
    "field",
    "is_breaking_change",
    "lens",
    "load_registry",
    "migrate",
    "register_migration",
    "resolve_backrefs",
    "save_registry",
    "schema_uri",
    "synthesise_migration",
    "testing",
    "types",
    "validate_with_uri_lookup",
    "validates",
]
