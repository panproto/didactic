# didactic

A typed-data library for Python that uses
[panproto](https://github.com/panproto/panproto) as its substrate.
Authoring is class-based and looks like Pydantic. Underneath, every
Model corresponds to a panproto `Theory`, every value to a panproto
`Schema`, and every transformation between Models to a panproto
`Lens`.

```python
import didactic as dx


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

## Repository layout

The repository is a `uv` workspace containing four distributions:

| distribution | path | contributes |
| --- | --- | --- |
| `didactic` | `packages/didactic` | core library |
| `didactic-pydantic` | `packages/didactic-pydantic` | `didactic.pydantic` adapters |
| `didactic-settings` | `packages/didactic-settings` | `didactic.settings` |
| `didactic-fastapi` | `packages/didactic-fastapi` | `didactic.fastapi` |

The siblings ship as namespace-package contributions under
`didactic.<name>`. Install only the ones you need:

```sh
pip install didactic                # core
pip install didactic-pydantic       # adds didactic.pydantic
pip install didactic-settings       # adds didactic.settings
pip install didactic-fastapi        # adds didactic.fastapi
```

didactic targets Python 3.14 and panproto 0.42+.

## What the core library covers

- `dx.Model` and `dx.BaseModel`: frozen, type-checked records.
- `dx.field(...)`: field-metadata constructor with default,
  default_factory, alias, description, examples, deprecated,
  nominal-id flag, custom converters (PEP 712), and pass-through
  extras.
- `dx.RootModel[T]` and `dx.TypeAdapter[T]`: typed wrappers for
  non-record payloads and ad-hoc validation.
- `dx.types.EmailStr`, `HttpUrl`, `SecretStr`, `Json[T]`:
  constrained scalar annotations.
- `dx.Ref[T]`, `dx.Embed[T]`, `dx.Backref[T, "field"]`: cross-vertex
  reference, owned sub-vertex, and inverse-of-Ref markers.
- `dx.resolve_backrefs(...)` and `dx.ModelPool`: in-memory backref
  resolution.
- `dx.TaggedUnion`: discriminated unions with subclass dispatch.
- `dx.Lens`, `dx.Iso`, `dx.Mapping`: lens classes with `>>`
  composition, identity, `inverse()` for isos.
- `dx.DependentLens`: schema-parametric lens family wrapping
  `panproto.ProtolensChain`.
- `dx.computed` and `dx.derived`: output-only fields that
  participate in `model_dump`. The first recomputes on every read;
  the second is computed once at construction and cached.
- `dx.axiom(...)` and `__axioms__`: class-level constraints,
  enforced at construction via the panproto-Expr parser.
- `dx.validates(field_name)`: per-field validator decorator.
- `Annotated[T, ...]` reading: `annotated-types` primitives produce
  axioms; PEP 727 `Doc` populates descriptions.
- JSON and pickle round-trip with per-field re-coercion of
  JSON-friendly forms back to native types.
- `dx.register_migration(...)` and `dx.migrate(...)`: schema
  migrations as registered lenses, keyed by structural fingerprint.
  Survives class renames and re-imports.
- `dx.save_registry(path)` and `dx.load_registry(path)`: registry
  persistence as human-readable JSON.
- `dx.diff(M1, M2)`, `dx.classify_change(M1, M2)`,
  `dx.is_breaking_change(M1, M2)`: schema diff and breaking-change
  detection.
- `dx.synthesise_migration(SourceModel, TargetModel)`: auto-generate
  a candidate migration lens for review.
- `Model.emit_as(target)` and `dx.codegen.write(...)`: emit a Model
  as JSON Schema, Avro, OpenAPI, FHIR, Protobuf, BSON, CDDL,
  Parquet, or any of 50+ panproto codecs and 10+ tree-sitter
  source languages.
- `dx.codegen.emitter` decorator and `IndentWriter` helper: register
  custom emitters for formats panproto does not ship.
- `dx.schema_uri`, `dx.embed_schema_uri`, `dx.FingerprintRegistry`:
  content-addressed self-describing JSON.
- `dx.Repository.init(path)`: filesystem-backed schema VCS over
  `panproto.Repository`. `repo.add(SomeModel)` synthesises a
  single-vertex schema via `Protocol.from_theories`.
- Theory colimit on multiple inheritance: `class D(B, C)` builds
  the panproto pushout of B and C over their lowest common Model
  ancestor.
- `dx.testing.verify_iso(iso, strategy)` and friends: Hypothesis
  fixtures for the GetPut, PutGet, composition, and inverse laws.
- `didactic` CLI: `schema show`, `registry list`, `emit`, `targets`,
  `check breaking`, `version`.

## Sibling packages

- `didactic.pydantic`: bidirectional adapter between
  `pydantic.BaseModel` and `dx.Model`. Both `from_pydantic` and
  `to_pydantic` ship.
- `didactic.settings`: typed application settings drawn from
  environment variables, dotenv, JSON / TOML / YAML files, and CLI
  arguments. Each field's value records the source it came from.
- `didactic.fastapi`: `as_request` / `as_response` adapters and a
  422 handler so `dx.Model` types can be used as FastAPI request and
  response bodies.

## Documentation

The site under `docs/` follows the [Diátaxis](https://diataxis.fr/)
structure: tutorial, task-oriented guides, conceptual background,
and per-symbol API reference. Build locally:

```sh
uv run mkdocs serve
```

The full reference is generated from numpy-style docstrings on every
public symbol.

## Examples

Runnable end-to-end snippets live under `examples/`:

| file | demonstrates |
| --- | --- |
| `01_basic_model.py` | Model definition, JSON round-trip, immutability |
| `02_migration.py` | registering an Iso and migrating a payload |
| `03_lens.py` | defining an Iso and verifying its laws |
| `04_pydantic_interop.py` | bidirectional Pydantic adapter |

Each is self-contained: `uv run python examples/01_basic_model.py`.

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

## License

MIT.
