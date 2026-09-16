"""Per-leaf provenance through nested models, maps and tagged unions.

The record covers exactly the leaves of ``value.model_dump_json()``; every
leaf names the layer that wrote it, or ``default`` when no layer did. The
leaf definition used here is the one LoFI's conformance helper uses: a
non-empty dict descends, an empty dict is a leaf, a list is a leaf, and
every scalar and ``None`` is a leaf.

This module deliberately omits ``from __future__ import annotations``;
see ``_schemas.py``.
"""

import json
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Literal

import pytest

import didactic.api as dx
from didactic.settings import (
    Composed,
    ConfigError,
    Origin,
    Provenance,
    compose,
    compose_traced,
    provenance_of,
)

from ._schemas import (
    Adam,
    AdditiveAttention,
    GruEncoder,
    LinearDecoder,
    LstmEncoder,
    RunSpec,
    TransformerEncoder,
)

type _Json = str | int | float | bool | None | list[_Json] | dict[str, _Json]


def _leaves(node: _Json, path: tuple[str, ...] = ()) -> Iterator[tuple[str, _Json]]:
    if isinstance(node, dict) and node:
        for key, child in node.items():
            yield from _leaves(child, (*path, key))
    else:
        yield ".".join(path), node


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


# -- coverage law ----------------------------------------------------------------


def test_provenance_covers_exactly_the_leaves_of_the_dump(tmp_path: Path) -> None:
    cfg = _write(
        tmp_path / "run.yaml",
        "model:\n"
        "  type_encoder:\n"
        "    kind: gru\n"
        "    attention:\n"
        "      kind: additive\n"
        "  combinator_decoders:\n"
        "    fwd:\n"
        "      kind: linear\n"
        "    bwd:\n"
        "      kind: mlp\n"
        "      hidden: 3\n"
        "paths:\n"
        "  data_dir: /d\n"
        "  cache: /c\n"
        "encoders:\n"
        "  - kind: lstm\n",
    )
    run = compose_traced(cfg, schema=RunSpec)
    dumped = json.loads(run.value.model_dump_json())
    assert set(run.provenance.paths) == {path for path, _ in _leaves(dumped)}
    assert run.provenance["paths.data_dir"].label == "file:run.yaml"
    assert run.provenance["paths.cache"].label == "file:run.yaml"
    assert run.provenance["encoders"].label == "file:run.yaml"
    assert (
        run.provenance["model.combinator_decoders.bwd.hidden"].label == "file:run.yaml"
    )
    assert (
        run.provenance["model.combinator_decoders.bwd.temperature"].label == "default"
    )


def test_coverage_with_nulls_empty_maps_and_empty_tuples() -> None:
    class Inner(dx.Model, extra="forbid"):
        x: int = 0

    class Holder(dx.Model, extra="forbid"):
        maybe: Inner | None = None
        table: dict[str, str] = dx.field(default_factory=dict[str, str])
        items: tuple[int, ...] = ()
        inner: Inner = dx.field(default_factory=Inner)

    run = compose_traced(schema=Holder, overlays=[{"maybe": None, "table": {}}])
    dumped = json.loads(run.value.model_dump_json())
    assert dumped == {"maybe": None, "table": {}, "items": [], "inner": {"x": 0}}
    assert set(run.provenance.paths) == {"maybe", "table", "items", "inner.x"}
    assert run.provenance["maybe"].label == "overlay:#0"
    # an empty mapping at a map slot merges no entries, so the empty map the
    # dump shows is the field default and completion labels it as such
    assert run.provenance["table"].label == "default"
    assert run.provenance["items"].label == "default"
    assert run.provenance["inner.x"].label == "default"


def test_untouched_nested_model_has_every_field_labelled_default() -> None:
    run = compose_traced(schema=RunSpec)
    p = run.provenance
    assert p.under("trainer").keys() == {
        "trainer.epochs",
        "trainer.out_dir",
        "trainer.log_dir",
    }
    assert {o.label for o in p.under("trainer").values()} == {"default"}
    assert {o.label for o in p.under("optimizer").values()} == {"default"}
    assert p["optimizer.kind"].label == "default"
    assert run.value.trainer.log_dir == "runs/logs"


# -- per-leaf attribution ---------------------------------------------------------


