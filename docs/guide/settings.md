# Settings

The `didactic-settings` distribution provides a `Settings` base class
that draws values from one or more sources. Each field in the
resulting Settings instance carries the name of the source it came
from, on a per-instance `__provenance__` dict.

## Installation

```bash
pip install didactic-settings           # core
pip install 'didactic-settings[yaml]'   # adds YAML support
```

## Basic shape

```python
import didactic.api as dx
from didactic.settings import Settings, EnvSource, FileSource


class App(Settings):
    debug: bool = False
    db_url: str
    port: int = 8080

    __sources__ = (
        FileSource(path="config.toml"),
        EnvSource(prefix="APP_"),
    )


cfg = App.load()
cfg.port                     # the resolved value
cfg.__provenance__["port"]   # 'env' / 'file' / 'default' / 'override'
```

`Settings` inherits from `dx.Model`, so every Model feature works:
type checks, axioms, validators, JSON Schema export.

## Sources

| source | reads from |
| --- | --- |
| `EnvSource(prefix="APP_")` | environment variables, with the prefix applied |
| `DotEnvSource(path=".env")` | a dotenv file with the same prefix logic |
| `FileSource(path="config.toml")` | JSON, TOML, or YAML, dispatched by suffix |
| `CliSource(args=ns)` | a parsed `argparse.Namespace` or dict |

Each source has a `name` keyword used in provenance reporting; the
defaults are `"env"`, `"dotenv"`, `"file"`, `"cli"`.

### Environment variables

`EnvSource(prefix="APP_")` reads `APP_PORT`, `APP_DB_URL`, etc. Field
names are upper-cased after the prefix. String values from the
environment are coerced to `int`, `float`, and `bool` based on the
field's annotation; everything else passes through unchanged.

### Dotenv files

`DotEnvSource(path=".env", prefix="APP_")` parses a file of
`KEY=value` pairs; lines starting with `#` and blank lines are
ignored. The same prefix and coercion rules apply.

### Structured config files

`FileSource(path="config.toml")` reads JSON, TOML, or YAML by file
suffix. The file's top level must be a mapping. Keys not in the
Settings field set are silently ignored.

### CLI arguments

`CliSource(args=ns)` accepts either an `argparse.Namespace` or a
plain dict. `None` values are skipped (so `argparse` defaults of
`None` correctly fall through to the next source).

## Source precedence

Sources are walked in the order declared in `__sources__`. Later
sources override earlier ones. A common pattern is "file first, env
on top, CLI at the very top":

```python
class App(Settings):
    port: int = 8080
    __sources__ = (
        FileSource(path="config.toml"),     # base
        EnvSource(prefix="APP_"),           # env overrides file
        CliSource(args=parsed_argv),        # cli overrides env
    )
```

Keyword overrides at `App.load(port=9999)` win over every source.

## Provenance

`cfg.__provenance__` records, for each field, the name of the source
that supplied the value. If a field falls through to its declared
default, the value is `"default"`. If overridden via `load(**kwargs)`,
the value is `"override"`.

Use this for diagnostics:

```python
for field, source in cfg.__provenance__.items():
    print(f"{field:<20} <- {source}")
```
