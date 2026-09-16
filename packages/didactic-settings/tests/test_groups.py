"""Config groups: a directory of fragments per swappable slot.

A fragment holds the value of a slot; the ``defaults:`` list of the primary
file, the ``groups=`` argument and ``slot/path=name`` override strings feed
one selection table that is merged above ``base`` and below the file body.

This module deliberately omits ``from __future__ import annotations``;
see ``_schemas.py``.
"""

from itertools import product
from pathlib import Path

import pytest

import didactic.api as dx
from didactic.settings import (
    ConfigError,
    MissingFragmentError,
    UnknownKeyError,
    compose,
    compose_traced,
)

from ._schemas import (
    Adam,
    LinearDecoder,
    LstmEncoder,
    MlpDecoder,
    RunSpec,
    TransformerEncoder,
    subtree,
)


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


@pytest.fixture
def conf(tmp_path: Path) -> Path:
    """The ``conf/`` directory from the design's worked example."""
    root = tmp_path / "conf"
    _write(root / "paths.yaml", "paths:\n  data_dir: /data/ccg\n")
    _write(root / "profiles" / "dev.yaml", "trainer:\n  epochs: 1\n")
    _write(root / "big.yaml", "model:\n  type_encoder:\n    width: 1024\n")
    _write(
        root / "model" / "type_encoder" / "transformer.yaml",
        "kind: transformer\nnum_heads: 8\n",
    )
    _write(root / "model" / "type_encoder" / "lstm.yaml", "kind: lstm\n")
    _write(
        root / "model" / "combinator_decoders" / "fwd" / "linear.yaml",
        "kind: linear\n",
    )
    _write(
        root / "model" / "combinator_decoders" / "fwd" / "mlp.toml",
        'kind = "mlp"\nhidden = 8\n',
    )
    _write(root / "trainer" / "fast.json", '{"epochs": 2, "out_dir": "fast"}')
    _write(
        root / "run.yaml",
        "defaults:\n"
        "  - paths\n"
        "  - model.type_encoder: transformer\n"
        "  - model.combinator_decoders.fwd: linear\n"
        "trainer:\n"
        "  epochs: 20\n"
        "  out_dir: ${paths.data_dir}/runs/${oc.env:USER,anon}\n"
        "optimizer:\n"
        "  lr: 0.01\n",
    )
    return root


# -- the worked example --------------------------------------------------------


