# didactic

*A typed-data library for Python on top of [panproto](https://github.com/panproto/panproto).*

[![PyPI](https://img.shields.io/pypi/v/didactic?style=flat-square&color=blue)](https://pypi.org/project/didactic/)
[![Python](https://img.shields.io/pypi/pyversions/didactic?style=flat-square)](https://pypi.org/project/didactic/)
[![License](https://img.shields.io/pypi/l/didactic?style=flat-square&color=green)](LICENSE)
[![CI](https://img.shields.io/github/actions/workflow/status/panproto/didactic/ci.yml?branch=main&style=flat-square&label=ci)](https://github.com/panproto/didactic/actions/workflows/ci.yml)
[![Docs](https://img.shields.io/badge/docs-panproto.dev-blue?style=flat-square)](https://panproto.dev/didactic/)

Authoring is class-based and looks like Pydantic. Underneath, every
Model corresponds to a panproto `Theory`, every value to a panproto
`Schema`, and every transformation between Models to a panproto
`Lens`.

```python
import didactic.api as dx


class User(dx.Model):
    """A user record."""

    id: str
    email: str
    display_name: str = ""


u = User(id="u1", email="alice@example.com")
u2 = u.with_(display_name="Alice")
u2.model_dump()
# {"id": "u1", "email": "alice@example.com", "display_name": "Alice"}
```

The class above is also a panproto Theory:

```python
theory = User.__theory__   # a real panproto.Theory
theory.name                # "User"
theory.sort_count          # 4
theory.op_count            # 3
```

## Install

didactic targets Python 3.14 and panproto 0.43+.

```sh
pip install didactic                # core
pip install didactic-pydantic       # adds didactic.pydantic
pip install didactic-settings       # adds didactic.settings
pip install didactic-fastapi        # adds didactic.fastapi
```

The siblings ship as namespace-package contributions under
`didactic.<name>`. Install only the ones you need.

## Workspace layout

The repository is a `uv` workspace containing four distributions:

| distribution | path | contributes |
| --- | --- | --- |
| [`didactic`](packages/didactic) | `packages/didactic` | core library |
| [`didactic-pydantic`](packages/didactic-pydantic) | `packages/didactic-pydantic` | `didactic.pydantic` adapters |
| [`didactic-settings`](packages/didactic-settings) | `packages/didactic-settings` | `didactic.settings` |
| [`didactic-fastapi`](packages/didactic-fastapi) | `packages/didactic-fastapi` | `didactic.fastapi` |

## Highlights

- **Models with teeth.** `dx.Model` is frozen and type-checked. Fields
  carry defaults, factories, aliases, descriptions, examples,
  deprecation flags, custom converters (PEP 712), and pass-through
  extras.
- **Graph-shaped data.** `dx.Ref[T]`, `dx.Embed[T]`, and
  `dx.Backref[T, "field"]` express cross-vertex references, owned
  sub-vertices, and inverse-of-Ref pointers.
- **Lenses, isos, and dependent lenses.** Compose with `>>`, invert
  isos, generate from `panproto.ProtolensChain`.
- **Axioms and validators.** Class-level `dx.axiom("...")` constraints
  and per-field `@dx.validates` hooks, both enforced at construction.
- **Schema migrations.** `dx.register_migration(...)` and
  `dx.migrate(...)` index lenses by structural fingerprint, so
  registrations survive class renames and re-imports.
- **Schema diff.** `dx.diff`, `dx.classify_change`,
  `dx.is_breaking_change`, and `dx.synthesise_migration` for
  reviewing schema evolution.
- **Multi-format codegen.** `Model.emit_as(target)` and
  `dx.codegen.write(...)` cover JSON Schema, Avro, OpenAPI, FHIR,
  Protobuf, BSON, CDDL, Parquet, and 50+ other panproto codecs;
  custom emitters register through `@dx.codegen.emitter`.
- **Self-describing JSON.** Content-addressed schema URIs via
  `dx.schema_uri` and `dx.FingerprintRegistry`.
- **Schema VCS.** `dx.Repository.init(path)` wraps panproto's
  filesystem-backed schema repository, including branches, refs,
  tags, and log.
- **Theory colimit on inheritance.** `class D(B, C)` builds the
  panproto pushout of B and C over their lowest common ancestor.
- **Property-based law checks.** `dx.testing.verify_iso(iso, strategy)`
  and friends supply Hypothesis fixtures for the GetPut, PutGet,
  composition, and inverse laws.
- **CLI.** `didactic schema show`, `registry list`, `emit`, `targets`,
  `check breaking`, `version`.

The full feature surface is documented at
[panproto.dev/didactic](https://panproto.dev/didactic/).

## Sibling packages

| package | purpose |
| --- | --- |
| [`didactic.pydantic`](packages/didactic-pydantic) | bidirectional adapter between `pydantic.BaseModel` and `dx.Model` |
| [`didactic.settings`](packages/didactic-settings) | typed application settings drawn from env, dotenv, JSON/TOML/YAML files, and CLI |
| [`didactic.fastapi`](packages/didactic-fastapi) | `as_request`/`as_response` adapters and a 422 handler for FastAPI |

## Examples

Runnable end-to-end snippets live under `examples/`:

| file | demonstrates |
| --- | --- |
| `01_basic_model.py` | Model definition, JSON round-trip, immutability |
| `02_migration.py` | registering an Iso and migrating a payload |
| `03_lens.py` | defining an Iso and verifying its laws |
| `04_pydantic_interop.py` | bidirectional Pydantic adapter |

Each is self-contained: `uv run python examples/01_basic_model.py`.

## Documentation

The site under `docs/` follows the [Diátaxis](https://diataxis.fr/)
structure: tutorial, task-oriented guides, conceptual background,
and per-symbol API reference. The full reference is generated from
numpy-style docstrings on every public symbol. Build locally:

```sh
uv run mkdocs serve
```

## Development

Requires Python 3.14+ and [`uv`](https://github.com/astral-sh/uv).

```sh
uv sync --all-packages
uv run pytest
uv run ruff format
uv run ruff check
uv run pyright
uv run mkdocs build --strict
```

CI runs lint, pyright, pytest, and the docs build on Linux and macOS
for every PR.

## Status

didactic is pre-1.0. The public API is the surface listed in the
documentation. The internal panproto encoding may change between
minor releases; the structural fingerprint and the migration
registry's on-disk format are stable across such changes.

## Acknowledgments

didactic was architected and implemented with substantial assistance from Claude Code.

## License

Released under the [MIT License](LICENSE).
