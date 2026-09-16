# Settings

The `didactic-settings` distribution composes a validated `dx.Model` from
layered configuration: a primary file and the fragments its `defaults:` list
selects, a profile, overlay files, the environment, and dotted overrides from
a command line. Every layer is checked against the schema at every depth,
tagged-union fields are descended into the variant their discriminator selects,
`${...}` expressions are resolved against the composed tree, and the instance
that comes back records which layer wrote each leaf.

There are two entry points over one engine. `compose()` takes a schema and the
layers as arguments; `Settings` is a `dx.Model` base class whose subclasses
declare their sources once and load through `Settings.load()`.

## Installation

```bash
pip install didactic-settings           # JSON and TOML through the standard library
pip install 'didactic-settings[yaml]'   # adds PyYAML for .yaml and .yml files
```

The engine reads JSON with `json` and TOML with `tomllib`, so those formats
need nothing beyond the core distribution. YAML is read through PyYAML, which
is imported only when a `.yaml` or `.yml` file is opened; without the extra,
opening one raises `ConfigError` naming `didactic-settings[yaml]`, and every
composition over JSON and TOML keeps working.

## A schema

The examples below compose a training run. The schema is a plain `dx.Model`
tree with two tagged unions in it: an encoder behind an optional slot, and an
optimizer whose default is one of its variants.

```python
import os
import tempfile
from pathlib import Path
from typing import Literal

import didactic.api as dx
from didactic.settings import compose, compose_traced


class EncoderSpec(dx.TaggedUnion, discriminator="kind", extra="forbid"):
    pass


class TransformerEncoder(EncoderSpec):
    kind: Literal["transformer"] = "transformer"
    num_heads: int = 4
    width: int = 256


class LstmEncoder(EncoderSpec):
    kind: Literal["lstm"] = "lstm"
    hidden: int = 128


class OptimizerSpec(dx.TaggedUnion, discriminator="kind", extra="forbid"):
    lr: float = 1e-3


class Adam(OptimizerSpec):
    kind: Literal["adam"] = "adam"
    betas: tuple[float, ...] = (0.9, 0.999)


class Sgd(OptimizerSpec):
    kind: Literal["sgd"] = "sgd"
    momentum: float = 0.9


class ModelSection(dx.Model, extra="forbid"):
    type_encoder: EncoderSpec | None = None


class TrainerSpec(dx.Model, extra="forbid"):
    epochs: int = 1
    out_dir: str = "runs"
    log_dir: str = "${.out_dir}/logs"


class RunSpec(dx.Model, extra="forbid"):
    model: ModelSection = dx.field(default_factory=ModelSection)
    optimizer: OptimizerSpec = dx.field(default_factory=Adam)
    trainer: TrainerSpec = dx.field(default_factory=TrainerSpec)
    paths: dict[str, str] = dx.field(default_factory=dict[str, str])
    tags: tuple[str, ...] = ()
```

`TrainerSpec.log_dir` has a default that is an expression. Defaults may refer
to the composed tree; the engine materialises such a default before
interpolation so it resolves against whatever the layers set. A default
expression is resolved at the path the field is mounted at, so a model meant
to be reused under several parents should refer to its siblings relatively
(`${.out_dir}`); the absolute `${trainer.out_dir}` binds `TrainerSpec` to the
`trainer` slot and fails with an unresolved reference anywhere else.

## Files

A configuration directory holds the primary file, root fragments, profiles and
config groups:

```text
conf/
  run.yaml                          # the primary file
  paths.yaml                        # a root fragment, selected by "- paths"
  profiles/dev.yaml                 # profile="dev"
  big.toml                          # an overlay
  model/type_encoder/transformer.yaml
  model/type_encoder/lstm.yaml
```

`run.yaml` selects fragments in its `defaults:` list and sets values in its
body:

```yaml
defaults:
  - paths
  - model.type_encoder: transformer
trainer:
  epochs: 20
  out_dir: ${paths.data_dir}/runs/${oc.env:RUN_USER,anon}
optimizer:
  lr: 0.01
```

A fragment holds the value of its slot, not a wrapper: `transformer.yaml` is
`kind: transformer` and `num_heads: 8`, and the engine mounts it under
`model.type_encoder`. A root fragment such as `paths.yaml` is a whole document
merged at the root. The snippet below writes this tree into a temporary
directory so the rest of the page can run against it.

```python
conf = Path(tempfile.mkdtemp()) / "conf"


def write(relative: str, text: str) -> Path:
    file = conf / relative
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(text, encoding="utf-8")
    return file


write(
    "run.yaml",
    "defaults:\n"
    "  - paths\n"
    "  - model.type_encoder: transformer\n"
    "trainer:\n"
    "  epochs: 20\n"
    "  out_dir: ${paths.data_dir}/runs/${oc.env:RUN_USER,anon}\n"
    "optimizer:\n"
    "  lr: 0.01\n",
)
write("paths.yaml", "paths:\n  data_dir: /data\n")
write("profiles/dev.yaml", "trainer:\n  epochs: 1\n")
write("big.toml", "[model.type_encoder]\nwidth = 1024\n")
write("model/type_encoder/transformer.yaml", "kind: transformer\nnum_heads: 8\n")
write("model/type_encoder/lstm.yaml", "kind: lstm\n")
```

