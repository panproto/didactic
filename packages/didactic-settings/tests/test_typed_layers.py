"""Typed layers are checked at the leaf, and expressions are typed after resolution.

A value that arrives typed (a file, a mapping, a ``(key, value)`` pair,
``Settings.load(**values)``, a resolver result) is checked against the
leaf annotation when it is written, so a wrong-typed value is refused as
``CoercionError`` with the leaf's path and the layer that set it, never
as a bare ``AssertionError`` from validation. Text that holds a
``${...}`` expression is written as it is from every layer and typed once
resolved.

This module deliberately omits ``from __future__ import annotations``;
see ``_schemas.py``.
"""

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import ClassVar, Literal, cast

import pytest

import didactic.api as dx
from didactic.settings import (
    CliSource,
    CoercionError,
    ConfigError,
    ConfigValue,
    EnvSource,
    Settings,
    UnknownKeyError,
    compose,
    compose_traced,
)

from ._schemas import (
    DecoderSpec,
    HeadSpec,
    MlpDecoder,
    Pipeline,
    RunSpec,
    StageOne,
    TransformerEncoder,
)

# -- wrong-typed values in typed layers ------------------------------------------------


def test_toml_file_string_at_int_leaf(tmp_path: Path) -> None:
    cfg = tmp_path / "bad.toml"
    cfg.write_text('[trainer]\nepochs = "20"\n')
    with pytest.raises(CoercionError) as info:
        compose(cfg, schema=RunSpec)
    e = info.value
    assert e.path == "trainer.epochs"
    assert e.expected == "int"
    assert e.text == "'20'"
    assert str(e) == (
        "Config key 'trainer.epochs' expects int (set by file:bad.toml); got '20'"
    )


@pytest.mark.parametrize(
    ("value", "got"),
    [("3", "'3'"), (2.0, "2.0"), (True, "True"), (None, "None")],
)
def test_overlay_mapping_wrong_scalar_at_int_leaf(value: ConfigValue, got: str) -> None:
    with pytest.raises(CoercionError) as info:
        compose(schema=RunSpec, overlays=[{"trainer": {"epochs": value}}])
    assert str(info.value) == (
        f"Config key 'trainer.epochs' expects int (set by overlay:#0); got {got}"
    )


@pytest.mark.parametrize(("value", "got"), [({"x": 1}, "dict"), ([1], "list")])
def test_overlay_mapping_container_at_scalar_leaf(value: ConfigValue, got: str) -> None:
    with pytest.raises(CoercionError) as info:
        compose(schema=RunSpec, overlays=[{"trainer": {"epochs": value}}])
    assert str(info.value) == (
        f"Config key 'trainer.epochs' expects int (set by overlay:#0); got {got}"
    )


def test_base_mapping_wrong_type() -> None:
    with pytest.raises(CoercionError, match=r"expects int \(set by base\); got 1\.5"):
        compose(schema=RunSpec, base={"trainer": {"epochs": 1.5}})


def test_typed_pair_wrong_type() -> None:
    with pytest.raises(CoercionError) as info:
        compose(schema=RunSpec, overrides=[("trainer.epochs", "abc")])
    assert str(info.value) == (
        "Config key 'trainer.epochs' expects int "
        "(set by override:trainer.epochs=\"abc\"); got 'abc'"
    )


def test_typed_pair_float_at_int_under_a_variant() -> None:
    with pytest.raises(CoercionError) as info:
        compose(
            schema=RunSpec,
            overlays=[{"model": {"type_encoder": {"kind": "transformer"}}}],
            overrides=[("model.type_encoder.num_heads", 2.5)],
        )
    assert info.value.path == "model.type_encoder.num_heads"
    assert info.value.expected == "int"


def test_settings_load_value_wrong_type() -> None:
    class App(Settings):
        port: int = 1

    with pytest.raises(CoercionError) as info:
        App.load(port="3")
    assert str(info.value) == (
        "Config key 'port' expects int (set by override:port=\"3\"); got '3'"
    )


def test_cli_source_typed_value_wrong_type() -> None:
    class App(Settings):
        port: int = 1
        __sources__: ClassVar = (CliSource({"port": 2.5}),)

    with pytest.raises(CoercionError, match=r"expects int \(set by source:cli\)"):
        App.load()