def test_partial_overlays_keep_per_leaf_attribution(tmp_path: Path) -> None:
    a = _write(tmp_path / "a.toml", "[trainer]\nepochs = 3\n")
    b = _write(tmp_path / "b.toml", '[trainer]\nout_dir = "b"\n')
    run = compose_traced(schema=RunSpec, overlays=[a, b])
    assert run.value.trainer.epochs == 3
    assert run.value.trainer.out_dir == "b"
    assert run.provenance["trainer.epochs"].label == "overlay:a.toml"
    assert run.provenance["trainer.out_dir"].label == "overlay:b.toml"
    assert run.provenance["trainer.log_dir"].label == "default"


def test_scalar_map_merges_key_by_key_with_per_key_attribution(tmp_path: Path) -> None:
    a = _write(tmp_path / "a.yaml", "paths:\n  data_dir: /a\n  cache: /a-cache\n")
    b = _write(tmp_path / "b.yaml", "paths:\n  data_dir: /b\n")
    run = compose_traced(schema=RunSpec, overlays=[a, b])
    assert run.value.paths == {"data_dir": "/b", "cache": "/a-cache"}
    assert run.provenance["paths.data_dir"].label == "overlay:b.yaml"
    assert run.provenance["paths.cache"].label == "overlay:a.yaml"


def test_map_of_unions_merges_per_entry(tmp_path: Path) -> None:
    a = _write(
        tmp_path / "a.yaml",
        "model:\n  combinator_decoders:\n    fwd:\n"
        "      kind: linear\n      bias: false\n",
    )
    b = _write(
        tmp_path / "b.yaml",
        "model:\n  combinator_decoders:\n    bwd:\n      kind: linear\n",
    )
    run = compose_traced(schema=RunSpec, overlays=[a, b])
    assert run.value.model.combinator_decoders == {
        "fwd": LinearDecoder(bias=False),
        "bwd": LinearDecoder(),
    }
    p = run.provenance
    assert p["model.combinator_decoders.fwd.bias"].label == "overlay:a.yaml"
    assert p["model.combinator_decoders.fwd.kind"].label == "overlay:a.yaml"
    assert p["model.combinator_decoders.bwd.kind"].label == "overlay:b.yaml"
    assert p["model.combinator_decoders.bwd.bias"].label == "default"


def test_null_replacing_a_map_prunes_the_old_leaves() -> None:
    class Holder(dx.Model, extra="forbid"):
        table: dict[str, str] | None = None

    run = compose_traced(
        schema=Holder,
        overlays=[{"table": {"a": "1", "b": "2"}}, {"table": None}],
        overrides=["table.c=3"],
    )
    assert run.value.table == {"c": "3"}
    assert run.provenance.paths == ("table.c",)
    assert run.provenance["table.c"].label == "override:table.c=3"
    cleared = compose_traced(
        schema=Holder, overlays=[{"table": {"a": "1", "b": "2"}}, {"table": None}]
    )
    assert cleared.value.table is None
    assert cleared.provenance.paths == ("table",)
    assert cleared.provenance["table"].label == "overlay:#1"


def test_none_clearing_an_optional_model_prunes_its_leaves(tmp_path: Path) -> None:
    class Inner(dx.Model, extra="forbid"):
        x: int = 0
        y: int = 0

    class Holder(dx.Model, extra="forbid"):
        maybe: Inner | None = None

    run = compose_traced(
        schema=Holder, overlays=[{"maybe": {"x": 1, "y": 2}}, {"maybe": None}]
    )
    assert run.value.maybe is None
    assert run.provenance.paths == ("maybe",)
    assert run.provenance["maybe"].label == "overlay:#1"


