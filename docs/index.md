# didactic

A typed-data library for Python that uses
[panproto](https://github.com/panproto/panproto) as its substrate.
Authoring is class-based and looks like Pydantic. Underneath, every
Model corresponds to a panproto `Theory`, every value to a panproto
`Schema`, and every transformation between Models to a panproto
`Lens`. The package adds the operations that fall out of that
substrate: structural fingerprints, schema migrations as registered
lenses, schema diffs, breaking-change classification, multi-format
code generation, and a wrapper over panproto's filesystem-backed
schema repository.

```python
import didactic.api as dx


class User(dx.Model):
    """A user record."""

    id: str
    email: str = dx.field(description="primary contact")
    nickname: str = ""


u = User(id="u1", email="ada@example.org")
print(u.model_dump_json())
# {"id": "u1", "email": "ada@example.org", "nickname": ""}
```

## Where to start

The documentation follows the [Diátaxis](https://diataxis.fr/)
structure:

- The [Tutorial](tutorial/index.md) walks through the most common
  operations on a single example. Read this first if you have not
  used didactic before.
- The [Guides](guide/index.md) are task-oriented. Each guide answers
  a question of the form "how do I do X". Reach for these when you
  know what you want to accomplish.
- The [Concepts](concepts/index.md) explain the underlying model:
  what a panproto Theory is, why didactic uses content-addressed
  fingerprints, what laws lenses obey. Read these when you want to
  understand why something is the way it is.
- The [API reference](reference/index.md) is the per-symbol detail:
  full signatures, parameters, raised exceptions, and small
  examples.

## Sibling distributions

didactic ships as a namespace package. Three sibling distributions
contribute submodules under `didactic.<name>`:

- `didactic-pydantic` provides `from_pydantic` and `to_pydantic` for
  converting between `pydantic.BaseModel` and `dx.Model` in either
  direction. Install it when you need to interoperate with
  Pydantic-shaped code. See [Guides > Pydantic interop](guide/pydantic.md).
- `didactic-settings` provides a `Settings` base class that draws
  values from environment variables, dotenv files, structured config
  files, and CLI arguments, with each field's resolved value tagged
  by the source it came from. See [Guides > Settings](guide/settings.md).
- `didactic-fastapi` provides `as_response`/`as_request` adapters
  and a 422 handler so `dx.Model` types can be used as FastAPI
  request and response bodies. See [Guides > FastAPI](guide/fastapi.md).

Install only what you need:

```bash
pip install didactic                # core only
pip install didactic-pydantic       # adds didactic.pydantic
pip install didactic-settings       # adds didactic.settings
pip install didactic-fastapi        # adds didactic.fastapi
```

## Project status

didactic is pre-1.0. The public API is the surface documented here.
The internal panproto encoding may change between minor releases;
the structural fingerprint and the migration registry format are
stable across such changes (see [Concepts > Fingerprints](concepts/fingerprints.md)).
