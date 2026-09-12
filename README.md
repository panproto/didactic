# didactic

[![PyPI](https://img.shields.io/pypi/v/didactic?style=flat-square&color=blue)](https://pypi.org/project/didactic/)
[![Python](https://img.shields.io/pypi/pyversions/didactic?style=flat-square)](https://pypi.org/project/didactic/)
[![License](https://img.shields.io/pypi/l/didactic?style=flat-square&color=green)](LICENSE)
[![CI](https://img.shields.io/github/actions/workflow/status/panproto/didactic/ci.yml?branch=main&style=flat-square&label=ci)](https://github.com/panproto/didactic/actions/workflows/ci.yml)
[![Docs](https://img.shields.io/badge/docs-panproto.dev-blue?style=flat-square)](https://panproto.dev/didactic/)

Didactic gives Python model classes a checked
[Panproto](https://github.com/panproto/panproto) semantics. Its authoring API
resembles Pydantic: annotations define fields, construction validates values,
and model instances are immutable. Each `Model` also compiles to a Panproto
`Theory`, each value has a schema representation, and model transformations use
Panproto lenses.

This connection supports indexed data, schema migration, compatibility checks,
code generation, and schema version control without maintaining a separate
schema definition.

## Install

Didactic requires Python 3.14 or later. The core distribution requires
`panproto>=0.74.2`.

```sh
pip install didactic
```

Install an integration only when the application needs it:

```sh
pip install didactic-pydantic
pip install didactic-settings
pip install didactic-fastapi
```

The integration distributions add modules under the `didactic` namespace.

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

assert updated.model_dump() == {
    "id": "u1",
    "email": "alice@example.com",
    "display_name": "Alice",
}
assert User.__theory__.name == "User"
```

Fields may carry defaults, factories, aliases, descriptions, examples,
deprecation flags, converters, and validation hooks. `dx.Ref`, `dx.Embed`, and
`dx.Backref` describe references and ownership in graph-shaped data.

## Index one field by another

`dx.Universe` defines a finite set of codes and associates each code with a
Python carrier type. An `IndexedBy` marker then states which sibling field
selects the carrier for a value:

```python
from typing import Annotated, Literal

import didactic.api as dx


Payload = dx.Universe("Payload", text=str, number=float)


class Record(dx.Model):
    kind: Literal["text", "number"]
    body: Annotated[str | float, Payload.at("kind")]


text = Record(kind="text", body="hello")
number = Record(kind="number", body=2.5)
```

`Record(kind="number", body="hello")` raises a `ValidationError` with an
`index_mismatch` entry. The generated theory records the dependency in its
parameter telescope. JSON Schema and OpenAPI preserve known cases as
conditions, Pydantic adapters retain cross-field validation, and compatibility
checks treat index changes as breaking.

`dx.GADT` provides the general declaration API behind this shorthand. It covers
families with dependent parameter telescopes, indexed constructors, motives,
case branches, equations, rewrites, and user-defined eliminators. `compile()`
checks the complete declaration with Panproto. See
[GADTs and indexed families](https://panproto.dev/didactic/guide/gadts/) for a
typed expression language and its evaluator.

## Work with schemas

| Task | API |
| --- | --- |
| Add class and field constraints | `dx.axiom(...)`, `@dx.validates` |
| Define reversible transformations | `dx.Lens`, `dx.Iso`, `dx.DependentLens` |
| Register and run migrations | `dx.register_migration(...)`, `dx.migrate(...)` |
| Review compatibility | `dx.diff(...)`, `dx.classify_change(...)`, `dx.is_breaking_change(...)` |
| Propose a migration | `dx.synthesise_migration(...)` |
| Emit schema formats | `Model.emit_as(target)`, `dx.codegen.write(...)` |
| Store schema history | `dx.Repository.init(path)` |
| Check transformation laws | `dx.testing.verify_iso(...)` and related helpers |

Panproto supplies JSON Schema, Avro, OpenAPI, FHIR, Protobuf, BSON, CDDL,
Parquet, and other emitters. Run `didactic targets` to inspect the formats
available in the installed Panproto version.

## Packages

This repository is a `uv` workspace with four distributions:

| Distribution | Import | Purpose |
| --- | --- | --- |
| [`didactic`](packages/didactic) | `didactic.api` | models, GADTs, lenses, migrations, code generation, and schema VCS |
| [`didactic-pydantic`](packages/didactic-pydantic) | `didactic.pydantic` | conversion between Pydantic and Didactic models |
| [`didactic-settings`](packages/didactic-settings) | `didactic.settings` | settings loaded from files, environment variables, and CLI input |
| [`didactic-fastapi`](packages/didactic-fastapi) | `didactic.fastapi` | request and response adapters plus validation error handling |

## Run the examples

The [`examples`](examples) directory contains four self-contained programs:

| File | Demonstrates |
| --- | --- |
| [`01_basic_model.py`](examples/01_basic_model.py) | model definition, JSON round trip, and immutable updates |
| [`02_migration.py`](examples/02_migration.py) | migration registration and execution |
| [`03_lens.py`](examples/03_lens.py) | an isomorphism and its property-based law checks |
| [`04_pydantic_interop.py`](examples/04_pydantic_interop.py) | conversion in both directions between Pydantic and Didactic |

```sh
uv run python examples/01_basic_model.py
```

## Documentation

The [documentation](https://panproto.dev/didactic/) contains a tutorial,
task-oriented guides, explanations of the Panproto encoding, and API reference
generated from public docstrings.

To serve it locally:

```sh
uv run mkdocs serve
```

## Develop

Development requires Python 3.14 or later and
[`uv`](https://docs.astral.sh/uv/).

```sh
uv sync --all-packages --all-extras
uv run ruff format --check
uv run ruff check
uv run pyright
uv run pytest -ra
uv run mkdocs build --strict
```

## Stability

Didactic is pre-1.0. The documented public API is supported. The internal
Panproto encoding may change between minor releases, while structural
fingerprints and the migration registry's on-disk format remain stable across
those changes.

## Acknowledgments

Claude Code provided substantial assistance with Didactic's design and
implementation.

## License

Released under the [MIT License](LICENSE).