def test_provenance_through_a_variant_with_nested_model_and_union(
    tmp_path: Path,
) -> None:
    cfg = _write(
        tmp_path / "run.yaml",
        "model:\n  type_encoder:\n    kind: gru\n    head:\n      layers: 2\n",
    )
    run = compose_traced(
        cfg,
        schema=RunSpec,
        overrides=[
            "model.type_encoder.attention.kind=additive",
            "model.type_encoder.head.dropout=0.3",
        ],
    )
    enc = run.value.model.type_encoder
    assert isinstance(enc, GruEncoder)
    assert enc.attention == AdditiveAttention()
    p = run.provenance.under("model.type_encoder")
    assert dict(p.by_layer()) == {
        "file:run.yaml": ("model.type_encoder.head.layers", "model.type_encoder.kind"),
        "override:model.type_encoder.attention.kind=additive": (
            "model.type_encoder.attention.kind",
        ),
        "override:model.type_encoder.head.dropout=0.3": (
            "model.type_encoder.head.dropout",
        ),
        "default": (
            "model.type_encoder.attention.hidden",
            "model.type_encoder.dropout",
        ),
    }


# -- interpolation ---------------------------------------------------------------


def test_interpolated_leaf_keeps_its_layer_and_gains_the_expression(
    tmp_path: Path,
) -> None:
    cfg = _write(
        tmp_path / "run.yaml",
        "paths:\n  data_dir: /d\ntrainer:\n  out_dir: ${paths.data_dir}/runs\n",
    )
    run = compose_traced(cfg, schema=RunSpec)
    assert run.value.trainer.out_dir == "/d/runs"
    origin = run.provenance["trainer.out_dir"]
    assert origin.kind == "file"
    assert origin.name == "run.yaml"
    assert origin.expression == "${paths.data_dir}/runs"
    assert run.provenance["paths.data_dir"].expression is None
    # the default expression on ``log_dir`` is recorded the same way
    assert run.provenance["trainer.log_dir"].label == "default"
    assert run.provenance["trainer.log_dir"].expression == "${trainer.out_dir}/logs"
    assert run.value.trainer.log_dir == "/d/runs/logs"


def test_whole_node_interpolation_at_a_mapping_slot_is_refused(tmp_path: Path) -> None:
    # a string at a model, union or map slot is refused before interpolation
    # runs, so ``section: ${other}`` never pastes a subtree into the tree
    class Holder(dx.Model, extra="forbid"):
        a: dict[str, str] = dx.field(default_factory=dict[str, str])
        b: dict[str, str] = dx.field(default_factory=dict[str, str])

    a = _write(tmp_path / "a.yaml", "a:\n  x: '1'\nb: ${a}\n")
    with pytest.raises(ConfigError) as info:
        compose(schema=Holder, overlays=[a])
    assert info.value.path == "b"
    assert str(info.value) == (
        "Config key 'b' expects a mapping for dict[str, str] (set by overlay:a.yaml); "
        "got str"
    )
    cfg = _write(tmp_path / "run.yaml", "trainer: ${paths}\npaths:\n  d: /d\n")
    with pytest.raises(ConfigError) as info2:
        compose(cfg, schema=RunSpec)
    assert str(info2.value) == (
        "Config key 'trainer' expects a mapping for TrainerSpec "
        "(set by file:run.yaml); got str"
    )


# -- origins -----------------------------------------------------------------------


def test_every_origin_kind_appears_with_its_name_and_path(tmp_path: Path) -> None:
    conf = tmp_path / "conf"
    _write(conf / "paths.yaml", "paths:\n  data_dir: /d\n")
    _write(conf / "model" / "type_encoder" / "lstm.yaml", "kind: lstm\n")
    _write(conf / "profiles" / "dev.yaml", "trainer:\n  epochs: 1\n")
    overlay = _write(conf / "over.yaml", "trainer:\n  out_dir: o\n")
    cfg = _write(
        conf / "run.yaml",
        "defaults:\n  - paths\n  - model.type_encoder: lstm\n"
        "model:\n  combinator_decoders:\n    fwd:\n      kind: linear\n",
    )
    run = compose_traced(
        cfg,
        schema=RunSpec,
        base={"optimizer": {"lr": 0.5}},
        profile="dev",
        overlays=[overlay, {"paths": {"cache": "/c"}}],
        overrides=["model.type_encoder.hidden=2", ("trainer.epochs", 7)],
    )
    p = run.provenance
    assert p["optimizer.lr"] == Origin(kind="base")
    assert p["paths.data_dir"] == Origin(
        kind="defaults", name="paths", path=str(conf / "paths.yaml")
    )
    assert p["model.type_encoder.kind"] == Origin(
        kind="group",
        name="model.type_encoder=lstm",
        path=str(conf / "model" / "type_encoder" / "lstm.yaml"),
    )
    assert p["model.combinator_decoders.fwd.kind"] == Origin(
        kind="file", name="run.yaml", path=str(cfg)
    )
    assert p["trainer.out_dir"] == Origin(
        kind="overlay", name="over.yaml", path=str(overlay)
    )
    assert p["paths.cache"] == Origin(kind="overlay", name="#1")
    assert p["model.type_encoder.hidden"] == Origin(
        kind="override", name="model.type_encoder.hidden=2"
    )
    assert p["trainer.epochs"] == Origin(kind="override", name="trainer.epochs=7")
    assert p["optimizer.kind"] == Origin(kind="default")
    assert {o.kind for o in p.values()} == {
        "default",
        "base",
        "group",
        "defaults",
        "file",
        "overlay",
        "override",
    }
    assert run.value.trainer.epochs == 7


