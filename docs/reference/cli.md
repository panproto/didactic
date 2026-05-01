# CLI

The `didactic` console script is wired by
`[project.scripts] didactic = "didactic.cli._cli:main"` in the
core package. The Python entry point is
`didactic.cli._cli.main(argv=None)`, which parses arguments and
dispatches to the subcommand handlers.

## Subcommands

The full per-subcommand reference lives in
[Guides > CLI](../guide/cli.md):

- `didactic schema show <module:Class>`
- `didactic registry list`
- `didactic emit <module:Class> --target <name> [--out <path>]`
- `didactic targets`
- `didactic check breaking <old> <new>`
- `didactic version`

## Exit codes

| code | meaning |
| --- | --- |
| 0 | success (or non-breaking change for `check breaking`) |
| 1 | user error (bad arguments, unimportable module, missing subcommand) |
| 2 | breaking change detected by `check breaking` |
