# didactic

[![PyPI](https://img.shields.io/pypi/v/didactic?style=flat-square&color=blue)](https://pypi.org/project/didactic/)
[![Python](https://img.shields.io/pypi/pyversions/didactic?style=flat-square)](https://pypi.org/project/didactic/)
[![License](https://img.shields.io/pypi/l/didactic?style=flat-square&color=green)](https://github.com/panproto/didactic/blob/main/LICENSE)
[![CI](https://img.shields.io/github/actions/workflow/status/panproto/didactic/ci.yml?branch=main&style=flat-square&label=ci)](https://github.com/panproto/didactic/actions/workflows/ci.yml)
[![Docs](https://img.shields.io/badge/docs-panproto.dev-blue?style=flat-square)](https://panproto.dev/didactic/)

The `didactic` distribution provides immutable, validated Python models backed
by [Panproto](https://github.com/panproto/panproto). Each `dx.Model` compiles to
a Panproto theory, so the same declaration can drive validation, schema
migration, compatibility checks, code generation, and schema version control.

## Install

Didactic requires Python 3.14 or later and `panproto>=0.74.2`.

```sh
pip install didactic
```

## Define a model

```python
import didactic.api as dx


class User(dx.Model):
    """A user record."""

    id: str
    email: str
    display_name: str = ""


user = User(id="u1", email="alice@example.com")
updated = user.with_(display_name="Alice")

assert updated.display_name == "Alice"
assert User.__theory__.name == "User"
```

Model construction checks Python types, field constraints, class axioms, and
custom validators. Instances serialize to Python objects or JSON and update
through `with_()`, which returns a new validated instance.

## Describe indexed data

Use `dx.Universe` when one field selects the Python type accepted by another:

```python
from typing import Annotated, Literal

import didactic.api as dx


Payload = dx.Universe("Payload", text=str, number=float)


class Record(dx.Model):
    kind: Literal["text", "number"]
    body: Annotated[str | float, Payload.at("kind")]


record = Record(kind="number", body=2.5)
```

The general `dx.GADT` API defines arbitrary indexed families, constructors,
dependent motives, equations, rewrites, and user-defined eliminators. Panproto
checks the declaration when `compile()` is called. Generated JSON Schema and
OpenAPI preserve known cases as conditions, Pydantic adapters retain
cross-field validation, and compatibility checks treat index changes as
breaking.

## Included APIs

The core distribution includes:

- `dx.Model`, fields, validators, computed fields, and class axioms
- references and embedded models for graph-shaped data
- lenses, isomorphisms, and dependent lenses
- migration registration, schema diffing, and migration synthesis
- schema emitters and a filesystem-backed schema repository
- property-based helpers for checking lens and migration laws
- GADTs, indexed families, symbolic terms, reduction, and coverage checking

The `didactic-pydantic`, `didactic-settings`, and `didactic-fastapi`
distributions add their modules under the `didactic` namespace.

## Documentation

Read the [tutorial and guides](https://panproto.dev/didactic/) or the
[API reference](https://panproto.dev/didactic/reference/).

## License

Released under the [MIT License](https://github.com/panproto/didactic/blob/main/LICENSE).