def test_origin_label_and_hashability() -> None:
    assert Origin(kind="default").label == "default"
    assert Origin(kind="profile", name="dev").label == "profile:dev"
    assert (
        Origin(kind="file", name="run.yaml", path="/x/run.yaml").label
        == "file:run.yaml"
    )
    assert len({Origin(kind="default"), Origin(kind="default")}) == 1


# -- the read API ------------------------------------------------------------------


def test_provenance_is_a_sorted_immutable_mapping(tmp_path: Path) -> None:
    run = compose_traced(schema=RunSpec, overlays=[{"paths": {"b": "1", "a": "2"}}])
    p = run.provenance
    assert isinstance(p, Provenance)
    assert isinstance(p, Mapping)
    assert list(p) == sorted(p)
    assert p.paths == tuple(sorted(p))
    assert "paths.a" in p
    assert p.source_of("paths.a") == p["paths.a"]
    with pytest.raises(TypeError):
        p["paths.a"] = Origin(kind="default")  # type: ignore[index]


def test_source_of_miss_lists_the_leaves() -> None:
    run = compose_traced(schema=RunSpec, overlays=[{"paths": {"a": "1"}}])
    with pytest.raises(ConfigError) as info:
        run.provenance.source_of("paths.zzz")
    assert str(info.value).startswith(
        "No provenance recorded for 'paths.zzz'; leaves: "
    )
    assert "paths.a" in str(info.value)


def test_under_by_layer_and_to_dict(tmp_path: Path) -> None:
    cfg = _write(
        tmp_path / "run.yaml",
        "trainer:\n  epochs: 2\n  out_dir: ${paths.d}\npaths:\n  d: /d\n",
    )
    run = compose_traced(cfg, schema=RunSpec, overrides=["trainer.epochs=5"])
    p = run.provenance
    under = p.under("trainer")
    assert isinstance(under, Provenance)
    assert under.paths == ("trainer.epochs", "trainer.log_dir", "trainer.out_dir")
    assert p.under("trainer.epochs").paths == ("trainer.epochs",)
    assert p.under("train").paths == ()
    by_layer = p.by_layer()
    assert by_layer["override:trainer.epochs=5"] == ("trainer.epochs",)
    assert by_layer["file:run.yaml"] == ("paths.d", "trainer.out_dir")
    assert p.to_dict()["trainer.out_dir"] == {
        "kind": "file",
        "name": "run.yaml",
        "path": str(cfg),
        "expression": "${paths.d}",
    }
    assert p.to_dict()["trainer.epochs"] == {
        "kind": "override",
        "name": "trainer.epochs=5",
        "path": None,
        "expression": None,
    }
    assert json.dumps(p.to_dict())


def test_equal_calls_give_equal_records(tmp_path: Path) -> None:
    cfg = _write(
        tmp_path / "run.yaml",
        "model:\n  type_encoder:\n    kind: transformer\ntrainer:\n  epochs: 2\n",
    )
    first = compose_traced(cfg, schema=RunSpec, overrides=["trainer.epochs=5"])
    second = compose_traced(cfg, schema=RunSpec, overrides=["trainer.epochs=5"])
    assert first.provenance == second.provenance
    assert first.tree == second.tree
    assert first.value == second.value
    assert first.layers == second.layers