Composing the run reads the file, its fragments, a profile, an overlay and two
overrides, and returns a validated `RunSpec`:

```python
os.environ.pop("RUN_USER", None)

spec = compose(
    conf / "run.yaml",
    schema=RunSpec,
    profile="dev",
    overlays=[conf / "big.toml"],
    overrides=["model.type_encoder.num_heads=16", ("optimizer.lr", 0.1)],
)

assert spec.model.type_encoder == TransformerEncoder(num_heads=16, width=1024)
assert spec.trainer.epochs == 1
assert spec.trainer.out_dir == "/data/runs/anon"
assert spec.trainer.log_dir == "/data/runs/anon/logs"
assert spec.optimizer == Adam(lr=0.1)
```

The profile's `epochs: 1` beat the file body's `epochs: 20`; the overlay set
`width` on the variant the fragment selected; the override string set
`num_heads` as text and the typed pair set `lr` as a float; `out_dir` resolved
against `paths.data_dir` from the root fragment; and `log_dir`, which no layer
set, resolved its default expression against the composed `out_dir`.

### The ladder

Layers merge lowest precedence first. Each rung stamps the origin kind named in
parentheses on every leaf it writes:

1. schema defaults (`default`), written only by provenance completion and by
   the settle pass for an injected discriminator;
2. the `base` mapping (`base`);
3. the selection table (`defaults` for a root fragment, `group` for a slot
   fragment): the primary file's `defaults:` entries in list order, with
   `groups=` and `slot/path=name` overrides replacing an entry for the same
   slot in place or appending one;
4. the primary file's body minus `defaults` (`file`);
5. the profile (`profile`): a name loads `profiles/<name>` from the search
   roots, a mapping is used as given;
6. the overlays in order (`overlay`): a path loads a file, a mapping is used in
   process and named `#<index>`;
7. a `Settings` class's `__sources__` in declaration order (`source`);
8. the overrides in the order given (`override`), `key=value` strings and
   `(key, value)` pairs alike, then `Settings.load(**values)`.

After the last layer the engine settles the tree (injecting the discriminator
a field default selects into every union node that has none), interpolates the
whole tree once, checks the resolved tree against the schema, validates it
once through `schema.model_validate_json`, so that a `Path` or `datetime` leaf
written as text and a `tuple` field written as a list take their typed forms,
and completes the provenance record from the validated instance.

The search roots are the primary file's parent, then the `search_path` entries
in order. Fragments and profiles are looked up in every root; the earliest
root holding a name wins, and a name without a suffix tries `.yaml`, `.yml`,
`.toml` and `.json` in that order. Within one root, two files sharing a stem
with different suffixes are refused as ambiguous.

The `defaults` key of the primary file is always the selection list, even
when the schema declares a field of that name; such a field can be set from
any other layer. In an overlay, a profile, a fragment or a `FileSource`,
`defaults` is an ordinary key, so a schema that does not declare it refuses
it as unknown.

## Config groups

A config group is a directory whose path under a search root is the slot's
dotted schema path with `.` replaced by `/`; a fragment is one document in it.
Three spellings select a fragment, and all three feed one ordered table keyed
by slot:

- a one-key mapping entry in the primary file's `defaults:` list,
  `model.type_encoder: transformer` (Hydra's `model/type_encoder: transformer`
  spelling is accepted and normalised); `model.type_encoder: null` records the
  slot with no selection;
- the `groups=` argument, a mapping from slot to name, applied after the
  file's entries; `None` deselects a slot the file chose;
- an override string whose key contains `/`, `model/type_encoder=lstm`. A key
  with `/` is always a group selection and a key without one is always a field
  path, so the two never collide; selections are consumed before the merge. A
  top-level slot such as `optimizer` has no `/` in its path, so it is selected
  through `defaults:` or `groups=` rather than an override string.

A later selection for a slot already in the table replaces it in place, so a
sweep that re-selects a slot replaces the file's fragment rather than merging
over it. The whole table merges above `base` and below the primary file body,
whichever spelling made the selection, so a value the file body sets beats
the fragment and an override beats both.

