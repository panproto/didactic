# didactic-settings

[![PyPI](https://img.shields.io/pypi/v/didactic-settings?style=flat-square&color=blue)](https://pypi.org/project/didactic-settings/)
[![Python](https://img.shields.io/pypi/pyversions/didactic-settings?style=flat-square)](https://pypi.org/project/didactic-settings/)
[![License](https://img.shields.io/pypi/l/didactic-settings?style=flat-square&color=green)](https://github.com/panproto/didactic/blob/main/LICENSE)
[![CI](https://img.shields.io/github/actions/workflow/status/panproto/didactic/ci.yml?branch=main&style=flat-square&label=ci)](https://github.com/panproto/didactic/actions/workflows/ci.yml)
[![Docs](https://img.shields.io/badge/docs-panproto.dev-blue?style=flat-square)](https://panproto.dev/didactic/guide/settings/)

`didactic-settings` composes a validated `dx.Model` from layered configuration:
a primary file and the config-group fragments its `defaults:` list selects, a
profile, overlay files, environment variables, dotenv files, command-line
arguments and dotted overrides. Every layer is checked against the schema at
every depth, tagged-union fields are descended into the variant their
discriminator selects, `${...}` expressions are resolved against the composed
tree, and the instance records which layer wrote each leaf.

## Install

```sh
pip install didactic-settings
pip install 'didactic-settings[yaml]'
```

JSON and TOML are read through the standard library; the `yaml` extra installs
PyYAML for `.yaml` and `.yml` files.

## Compose a configuration

```python
from typing import Literal

import didactic.api as dx
from didactic.settings import compose_traced


class OptimizerSpec(dx.TaggedUnion, discriminator="kind", extra="forbid"):
    lr: float = 1e-3


class Adam(OptimizerSpec):
    kind: Literal["adam"] = "adam"
    betas: tuple[float, ...] = (0.9, 0.999)


class Sgd(OptimizerSpec):
    kind: Literal["sgd"] = "sgd"
    momentum: float = 0.9


class TrainerSpec(dx.Model, extra="forbid"):
    epochs: int = 1
    out_dir: str = "runs"
    log_dir: str = "${trainer.out_dir}/logs"


class RunSpec(dx.Model, extra="forbid"):
    optimizer: OptimizerSpec = dx.field(default_factory=Adam)
    trainer: TrainerSpec = dx.field(default_factory=TrainerSpec)


run = compose_traced(
    "conf/run.yaml",
    schema=RunSpec,
    profile="dev",
    overlays=["conf/big.toml"],
    groups={"optimizer": "sgd"},
    overrides=["optimizer.momentum=0.5", ("trainer.epochs", 3)],
)
run.value.trainer.log_dir
run.provenance["trainer.epochs"].label      # "override:trainer.epochs=3"
run.provenance["optimizer.momentum"].label  # "override:optimizer.momentum=0.5"
```

`conf/run.yaml` may carry a `defaults:` list selecting root fragments and
config-group fragments (`optimizer: adam` loads `conf/optimizer/adam.yaml`);
`groups=` replaces the file's choice for a slot; `profile="dev"` loads
`conf/profiles/dev.yaml`; an override whose key contains `/`
(`model/type_encoder=lstm`) selects a nested group and one without sets a
field, decoded by the leaf's annotation. A key the schema does not declare, at any depth and in any layer,
is refused with its dotted path and the layer that set it.

## Class-based settings

```python
from didactic.settings import EnvSource, FileSource, Settings


class RunSettings(Settings, RunSpec):
    __sources__ = (FileSource("local.toml"), EnvSource(prefix="APP_"))


settings = RunSettings.load("conf/run.yaml", profile="dev", trainer__epochs=3)
settings.__provenance__["trainer.epochs"].label
```

`Settings.load()` composes the primary file, its groups, the profile, overlays,
the declared sources and the overrides in that precedence. `EnvSource` reads
`APP_TRAINER__EPOCHS` for `trainer.epochs` and decodes the text by the field's
annotation; `APP_OPTIMIZER='{"kind": "sgd"}'` sets a whole slot.

| Source | Input |
| --- | --- |
| `EnvSource(prefix="APP_")` | environment variables |
| `DotEnvSource(path=".env", prefix="APP_")` | a dotenv file |
| `FileSource(path="config.toml")` | one JSON, TOML, or YAML document |
| `CliSource(args=namespace)` | an `argparse.Namespace` or mapping |

Because `Settings` extends `dx.Model`, the composed tree receives the same type
checks, axioms, field validators, and indexed-field checks as any other
Didactic model.

## Documentation

See the [settings guide](https://panproto.dev/didactic/guide/settings/) for the
composition ladder, config groups, union descent, interpolation and the
resolver registry, and per-leaf provenance.

## License

Released under the [MIT License](https://github.com/panproto/didactic/blob/main/LICENSE).