def test_composed_layers_follow_the_ladder(tmp_path: Path) -> None:
    conf = tmp_path / "conf"
    _write(conf / "paths.yaml", "paths:\n  d: /d\n")
    _write(conf / "model" / "type_encoder" / "lstm.yaml", "kind: lstm\n")
    _write(conf / "profiles" / "dev.yaml", "trainer:\n  epochs: 1\n")
    overlay = _write(conf / "over.yaml", "trainer:\n  out_dir: o\n")
    cfg = _write(
        conf / "run.yaml", "defaults:\n  - paths\n  - model.type_encoder: lstm\n"
    )
    run = compose_traced(
        cfg,
        schema=RunSpec,
        base={"optimizer": {"lr": 0.5}},
        profile="dev",
        overlays=[overlay, {"paths": {"c": "/c"}}],
        overrides=["trainer.epochs=3", ("optimizer.lr", 0.25)],
    )
    assert isinstance(run, Composed)
    assert [layer.origin.label for layer in run.layers] == [
        "base",
        "defaults:paths",
        "group:model.type_encoder=lstm",
        "file:run.yaml",
        "profile:dev",
        "overlay:over.yaml",
        "overlay:#1",
        "override:trainer.epochs=3",
        "override:optimizer.lr=0.25",
    ]
    assert [layer.textual for layer in run.layers] == [False] * 7 + [True, False]
    assert run.layers[3].document == {}
    assert run.layers[0].document == {"optimizer": {"lr": 0.5}}
    assert run.layers[7].document == {"trainer": {"epochs": "3"}}
    assert run.layers[8].document == {"optimizer": {"lr": 0.25}}


def test_provenance_of_reads_the_attached_record_and_refuses_plain_instances(
    tmp_path: Path,
) -> None:
    run = compose_traced(schema=RunSpec, overrides=["trainer.epochs=3"])
    assert provenance_of(run.value) is run.provenance
    plain = compose(schema=RunSpec, overrides=["trainer.epochs=3"])
    assert isinstance(provenance_of(plain), Provenance)
    assert provenance_of(plain)["trainer.epochs"].label == "override:trainer.epochs=3"
    with pytest.raises(ConfigError) as info:
        provenance_of(RunSpec())
    assert str(info.value) == (
        "RunSpec instance carries no provenance; build it with compose() or "
        "Settings.load()"
    )
    with pytest.raises(ConfigError):
        provenance_of(plain.with_(trainer=plain.trainer))


def test_unions_in_every_position_are_covered(tmp_path: Path) -> None:
    class Root(dx.TaggedUnion, discriminator="kind", extra="forbid"):
        shared: int = 0

    class V(Root):
        kind: Literal["v"] = "v"
        own: str = "o"

    class Holder(dx.Model, extra="forbid"):
        one: Root = dx.field(default_factory=V)
        maybe: Root | None = None
        many: tuple[Root, ...] = ()
        table: dict[str, Root] = dx.field(default_factory=dict[str, Root])

    run = compose_traced(
        schema=Holder,
        overlays=[
            {
                "maybe": {"kind": "v", "shared": 1},
                "many": [{"kind": "v"}],
                "table": {"k": {"kind": "v", "own": "x"}},
            }
        ],
    )
    dumped = json.loads(run.value.model_dump_json())
    assert set(run.provenance.paths) == {path for path, _ in _leaves(dumped)}
    assert run.provenance["one.kind"].label == "default"
    assert run.provenance["maybe.shared"].label == "overlay:#0"
    assert run.provenance["maybe.own"].label == "default"
    assert run.provenance["many"].label == "overlay:#0"
    assert run.provenance["table.k.own"].label == "overlay:#0"
    assert run.provenance["table.k.shared"].label == "default"
    assert run.value.one == V()
    assert run.value.many == (V(),)
    assert isinstance(run.value.table["k"], V)
    # the other schema classes keep their defaults through the same machinery
    assert compose(schema=RunSpec).optimizer == Adam()
    assert compose(
        schema=RunSpec, overlays=[{"encoders": [{"kind": "lstm"}]}]
    ).encoders == (LstmEncoder(),)
    assert isinstance(
        compose(
            schema=RunSpec,
            overlays=[{"model": {"type_encoder": {"kind": "transformer"}}}],
        ).model.type_encoder,
        TransformerEncoder,
    )