```python
from itertools import product

sweep = [
    compose(
        conf / "run.yaml",
        schema=RunSpec,
        groups={"model.type_encoder": encoder},
        overrides=[("optimizer.lr", lr)],
    )
    for encoder, lr in product(("transformer", "lstm"), (1e-3, 1e-2))
]
assert len(sweep) == 4
assert isinstance(sweep[0].model.type_encoder, TransformerEncoder)
assert isinstance(sweep[2].model.type_encoder, LstmEncoder)

from_cli = compose(
    conf / "run.yaml",
    schema=RunSpec,
    overrides=["model/type_encoder=lstm", "model.type_encoder.hidden=64"],
)
assert from_cli.model.type_encoder == LstmEncoder(hidden=64)

deselected = compose(
    conf / "run.yaml", schema=RunSpec, groups={"model.type_encoder": None}
)
assert deselected.model.type_encoder is None
```

A missing fragment raises `MissingFragmentError` listing every path tried in
the order tried and the names that do exist; a group directory in no root
lists the roots searched; a selection with no roots at all (no primary file
and no `search_path`) raises `ConfigError` asking for a config directory.

```python
from didactic.settings import MissingFragmentError

try:
    compose(conf / "run.yaml", schema=RunSpec, groups={"model.type_encoder": "gru"})
except MissingFragmentError as error:
    assert error.group == "model.type_encoder"
    assert error.name == "gru"
    assert error.available == ("lstm", "transformer")
    assert len(error.tried) == 4
```

## Profiles and overlays

A profile is a document under `profiles/` in a search root, selected by name,
or a mapping passed directly; it sits above the file body and below the
overlays. Overlays are file paths or mappings merged in order above the
profile. Both are checked like every other layer: a key the schema does not
declare is refused with its dotted path and the layer that set it.

```python
from didactic.settings import UnknownKeyError

with_mapping_profile = compose(
    conf / "run.yaml", schema=RunSpec, profile={"trainer": {"epochs": 3}}
)
assert with_mapping_profile.trainer.epochs == 3

try:
    compose(conf / "run.yaml", schema=RunSpec, overlays=[{"trainer": {"epoch": 3}}])
except UnknownKeyError as error:
    assert error.path == "trainer.epoch"
    assert error.allowed == ("epochs", "log_dir", "out_dir")
    assert error.set_by is not None and error.set_by.label == "overlay:#0"
```

## Dotted overrides

An override is either a `key=value` string or a `(key, value)` pair. A string
is textual: the value text is decoded by the annotation of the leaf it lands
on, so `"123"` stays a string under `str` and becomes an integer under `int`.
A pair is typed and its value is used as given, after a check against the
leaf annotation. Both become a one-leaf layer mounted at the key and merge
through the same checks as a file, so an unknown key is `UnknownKeyError` at
merge time, never a validation error later.

Textual decoding follows the annotation:

- `str` keeps the text verbatim;
- `bool` accepts `1`, `0`, `true`, `false`, `yes`, `no`, `on` and `off` in any
  case;
- `int` and `float` use the constructors;
- `Literal[...]` matches the text against each member and returns the member;
  an `Enum` is matched by member name, then by value;
- `T | None` reads `null`, `~` and the empty string as `None`, then decodes
  `T`; `Annotated[T, ...]` unwraps to `T`;
- `tuple[T, ...]` and `frozenset[T]` read JSON when the text starts with `[`
  and otherwise split on commas, decoding each item as `T`;
- a model, union or map slot requires JSON object text, so
  `model.type_encoder={"kind": "lstm", "hidden": 64}` sets the whole slot, and
  an optional model, union or map slot reads `null`, `~` and the empty string
  as `None`;
- text holding a `${...}` expression is kept as it is, whatever the
  annotation, and decoded the same way once interpolation has resolved it, so
  `trainer.epochs=${oc.env:EPOCHS}` sets an `int` leaf from the environment.

Text that cannot be read raises `CoercionError` naming the path, the expected
form and the text. Lists are set whole: a key that indexes into one, such as
`tags.0`, is refused as `OverrideSyntaxError`.

A value that arrives typed (from a file, a `base` or overlay mapping, a
`(key, value)` pair, `Settings.load(**values)`, a typed CLI argument, or a
resolver) is checked against the leaf annotation when it is written: `bool`
never satisfies `int`, `int` satisfies `float`, `None` needs an optional
annotation, a `Literal` or `Enum` needs a member of the same type, and a
`Path`, `datetime`, `date`, `time`, `UUID`, `Decimal` or `bytes` leaf takes
its JSON text form. A mismatch is the same `CoercionError`, with the value's
`repr` (or `dict` or `list` for a container) as the text, so a TOML file
setting `epochs = "20"` is refused with `trainer.epochs`, the file's name and
the text `'20'`.

```python
from didactic.settings import CoercionError, OverrideSyntaxError

overridden = compose(
    conf / "run.yaml",
    schema=RunSpec,
    overrides=[
        "trainer.epochs=7",
        "tags=a,b",
        "optimizer.betas=[0.8, 0.95]",
        'model.type_encoder={"kind": "lstm", "hidden": 64}',
    ],
)
assert overridden.trainer.epochs == 7
assert overridden.tags == ("a", "b")
assert overridden.optimizer == Adam(lr=0.01, betas=(0.8, 0.95))
assert overridden.model.type_encoder == LstmEncoder(hidden=64)

try:
    compose(conf / "run.yaml", schema=RunSpec, overrides=["trainer.epochs=many"])
except CoercionError as error:
    assert error.path == "trainer.epochs"
    assert error.expected == "int"
    assert error.text == "many"

try:
    compose(conf / "run.yaml", schema=RunSpec, overrides=["tags.0=x"])
except OverrideSyntaxError as error:
    assert "lists are set whole" in str(error)
```