def test_worked_example_composes_and_traces(
    conf: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("USER", "awhite48")
    run = compose_traced(
        conf / "run.yaml",
        schema=RunSpec,
        profile="dev",
        overlays=[
            conf / "big.yaml",
            {
                "model": {
                    "combinator_decoders": {"bwd": {"kind": "linear", "bias": False}}
                }
            },
        ],
        overrides=[
            "model.type_encoder.num_heads=16",
            "optimizer.betas=[0.8, 0.95]",
            ("optimizer.lr", 0.1),
        ],
    )
    spec = run.value
    assert spec.model.type_encoder == TransformerEncoder(num_heads=16, width=1024)
    assert spec.trainer.epochs == 1
    assert spec.trainer.out_dir == "/data/ccg/runs/awhite48"
    assert spec.trainer.log_dir == "/data/ccg/runs/awhite48/logs"
    assert spec.optimizer == Adam(lr=0.1, betas=(0.8, 0.95))
    assert spec.model.combinator_decoders == {
        "fwd": LinearDecoder(),
        "bwd": LinearDecoder(bias=False),
    }
    p = run.provenance
    assert p["model.type_encoder.kind"].label == "group:model.type_encoder=transformer"
    assert (
        p["model.type_encoder.num_heads"].label
        == "override:model.type_encoder.num_heads=16"
    )
    assert p["model.type_encoder.width"].label == "overlay:big.yaml"
    assert (
        p["model.combinator_decoders.fwd.kind"].label
        == "group:model.combinator_decoders.fwd=linear"
    )
    assert p["model.combinator_decoders.bwd.bias"].label == "overlay:#1"
    assert p["trainer.epochs"].label == "profile:dev"
    assert p["trainer.out_dir"].kind == "file"
    assert (
        p["trainer.out_dir"].expression == "${paths.data_dir}/runs/${oc.env:USER,anon}"
    )
    assert p["trainer.log_dir"].label == "default"
    assert p["optimizer.kind"].label == "default"
    assert p["optimizer.lr"].label == "override:optimizer.lr=0.1"
    assert p["optimizer.betas"].label == "override:optimizer.betas=[0.8, 0.95]"
    assert p["paths.data_dir"].label == "defaults:paths"
    assert set(p.paths) == {
        "model.type_encoder.kind",
        "model.type_encoder.num_heads",
        "model.type_encoder.width",
        "model.type_encoder.declared_output",
        "model.combinator_decoders.fwd.kind",
        "model.combinator_decoders.fwd.temperature",
        "model.combinator_decoders.fwd.bias",
        "model.combinator_decoders.bwd.kind",
        "model.combinator_decoders.bwd.temperature",
        "model.combinator_decoders.bwd.bias",
        "optimizer.kind",
        "optimizer.lr",
        "optimizer.betas",
        "trainer.epochs",
        "trainer.out_dir",
        "trainer.log_dir",
        "paths.data_dir",
        "encoders",
    }


def test_sweep_over_groups_and_overrides(conf: Path) -> None:
    runs = [
        compose(
            conf / "run.yaml",
            schema=RunSpec,
            groups={"model.type_encoder": enc},
            overrides=[("optimizer.lr", lr)],
        )
        for enc, lr in product(("transformer", "lstm"), (1e-3, 1e-2))
    ]
    assert len(runs) == 4
    assert (
        len({(type(r.model.type_encoder).__name__, r.optimizer.lr) for r in runs}) == 4
    )
    assert isinstance(runs[0].model.type_encoder, TransformerEncoder)
    assert runs[0].optimizer.lr == 1e-3
    assert isinstance(runs[3].model.type_encoder, LstmEncoder)
    assert runs[3].optimizer.lr == 1e-2


# -- selection spellings -------------------------------------------------------


def test_defaults_string_entry_merges_at_the_root(conf: Path) -> None:
    run = compose_traced(conf / "run.yaml", schema=RunSpec)
    assert run.value.paths == {"data_dir": "/data/ccg"}
    origin = run.provenance["paths.data_dir"]
    assert origin.kind == "defaults"
    assert origin.name == "paths"
    assert origin.path == str(conf / "paths.yaml")


def test_defaults_mapping_entry_mounts_the_fragment_at_the_slot(conf: Path) -> None:
    run = compose_traced(conf / "run.yaml", schema=RunSpec)
    assert run.value.model.type_encoder == TransformerEncoder(num_heads=8)
    origin = run.provenance["model.type_encoder.num_heads"]
    assert origin.kind == "group"
    assert origin.name == "model.type_encoder=transformer"
    assert origin.path == str(conf / "model" / "type_encoder" / "transformer.yaml")


def test_hydra_slash_spelling_in_defaults_is_normalised(conf: Path) -> None:
    cfg = _write(
        conf / "slash.yaml",
        "defaults:\n  - model/type_encoder: lstm\n",
    )
    run = compose_traced(cfg, schema=RunSpec)
    assert run.value.model.type_encoder == LstmEncoder()
    assert (
        run.provenance["model.type_encoder.kind"].label
        == "group:model.type_encoder=lstm"
    )


def test_null_defaults_entry_selects_nothing(conf: Path) -> None:
    cfg = _write(conf / "none.yaml", "defaults:\n  - model.type_encoder: null\n")
    spec = compose(cfg, schema=RunSpec)
    assert spec.model.type_encoder is None


def test_groups_argument_replaces_the_files_choice_in_place(conf: Path) -> None:
    run = compose_traced(
        conf / "run.yaml", schema=RunSpec, groups={"model.type_encoder": "lstm"}
    )
    assert run.value.model.type_encoder == LstmEncoder()
    assert (
        run.provenance["model.type_encoder.kind"].label
        == "group:model.type_encoder=lstm"
    )
    # the replaced fragment's keys never reach the tree
    assert "model.type_encoder.num_heads" not in run.provenance
    assert subtree(run.tree, "model", "type_encoder") == {"kind": "lstm"}
    # the table keeps its position: ``paths`` is still the first layer applied
    kinds = [layer.origin.label for layer in run.layers]
    assert kinds.index("defaults:paths") < kinds.index("group:model.type_encoder=lstm")
    assert kinds.index("group:model.type_encoder=lstm") < kinds.index(
        "group:model.combinator_decoders.fwd=linear"
    )


def test_groups_argument_appends_a_slot_the_file_did_not_choose(conf: Path) -> None:
    cfg = _write(conf / "bare.yaml", "trainer:\n  epochs: 3\n")
    run = compose_traced(cfg, schema=RunSpec, groups={"trainer": "fast"})
    assert run.value.trainer.epochs == 3
    assert run.value.trainer.out_dir == "fast"
    assert run.provenance["trainer.epochs"].label == "file:bare.yaml"
    assert run.provenance["trainer.out_dir"].label == "group:trainer=fast"


def test_groups_argument_none_deselects_a_slot(conf: Path) -> None:
    spec = compose(
        conf / "run.yaml", schema=RunSpec, groups={"model.type_encoder": None}
    )
    assert spec.model.type_encoder is None


def test_slash_override_selects_a_group_and_never_reaches_the_merge(conf: Path) -> None:
    run = compose_traced(
        conf / "run.yaml",
        schema=RunSpec,
        overrides=["model/type_encoder=lstm", "model.type_encoder.hidden=64"],
    )
    assert run.value.model.type_encoder == LstmEncoder(hidden=64)
    assert (
        run.provenance["model.type_encoder.kind"].label
        == "group:model.type_encoder=lstm"
    )
    assert not any(
        layer.origin.name == "model/type_encoder=lstm" for layer in run.layers
    )


def test_slash_override_beats_groups_argument_for_the_same_slot(conf: Path) -> None:
    spec = compose(
        conf / "run.yaml",
        schema=RunSpec,
        groups={"model.type_encoder": "transformer"},
        overrides=["model/type_encoder=lstm"],
    )
    assert spec.model.type_encoder == LstmEncoder()


# -- precedence ----------------------------------------------------------------


def test_fragment_sits_above_base_and_below_the_file_body(conf: Path) -> None:
    cfg = _write(
        conf / "layered.yaml",
        "defaults:\n  - trainer: fast\ntrainer:\n  epochs: 5\n",
    )
    run = compose_traced(
        cfg,
        schema=RunSpec,
        base={"trainer": {"epochs": 99, "out_dir": "base", "log_dir": "base/logs"}},
    )
    assert run.value.trainer.epochs == 5
    assert run.value.trainer.out_dir == "fast"
    assert run.value.trainer.log_dir == "base/logs"
    assert run.provenance["trainer.epochs"].label == "file:layered.yaml"
    assert run.provenance["trainer.out_dir"].label == "group:trainer=fast"
    assert run.provenance["trainer.log_dir"].label == "base"


def test_reselecting_a_slot_replaces_rather_than_merges_over(conf: Path) -> None:
    # the file chooses transformer (kind + num_heads); groups= re-chooses
    # transformer again after an in-place edit, so the old keys do not linger
    _write(
        conf / "model" / "type_encoder" / "wide.yaml", "kind: transformer\nwidth: 512\n"
    )
    run = compose_traced(
        conf / "run.yaml", schema=RunSpec, groups={"model.type_encoder": "wide"}
    )
    assert run.value.model.type_encoder == TransformerEncoder(width=512)
    assert run.provenance["model.type_encoder.num_heads"].label == "default"


# -- fragment contents ---------------------------------------------------------


def test_unknown_key_in_a_fragment_is_refused_with_the_full_path(conf: Path) -> None:
    _write(conf / "model" / "type_encoder" / "bad.yaml", "kind: lstm\nbogus: 1\n")
    with pytest.raises(UnknownKeyError) as info:
        compose(conf / "run.yaml", schema=RunSpec, groups={"model.type_encoder": "bad"})
    e = info.value
    assert e.path == "model.type_encoder.bogus"
    assert e.set_by is not None
    assert e.set_by.label == "group:model.type_encoder=bad"
    assert "(set by group:model.type_encoder=bad)" in str(e)


def test_fragment_carrying_defaults_is_refused_as_an_unknown_key(conf: Path) -> None:
    _write(
        conf / "model" / "type_encoder" / "nested.yaml",
        "defaults:\n  - other\nkind: lstm\n",
    )
    with pytest.raises(UnknownKeyError) as info:
        compose(
            conf / "run.yaml", schema=RunSpec, groups={"model.type_encoder": "nested"}
        )
    assert info.value.path == "model.type_encoder.defaults"
    assert info.value.set_by is not None
    assert info.value.set_by.label == "group:model.type_encoder=nested"


def test_toml_and_json_fragments_are_supported(conf: Path) -> None:
    # ``run.yaml`` sets ``trainer.out_dir`` in its body, which beats the
    # fragment; a primary file that leaves the slot alone shows the fragment
    cfg = _write(
        conf / "fragments.yaml",
        "defaults:\n  - model.combinator_decoders.fwd: linear\n",
    )
    run = compose_traced(
        cfg,
        schema=RunSpec,
        groups={"model.combinator_decoders.fwd": "mlp", "trainer": "fast"},
    )
    assert run.value.model.combinator_decoders["fwd"] == MlpDecoder(hidden=8)
    assert run.value.trainer.out_dir == "fast"
    assert run.provenance["model.combinator_decoders.fwd.hidden"].path == str(
        conf / "model" / "combinator_decoders" / "fwd" / "mlp.toml"
    )
    assert run.provenance["trainer.out_dir"].path == str(conf / "trainer" / "fast.json")


def test_fragment_expressions_resolve_against_the_whole_tree(conf: Path) -> None:
    _write(conf / "trainer" / "data.yaml", "out_dir: ${paths.data_dir}/out\n")
    # the fragment sits below the file body, so the primary file must not set
    # ``trainer.out_dir`` itself; ``paths`` comes from the root fragment
    cfg = _write(conf / "exprs.yaml", "defaults:\n  - paths\n")
    run = compose_traced(cfg, schema=RunSpec, groups={"trainer": "data"})
    assert run.value.trainer.out_dir == "/data/ccg/out"
    origin = run.provenance["trainer.out_dir"]
    assert origin.label == "group:trainer=data"
    assert origin.expression == "${paths.data_dir}/out"


def test_slot_through_a_map_key_mounts_at_the_entry(conf: Path) -> None:
    run = compose_traced(conf / "run.yaml", schema=RunSpec)
    assert run.value.model.combinator_decoders["fwd"] == LinearDecoder()
    assert (
        run.provenance["model.combinator_decoders.fwd.kind"].label
        == "group:model.combinator_decoders.fwd=linear"
    )
    assert (
        run.provenance["model.combinator_decoders.fwd.temperature"].label == "default"
    )


def test_fragment_body_must_be_a_mapping(conf: Path) -> None:
    bad = _write(conf / "model" / "type_encoder" / "list.yaml", "- kind\n")
    with pytest.raises(ConfigError) as info:
        compose(
            conf / "run.yaml", schema=RunSpec, groups={"model.type_encoder": "list"}
        )
    assert str(info.value) == f"Top-level config in {bad} must be a mapping; got list"


def test_slot_not_in_the_schema_falls_out_of_the_merge(conf: Path) -> None:
    _write(conf / "model" / "type_encodr" / "lstm.yaml", "kind: lstm\n")
    with pytest.raises(UnknownKeyError) as info:
        compose(conf / "run.yaml", schema=RunSpec, groups={"model.type_encodr": "lstm"})
    assert info.value.path == "model.type_encodr"
    assert "(set by group:model.type_encodr=lstm)" in str(info.value)


# -- search path and shadowing -------------------------------------------------


def test_missing_fragment_lists_every_path_tried_and_the_available_names(
    conf: Path, tmp_path: Path
) -> None:
    site = tmp_path / "site"
    _write(site / "model" / "type_encoder" / "gru.yaml", "kind: gru\n")
    with pytest.raises(MissingFragmentError) as info:
        compose(
            conf / "run.yaml",
            schema=RunSpec,
            groups={"model.type_encoder": "rnn"},
            search_path=[site],
        )
    e = info.value
    assert e.group == "model.type_encoder"
    assert e.name == "rnn"
    assert e.available == ("gru", "lstm", "transformer")
    group = conf / "model" / "type_encoder"
    site_group = site / "model" / "type_encoder"
    assert e.tried == (
        group / "rnn.yaml",
        group / "rnn.yml",
        group / "rnn.toml",
        group / "rnn.json",
        site_group / "rnn.yaml",
        site_group / "rnn.yml",
        site_group / "rnn.toml",
        site_group / "rnn.json",
    )
    assert str(e) == (
        "Config group 'model.type_encoder' has no fragment 'rnn'; tried: "
        + ", ".join(str(t) for t in e.tried)
        + "; available: ['gru', 'lstm', 'transformer']"
    )


def test_fragment_name_is_searched_across_every_root(
    conf: Path, tmp_path: Path
) -> None:
    # the project root holds the group directory but not this name; the
    # packaged root supplies it
    site = tmp_path / "site"
    _write(site / "model" / "type_encoder" / "gru.yaml", "kind: gru\ndropout: 0.5\n")
    run = compose_traced(
        conf / "run.yaml",
        schema=RunSpec,
        groups={"model.type_encoder": "gru"},
        search_path=[site],
    )
    assert run.value.model.type_encoder is not None
    assert run.value.model.type_encoder.kind == "gru"
    assert run.provenance["model.type_encoder.dropout"].path == str(
        site / "model" / "type_encoder" / "gru.yaml"
    )


def test_earliest_root_shadows_a_fragment_of_the_same_name(
    conf: Path, tmp_path: Path
) -> None:
    site = tmp_path / "site"
    _write(site / "model" / "type_encoder" / "lstm.yaml", "kind: lstm\nhidden: 999\n")
    run = compose_traced(
        conf / "run.yaml",
        schema=RunSpec,
        groups={"model.type_encoder": "lstm"},
        search_path=[site],
    )
    assert run.value.model.type_encoder == LstmEncoder()
    assert run.provenance["model.type_encoder.kind"].path == str(
        conf / "model" / "type_encoder" / "lstm.yaml"
    )
    # reversed roots: the project root is still first because it holds the
    # primary file; an explicit search_path root can only shadow a later one
    other = tmp_path / "other"
    _write(other / "model" / "type_encoder" / "gru.yaml", "kind: gru\ndropout: 0.1\n")
    _write(site / "model" / "type_encoder" / "gru.yaml", "kind: gru\ndropout: 0.9\n")
    run2 = compose_traced(
        conf / "run.yaml",
        schema=RunSpec,
        groups={"model.type_encoder": "gru"},
        search_path=[other, site],
    )
    assert subtree(run2.tree, "model", "type_encoder") == {
        "kind": "gru",
        "dropout": 0.1,
    }


def test_group_directory_in_no_root_is_reported_with_the_roots_searched(
    conf: Path, tmp_path: Path
) -> None:
    site = tmp_path / "site"
    site.mkdir()
    with pytest.raises(MissingFragmentError) as info:
        compose(
            conf / "run.yaml",
            schema=RunSpec,
            groups={"model.type_encodr": "lstm"},
            search_path=[site],
        )
    assert str(info.value) == (
        f"Config group 'model.type_encodr' not found; searched: {conf}, {site}"
    )


def test_ambiguous_fragment_stems_are_refused(conf: Path) -> None:
    _write(conf / "model" / "type_encoder" / "lstm.toml", 'kind = "lstm"\n')
    with pytest.raises(ConfigError) as info:
        compose(
            conf / "run.yaml", schema=RunSpec, groups={"model.type_encoder": "lstm"}
        )
    assert str(info.value) == (
        "Fragment 'lstm' of config group 'model.type_encoder' is ambiguous: "
        "lstm.toml, lstm.yaml"
    )


def test_missing_root_fragment_lists_every_path_tried(
    conf: Path, tmp_path: Path
) -> None:
    site = tmp_path / "site"
    site.mkdir()
    cfg = _write(conf / "missing.yaml", "defaults:\n  - base\n")
    with pytest.raises(MissingFragmentError) as info:
        compose(cfg, schema=RunSpec, search_path=[site])
    assert str(info.value) == (
        "'defaults' entry 'base' not found; tried: "
        f"{conf / 'base.yaml'}, {conf / 'base.yml'}, {conf / 'base.toml'}, "
        f"{conf / 'base.json'}, {site / 'base.yaml'}, {site / 'base.yml'}, "
        f"{site / 'base.toml'}, {site / 'base.json'}"
    )


def test_selection_without_any_root_needs_a_config_directory() -> None:
    with pytest.raises(ConfigError) as info:
        compose(schema=RunSpec, groups={"model.type_encoder": "transformer"})
    assert str(info.value) == (
        "Config group selection 'model.type_encoder=transformer' needs a config "
        "directory; pass path= or search_path="
    )


def test_selection_with_search_path_but_no_primary_file(conf: Path) -> None:
    spec = compose(
        schema=RunSpec, groups={"model.type_encoder": "lstm"}, search_path=[conf]
    )
    assert spec.model.type_encoder == LstmEncoder()


# -- malformed defaults entries ------------------------------------------------


def test_defaults_entry_of_the_wrong_shape_is_refused(conf: Path) -> None:
    cfg = _write(conf / "shape.yaml", "defaults:\n  - paths\n  - [a, b]\n")
    with pytest.raises(ConfigError) as info:
        compose(cfg, schema=RunSpec)
    assert str(info.value) == (
        f"'defaults' entry 2 in {cfg} must be a file name or a one-key "
        "{slot: name} mapping; got list"
    )


def test_defaults_entry_with_a_non_string_name_is_refused(conf: Path) -> None:
    cfg = _write(conf / "shape.yaml", "defaults:\n  - model.type_encoder: 3\n")
    with pytest.raises(ConfigError) as info:
        compose(cfg, schema=RunSpec)
    assert str(info.value) == (
        f"'defaults' entry 'model.type_encoder' in {cfg} must name a fragment "
        "as a string or null; got int"
    )


# -- the ``defaults`` key --------------------------------------------------------


class _WithDefaultsField(dx.Model, extra="forbid"):
    """A schema that declares a field spelled ``defaults``."""

    name: str = ""
    defaults: tuple[str, ...] = ()


def test_defaults_in_the_primary_file_is_always_the_selection_list(
    tmp_path: Path,
) -> None:
    # bead strips ``defaults`` from the primary file unconditionally; the
    # engine keeps that rule even when the schema declares such a field, so
    # the field can only be set from another layer
    _write(tmp_path / "base.yaml", "name: from_base\n")
    cfg = _write(tmp_path / "primary.yaml", "defaults:\n  - base\n")
    run = compose_traced(cfg, schema=_WithDefaultsField)
    assert run.value.name == "from_base"
    assert run.value.defaults == ()
    assert run.provenance["defaults"].label == "default"
    run2 = compose_traced(
        cfg, schema=_WithDefaultsField, overrides=['defaults=["x", "y"]']
    )
    assert run2.value.defaults == ("x", "y")
    assert run2.provenance["defaults"].label == 'override:defaults=["x", "y"]'


def test_defaults_in_an_overlay_is_an_ordinary_key(tmp_path: Path) -> None:
    # for a schema that declares the field, an overlay sets it
    overlay = _write(tmp_path / "overlay.yaml", "defaults:\n  - z\n")
    run = compose_traced(schema=_WithDefaultsField, overlays=[overlay])
    assert run.value.defaults == ("z",)
    assert run.provenance["defaults"].label == "overlay:overlay.yaml"
    # for a schema that does not, it is refused as unknown
    with pytest.raises(UnknownKeyError) as info:
        compose(schema=RunSpec, overlays=[overlay])
    assert info.value.path == "defaults"
    assert info.value.set_by is not None
    assert info.value.set_by.label == "overlay:overlay.yaml"


def test_defaults_in_a_profile_is_an_ordinary_key(tmp_path: Path) -> None:
    _write(tmp_path / "profiles" / "dev.yaml", "defaults:\n  - z\n")
    with pytest.raises(UnknownKeyError) as info:
        compose(schema=RunSpec, profile="dev", search_path=[tmp_path])
    assert info.value.path == "defaults"
    assert info.value.set_by is not None
    assert info.value.set_by.label == "profile:dev"
    spec = compose(schema=_WithDefaultsField, profile="dev", search_path=[tmp_path])
    assert spec.defaults == ("z",)
