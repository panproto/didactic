# didactic-settings

[![PyPI](https://img.shields.io/pypi/v/didactic-settings?style=flat-square&color=blue)](https://pypi.org/project/didactic-settings/)
[![Python](https://img.shields.io/pypi/pyversions/didactic-settings?style=flat-square)](https://pypi.org/project/didactic-settings/)
[![License](https://img.shields.io/pypi/l/didactic-settings?style=flat-square&color=green)](https://github.com/panproto/didactic/blob/main/LICENSE)
[![CI](https://img.shields.io/github/actions/workflow/status/panproto/didactic/ci.yml?branch=main&style=flat-square&label=ci)](https://github.com/panproto/didactic/actions/workflows/ci.yml)
[![Docs](https://img.shields.io/badge/docs-panproto.dev-blue?style=flat-square)](https://panproto.dev/didactic/guide/settings/)

`didactic-settings` loads typed application settings into a `dx.Model`. It adds
the `didactic.settings` module with sources for environment variables, dotenv
files, JSON, TOML, YAML, and parsed command-line arguments.

## Install

```sh
pip install didactic-settings
pip install 'didactic-settings[yaml]'
```

The `yaml` extra installs PyYAML for `.yaml` and `.yml` files.

## Load settings

```python
from didactic.settings import EnvSource, FileSource, Settings


class AppSettings(Settings):
    db_url: str
    debug: bool = False
    port: int = 8080

    __sources__ = (
        FileSource(path="config.toml"),
        EnvSource(prefix="APP_"),
    )


settings = AppSettings.load(db_url="postgresql://localhost/app")
source = settings.__provenance__["port"]
```

`AppSettings.load()` reads the declared sources, applies keyword overrides, and
then validates the result as a Didactic model. `__provenance__` records whether
each value came from a source, a default, or a keyword override.

## Source precedence

Sources run in declaration order. A later source overrides values supplied by
an earlier one, and keyword arguments to `Settings.load(...)` take final
precedence.

| Source | Input |
| --- | --- |
| `EnvSource(prefix="APP_")` | environment variables |
| `DotEnvSource(path=".env", prefix="APP_")` | a dotenv file |
| `FileSource(path="config.toml")` | JSON, TOML, or YAML selected by suffix |
| `CliSource(args=namespace)` | an `argparse.Namespace` or mapping |

Because `Settings` extends `dx.Model`, loaded values receive the same type
checks, axioms, field validators, and indexed-field checks as other Didactic
models.

## Documentation

See the [settings guide](https://panproto.dev/didactic/guide/settings/) for
source configuration, coercion rules, and provenance reporting.

## License

Released under the [MIT License](https://github.com/panproto/didactic/blob/main/LICENSE).