Where no annotation is at hand, text is read with the schema-free grammar of
`parse_scalar`: `null`, `~` and the empty string give `None`; `true` and
`false` give booleans; integer and float literals (including `1e-3`, `inf`
and `nan`) give numbers; text starting with `[` or `{` is JSON; a quoted
string gives its contents; anything else, `yes` and `007` included, is the
text itself.

```python
from didactic.settings import parse_scalar

assert parse_scalar("1e3") == 1000.0
assert parse_scalar("[1, 2]") == [1, 2]
assert parse_scalar("yes") == "yes"
assert parse_scalar("007") == "007"
assert parse_scalar("~") is None
```

## Tagged unions

A tagged-union field is descended, not treated as an opaque leaf. At a union
node the engine reads the discriminator before any sibling key, in the
incoming layer first and then in the tree accumulated so far. With a tag in
hand it checks the node's keys against the selected variant's fields, so a
key that belongs to another variant is refused naming both variants and the
layer that selected the one in force:

```python
try:
    compose(conf / "run.yaml", schema=RunSpec, overrides=["model.type_encoder.hidden=3"])
except UnknownKeyError as error:
    assert error.path == "model.type_encoder.hidden"
    assert error.declared_by == ("lstm",)
    assert str(error) == (
        "Unknown config key 'model.type_encoder.hidden' "
        "(set by override:model.type_encoder.hidden=3): "
        "variant 'transformer' of EncoderSpec "
        "(set by group:model.type_encoder=transformer) has no field 'hidden'; "
        "it belongs to variant 'lstm'"
    )
```

Before any layer has set a tag, a node is provisional: each key merges under
the target the variants declaring it agree on, and the node keeps no
discriminator. The field default never selects a variant during the merge.
Only the settle pass, after the last layer, consults it: a tagless node
receives the tag of the variant the enclosing field's default is an instance
of, stamped `default`, and its keys are then checked against that variant.
This is what makes composition order-independent: `{momentum: 0.5}` then
`{kind: sgd}` and the reverse compose to the same tree with the same
provenance, while `{momentum: 0.5}` alone is refused at settle, since the
default variant is `adam`.

```python
from didactic.settings import ConfigError

forward = compose(
    schema=RunSpec,
    overlays=[{"optimizer": {"momentum": 0.5}}, {"optimizer": {"kind": "sgd"}}],
)
reverse = compose(
    schema=RunSpec,
    overlays=[{"optimizer": {"kind": "sgd"}}, {"optimizer": {"momentum": 0.5}}],
)
assert forward.optimizer == reverse.optimizer == Sgd(momentum=0.5)

try:
    compose(schema=RunSpec, overlays=[{"optimizer": {"momentum": 0.5}}])
except UnknownKeyError as error:
    assert "variant 'adam' of OptimizerSpec (selected by default)" in str(error)
```

Two rules do depend on order. First, a later layer that sets a different tag
switches the variant: the old variant's private fields are dropped from the
node (root-shared fields and fields both variants declare survive), which is
what lets `model.type_encoder.kind=lstm` sit on top of a file that chose
`transformer`. Second, a key that several variants declare with different
types cannot be merged provisionally; the engine asks for the tag in the same
or an earlier layer.

```python
switched = compose(
    conf / "run.yaml", schema=RunSpec, overrides=["model.type_encoder.kind=lstm"]
)
assert switched.model.type_encoder == LstmEncoder()
```

A node with no tag and no default variant (an optional slot, a map entry, a
list element, or a default that is a bare root instance) is refused at settle
with the registered tags. A tag naming no registered variant is
`UnknownVariantError` listing the registry, which is read live, so variants a
plugin registers after the root was defined take part. A discriminator must be
a literal value: `kind: ${encoder}` is refused, because variant selection
happens at merge time and interpolation runs after it. Under a textual layer
the tag text is decoded against every variant's literal, so a union tagged by
`Literal[1]` is selected by the environment variable value `1`. A typed tag
must match a literal by type as well as value: `True` does not select a
`Literal[1]` variant and `1` does not select a `Literal[True]` one, and the
registry is rendered with the live values (`Stage registers: [1, 2]`), so a
`'1'` given where `1` is registered reads as the mismatch it is. A variant
registered under several literals is named by its first. When the variants
alias the discriminator field (`kind: Literal["w"] = dx.field(default="w",
alias="type")`), a tag given under the alias selects the variant and is stored
under the field name.

