# Settings

The `didactic-settings` distribution. See
[Guides > Settings](../guide/settings.md) for the per-source
documentation and usage patterns.

```python
from didactic.settings import (
    Settings,
    EnvSource,
    DotEnvSource,
    FileSource,
    CliSource,
)


class App(Settings):
    debug: bool = False
    port: int = 8080

    __sources__ = (
        FileSource(path="config.toml"),
        EnvSource(prefix="APP_"),
    )


cfg = App.load()
cfg.port                       # the resolved value
cfg.__provenance__["port"]     # 'env' / 'file' / 'default' / 'override'
```

## Sources

| source | reads from |
| --- | --- |
| `EnvSource(prefix=, name="env")` | environment variables |
| `DotEnvSource(path=, prefix=, name="dotenv")` | dotenv file |
| `FileSource(path=, name="file")` | JSON / TOML / YAML by suffix |
| `CliSource(args=, name="cli")` | argparse `Namespace` or dict |

Each source has a `name` keyword used in provenance reporting.

## `Settings.load`

`Settings.load(**overrides)` walks the declared `__sources__`
in order, then applies any `**overrides`. The result is a
`Settings` instance with `__provenance__` populated.

The final precedence (lowest to highest) is:

1. The declared default on the field.
2. Sources, in the order declared in `__sources__`.
3. Keyword overrides passed to `load(...)`.

A field that falls through to its declared default has provenance
`"default"`. A field set by a keyword override has provenance
`"override"`.
