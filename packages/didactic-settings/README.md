# didactic-settings

*Typed application settings on top of `dx.Model`.*

[![PyPI](https://img.shields.io/pypi/v/didactic-settings?style=flat-square&color=blue)](https://pypi.org/project/didactic-settings/)
[![Python](https://img.shields.io/pypi/pyversions/didactic-settings?style=flat-square)](https://pypi.org/project/didactic-settings/)
[![License](https://img.shields.io/pypi/l/didactic-settings?style=flat-square&color=green)](https://github.com/panproto/didactic/blob/main/LICENSE)
[![CI](https://img.shields.io/github/actions/workflow/status/panproto/didactic/ci.yml?branch=main&style=flat-square&label=ci)](https://github.com/panproto/didactic/actions/workflows/ci.yml)
[![Docs](https://img.shields.io/badge/docs-panproto.dev-blue?style=flat-square)](https://panproto.dev/didactic/guide/settings/)

Contributes `didactic.settings` to the namespace package.

## Install

```sh
pip install didactic-settings
pip install 'didactic-settings[yaml]'   # adds YAML support
```

The package depends on `didactic`. The optional `yaml` extra adds
PyYAML for `.yaml` / `.yml` config files.

## Quickstart

```python
import didactic.api as dx
from didactic.settings import Settings, EnvSource, FileSource


class AppSettings(Settings):
    debug: bool = False
    db_url: str
    port: int = 8080

    __sources__ = (
        FileSource(path="config.toml"),
        EnvSource(prefix="APP_"),
    )


cfg = AppSettings.load()
cfg.port                      # the resolved value
cfg.__provenance__["port"]    # 'env' / 'file' / 'default' / 'override'
```

`Settings` inherits from `dx.Model`, so every Model feature works:
type checks, axioms, validators, JSON Schema export.

## Sources

| source | reads from |
| --- | --- |
| `EnvSource(prefix="APP_")` | environment variables |
| `DotEnvSource(path=".env", prefix="APP_")` | dotenv file |
| `FileSource(path="config.toml")` | JSON, TOML, or YAML by suffix |
| `CliSource(args=ns)` | parsed `argparse.Namespace` or dict |

Sources are walked in declaration order; later sources override
earlier ones. Keyword overrides at `Settings.load(...)` win over
every source.

## Documentation

See [Guides > Settings](https://panproto.dev/didactic/guide/settings/)
for the full source documentation, coercion rules, and provenance
reporting.

## License

Released under the [MIT License](https://github.com/panproto/didactic/blob/main/LICENSE).