```python
from didactic.settings import UnknownVariantError

try:
    compose(schema=RunSpec, overlays=[{"model": {"type_encoder": {"hidden": 3}}}])
except ConfigError as error:
    assert "selects no variant of EncoderSpec" in str(error)

try:
    compose(schema=RunSpec, overlays=[{"optimizer": {"kind": "rmsprop"}}])
except UnknownVariantError as error:
    assert error.registered == ("adam", "sgd")

try:
    compose(schema=RunSpec, overlays=[{"optimizer": {"kind": "${choice}"}}])
except UnknownVariantError as error:
    assert "must be a literal value" in str(error)
```

Unions nest: a variant's own fields may hold further models, unions, maps and
lists, and the same rules apply at every depth. Map keys are data and are
never checked against the schema; each entry's value merges under the map's
value type, so `dict[str, DecoderSpec]` entries descend into their variants
and `dict[str, str]` entries merge key by key. The schema's default map is the
lowest layer of a map slot: a default entry survives a layer that adds another
key, and a layer's entry composes over the default entry of the same key,
through a default union entry's tag included. Lists are set wholesale by
whichever layer wrote them last; every element of a model or union list is
checked, so a string, a number, `null` or a nested list where a mapping is
declared is refused as `encoders[0]`, and an unknown key inside an element is
reported as `items[0].bogus`.

Names a document layer (a file, a mapping, a profile, an overlay, a file
source) carries for computed and derived fields are accepted and dropped, so
a document produced by `model_dump()` composes back without error. An
override, a `Settings.load(**values)` keyword, or a textual source (the
environment, a dotenv file, the command line) is never a dump, so there such
a name is refused as `UnknownKeyError` saying the field is computed. A model
declaring `extra="ignore"` has its unknown keys skipped without a record;
every other model refuses them.

Before any tag is known, a key is merged under the type the variants that
declare it agree on. A field the root declares counts as declared by every
variant, so a variant that shadows it with another annotation (`width: int`
under a root `width: float`) or with another optionality (`att: Spec | None`
beside `att: Spec`) makes the variants disagree, and the key is refused until
the tag is set in the same or an earlier layer.

## Interpolation and the resolver registry

`${...}` expressions are resolved once, after every layer has merged and the
tree has settled, against the composed tree backed by the schema's defaults.
The grammar is OmegaConf's:

- `${section.field}` is an absolute reference; `${.x}` and `${..x}` are
  relative, each leading dot walking one level up from the leaf's parent;
- `${a.b[0]}` and `${a.b.0}` index a list;
- `${a.${b.c}}` nests, inner first;
- `${name:arg1,arg2}` calls a resolver; arguments are split on commas outside
  brackets, braces and quotes, and each is itself interpolated, so
  `${oc.decode:[1, 2]}` passes one argument;
- `prefix_${a.b}_suffix` concatenates; a string that is exactly one expression
  substitutes the typed value, and a substring use renders it as text;
- `\${literal}` escapes.

A cycle between references is reported as a cycle, and nesting deeper than 64
levels is refused. An expression may sit at a leaf, a list, a map or a model
slot: `section: ${other}` pastes the subtree `other` resolves to, and
`tags: ${oc.dict.keys:paths}` fills a `tuple[str, ...]` from a resolver. The
resolved tree is checked against the schema once more, so a resolver result of
the wrong shape or type is refused with the slot's path and the layer that
wrote the expression, and text a resolver produced at a non-`str` leaf is
decoded by the annotation the way a textual layer's text is. A union slot is
the exception: its tag must be a literal at merge time, so a string there is
refused as the wrong shape.

The built-in resolvers mirror OmegaConf's: `oc.env:VAR[,default]`,
`oc.select:path[,default]` (a lenient lookup; `None` or the default when the
path is absent), `oc.dict.keys:path`, `oc.dict.values:path`,
`oc.deprecated:new_path[,message]` (warns with `DeprecationWarning`, then
reads the new path), `oc.create:text` (the scalar grammar, so JSON text becomes
a typed value), and `oc.decode:value[,encoding]`. Note that `oc.decode` reads
base64 text by default (`ascii` and `utf-8` pass the value through) rather
than performing OmegaConf's typed decode; the typed reading is `oc.create`.

```python
from didactic.settings import list_resolvers, resolve

assert resolve("${oc.decode:aGVsbG8=}", root={}) == "hello"
assert resolve("${oc.create:[1, 2]}", root={}) == [1, 2]
assert resolve("${oc.select:paths.missing,7}", root={"paths": {}}) == 7
assert resolve("${trainer.epochs}", root={"trainer": {"epochs": 3}}) == 3
assert resolve("run-${trainer.epochs}", root={"trainer": {"epochs": 3}}) == "run-3"
assert "oc.env" in list_resolvers()
```