def test_typed_values_that_fit_are_accepted() -> None:
    class Wide(dx.Model, extra="forbid"):
        f: float = 0.0
        opt: int | None = 1
        mode: Literal["a", "b"] = "a"
        either: int | str = 0
        tags: tuple[str, ...] = ()
        table: dict[str, float] = dx.field(default_factory=dict[str, float])

    wide = compose(
        schema=Wide,
        overlays=[
            {
                "f": 2,
                "opt": None,
                "mode": "b",
                "either": "x",
                "tags": ["a"],
                "table": {"k": 1},
            }
        ],
    )
    assert wide == Wide(
        f=2.0, opt=None, mode="b", either="x", tags=("a",), table={"k": 1.0}
    )


def test_literal_and_tuple_element_mismatches() -> None:
    class Wide(dx.Model, extra="forbid"):
        mode: Literal["a", "b"] = "a"
        tags: tuple[int, ...] = ()

    with pytest.raises(CoercionError) as literal:
        compose(schema=Wide, overlays=[{"mode": "c"}])
    assert str(literal.value) == (
        "Config key 'mode' expects Literal['a', 'b'] (set by overlay:#0); got 'c'"
    )
    with pytest.raises(CoercionError) as element:
        compose(schema=Wide, overlays=[{"tags": [1, "x"]}])
    assert str(element.value) == (
        "Config key 'tags' expects tuple[int, ...] (set by overlay:#0); got list"
    )


def test_core_validation_refuses_scalar_mismatches_with_a_location() -> None:
    for kwargs in ({"layers": 2.0}, {"layers": True}):
        with pytest.raises(dx.ValidationError) as info:
            HeadSpec(**kwargs)  # type: ignore[arg-type]
        assert info.value.entries[0].loc == ("layers",)
        assert info.value.entries[0].type == "type_error"
    with pytest.raises(dx.ValidationError) as tag:
        StageOne(code=True)  # type: ignore[arg-type]
    assert tag.value.entries[0].loc == ("code",)
    with pytest.raises(dx.ValidationError) as stage:
        Pipeline.model_validate({"stage": {"code": True}})
    assert stage.value.model is Pipeline
    assert stage.value.entries[0].loc == ("stage", "code")


