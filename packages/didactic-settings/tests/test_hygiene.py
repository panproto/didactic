"""Import hygiene: a plain compose never imports panproto, torch, transformers or yaml.

The compose runs happen in a subprocess because the in-process session has
already imported panproto through the core package's tests.

This module deliberately omits ``from __future__ import annotations``;
see ``_schemas.py``.
"""

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

import didactic.settings
from didactic.settings import ConfigError, compose, load_document

from ._schemas import RunSpec

FORBIDDEN = ("panproto", "torch", "transformers", "yaml")

_SCHEMA_SCRIPT = """
import json
import sys
from typing import Literal

import didactic.api as dx
from didactic.settings import compose_traced


class TypeEncoderSpec(dx.TaggedUnion, discriminator="kind", extra="forbid"):
    pass


class TransformerEncoder(TypeEncoderSpec):
    kind: Literal["transformer"] = "transformer"
    num_heads: int = 4
    width: int = 256


class LstmEncoder(TypeEncoderSpec):
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


class DecoderSpec(dx.TaggedUnion, discriminator="kind", extra="forbid"):
    temperature: float = 1.0


class LinearDecoder(DecoderSpec):
    kind: Literal["linear"] = "linear"
    bias: bool = True


class ModelSection(dx.Model, extra="forbid"):
    type_encoder: TypeEncoderSpec | None = None
    combinator_decoders: dict[str, DecoderSpec] = dx.field(default_factory=dict)


class TrainerSpec(dx.Model, extra="forbid"):
    epochs: int = 1
    out_dir: str = "runs"


class RunSpec(dx.Model, extra="forbid"):
    model: ModelSection = dx.field(default_factory=ModelSection)
    optimizer: OptimizerSpec = dx.field(default_factory=Adam)
    trainer: TrainerSpec = dx.field(default_factory=TrainerSpec)
    paths: dict[str, str] = dx.field(default_factory=dict)


run = compose_traced(
    sys.argv[1],
    schema=RunSpec,
    profile="dev",
    groups={"model.type_encoder": "transformer"},
    overlays=[{"model": {"combinator_decoders": {"fwd": {"kind": "linear"}}}}],
    overrides=["model.type_encoder.num_heads=16", ("optimizer.lr", 0.1)],
)
spec = run.value
assert isinstance(spec.model.type_encoder, TransformerEncoder), spec
assert spec.model.type_encoder.num_heads == 16, spec
assert spec.model.type_encoder.width == 256, spec
assert spec.trainer.epochs == 1, spec
assert spec.trainer.out_dir == "/data/runs", spec
assert spec.optimizer == Adam(lr=0.1), spec
assert spec.model.combinator_decoders["fwd"] == LinearDecoder(), spec
assert run.provenance["trainer.epochs"].label == "profile:dev", run.provenance
print(
    json.dumps(
        sorted(
            m
            for m in sys.modules
            if m.split(".")[0] in {"panproto", "torch", "transformers", "yaml"}
        )
    )
)
"""


def _run(script: str, *args: str) -> str:
    result = subprocess.run(
        [sys.executable, "-c", script, *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip().splitlines()[-1]


def _toml_tree(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "profiles").mkdir()
    (root / "profiles" / "dev.toml").write_text("[trainer]\nepochs = 1\n")
    (root / "model" / "type_encoder").mkdir(parents=True)
    (root / "model" / "type_encoder" / "transformer.toml").write_text(
        'kind = "transformer"\nnum_heads = 8\n'
    )
    primary = root / "run.toml"
    primary.write_text(
        "[paths]\n"
        'data_dir = "/data"\n'
        "[trainer]\n"
        "epochs = 20\n"
        'out_dir = "${paths.data_dir}/runs"\n'
        "[optimizer]\n"
        "lr = 0.01\n"
    )
    return primary


def _yaml_tree(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "profiles").mkdir()
    (root / "profiles" / "dev.yaml").write_text("trainer:\n  epochs: 1\n")
    (root / "model" / "type_encoder").mkdir(parents=True)
    (root / "model" / "type_encoder" / "transformer.yaml").write_text(
        "kind: transformer\nnum_heads: 8\n"
    )
    primary = root / "run.yaml"
    primary.write_text(
        "paths:\n"
        "  data_dir: /data\n"
        "trainer:\n"
        "  epochs: 20\n"
        "  out_dir: ${paths.data_dir}/runs\n"
        "optimizer:\n"
        "  lr: 0.01\n"
    )
    return primary


def test_plain_compose_imports_no_panproto_torch_transformers_or_yaml(
    tmp_path: Path,
) -> None:
    primary = _toml_tree(tmp_path / "conf")
    loaded = json.loads(_run(_SCHEMA_SCRIPT, str(primary)))
    assert loaded == []


def test_yaml_compose_imports_yaml_but_not_panproto(tmp_path: Path) -> None:
    primary = _yaml_tree(tmp_path / "conf")
    loaded = json.loads(_run(_SCHEMA_SCRIPT, str(primary)))
    assert "yaml" in loaded
    assert not [
        m for m in loaded if m.split(".")[0] in {"panproto", "torch", "transformers"}
    ]


def test_engine_modules_have_no_forbidden_import_nodes() -> None:
    package = Path(didactic.settings.__file__).parent
    sources = sorted(package.glob("*.py"))
    assert sources
    allowed_didactic = {"didactic.api", "didactic.types", "didactic.fields"}
    offenders: list[str] = []
    for source in sources:
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                names = [node.module]
            for name in names:
                top = name.split(".")[0]
                if top in FORBIDDEN:
                    offenders.append(f"{source.name}: {name}")
                if (
                    top == "didactic"
                    and name != "didactic.settings"
                    and not (
                        name.startswith("didactic.settings.")
                        or any(
                            name == a or name.startswith(a + ".")
                            for a in allowed_didactic
                        )
                    )
                ):
                    offenders.append(f"{source.name}: {name}")
    assert offenders == []
    importers = [
        source.name
        for source in sources
        if 'import_module("yaml")' in source.read_text(encoding="utf-8")
    ]
    assert importers == ["_documents.py"]


def test_yaml_loader_names_the_extra_when_pyyaml_is_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(sys.modules, "yaml", None)
    doc = tmp_path / "x.yaml"
    doc.write_text("a: 1\n")
    with pytest.raises(ConfigError, match=r"didactic-settings\[yaml\]") as info:
        load_document(doc)
    assert str(info.value) == (
        f"Loading {doc} requires PyYAML; install 'didactic-settings[yaml]'"
    )
    toml = tmp_path / "run.toml"
    toml.write_text("[trainer]\nepochs = 4\n")
    assert compose(toml, schema=RunSpec).trainer.epochs == 4
    js = tmp_path / "run.json"
    js.write_text('{"trainer": {"epochs": 5}}')
    assert compose(js, schema=RunSpec).trainer.epochs == 5


def test_import_didactic_settings_pulls_none_of_the_forbidden_modules() -> None:
    script = (
        "import json, sys\n"
        "import didactic.settings\n"
        "print(json.dumps(sorted(m for m in sys.modules "
        f"if m.split('.')[0] in {set(FORBIDDEN)!r})))\n"
    )
    assert json.loads(_run(script)) == []
