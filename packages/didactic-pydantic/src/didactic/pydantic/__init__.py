"""didactic-pydantic: bidirectional adapter for Pydantic interop.

Two complementary adapters:

[from_pydantic][didactic.pydantic.from_pydantic]
    ``BaseModel -> dx.Model``. For incremental adoption: convert one
    Pydantic model at a time without rewriting field declarations by
    hand.
[to_pydantic][didactic.pydantic.to_pydantic]
    ``dx.Model -> BaseModel``. For interop with FastAPI, OpenAPI
    generators, and any Pydantic-shaped consumer that wants the
    didactic model exposed as a ``BaseModel``.

Notes
-----
The adapter is **structural**: it inspects a Pydantic v2
``BaseModel``'s ``model_fields`` and constructs an equivalent
[didactic.api.Model][didactic.api.Model] subclass. Per-field metadata that
maps cleanly (default, default_factory, alias, description, examples,
deprecated) is preserved. ``Annotated[...]`` constraint metadata
flows through unchanged, so ``annotated-types`` primitives like
``Ge``/``Le`` continue to produce axioms on the didactic side.

Custom Pydantic validators (``@field_validator``, ``@model_validator``)
are **not** translated; they live on the Pydantic side. If you need
similar behaviour on the didactic side, port them to
[didactic.api.validates][didactic.api.validates] manually.

Examples
--------
>>> from pydantic import BaseModel, Field
>>> from didactic.pydantic import from_pydantic
>>>
>>> class PydUser(BaseModel):
...     id: str
...     email: str = Field(description="primary contact")
...     display_name: str = ""
>>>
>>> User = from_pydantic(PydUser)  # User is a dx.Model subclass
>>> u = User(id="u1", email="a@b.c")
>>> u.email
'a@b.c'
"""

from didactic.pydantic._adapter import from_pydantic
from didactic.pydantic._reverse import to_pydantic

__version__ = "0.3.1"

__all__ = [
    "__version__",
    "from_pydantic",
    "to_pydantic",
]