The registry is module-global, so a library registers its resolvers once at
import. A resolver receives the interpolated string arguments and returns any
config value; to read other parts of the tree it calls `lookup`, which
evaluates a dotted path inside the active evaluation and therefore shares its
cycle detection, so a reference cycle that passes through a resolver is
reported as a cycle rather than overflowing the stack. `lookup` outside an
active `resolve` raises `InterpolationError`. A per-call `resolvers=` mapping
is consulted before the registry for that call only.

```python
from didactic.settings import InterpolationError, lookup, register_resolver, resolve_traced


def run_dir(*args: str) -> str:
    return f"{lookup('paths.data_dir')}/runs/{','.join(args)}"


register_resolver("my.run_dir", run_dir)

named = compose(
    conf / "run.yaml",
    schema=RunSpec,
    overrides=["trainer.out_dir=${my.run_dir:exp,1}"],
)
assert named.trainer.out_dir == "/data/runs/exp,1"

try:
    lookup("paths.data_dir")
except InterpolationError as error:
    assert "outside an active resolve()" in str(error)

per_call = compose(
    conf / "run.yaml",
    schema=RunSpec,
    overrides=["trainer.out_dir=${shout:hi}"],
    resolvers={"shout": lambda text: text.upper()},
)
assert per_call.trainer.out_dir == "HI"

resolved, expressions = resolve_traced({"a": "x", "b": "${a}y"})
assert resolved == {"a": "x", "b": "xy"}
assert expressions == {("b",): "${a}y"}
```

`register_resolver` refuses a name already registered unless `replace=True`
is passed; `unregister_resolver` removes one and `list_resolvers` lists them
sorted.

## Per-leaf provenance

`compose_traced()` and `Settings.load_traced()` return a `Composed` record:
the validated `value`, the `tree` that `model_validate` received, the
`provenance`, and the `layers` applied, lowest precedence first. The same
`Provenance` object is attached to the instance as `__provenance__`, and
`provenance_of(instance)` reads it back; an instance built directly, or
through `Model.with_()`, carries none and `provenance_of` raises
`ConfigError`.

