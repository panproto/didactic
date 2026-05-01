# Code generation

Every Model knows how to emit itself in a target format.
[Model.emit_as][didactic.api.Model.emit_as] is the dispatch entry; it
delegates in this order:

1. Custom emitters registered via
   [@dx.codegen.emitter][didactic.codegen.emitter] or
   [register_emitter][didactic.codegen.register_emitter].
2. didactic's own JSON Schema emitter when `target == "json_schema"`.
3. panproto's `IoRegistry` codecs (Avro, OpenAPI, FHIR, BSON, CDDL,
   Parquet, K8s CRD, GeoJSON, ...).
4. panproto's `AstParserRegistry` grammars for source-language
   emission (Rust, TypeScript, Python, Go, Java, ...).

Unknown targets raise `LookupError` with a message naming the
enumeration helpers.

## Single-target emission

```python
import didactic.api as dx


class User(dx.Model):
    """A user record."""

    id: str
    email: str = dx.field(description="primary contact")


User.emit_as("json_schema")     # bytes (JSON document)
User.emit_as("avro")            # bytes (Avro schema)
User.emit_as("rust")            # bytes (Rust source)
User.emit_as("typescript")      # bytes (TypeScript source)
```

Output is always `bytes`. Decode with `.decode("utf-8")` for text
formats.

## Bulk export

[didactic.codegen.write][didactic.codegen.write] writes every
combination of `(model, target)` to a directory:

```python
dx.codegen.write(
    [User, Account, Order],
    targets={
        "json_schema": "schemas/json/",
        "avro": "schemas/avro/",
        "rust": "api-types/src/",
        "typescript": "client/types/",
    },
)
```

Each output directory is created if it does not exist. The default
filename template is `{model_name}.{ext}`; pass `filename=` to
override. The canonical extension per target is recorded in
`didactic.codegen._write._DEFAULT_EXTENSIONS` and falls back to the
target name.

## JSON Schema

`Model.model_json_schema()` returns the JSON Schema as a Python dict
(useful for in-process inspection). `Model.emit_as("json_schema")`
serialises that dict to bytes with two-space indentation.

The emitter handles:

- field annotations to `type` / `format`
- `description`, `examples`, `deprecated` keywords
- required-field tracking
- `annotated-types` constraints (`Ge`, `Le`, `MinLen`, etc.) to
  `minimum`, `maximum`, `minLength`, etc.
- `extras["json_schema_extra"]` dicts merge verbatim into the
  property
- `Predicate` constraints land under `x-didactic-predicate` (no JSON
  Schema standard equivalent exists)

## Custom emitters

A custom emitter is a class registered under a target name. It must
satisfy [didactic.codegen.Emitter][didactic.codegen.Emitter]:

```python
from didactic.codegen import emitter, IndentWriter


@emitter("graphql_lite")
class GraphQLLite:
    file_extension = "graphql"

    def emit_class(self, cls):
        w = IndentWriter()
        w.line(f"type {cls.__name__} {{")
        with w.indent():
            for name, spec in cls.__field_specs__.items():
                w.line(f"{name}: {self._gql_type(spec)}")
        w.line("}")
        return w.bytes()

    def emit_instance(self, instance):
        raise NotImplementedError

    def _gql_type(self, spec):
        return spec.translation.sort
```

After `@emitter("graphql_lite")` runs, `User.emit_as("graphql_lite")`
and `dx.codegen.write(..., targets={"graphql_lite": "schema/"})`
both work.

### Discovery

Three discovery paths, in priority order:

1. `@emitter("name")` decorator registers in the importing process.
2. [register_emitter("name", instance)][didactic.codegen.register_emitter]
   for explicit registration.
3. `[project.entry-points."didactic.emitters"]` in your
   `pyproject.toml`. The first call to
   [list_emitters][didactic.codegen.list_emitters] (or to
   [Model.emit_as][didactic.api.Model.emit_as]) loads each entry point.

