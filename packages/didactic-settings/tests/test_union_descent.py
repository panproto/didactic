"""Descent into tagged unions during composition.

Every case composes a LoFI-shaped tree (``_schemas.RunSpec``) and pins the
merge, settle and provenance behaviour the engine owes bead and LoFI: the
variant is selected by the incoming or accumulated tag, a field default
selects a variant only at settle, unknown keys are refused at every depth
with the variant that declares them named, and provenance reaches every
leaf below the union.

This module deliberately omits ``from __future__ import annotations``;
see ``_schemas.py``.
"""

import json
from pathlib import Path
from typing import Literal

import pytest

import didactic.api as dx
from didactic.settings import (
    ConfigError,
    UnknownKeyError,
    UnknownVariantError,
    compose,
    compose_traced,
)

from ._schemas import (
    Adam,
    AdditiveAttention,
    DotAttention,
    GruEncoder,
    LinearDecoder,
    LstmEncoder,
    MlpDecoder,
    Pipeline,
    RunSpec,
    Sgd,
    StageTwo,
    TransformerEncoder,
    subtree,
)


def _write(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


# -- (a) tag read first, selected mode, per-leaf provenance ------------------


def test_a_selected_variant_from_file_through_optional_slot(tmp_path: Path) -> None:
    cfg = _write(
        tmp_path / "run.yaml",
        "model:\n  type_encoder:\n    kind: transformer\n    num_heads: 8\n",
    )
    run = compose_traced(cfg, schema=RunSpec)
    enc = run.value.model.type_encoder
    assert isinstance(enc, TransformerEncoder)
    assert enc.num_heads == 8
    assert enc.width == 256
    p = run.provenance
    assert p["model.type_encoder.kind"].label == "file:run.yaml"
    assert p["model.type_encoder.kind"].path == str(cfg)
    assert p["model.type_encoder.num_heads"].label == "file:run.yaml"
    assert p["model.type_encoder.width"].label == "default"
    assert run.tree["model"] == {
        "type_encoder": {"kind": "transformer", "num_heads": 8},
        "combinator_decoders": {},
    }


def test_a_discriminator_is_read_before_sibling_keys(tmp_path: Path) -> None:
    cfg = _write(
        tmp_path / "run.yaml",
        "model:\n  type_encoder:\n    hidden: 3\n    kind: lstm\n",
    )
    spec = compose(cfg, schema=RunSpec)
    assert spec.model.type_encoder == LstmEncoder(hidden=3)


# -- (b) provisional mode on a root-shared field, default variant at settle --


def test_b_root_shared_field_without_tag_settles_to_default_variant(
    tmp_path: Path,
) -> None:
    cfg = _write(tmp_path / "run.yaml", "optimizer:\n  lr: 0.01\n")
    run = compose_traced(cfg, schema=RunSpec)
    assert run.value.optimizer == Adam(lr=0.01)
    assert run.tree["optimizer"] == {"kind": "adam", "lr": 0.01}
    p = run.provenance
    assert p["optimizer.kind"].label == "default"
    assert p["optimizer.lr"].label == "file:run.yaml"
    assert p["optimizer.betas"].label == "default"


def test_b_variant_private_field_under_default_variant_is_refused_at_settle(
    tmp_path: Path,
) -> None:
    cfg = _write(tmp_path / "run.yaml", "optimizer:\n  momentum: 0.5\n")
    with pytest.raises(UnknownKeyError) as info:
        compose(cfg, schema=RunSpec)
    e = info.value
    assert e.path == "optimizer.momentum"
    assert e.declared_by == ("sgd",)
    assert e.set_by is not None
    assert e.set_by.label == "file:run.yaml"
    assert str(e) == (
        "Unknown config key 'optimizer.momentum' (set by file:run.yaml): "
        "variant 'adam' of OptimizerSpec (selected by default) has no field "
        "'momentum'; it belongs to variant 'sgd'"
    )


def test_b_provisional_field_then_tag_and_reverse_agree(tmp_path: Path) -> None:
    field_layer = _write(tmp_path / "field.yaml", "optimizer:\n  momentum: 0.5\n")
    tag_layer = _write(tmp_path / "tag.yaml", "optimizer:\n  kind: sgd\n")
    forward = compose_traced(
        schema=RunSpec, overlays=[field_layer, tag_layer], search_path=[tmp_path]
    )
    backward = compose_traced(
        schema=RunSpec, overlays=[tag_layer, field_layer], search_path=[tmp_path]
    )
    assert forward.value == backward.value
    assert forward.value.optimizer == backward.value.optimizer == Sgd(momentum=0.5)
    assert forward.tree == backward.tree
    assert forward.provenance == backward.provenance
    assert forward.provenance["optimizer.momentum"].label == "overlay:field.yaml"
    assert forward.provenance["optimizer.kind"].label == "overlay:tag.yaml"


def test_b_conflicting_variant_field_then_tag_is_refused_in_both_orders(
    tmp_path: Path,
) -> None:
    field_layer = _write(
        tmp_path / "field.yaml", "model:\n  type_encoder:\n    num_heads: 2\n"
    )
    tag_layer = _write(
        tmp_path / "tag.yaml", "model:\n  type_encoder:\n    kind: lstm\n"
    )
    expected = (
        "Unknown config key 'model.type_encoder.num_heads' "
        "(set by overlay:field.yaml): variant 'lstm' of TypeEncoderSpec "
        "(set by overlay:tag.yaml) has no field 'num_heads'; "
        "it belongs to variant 'transformer'"
    )
    # field first: the provisional merge accepts it and settle refuses it
    with pytest.raises(UnknownKeyError) as forward:
        compose(schema=RunSpec, overlays=[field_layer, tag_layer])
    assert str(forward.value) == expected
    assert forward.value.path == "model.type_encoder.num_heads"
    assert forward.value.declared_by == ("transformer",)
    # tag first: the second layer is refused at merge time
    with pytest.raises(UnknownKeyError) as backward:
        compose(schema=RunSpec, overlays=[tag_layer, field_layer])
    assert str(backward.value) == expected
    assert backward.value.path == "model.type_encoder.num_heads"
    assert backward.value.declared_by == ("transformer",)


# -- (c) no tag and no default variant: refused at settle, naming the origin --


def test_c_tagless_optional_slot_is_refused_at_settle_with_origin(
    tmp_path: Path,
) -> None:
    cfg = _write(tmp_path / "run.yaml", "model:\n  type_encoder:\n    num_heads: 8\n")
    with pytest.raises(ConfigError) as info:
        compose(cfg, schema=RunSpec)
    e = info.value
    assert e.path == "model.type_encoder"
    assert str(e) == (
        "Config key 'model.type_encoder' selects no variant of TypeEncoderSpec "
        "(set by file:run.yaml): set model.type_encoder.kind to one of "
        "['gru', 'lstm', 'transformer']"
    )


def test_c_tagless_map_entry_is_refused_at_settle_with_origin(tmp_path: Path) -> None:
    cfg = _write(
        tmp_path / "run.yaml",
        "model:\n  combinator_decoders:\n    fwd:\n      bias: false\n",
    )
    with pytest.raises(ConfigError) as info:
        compose(cfg, schema=RunSpec)
    e = info.value
    assert e.path == "model.combinator_decoders.fwd"
    assert str(e) == (
        "Config key 'model.combinator_decoders.fwd' selects no variant of DecoderSpec "
        "(set by file:run.yaml): set model.combinator_decoders.fwd.kind to one of "
        "['linear', 'mlp']"
    )


def test_c_tagless_override_on_optional_slot_names_the_override(
    tmp_path: Path,
) -> None:
    with pytest.raises(ConfigError) as info:
        compose(schema=RunSpec, overrides=["model.type_encoder.num_heads=8"])
    assert info.value.path == "model.type_encoder"
    assert "(set by override:model.type_encoder.num_heads=8)" in str(info.value)
    assert "selects no variant of TypeEncoderSpec" in str(info.value)


# -- (d) selected mode refuses another variant's field ------------------------


def test_d_other_variants_field_is_refused_naming_its_owner(tmp_path: Path) -> None:
    cfg = _write(
        tmp_path / "run.yaml", "model:\n  type_encoder:\n    kind: transformer\n"
    )
    with pytest.raises(UnknownKeyError) as info:
        compose(cfg, schema=RunSpec, overrides=["model.type_encoder.hidden=3"])
    e = info.value
    assert e.path == "model.type_encoder.hidden"
    assert e.declared_by == ("lstm",)
    assert e.allowed == ("kind", "num_heads", "width")
    assert e.set_by is not None
    assert e.set_by.kind == "override"
    assert e.set_by.name == "model.type_encoder.hidden=3"
    assert str(e) == (
        "Unknown config key 'model.type_encoder.hidden' "
        "(set by override:model.type_encoder.hidden=3): "
        "variant 'transformer' of TypeEncoderSpec (set by file:run.yaml) "
        "has no field 'hidden'; it belongs to variant 'lstm'"
    )


def test_d_key_no_variant_declares_lists_every_field(tmp_path: Path) -> None:
    cfg = _write(
        tmp_path / "run.yaml",
        "model:\n  type_encoder:\n    kind: transformer\n    bogus: 1\n",
    )
    with pytest.raises(UnknownKeyError) as info:
        compose(cfg, schema=RunSpec)
    e = info.value
    assert e.path == "model.type_encoder.bogus"
    assert e.declared_by == ()
    assert str(e) == (
        "Unknown config key 'model.type_encoder.bogus' (set by file:run.yaml); "
        "no variant of TypeEncoderSpec declares it; allowed: "
        "['attention', 'dropout', 'head', 'hidden', 'kind', 'num_heads', 'width']"
    )


def test_d_key_declared_by_several_variants_is_listed_in_plural(
    tmp_path: Path,
) -> None:
    cfg = _write(
        tmp_path / "run.yaml",
        "model:\n  type_encoder:\n    kind: transformer\n    dropout: 0.2\n",
    )
    with pytest.raises(UnknownKeyError) as info:
        compose(cfg, schema=RunSpec)
    e = info.value
    assert e.path == "model.type_encoder.dropout"
    assert e.declared_by == ("gru", "lstm")
    assert str(e) == (
        "Unknown config key 'model.type_encoder.dropout' (set by file:run.yaml): "
        "variant 'transformer' of TypeEncoderSpec (set by file:run.yaml) "
        "has no field 'dropout'; it belongs to variants 'gru', 'lstm'"
    )


# -- (e) textual override against a tag already in the tree -------------------


def test_e_textual_override_is_checked_against_the_accumulated_tag(
    tmp_path: Path,
) -> None:
    cfg = _write(tmp_path / "run.yaml", "model:\n  type_encoder:\n    kind: lstm\n")
    with pytest.raises(UnknownKeyError) as info:
        compose(cfg, schema=RunSpec, overrides=["model.type_encoder.num_heads=8"])
    e = info.value
    assert e.path == "model.type_encoder.num_heads"
    assert e.declared_by == ("transformer",)
    assert str(e) == (
        "Unknown config key 'model.type_encoder.num_heads' "
        "(set by override:model.type_encoder.num_heads=8): "
        "variant 'lstm' of TypeEncoderSpec (set by file:run.yaml) "
        "has no field 'num_heads'; it belongs to variant 'transformer'"
    )


def test_e_textual_override_decodes_by_the_selected_variants_annotation(
    tmp_path: Path,
) -> None:
    cfg = _write(tmp_path / "run.yaml", "model:\n  type_encoder:\n    kind: lstm\n")
    run = compose_traced(
        cfg, schema=RunSpec, overrides=["model.type_encoder.hidden=64"]
    )
    assert run.value.model.type_encoder == LstmEncoder(hidden=64)
    assert subtree(run.tree, "model", "type_encoder") == {"kind": "lstm", "hidden": 64}
    assert (
        run.provenance["model.type_encoder.hidden"].label
        == "override:model.type_encoder.hidden=64"
    )


def test_e_override_order_tag_then_field_is_accepted_and_reverse_refused(
    tmp_path: Path,
) -> None:
    cfg = _write(
        tmp_path / "run.yaml", "model:\n  type_encoder:\n    kind: transformer\n"
    )
    spec = compose(
        cfg,
        schema=RunSpec,
        overrides=["model.type_encoder.kind=lstm", "model.type_encoder.hidden=64"],
    )
    assert spec.model.type_encoder == LstmEncoder(hidden=64)
    with pytest.raises(UnknownKeyError) as info:
        compose(
            cfg,
            schema=RunSpec,
            overrides=["model.type_encoder.hidden=64", "model.type_encoder.kind=lstm"],
        )
    assert info.value.declared_by == ("lstm",)
    assert "variant 'transformer' of TypeEncoderSpec (set by file:run.yaml)" in str(
        info.value
    )


def test_e_json_text_override_at_a_union_slot_decodes_to_one_overlay(
    tmp_path: Path,
) -> None:
    run = compose_traced(
        schema=RunSpec,
        overrides=['model.type_encoder={"kind": "lstm", "hidden": 64}'],
    )
    assert run.value.model.type_encoder == LstmEncoder(hidden=64)
    label = 'override:model.type_encoder={"kind": "lstm", "hidden": 64}'
    assert run.provenance["model.type_encoder.kind"].label == label
    assert run.provenance["model.type_encoder.hidden"].label == label


# -- (f) nested targets inside a selected variant ------------------------------


def test_f_nested_model_and_union_inside_a_variant_are_stamped_per_leaf(
    tmp_path: Path,
) -> None:
    cfg = _write(
        tmp_path / "run.yaml",
        "model:\n"
        "  type_encoder:\n"
        "    kind: gru\n"
        "    head:\n"
        "      layers: 3\n"
        "    attention:\n"
        "      kind: additive\n"
        "      hidden: 16\n",
    )
    run = compose_traced(cfg, schema=RunSpec)
    enc = run.value.model.type_encoder
    assert isinstance(enc, GruEncoder)
    assert enc.head.layers == 3
    assert enc.head.dropout == 0.1
    assert enc.attention == AdditiveAttention(hidden=16)
    p = run.provenance
    assert p["model.type_encoder.kind"].label == "file:run.yaml"
    assert p["model.type_encoder.head.layers"].label == "file:run.yaml"
    assert p["model.type_encoder.head.dropout"].label == "default"
    assert p["model.type_encoder.attention.kind"].label == "file:run.yaml"
    assert p["model.type_encoder.attention.hidden"].label == "file:run.yaml"


def test_f_union_inside_a_variant_settles_from_the_variants_field_default(
    tmp_path: Path,
) -> None:
    cfg = _write(
        tmp_path / "run.yaml",
        "model:\n  type_encoder:\n    kind: gru\n    attention:\n      scale: 0.5\n",
    )
    run = compose_traced(cfg, schema=RunSpec)
    enc = run.value.model.type_encoder
    assert isinstance(enc, GruEncoder)
    assert enc.attention == DotAttention(scale=0.5)
    assert run.provenance["model.type_encoder.attention.kind"].label == "default"
    assert run.provenance["model.type_encoder.attention.scale"].label == "file:run.yaml"


def test_f_dotted_override_descends_two_unions_deep(tmp_path: Path) -> None:
    cfg = _write(tmp_path / "run.yaml", "model:\n  type_encoder:\n    kind: gru\n")
    spec = compose(
        cfg,
        schema=RunSpec,
        overrides=[
            "model.type_encoder.attention.kind=additive",
            "model.type_encoder.attention.hidden=8",
            "model.type_encoder.head.layers=2",
        ],
    )
    enc = spec.model.type_encoder
    assert isinstance(enc, GruEncoder)
    assert enc.attention == AdditiveAttention(hidden=8)
    assert enc.head.layers == 2
    with pytest.raises(UnknownKeyError) as info:
        compose(cfg, schema=RunSpec, overrides=["model.type_encoder.attention.bogus=1"])
    assert info.value.path == "model.type_encoder.attention.bogus"


# -- (g) unions as list elements ---------------------------------------------


def test_g_union_list_elements_are_checked_and_the_list_is_one_leaf(
    tmp_path: Path,
) -> None:
    cfg = _write(
        tmp_path / "run.yaml",
        "encoders:\n  - kind: lstm\n    hidden: 4\n  - kind: transformer\n",
    )
    run = compose_traced(cfg, schema=RunSpec)
    assert run.value.encoders == (LstmEncoder(hidden=4), TransformerEncoder())
    assert run.provenance["encoders"].label == "file:run.yaml"
    assert not [p for p in run.provenance.paths if p.startswith("encoders[")]


def test_g_unknown_key_inside_a_list_element_names_the_index(tmp_path: Path) -> None:
    cfg = _write(
        tmp_path / "run.yaml",
        "encoders:\n  - kind: lstm\n    bogus: 4\n",
    )
    with pytest.raises(UnknownKeyError) as info:
        compose(cfg, schema=RunSpec)
    assert info.value.path == "encoders[0].bogus"
    assert str(info.value).startswith("Unknown config key 'encoders[0].bogus'")


def test_g_tagless_list_element_passes_merge_and_fails_at_settle(
    tmp_path: Path,
) -> None:
    cfg = _write(tmp_path / "run.yaml", "encoders:\n  - hidden: 4\n")
    with pytest.raises(ConfigError) as info:
        compose(cfg, schema=RunSpec)
    assert info.value.path == "encoders[0]"
    assert str(info.value).startswith(
        "Config key 'encoders[0]' selects no variant of TypeEncoderSpec"
    )


def test_g_list_replaces_wholesale_across_layers(tmp_path: Path) -> None:
    first = _write(tmp_path / "first.yaml", "encoders:\n  - kind: lstm\n")
    second = _write(tmp_path / "second.yaml", "encoders:\n  - kind: transformer\n")
    run = compose_traced(schema=RunSpec, overlays=[first, second])
    assert run.value.encoders == (TransformerEncoder(),)
    assert run.provenance["encoders"].label == "overlay:second.yaml"


# -- computed fields on a variant --------------------------------------------


def test_computed_field_key_on_a_variant_is_accepted_and_labelled_default(
    tmp_path: Path,
) -> None:
    cfg = _write(
        tmp_path / "run.yaml",
        "model:\n  type_encoder:\n    kind: transformer\n    declared_output: 999\n",
    )
    run = compose_traced(cfg, schema=RunSpec)
    enc = run.value.model.type_encoder
    assert isinstance(enc, TransformerEncoder)
    assert enc.declared_output == 4 * 256
    assert "declared_output" not in subtree(run.tree, "model", "type_encoder")
    assert run.provenance["model.type_encoder.declared_output"].label == "default"


def test_recomposing_a_resolved_document_changes_nothing(tmp_path: Path) -> None:
    cfg = _write(
        tmp_path / "run.yaml",
        "model:\n"
        "  type_encoder:\n"
        "    kind: transformer\n"
        "    num_heads: 8\n"
        "  combinator_decoders:\n"
        "    fwd:\n"
        "      kind: linear\n"
        "optimizer:\n"
        "  kind: sgd\n"
        "paths:\n"
        "  data_dir: /d\n"
        "trainer:\n"
        "  out_dir: ${paths.data_dir}/runs\n",
    )
    once = compose(cfg, schema=RunSpec)
    dumped = json.loads(once.model_dump_json())
    assert dumped["model"]["type_encoder"]["declared_output"] == 8 * 256
    again = compose(schema=RunSpec, base=dumped)
    assert again == once


# -- integer discriminators delivered as text --------------------------------


def test_literal_int_discriminator_is_decoded_from_override_text() -> None:
    spec = compose(schema=Pipeline, overrides=["stage.code=2", "stage.b=5"])
    assert spec.stage == StageTwo(b=5)


def test_literal_int_discriminator_from_json_text_override() -> None:
    spec = compose(schema=Pipeline, overrides=['stage={"code": 2, "b": 7}'])
    assert spec.stage == StageTwo(b=7)


def test_literal_int_discriminator_unknown_text_lists_registered_tags() -> None:
    with pytest.raises(UnknownVariantError) as info:
        compose(schema=Pipeline, overrides=["stage.code=3"])
    e = info.value
    assert e.path == "stage.code"
    assert str(e.value) == "3"
    assert e.registered == ("1", "2")
    assert "Stage registers: ['1', '2']" in str(e)


# -- tags ---------------------------------------------------------------------


def test_unknown_tag_lists_registered_variants(tmp_path: Path) -> None:
    with pytest.raises(UnknownVariantError) as info:
        compose(schema=RunSpec, overrides=["model.type_encoder.kind=rnn"])
    e = info.value
    assert e.path == "model.type_encoder.kind"
    assert e.value == "rnn"
    assert e.registered == ("gru", "lstm", "transformer")
    assert str(e) == (
        "Unknown variant 'model.type_encoder.kind' = 'rnn' "
        "(set by override:model.type_encoder.kind=rnn); "
        "TypeEncoderSpec registers: ['gru', 'lstm', 'transformer']"
    )


def test_interpolated_tag_is_refused(tmp_path: Path) -> None:
    cfg = _write(
        tmp_path / "run.yaml",
        "paths:\n  enc: lstm\nmodel:\n  type_encoder:\n    kind: ${paths.enc}\n",
    )
    with pytest.raises(UnknownVariantError) as info:
        compose(cfg, schema=RunSpec)
    assert str(info.value) == (
        "Discriminator 'model.type_encoder.kind' is the interpolation "
        "'${paths.enc}' (set by file:run.yaml); a discriminator must be a "
        "literal value; select variants with a config group or an override"
    )


def test_non_scalar_tag_is_refused(tmp_path: Path) -> None:
    cfg = _write(
        tmp_path / "run.yaml",
        "model:\n  type_encoder:\n    kind:\n      name: lstm\n",
    )
    with pytest.raises(ConfigError, match=r"must be a scalar; got dict") as info:
        compose(cfg, schema=RunSpec)
    assert info.value.path == "model.type_encoder.kind"


def test_string_at_a_union_slot_is_refused(tmp_path: Path) -> None:
    cfg = _write(tmp_path / "run.yaml", "model:\n  type_encoder: lstm\n")
    with pytest.raises(ConfigError) as info:
        compose(cfg, schema=RunSpec)
    assert str(info.value) == (
        "Config key 'model.type_encoder' expects a mapping for TypeEncoderSpec "
        "(set by file:run.yaml); got str"
    )


def test_null_clears_an_optional_union_slot(tmp_path: Path) -> None:
    cfg = _write(
        tmp_path / "run.yaml",
        "model:\n  type_encoder:\n    kind: transformer\n    num_heads: 8\n",
    )
    run = compose_traced(
        cfg, schema=RunSpec, overlays=[{"model": {"type_encoder": None}}]
    )
    assert run.value.model.type_encoder is None
    assert run.provenance["model.type_encoder"].label == "overlay:#0"
    assert "model.type_encoder.kind" not in run.provenance
    assert "model.type_encoder.num_heads" not in run.provenance


def test_variant_switch_drops_the_old_variants_private_keys(tmp_path: Path) -> None:
    cfg = _write(
        tmp_path / "run.yaml",
        "model:\n  combinator_decoders:\n    fwd:\n"
        "      kind: linear\n      bias: false\n      temperature: 0.5\n",
    )
    run = compose_traced(
        cfg, schema=RunSpec, overrides=["model.combinator_decoders.fwd.kind=mlp"]
    )
    fwd = run.value.model.combinator_decoders["fwd"]
    assert fwd == MlpDecoder(temperature=0.5)
    assert subtree(run.tree, "model", "combinator_decoders", "fwd") == {
        "kind": "mlp",
        "temperature": 0.5,
    }
    p = run.provenance
    assert p["model.combinator_decoders.fwd.temperature"].label == "file:run.yaml"
    assert (
        p["model.combinator_decoders.fwd.kind"].label
        == "override:model.combinator_decoders.fwd.kind=mlp"
    )
    assert p["model.combinator_decoders.fwd.hidden"].label == "default"
    assert "model.combinator_decoders.fwd.bias" not in p


def test_variant_switch_keeps_fields_both_variants_declare(tmp_path: Path) -> None:
    cfg = _write(
        tmp_path / "run.yaml",
        "model:\n  type_encoder:\n    kind: lstm\n    hidden: 7\n    dropout: 0.2\n",
    )
    # ``dropout`` is declared by both lstm and gru and survives the switch;
    # ``hidden`` is lstm's alone and is dropped with its provenance
    run = compose_traced(cfg, schema=RunSpec, overrides=["model.type_encoder.kind=gru"])
    enc = run.value.model.type_encoder
    assert enc == GruEncoder(dropout=0.2)
    assert subtree(run.tree, "model", "type_encoder") == {"kind": "gru", "dropout": 0.2}
    p = run.provenance
    assert p["model.type_encoder.dropout"].label == "file:run.yaml"
    assert p["model.type_encoder.kind"].label == "override:model.type_encoder.kind=gru"
    assert "model.type_encoder.hidden" not in p
    # a root-shared field survives a switch between decoder variants
    cfg2 = _write(
        tmp_path / "run2.yaml",
        "model:\n  combinator_decoders:\n    fwd:\n"
        "      kind: mlp\n      temperature: 0.3\n",
    )
    spec2 = compose(
        cfg2, schema=RunSpec, overrides=["model.combinator_decoders.fwd.kind=linear"]
    )
    assert spec2.model.combinator_decoders["fwd"] == LinearDecoder(temperature=0.3)


def test_variants_registered_after_the_root_is_used_participate(
    tmp_path: Path,
) -> None:
    class LateRoot(dx.TaggedUnion, discriminator="kind", extra="forbid"):
        pass

    class Holder(dx.Model, extra="forbid"):
        slot: LateRoot | None = None

    with pytest.raises(UnknownVariantError, match="registers no variants") as info:
        compose(schema=Holder, overlays=[{"slot": {"kind": "late"}}])
    assert "load the plugins that define them before composing" in str(info.value)

    class Late(LateRoot):
        kind: Literal["late"] = "late"
        n: int = 1

    spec = compose(schema=Holder, overlays=[{"slot": {"kind": "late", "n": 2}}])
    assert spec.slot == Late(n=2)


def test_zero_variant_root_accepts_shared_fields_only() -> None:
    class SharedRoot(dx.TaggedUnion, discriminator="kind", extra="forbid"):
        label: str = ""

    class Holder(dx.Model, extra="forbid"):
        slot: SharedRoot | None = None

    with pytest.raises(UnknownVariantError, match="registers no variants") as info:
        compose(schema=Holder, overlays=[{"slot": {"label": "x", "n": 1}}])
    assert info.value.path == "slot.n"
    # shared fields alone pass the merge; settle then has no variant to select
    with pytest.raises(ConfigError, match="registers no variants"):
        compose(schema=Holder, overlays=[{"slot": {"label": "x"}}])


def test_provisional_target_conflict_asks_for_the_tag() -> None:
    class Root(dx.TaggedUnion, discriminator="kind", extra="forbid"):
        pass

    class A(Root):
        kind: Literal["a"] = "a"
        width: int = 1

    class B(Root):
        kind: Literal["b"] = "b"
        width: str = "wide"

    class Holder(dx.Model, extra="forbid"):
        slot: Root = dx.field(default_factory=A)

    with pytest.raises(ConfigError) as info:
        compose(schema=Holder, overrides=["slot.width=8"])
    assert str(info.value) == (
        "Config key 'slot.width' is declared by variants 'a' and 'b' of Root "
        "with different types; set slot.kind in the same or an earlier layer"
    )
    spec = compose(schema=Holder, overrides=["slot.kind=b", "slot.width=8"])
    assert spec.slot == B(width="8")


# -- plain-model rules that the union path shares ----------------------------


def test_extra_ignore_model_drops_unknown_keys_and_records_nothing() -> None:
    class Lenient(dx.Model, extra="ignore"):
        x: int = 0

    class Holder(dx.Model, extra="forbid"):
        inner: Lenient = dx.field(default_factory=Lenient)

    run = compose_traced(schema=Holder, overlays=[{"inner": {"x": 1, "junk": 2}}])
    assert run.value.inner.x == 1
    assert run.tree == {"inner": {"x": 1}}
    assert set(run.provenance.paths) == {"inner.x"}


def test_alias_keys_are_normalised_to_field_names() -> None:
    class Aliased(dx.Model, extra="forbid"):
        user_id: str = dx.field(alias="userId", default="")

    run = compose_traced(schema=Aliased, overlays=[{"userId": "u1"}])
    assert run.value.user_id == "u1"
    assert run.tree == {"user_id": "u1"}
    assert run.provenance["user_id"].label == "overlay:#0"
    assert "userId" not in run.provenance


def test_unknown_override_key_is_unknown_key_error_not_validation_error() -> None:
    with pytest.raises(UnknownKeyError) as info:
        compose(schema=RunSpec, overrides=["trainer.epoch=3"])
    assert not isinstance(info.value, dx.ValidationError)
    assert info.value.path == "trainer.epoch"
    assert info.value.allowed == ("epochs", "log_dir", "out_dir")
    assert str(info.value) == (
        "Unknown config key 'trainer.epoch' (set by override:trainer.epoch=3); "
        "allowed: ['epochs', 'log_dir', 'out_dir']"
    )


def test_union_selected_by_group_then_field_from_file_body(tmp_path: Path) -> None:
    group_dir = tmp_path / "model" / "type_encoder"
    group_dir.mkdir(parents=True)
    _write(group_dir / "transformer.yaml", "kind: transformer\nnum_heads: 8\n")
    cfg = _write(
        tmp_path / "run.yaml",
        "defaults:\n  - model.type_encoder: transformer\n"
        "model:\n  type_encoder:\n    width: 1024\n",
    )
    run = compose_traced(cfg, schema=RunSpec)
    assert run.value.model.type_encoder == TransformerEncoder(num_heads=8, width=1024)
    p = run.provenance
    assert p["model.type_encoder.kind"].label == "group:model.type_encoder=transformer"
    assert (
        p["model.type_encoder.num_heads"].label
        == "group:model.type_encoder=transformer"
    )
    assert p["model.type_encoder.width"].label == "file:run.yaml"


# -- default-variant edge cases ----------------------------------------------


def test_bare_root_instance_default_selects_no_variant() -> None:
    class Root(dx.TaggedUnion, discriminator="kind", extra="forbid"):
        lr: float = 1.0

    class Only(Root):
        kind: Literal["only"] = "only"

    class Holder(dx.Model, extra="forbid"):
        opt: Root = dx.field(default_factory=Root)

    with pytest.raises(ConfigError) as info:
        compose(schema=Holder, overlays=[{"opt": {"lr": 0.5}}])
    assert info.value.path == "opt"
    assert str(info.value) == (
        "Config key 'opt' selects no variant of Root (set by overlay:#0): "
        "set opt.kind to one of ['only']"
    )
    assert compose(schema=Holder, overlays=[{"opt": {"kind": "only"}}]).opt == Only()


def test_variant_with_several_literals_settles_to_its_first_tag() -> None:
    class Root(dx.TaggedUnion, discriminator="kind", extra="forbid"):
        pass

    class Both(Root):
        kind: Literal["a", "alpha"] = "a"
        n: int = 0

    class Holder(dx.Model, extra="forbid"):
        slot: Root = dx.field(default_factory=Both)

    run = compose_traced(schema=Holder, overlays=[{"slot": {"n": 3}}])
    assert run.tree == {"slot": {"kind": "a", "n": 3}}
    assert run.value.slot == Both(kind="a", n=3)
    assert run.provenance["slot.kind"].label == "default"
    aliased = compose(schema=Holder, overlays=[{"slot": {"kind": "alpha", "n": 3}}])
    assert aliased.slot == Both(kind="alpha", n=3)
    with pytest.raises(UnknownVariantError) as info:
        compose(schema=Holder, overlays=[{"slot": {"kind": "beta"}}])
    assert info.value.registered == ("a", "alpha")