`Provenance` is an immutable mapping from dotted leaf path to `Origin`,
iterating in sorted order and comparing by value, so two compositions from the
same layers give equal records. An `Origin` has a `kind` (the rung from the
ladder), a `name` (the profile name, `slot=name` for a fragment, the override
text, the file basename, a source's name, or `#<index>` for an in-process
overlay), a `path` (the on-disk file for file-backed layers), an `expression`
(the leaf's source text when it contained `${...}`), and a `label`, which is
`kind` when the name is empty and `kind:name` otherwise.

```python
from didactic.settings import Origin, provenance_of

run = compose_traced(
    conf / "run.yaml",
    schema=RunSpec,
    profile="dev",
    overlays=[conf / "big.toml"],
    overrides=["model.type_encoder.num_heads=16", ("optimizer.lr", 0.1)],
)
p = run.provenance
assert provenance_of(run.value) is p

assert p["model.type_encoder.kind"].label == "group:model.type_encoder=transformer"
assert p["model.type_encoder.num_heads"].label == "override:model.type_encoder.num_heads=16"
assert p["model.type_encoder.width"].label == "overlay:big.toml"
assert p["trainer.epochs"].label == "profile:dev"
assert p["paths.data_dir"].label == "defaults:paths"
assert p["optimizer.lr"].label == "override:optimizer.lr=0.1"
assert p["optimizer.kind"] == Origin("default")
assert p["optimizer.betas"].label == "default"

out_dir = p["trainer.out_dir"]
assert out_dir.kind == "file" and out_dir.name == "run.yaml"
assert out_dir.expression == "${paths.data_dir}/runs/${oc.env:RUN_USER,anon}"
assert p["trainer.log_dir"].expression == "${.out_dir}/logs"

assert [layer.origin.label for layer in run.layers] == [
    "defaults:paths",
    "group:model.type_encoder=transformer",
    "file:run.yaml",
    "profile:dev",
    "overlay:big.toml",
    "override:model.type_encoder.num_heads=16",
    "override:optimizer.lr=0.1",
]
```

The record covers exactly the leaves of `value.model_dump_json()`. A leaf is a
scalar or `None`, a whole list, an empty mapping, or any leaf reached by
descending a non-empty mapping; so every key of a `dict[str, str]` map, every
field of a nested model or selected variant, and every entry of a
`dict[str, Model]` map contributes its own leaves, and partial overlays from
two files keep per-leaf attribution. After validation, every leaf no layer
wrote (a variant default, an optional left `None`, an untouched nested model's
fields, a computed field present in the dump) is labelled `default`, and a
recorded path that is no longer a leaf of the dump (a value a validator
reshaped) is dropped. An interpolated leaf keeps the layer that wrote the
expression and gains the expression itself; values a resolver pulled from
elsewhere do not transfer their origin.

Three limits follow from the leaf definition. A list is one leaf: the
elements of a `tuple[T, ...]` field are checked against the schema and set
wholesale by the layer that wrote the list last, so attribution stops at the
list boundary and an element's origin is never recorded on its own. Map keys
are recorded verbatim as path segments, so a key containing `.` makes its
path ambiguous. And a computed field, or a value a validator reshaped, is
labelled `default` even though a layer contributed to it.

The read API covers the common questions: `paths` lists the leaves,
`source_of(path)` raises `ConfigError` listing the leaves when the path is not
one, `under(prefix)` narrows to a subtree with keys kept absolute,
`by_layer()` groups the paths by label (what did the profile change), and
`to_dict()` renders the record as JSON-shaped dicts for a sidecar file.

```python
import json

assert p.by_layer()["profile:dev"] == ("trainer.epochs",)
assert set(p.under("optimizer").paths) == {
    "optimizer.betas",
    "optimizer.kind",
    "optimizer.lr",
}
sidecar = json.dumps(p.to_dict(), indent=2)
assert json.loads(sidecar)["trainer.epochs"]["kind"] == "profile"

try:
    p.source_of("trainer.nope")
except ConfigError as error:
    assert "No provenance recorded for 'trainer.nope'" in str(error)
```

## The `Settings` class

`Settings` is a `dx.Model` base class for application settings. A subclass
declares fields like any model, a class-level `__sources__` tuple, and an
optional `__search_path__` of directories holding fragments and profiles. It
may inherit a schema alongside `Settings`, so an existing model tree becomes
loadable without redeclaring it.

```python
from didactic.settings import EnvSource, FileSource, Settings


class RunSettings(Settings, RunSpec):
    __sources__ = (FileSource(conf / "local.toml"), EnvSource(prefix="APP_"))


write("local.toml", "[trainer]\nout_dir = 'local'\n")
os.environ["APP_TRAINER__EPOCHS"] = "5"
os.environ["APP_MODEL__TYPE_ENCODER"] = '{"kind": "lstm", "hidden": 64}'
os.environ["APP_PATHS__CACHE_DIR"] = "/cache"

settings = RunSettings.load(conf / "run.yaml", profile="dev", optimizer__lr=0.5)

assert settings.trainer.epochs == 5
assert settings.trainer.out_dir == "local"
assert settings.model.type_encoder == LstmEncoder(hidden=64)
assert settings.paths == {"data_dir": "/data", "cache_dir": "/cache"}
assert settings.optimizer.lr == 0.5
assert settings.__provenance__["trainer.epochs"].label == "source:env"
assert settings.__provenance__["trainer.out_dir"].label == "source:file"
assert settings.__provenance__["optimizer.lr"].label == "override:optimizer.lr=0.5"
```

`Settings.load()` takes the same `path`, `profile`, `groups`, `overlays`,
`overrides`, `search_path` and `resolvers` as `compose()`, plus keyword
`values`: typed overrides keyed by dotted path with `__` as the separator,
applied last. The sources sit above the overlays and below the overrides. The
search roots are the primary file's parent, then the first `FileSource`'s
parent, then `search_path` (or `__search_path__` when omitted).
`Settings.load_traced()` returns the `Composed` record.

At class creation, a field named after one of `load`'s keywords (`path`,
`profile`, `groups`, `overlays`, `overrides`, `search_path`, `resolvers`) is
refused with `TypeError` suggesting an alias, and so are two sources sharing a
`name`.

### Sources

Every source is a frozen dataclass implementing `layer(schema)`, which returns
one `Layer` tagged `source:<name>` or `None` when the source has nothing. The
`Source` base class is public, so an application can add its own.

| source | reads |
| --- | --- |
| `EnvSource(prefix="", *, separator="__", name="env")` | environment variables |
| `DotEnvSource(path=".env", prefix="", *, separator="__", name="dotenv")` | a dotenv file |
| `FileSource(path="config.toml", *, name="file", required=False)` | one JSON, TOML or YAML document |
| `CliSource(args=None, *, name="cli")` | an `argparse.Namespace` or mapping |

`EnvSource` looks up every settable path of the schema (each leaf, and each
model, union and map slot) as the prefix plus the path segments joined by the
separator, upper-cased: `APP_TRAINER__EPOCHS` sets `trainer.epochs`, and
`APP_MODEL__TYPE_ENCODER` holding JSON object text sets the whole slot. Below
a map slot, a variable continuing the slot's name sets an entry, with the next
segment lower-cased as the key (`APP_PATHS__CACHE_DIR` sets
`paths["cache_dir"]`) and any further segments addressing the entry's own
fields. Variables that name no path are never read. Setting both a slot and a
path below it is refused, since the slot's text cannot also hold the nested
value. The layer is textual, so every value is decoded by the leaf's
annotation.

`DotEnvSource` parses `KEY=value` lines, optionally prefixed by `export`,
skipping blank lines and `#` comments and unquoting a value wrapped in
matching quotes; keys are looked up exactly as variables are. A missing file
contributes nothing.

