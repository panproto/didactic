# didactic-settings

Typed application settings on top of `dx.Model`. Contributes
`didactic.settings` to the namespace package.

## Install

```sh
pip install didactic-settings
pip install 'didactic-settings[yaml]'   # adds YAML support
```

The package depends on `didactic`. The optional `yaml` extra adds
PyYAML for `.yaml` / `.yml` config files.

## Usage

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

MIT.
