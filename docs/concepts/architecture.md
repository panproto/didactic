# Architecture

didactic is a thin Python layer over panproto: didactic owns the 
public API and the model authoring
experience; and panproto owns the runtime representation, the lens and
schema VCS implementations, and the protocol codecs.

## What didactic adds

- A class-based authoring surface (`dx.Model`, `dx.field`,
  `@dx.validates`, `dx.Ref`, `dx.Embed`, `dx.TaggedUnion`) that
  feels like Pydantic.
- An immutable, frozen-by-design instance shape with strict
  type checking at construction.
- A type translation layer that maps Python annotations to panproto
  sorts.
- A migration registry keyed by structural fingerprint.
- Thin wrappers around panproto's `Repository`, `IoRegistry`, and
  `AstParserRegistry` that own the public API contract independently
  of panproto's binding details.
- A JSON Schema emitter that matches Pydantic's dialect.
- A custom-emitter framework for formats panproto does not ship.
- A small CLI for inspecting Models and the migration registry.

## What panproto provides

- `panproto.Theory`: the categorical signature (sorts, operations,
  equations) for a data shape.
- `panproto.Schema`: a Theory instantiated against a Protocol with
  concrete vertices and edges.
- `panproto.Lens` and `panproto.ProtolensChain`: the lens runtime
  with formal complement-bearing get/put.
- `panproto.Repository`: a filesystem-backed schema VCS.
- `panproto.IoRegistry`: 50+ codecs for instance parse / emit
  (Avro, OpenAPI, FHIR, Protobuf, BSON, CDDL, Parquet, ...).
- `panproto.AstParserRegistry`: tree-sitter-backed parsers for many
  programming languages, with an emitter that walks `grammar.json`
  productions to produce syntactically valid source de novo.
- Schema diff, breaking-change classification, and migration
  synthesis.

## How a Model becomes a Theory

```text
class Foo(dx.Model):           [_meta.py]   [_theory.py]      [panproto]
    x: int             -->     FieldSpecs    spec dict     Theory object
    y: str
```

1. The metaclass walks the class's annotations once at class
   creation. Each annotation goes through
   `didactic.types._types.classify` which returns a
   `didactic.types._types.TypeTranslation` with an
   encode/decode pair plus a sort name. The result is a
   [FieldSpec][didactic.api.FieldSpec] cached on `__field_specs__`.
2. On first access of `Foo.__theory__`, the bridge in
   `didactic.theory._theory` builds a panproto-shaped spec dict
   from the FieldSpecs. This is a pure-Python dict.
3. The dict goes through `panproto.create_theory`. The result is the
   `panproto.Theory` cached on the class.

Steps 1 and 2 are cheap and deterministic. Step 3 invokes the
panproto runtime; failures here usually point at a malformed spec
dict, not at user code.

## How a value travels

A field's value is held in encoded form (always `str`) on the
underlying `ModelStorage`. Reading the field decodes through the
field's `TypeTranslation`. JSON dumps go through one extra encoding
pass for non-natively-JSON types (`datetime` to ISO 8601, `Decimal`
to numeric string, etc.); validation reverses the same conversion.

## Why frozen, why immutable

Lenses, fingerprints, the schema VCS, and panproto's content-addressed
hash all assume that values are immutable. didactic propagates that
property at the Python level: instances cannot have fields rewritten,
the storage is private, and the public update path
(`Model.with_(...)`) always produces a new instance.

The cost is that mutable in-place updates are not available. The
benefit is that every operation downstream of a Model is a pure
function.