def test_wrong_typed_file_is_refused_under_python_optimised_mode(
    tmp_path: Path,
) -> None:
    cfg = tmp_path / "bad.toml"
    cfg.write_text('[trainer]\nepochs = "20"\n')
    script = (
        "import didactic.api as dx\n"
        "from didactic.settings import CoercionError, compose\n"
        "class Trainer(dx.Model, extra='forbid'):\n"
        "    epochs: int = 1\n"
        "class Spec(dx.Model, extra='forbid'):\n"
        "    trainer: Trainer = dx.field(default_factory=Trainer)\n"
        "try:\n"
        f"    compose({str(cfg)!r}, schema=Spec)\n"
        "except CoercionError as exc:\n"
        "    print('refused', exc.path)\n"
        "try:\n"
        "    Trainer.model_validate({'epochs': '20'})\n"
        "except dx.ValidationError as exc:\n"
        "    print('validation', exc.entries[0].type)\n"
    )
    result = subprocess.run(
        [sys.executable, "-O", "-c", script],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.splitlines() == [
        "refused trainer.epochs",
        "validation type_error",
    ]


# -- Path and datetime leaves ----------------------------------------------------------


class Located(dx.Model, extra="forbid"):
    data_dir: Path = Path("/data")
    file: Path | None = None
    when: datetime | None = None


def test_path_and_datetime_leaves_from_a_file(tmp_path: Path) -> None:
    cfg = tmp_path / "c.toml"
    cfg.write_text('data_dir = "/x"\nfile = "/y"\nwhen = "2026-01-01T00:00:00"\n')
    located = compose(cfg, schema=Located)
    assert located.data_dir == Path("/x")
    assert located.file == Path("/y")
    assert located.when == datetime(2026, 1, 1, 0, 0)


def test_path_and_datetime_leaves_from_a_base_mapping() -> None:
    located = compose(
        schema=Located,
        base={"data_dir": "/x", "file": "/y", "when": "2026-01-01T00:00:00"},
    )
    assert (located.data_dir, located.file) == (Path("/x"), Path("/y"))
    assert located.when == datetime(2026, 1, 1, 0, 0)


def test_path_and_datetime_leaves_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class App(Settings, Located):
        __sources__: ClassVar = (EnvSource(prefix="LOC_"),)

    monkeypatch.setenv("LOC_DATA_DIR", "/env")
    monkeypatch.setenv("LOC_WHEN", "2026-02-03T04:05:06")
    app = App.load()
    assert app.data_dir == Path("/env")
    assert app.when == datetime(2026, 2, 3, 4, 5, 6)


def test_path_and_datetime_leaves_from_overrides() -> None:
    located = compose(
        schema=Located,
        overrides=[
            "data_dir=/o",
            ("file", cast("ConfigValue", Path("/typed"))),
            "when=2026-01-01T00:00:00",
        ],
    )
    assert located.data_dir == Path("/o")
    assert located.file == Path("/typed")
    assert located.when == datetime(2026, 1, 1, 0, 0)


def test_path_leaf_refuses_a_number() -> None:
    with pytest.raises(
        CoercionError, match=r"expects Path \(set by overlay:#0\); got 3"
    ):
        compose(schema=Located, overlays=[{"data_dir": 3}])


# -- expressions in textual layers -----------------------------------------------------


class Leafy(dx.Model, extra="forbid"):
    n: int = 0
    f: float = 0.0
    b: bool = False
    s: str = ""
    lst: tuple[int, ...] = ()
    words: tuple[str, ...] = ()


class Exprs(dx.Model, extra="forbid"):
    seed: int = 7
    t: Leafy = dx.field(default_factory=Leafy)
    paths: dict[str, str] = dx.field(default_factory=dict[str, str])


class ExprSettings(Settings, Exprs):
    __sources__: ClassVar = (EnvSource(prefix="EXPR_"),)


@pytest.mark.parametrize(
    ("override", "field", "expected"),
    [
        ("t.n=${oc.env:EXPR_N}", "n", 9),
        ("t.n=${seed}", "n", 7),
        ("t.f=${seed}", "f", 7.0),
        ("t.b=${oc.create:true}", "b", True),
        ("t.b=${oc.env:EXPR_FLAG}", "b", True),
        ("t.lst=${oc.create:[1,2]}", "lst", (1, 2)),
        ("t.lst=1,${seed}", "lst", (1, 7)),
        ("t.words=${seed},b", "words", ("7", "b")),
        ("t.s=${seed}-${oc.env:EXPR_N}", "s", "7-9"),
    ],
)
def test_expression_at_a_non_str_leaf_from_an_override_string(
    monkeypatch: pytest.MonkeyPatch, override: str, field: str, expected: object
) -> None:
    monkeypatch.setenv("EXPR_N", "9")
    monkeypatch.setenv("EXPR_FLAG", "yes")
    run = compose_traced(schema=Exprs, overrides=[override])
    assert getattr(run.value.t, field) == expected
    origin = run.provenance[f"t.{field}"]
    assert origin.label == f"override:{override}"
    text = override.partition("=")[2]
    # a comma-split list records the decoded list, in JSON
    recorded = {"1,${seed}": '[1, "${seed}"]', "${seed},b": '["${seed}", "b"]'}
    assert origin.expression == recorded.get(text, text)


def test_expression_at_a_non_str_leaf_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EXPR_N", "9")
    monkeypatch.setenv("EXPR_T__N", "${oc.env:EXPR_N}")
    monkeypatch.setenv("EXPR_T__F", "${seed}")
    monkeypatch.setenv("EXPR_T__B", "${oc.create:true}")
    monkeypatch.setenv("EXPR_T__LST", "${oc.create:[1,2]}")
    app = ExprSettings.load_traced()
    assert app.value.t == Leafy(n=9, f=7.0, b=True, lst=(1, 2))
    assert app.provenance["t.n"].label == "source:env"
    assert app.provenance["t.n"].expression == "${oc.env:EXPR_N}"
    assert app.provenance["t.lst"].expression == "${oc.create:[1,2]}"


def test_resolved_text_that_does_not_fit_is_refused_with_the_expression(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EXPR_N", "nine")
    with pytest.raises(CoercionError) as info:
        compose(schema=Exprs, overrides=["t.n=${oc.env:EXPR_N}"])
    assert str(info.value) == (
        "Config key 't.n' expects int (set by override:t.n=${oc.env:EXPR_N}); "
        "got 'nine'"
    )


def test_list_resolver_fills_a_tuple_leaf_from_a_mapping() -> None:
    run = compose_traced(
        schema=Exprs,
        base={"paths": {"a": "1", "b": "2"}, "t": {"words": "${oc.dict.keys:paths}"}},
    )
    assert run.value.t.words == ("a", "b")
    assert run.provenance["t.words"].expression == "${oc.dict.keys:paths}"
    values = compose(
        schema=Exprs,
        base={"paths": {"a": "1"}, "t": {"words": "${oc.dict.values:paths}"}},
    )
    assert values.t.words == ("1",)


def test_oc_create_fills_a_nested_model_slot() -> None:
    spec = compose(schema=Exprs, overlays=[{"t": '${oc.create:{"n": 3, "b": true}}'}])
    assert spec.t == Leafy(n=3, b=True)


def test_resolver_result_of_the_wrong_shape_is_refused() -> None:
    with pytest.raises(CoercionError) as info:
        compose(
            schema=Exprs,
            base={"paths": {"a": "1"}, "t": {"n": "${oc.dict.keys:paths}"}},
        )
    assert str(info.value) == ("Config key 't.n' expects int (set by base); got list")
    with pytest.raises(ConfigError) as shape:
        compose(schema=Exprs, base={"t": "${seed}"})
    assert str(shape.value) == (
        "Config key 't' expects a mapping for Leafy (set by base); got int"
    )


# -- textual null at optional slots ----------------------------------------------------


class Inner(dx.Model, extra="forbid"):
    x: int = 0


class Optionals(dx.Model, extra="forbid"):
    inner: Inner | None = dx.field(default_factory=Inner)
    dec: DecoderSpec | None = dx.field(default_factory=MlpDecoder)
    table: dict[str, str] | None = dx.field(default_factory=dict[str, str])
    opt: int | None = 3


class OptionalSettings(Settings, Optionals):
    __sources__: ClassVar = (EnvSource(prefix="OPT_"),)


@pytest.mark.parametrize("text", ["null", "~", ""])
def test_textual_null_clears_optional_model_union_and_map_slots(text: str) -> None:
    run = compose_traced(
        schema=Optionals,
        overrides=[f"inner={text}", f"dec={text}", f"table={text}", f"opt={text}"],
    )
    assert run.value == Optionals(inner=None, dec=None, table=None, opt=None)
    assert run.provenance["inner"].label == f"override:inner={text}"
    assert run.provenance["dec"].label == f"override:dec={text}"


def test_environment_null_clears_optional_model_and_union_slots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPT_INNER", "null")
    monkeypatch.setenv("OPT_DEC", "null")
    app = OptionalSettings.load()
    assert app.inner is None
    assert app.dec is None


def test_textual_null_at_a_required_model_slot_is_refused() -> None:
    with pytest.raises(ConfigError) as info:
        compose(schema=RunSpec, overrides=["trainer=null"])
    assert str(info.value) == (
        "Config key 'trainer' expects a mapping for TrainerSpec "
        "(set by override:trainer=null); got null"
    )


# -- computed fields -------------------------------------------------------------------


TRANSFORMER = {"model": {"type_encoder": {"kind": "transformer"}}}


def test_computed_field_in_a_document_layer_is_accepted_and_dropped() -> None:
    run = compose_traced(
        schema=RunSpec,
        overlays=[
            {"model": {"type_encoder": {"kind": "transformer", "declared_output": 1}}}
        ],
    )
    assert run.value.model.type_encoder == TransformerEncoder()
    assert run.provenance["model.type_encoder.declared_output"].label == "default"
    dumped = json.loads(run.value.model_dump_json())
    again = compose(schema=RunSpec, overlays=[dumped])
    assert again == run.value


@pytest.mark.parametrize(
    "override",
    [
        "model.type_encoder.declared_output=999",
        ("model.type_encoder.declared_output", 5),
    ],
)
def test_computed_field_override_is_refused(override: str | tuple[str, int]) -> None:
    with pytest.raises(UnknownKeyError) as info:
        compose(schema=RunSpec, overlays=[TRANSFORMER], overrides=[override])
    e = info.value
    assert e.path == "model.type_encoder.declared_output"
    label = override if isinstance(override, str) else f"{override[0]}={override[1]}"
    assert str(e) == (
        f"Config key 'model.type_encoder.declared_output' (set by override:{label}) "
        "is a computed field of TransformerEncoder and cannot be set"
    )
    assert e.set_by is not None
    assert e.set_by.kind == "override"


def test_computed_field_load_value_is_refused() -> None:
    class App(Settings, RunSpec):
        pass

    with pytest.raises(
        UnknownKeyError, match="is a computed field of TransformerEncoder"
    ):
        App.load(overlays=[TRANSFORMER], model__type_encoder__declared_output=5)


def test_computed_field_from_a_textual_source_is_refused() -> None:
    class App(Settings, RunSpec):
        __sources__: ClassVar = (
            CliSource({"model.type_encoder.declared_output": "5"}),
        )

    with pytest.raises(UnknownKeyError, match=r"\(set by source:cli\) is a computed"):
        App.load(overlays=[TRANSFORMER])


def test_computed_field_before_the_tag_is_refused_in_an_override() -> None:
    with pytest.raises(
        UnknownKeyError, match="is a computed field of TransformerEncoder"
    ):
        compose(schema=RunSpec, overrides=["model.type_encoder.declared_output=1"])


# -- list elements ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("element", "got"),
    [
        ("lstm", "str"),
        (42, "int"),
        (None, "null"),
        ([1], "list"),
        ("${trainer.out_dir}", "str"),
    ],
)
def test_non_mapping_element_of_a_union_list_is_refused(
    element: ConfigValue, got: str
) -> None:
    with pytest.raises(ConfigError) as info:
        compose(schema=RunSpec, overlays=[{"encoders": [element]}])
    assert info.value.path == "encoders[0]"
    assert str(info.value) == (
        "Config key 'encoders[0]' expects a mapping for TypeEncoderSpec "
        f"(set by overlay:#0); got {got}"
    )


def test_non_mapping_element_of_a_model_list_is_refused_after_resolution() -> None:
    class Holder(dx.Model, extra="forbid"):
        heads: tuple[HeadSpec, ...] = ()
        name: str = "x"

    with pytest.raises(ConfigError) as info:
        compose(schema=Holder, overlays=[{"heads": [42]}])
    assert str(info.value) == (
        "Config key 'heads[0]' expects a mapping for HeadSpec (set by overlay:#0); "
        "got int"
    )
    with pytest.raises(ConfigError) as pasted:
        compose(schema=Holder, overlays=[{"heads": ["${name}"]}])
    assert str(pasted.value) == (
        "Config key 'heads[0]' expects a mapping for HeadSpec (set by overlay:#0); "
        "got str"
    )


# -- map defaults ----------------------------------------------------------------------


class Maps(dx.Model, extra="forbid"):
    plain: dict[str, str] = dx.field(default_factory=lambda: {"a": "1"})
    heads: dict[str, HeadSpec] = dx.field(
        default_factory=lambda: {"h": HeadSpec(layers=3)}
    )
    decoders: dict[str, DecoderSpec] = dx.field(
        default_factory=lambda: {"fwd": MlpDecoder(hidden=7)}
    )


def test_default_map_entries_survive_a_layer_adding_another_key() -> None:
    run = compose_traced(schema=Maps, overlays=[{"plain": {"b": "2"}}])
    assert run.value.plain == {"a": "1", "b": "2"}
    assert run.provenance["plain.a"].label == "default"
    assert run.provenance["plain.b"].label == "overlay:#0"
    assert run.tree["plain"] == {"a": "1", "b": "2"}


def test_dotted_override_into_a_default_model_entry_keeps_its_other_fields() -> None:
    run = compose_traced(schema=Maps, overrides=["heads.h.dropout=0.5"])
    assert run.value.heads == {"h": HeadSpec(layers=3, dropout=0.5)}
    assert run.provenance["heads.h.layers"].label == "default"
    assert run.provenance["heads.h.dropout"].label == "override:heads.h.dropout=0.5"


def test_dotted_override_into_a_default_union_entry_composes_with_its_tag() -> None:
    run = compose_traced(schema=Maps, overrides=["decoders.fwd.temperature=0.5"])
    assert run.value.decoders == {"fwd": MlpDecoder(hidden=7, temperature=0.5)}
    assert run.provenance["decoders.fwd.kind"].label == "default"
    assert run.provenance["decoders.fwd.hidden"].label == "default"
    assert run.provenance["decoders.fwd.temperature"].label == (
        "override:decoders.fwd.temperature=0.5"
    )


def test_layer_tag_switches_a_default_union_entry() -> None:
    run = compose_traced(
        schema=Maps, overlays=[{"decoders": {"fwd": {"kind": "linear", "bias": False}}}]
    )
    assert run.value.decoders["fwd"].kind == "linear"
    # the default entry's private field is dropped by the switch and its
    # root-shared field is kept
    assert run.tree["decoders"] == {
        "fwd": {"kind": "linear", "bias": False, "temperature": 1.0}
    }
    assert run.provenance["decoders.fwd.temperature"].label == "default"
    assert "decoders.fwd.hidden" not in run.provenance


def test_key_of_another_variant_against_a_default_union_entry_is_refused() -> None:
    with pytest.raises(UnknownKeyError) as info:
        compose(schema=Maps, overrides=["decoders.fwd.bias=true"])
    assert str(info.value) == (
        "Unknown config key 'decoders.fwd.bias' "
        "(set by override:decoders.fwd.bias=true): variant 'mlp' of DecoderSpec "
        "(selected by default) has no field 'bias'; it belongs to variant 'linear'"
    )


def test_untouched_map_keeps_its_default_and_an_untouched_nested_model_too() -> None:
    run = compose_traced(schema=Maps)
    assert run.value == Maps()
    assert set(run.provenance.by_layer()) == {"default"}
