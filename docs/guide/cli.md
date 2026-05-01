# CLI

The `didactic` console script ships with the core distribution. It
covers Model inspection, the migration registry, schema-format
emission, and the breaking-change check.

## Subcommands

```text
didactic schema show <module:Class>
didactic registry list
didactic emit <module:Class> --target <name> [--out <path>]
didactic targets
didactic check breaking <old> <new>
didactic version
```

## schema show

Prints the Theory spec, structural fingerprint, and JSON Schema for
a Model:

```bash
didactic schema show myapp.models:User
# # Theory: User
# # fingerprint: 06ac976d...
#
# # spec:
# {
#   ...
# }
#
# # json_schema:
# {
#   ...
# }
```

The argument is the Python `module:ClassName` shorthand. The module
must be importable from the current interpreter.

## registry list

Prints every registered migration's source and target structural
fingerprints, truncated to 12 hex characters each:

```bash
didactic registry list
# 06ac976d2317... -> 72aee87d4be9...
# 72aee87d4be9... -> a455d08082...
```

Empty output (the literal string `(empty registry)`) means no
migrations have been registered in the current process. Most
applications register their migrations at module import time, so
ensure the relevant modules have been imported before running this.

## emit

Emit a Model under a named target:

```bash
didactic emit myapp.models:User --target rust --out user.rs
didactic emit myapp.models:User --target avro --out user.avsc
didactic emit myapp.models:User --target json_schema     # to stdout
```

If `--out` is `-` (the default), the emitted bytes are written to
stdout.

## targets

Lists the available emit targets, grouped by category (custom
emitters, IoRegistry codecs, AstParserRegistry grammars):

```bash
didactic targets
# # custom emitters:
#   graphql_lite
# # IoRegistry protocols:
#   amr
#   ansible
#   ...
# # AstParserRegistry grammars:
#   bash
#   c
#   ...
```

## check breaking

Diffs two Models and exits non-zero on a breaking change:

```bash
didactic check breaking myapp.models:UserV1 myapp.models:UserV2
# BREAKING: myapp.models:UserV1 -> myapp.models:UserV2
#   {'RemovedVertex': {'vertex_id': 'V1'}}
```

Drop this into a CI step that runs against every PR. The exit codes
are:

- `0` compatible
- `2` breaking
- `1` user error (bad arguments, unimportable module)

## version

Prints didactic's version followed by panproto's:

```bash
didactic version
# didactic 0.0.1.dev0
# panproto 0.42.0
```