`FileSource` reads the whole document as one layer, checked against the
schema at every depth like any other file; its `defaults` key is an ordinary
key, since only the primary `path` carries a selection list. A missing file
contributes nothing unless `required=True`, in which case
`FileNotFoundError` is raised.

`CliSource` takes dotted keys or keys joined by `__`; a `None` value means the
argument was not given and is skipped, so `argparse` defaults of `None` fall
through. String values are decoded by annotation and typed values pass
through.

```python
import argparse

from didactic.settings import CliSource, DotEnvSource


class CliSettings(Settings, RunSpec):
    __sources__ = (
        DotEnvSource(conf / ".env", prefix="APP_"),
        CliSource(argparse.Namespace(trainer__epochs="9", tags=None)),
    )


write(".env", "export APP_TRAINER__OUT_DIR='dotenv'\n")
cli = CliSettings.load()
assert cli.trainer.epochs == 9
assert cli.trainer.out_dir == "dotenv"
assert cli.__provenance__["trainer.epochs"].label == "source:cli"
assert cli.__provenance__["trainer.out_dir"].label == "source:dotenv"
```

## Errors

Every refusal is a `ConfigError` (a `ValueError`) carrying a `path`, the
dotted path of the offending leaf, or `None` when the error is not about one
leaf. The subclasses carry structured attributes so a caller translating
errors at a boundary never parses message text:

- `UnknownKeyError`: `path`, `allowed` (the field names accepted at the
  node), `declared_by` (tags of the variants that declare the key), `set_by`
  (the `Origin` of the layer that set it);
- `UnknownVariantError`: `path` (the discriminator's), `value`, `registered`;
- `MissingFragmentError`: `group`, `name`, `tried`, `available`;
- `CoercionError`: `path`, `expected`, `text`;
- `OverrideSyntaxError` for a malformed `key=value` string.

`InterpolationError` is a sibling of `ConfigError`, also a `ValueError`,
raised for an unresolved reference, an unknown resolver, a resolver that
raised, a cycle, or a syntax error; it carries the `path` of the leaf being
resolved. What the engine cannot check (an `Annotated` constraint, a
validator, an axiom) is left to the model, and a failure there surfaces as
`didactic.api.ValidationError` from the single validation call; an entry
raised inside a nested model is reported by the outer class with its `loc`
prefixed by the field path (`("trainer", "mode")`), and sibling fields keep
being collected.

## The hygiene guarantee

Composing a configuration imports nothing beyond the standard library and the
`didactic` core. The engine never touches a model's theory, code generation,
or axiom enforcement, which are the only parts of `didactic` that import
`panproto`, and PyYAML is imported only inside the YAML branch of document
loading. A subprocess test in the workspace pins this: after composing a
schema with nested models, unions behind optional slots and maps, a profile,
groups, overlays and overrides from TOML, neither `panproto` nor `yaml` (nor
`torch` or `transformers`) is present in `sys.modules`; composing the same
tree from YAML adds `yaml` and nothing else. The one exposure is schema-side:
a model that declares `__axioms__` imports `panproto` when it validates (at
compose time, not at class definition), and that is the schema's choice rather
than the engine's.

## Lower-level pieces

The building blocks the entry points are made of are public for callers that
hold their own documents:

- `compose_layers(schema=, layers=, resolvers=)` runs the engine over an
  assembled ladder of `Layer` records;
- `strict_merge(base, overlay, *, schema, origin=, provenance=)` merges one
  mapping over another under a schema with the same checks and union descent;
- `load_document(path)` reads one JSON, TOML or YAML file as a mapping;
- `nest_override(key, value)` mounts a value under a dotted key;
  `parse_override(text)` splits `key=value` and validates the key;
- `resolve(node, *, root, here=(), resolvers=None)` interpolates one value
  against a tree, and `resolve_traced(document, *, resolvers=None)` returns
  the resolved document with the source text of every expression-carrying
  leaf.

```python
from didactic.settings import Layer, compose_layers, load_document, nest_override, strict_merge

merged = strict_merge(
    {"trainer": {"epochs": 1}}, {"trainer": {"out_dir": "x"}}, schema=RunSpec
)
assert merged == {"trainer": {"epochs": 1, "out_dir": "x"}}
assert nest_override("trainer.epochs", 3) == {"trainer": {"epochs": 3}}
assert load_document(conf / "big.toml") == {"model": {"type_encoder": {"width": 1024}}}

layered = compose_layers(
    schema=RunSpec,
    layers=[
        Layer(origin=Origin("base"), document={"trainer": {"epochs": 2}}),
        Layer(
            origin=Origin("override", name="cli"),
            document={"trainer": {"epochs": "4"}},
            textual=True,
        ),
    ],
)
assert layered.value.trainer.epochs == 4
assert layered.provenance["trainer.epochs"].label == "override:cli"
```