### IndentWriter

[didactic.codegen.IndentWriter][didactic.codegen.IndentWriter] is the
helper for emitter authors. Methods: `line(text)`, `text(text)`,
`indent()` (context manager), `text_str()`, and `bytes()`.

## Source-level parse and emit

For the AST grammars panproto bundles (Rust, TypeScript, Python, Go,
Java, JavaScript, etc.), didactic also exposes the inverse direction:

```python
from didactic.codegen import source

# parse a Rust source file
schema = source.parse(b"struct User { id: String }", protocol="rust")

# transform schema...

# emit back as Rust
source.emit(schema, protocol="rust")
```

The two directions form a parse-emit lens; see
[for_protocol][didactic.codegen.source.for_protocol] for the
lens-shaped wrapper. Two laws are machine-checkable on concrete
inputs:

- `parse(emit(schema)) ≅ schema` modulo byte positions.
- `emit(parse(bytes)) == bytes` byte-for-byte when `bytes` is
  parseable.

## Instance emit and parse

[didactic.codegen.io.emit][didactic.codegen.io.emit] and
[didactic.codegen.io.parse][didactic.codegen.io.parse] move a Model
*instance* through one of panproto's 50 instance codecs (Avro, FHIR,
BSON, CDDL, OpenAPI, Parquet, K8s CRD, ...). The unified entry point
is [didactic.codegen.io.check_round_trip][] which asserts
`parse(emit(x)) == x` for the named protocol.

```python
import didactic.api as dx
from didactic.codegen import io

class User(dx.Model):
    id: str
    email: str

u = User(id="u1", email="ada@example.org")
data = io.emit("avro", u)
back = io.parse("avro", data, schema=User)
assert back == u
```

### Wire format and lossiness

The instance round trip routes Python values through a JSON
intermediary so that panproto's pyo3 boundary
(`Instance.from_json`) can build the Instance from a single
string. **The JSON in the middle is *not* the lossy form**: each
field is encoded into its sort's canonical wire form *before* JSON
sees it. Decimal becomes a string ("1.23"), datetime becomes an ISO
string, bytes becomes a hex string, UUID becomes its canonical
string, and so on. The schema then tells panproto each field's sort,
and the codec emits its native rich type (avro `decimal(p, s)`, bson
`Decimal128`, fhir `dateTime`, ...).

What this *does* mean:

- **Two different Python types that share a JSON literal would
  collide.** Today's eleven scalars (str/int/float/bool/bytes/Decimal/
  datetime/date/time/UUID/None) all have distinct canonical wire
  forms, so the boundary is lossless for the v0.1 type space.
- **Protocols with native types richer than didactic's declared
  sorts** (e.g. bson ObjectId, avro `fixed(N)`, protobuf
  `sint64`/`fixed64` distinctions) cannot round-trip those riches
  through a didactic Model, not because of the JSON intermediary,
  but because the Model schema cannot *declare* the distinction in
  the first place. Adding a richer Model field type (e.g. a future
  `dx.Fixed[N]`) is what unlocks the corresponding codec features.
- **`io.parse` re-coerces wire strings through each field's
  `from_json` adapter** before handing the dict to
  `Model.model_validate`. If a future panproto codec returns a
  Python-native value (e.g. a real `datetime` rather than the ISO
  string), the adapter falls back to passing the value through
  unchanged. This is a soft contract; if it ever drifts, the symptom
  will be a quiet type mismatch in `Model.model_validate`. A
  `Instance.from_python(...)` constructor on the panproto side would
  let didactic skip the JSON hop entirely; tracked for a future
  panproto release.

## Listing available targets

```python
dx.codegen.list_emitters()
# every custom emitter name

dx.codegen.io.list_protocols()
# every IoRegistry protocol name

dx.codegen.source.available_targets()
# every panproto grammar name
```

The `didactic targets` CLI command prints all three categories.
