"""Tests for ``dx.codegen`` and ``Model.emit_as``."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

import didactic.api as dx
from didactic.codegen import IndentWriter, emitter, list_emitters

# -- json schema ------------------------------------------------------


class JsonSchemaUser(dx.Model):
    """A user record."""

    id: str
    email: str = dx.field(description="primary contact")
    nickname: str = ""


def test_json_schema_basic_shape() -> None:
    schema = JsonSchemaUser.model_json_schema()
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["title"] == "JsonSchemaUser"
    assert schema["type"] == "object"
    assert set(schema["properties"]) == {"id", "email", "nickname"}


def test_json_schema_required_only_for_required_fields() -> None:
    schema = JsonSchemaUser.model_json_schema()
    assert schema.get("required") == ["id", "email"]


def test_json_schema_carries_field_description() -> None:
    schema = JsonSchemaUser.model_json_schema()
    assert schema["properties"]["email"].get("description") == "primary contact"


def test_json_schema_carries_class_doc() -> None:
    schema = JsonSchemaUser.model_json_schema()
    assert schema.get("description") == "A user record."


def test_json_schema_int_is_integer() -> None:
    class M(dx.Model):
        n: int

    assert M.model_json_schema()["properties"]["n"]["type"] == "integer"


def test_json_schema_bytes_format_byte() -> None:
    class M(dx.Model):
        blob: bytes = b""

    schema = M.model_json_schema()["properties"]["blob"]
    assert schema["type"] == "string"
    assert schema.get("format") == "byte"


def test_json_schema_examples_propagate() -> None:
    class M(dx.Model):
        id: str = dx.field(examples=("u1", "u2"))

    schema = M.model_json_schema()
    assert schema["properties"]["id"].get("examples") == ["u1", "u2"]


def test_json_schema_deprecated_propagates() -> None:
    class M(dx.Model):
        legacy: str | None = dx.field(default=None, deprecated=True)

    schema = M.model_json_schema()
    assert schema["properties"]["legacy"].get("deprecated") is True


def test_json_schema_annotated_constraints_propagate() -> None:
    """Ge/Gt/Le/Lt/MinLen/MaxLen/MultipleOf surface as JSON Schema keywords.

    The metadata reaches the JSON Schema emitter through
    ``extras["annotated_metadata"]`` (the same channel ``from_pydantic``
    uses); we exercise the propagation directly so the test does not
    depend on the metaclass accepting bare ``Annotated[...]`` annotations.
    """
    from annotated_types import Ge, Gt, Le, Lt, MaxLen, MinLen, MultipleOf

    class M(dx.Model):
        age: int = dx.field(default=0, extras={"annotated_metadata": (Ge(0), Le(127))})
        positive: int = dx.field(default=1, extras={"annotated_metadata": (Gt(0),)})
        bounded: int = dx.field(default=0, extras={"annotated_metadata": (Lt(10),)})
        nick: str = dx.field(
            default="x", extras={"annotated_metadata": (MinLen(1), MaxLen(32))}
        )
        even: int = dx.field(default=0, extras={"annotated_metadata": (MultipleOf(2),)})

    props = M.model_json_schema()["properties"]
    assert props["age"].get("minimum") == 0
    assert props["age"].get("maximum") == 127
    assert props["positive"].get("exclusiveMinimum") == 0
    assert props["bounded"].get("exclusiveMaximum") == 10
    assert props["nick"].get("minLength") == 1
    assert props["nick"].get("maxLength") == 32
    assert props["even"].get("multipleOf") == 2


def test_json_schema_predicate_constraint_falls_back_to_extension() -> None:
    """``Predicate`` has no JSON Schema equivalent.

    It lands in ``x-didactic-predicate`` instead.
    """
    from annotated_types import Predicate

    class M(dx.Model):
        x: int = dx.field(
            default=0,
            extras={"annotated_metadata": (Predicate(lambda v: v >= 0),)},
        )

    schema = M.model_json_schema()["properties"]["x"]
    assert "x-didactic-predicate" in schema


def test_json_schema_extra_dict_merges_into_property() -> None:
    """A ``json_schema_extra`` extras entry is folded into the property."""

    class M(dx.Model):
        id: str = dx.field(extras={"json_schema_extra": {"x-custom": True}})

    schema = M.model_json_schema()
    assert schema["properties"]["id"].get("x-custom") is True


# -- emit_as: json_schema target -------------------------------------


def test_emit_as_json_schema_returns_bytes() -> None:
    payload = JsonSchemaUser.emit_as("json_schema")
    assert isinstance(payload, bytes)
    parsed = json.loads(payload)
    assert parsed["title"] == "JsonSchemaUser"


# -- emit_as: rejected target ----------------------------------------


def test_emit_as_unknown_target_raises_lookup() -> None:
    with pytest.raises(LookupError, match="no registered emitter"):
        JsonSchemaUser.emit_as("not_a_real_target")


# -- emit_as: panproto IoRegistry protocol ---------------------------


def test_emit_as_panproto_protocol_returns_bytes() -> None:
    """Any panproto IoRegistry codec is reachable via emit_as."""
    # avro is a stable codec across panproto releases
    out = JsonSchemaUser.emit_as("avro")
    assert isinstance(out, bytes)
    assert len(out) > 0


# -- emit_as: source-code target -------------------------------------


def test_emit_as_python_grammar_returns_bytes() -> None:
    out = JsonSchemaUser.emit_as("python")
    assert isinstance(out, bytes)


# -- custom emitters --------------------------------------------------


def test_custom_emitter_dispatches_through_emit_as() -> None:
    # the @emitter decorator registers the class in the global emitter
    # table; the local name is therefore "unused" from a pyright POV
    # but the registry side effect is exactly what this test exercises
    @emitter("test_marker_emitter")
    class _MarkerEmitter:
        file_extension = "marker"

        def emit_class(self, cls: type[dx.Model]) -> bytes:
            return f"[{cls.__name__}]".encode()

        def emit_instance(self, instance: dx.Model) -> bytes:
            raise NotImplementedError

    del _MarkerEmitter  # silence reportUnusedClass; registry holds it

    out = JsonSchemaUser.emit_as("test_marker_emitter")
    assert out == b"[JsonSchemaUser]"
    assert "test_marker_emitter" in list_emitters()


# -- IndentWriter -----------------------------------------------------


def test_indent_writer_basic() -> None:
    w = IndentWriter()
    w.line("class Foo:")
    with w.indent():
        w.line("x: int")
        w.line("y: int")
    assert w.text_str() == "class Foo:\n    x: int\n    y: int\n"


def test_indent_writer_nested() -> None:
    w = IndentWriter()
    w.line("a")
    with w.indent():
        w.line("b")
        with w.indent():
            w.line("c")
        w.line("b2")
    assert w.text_str() == "a\n    b\n        c\n    b2\n"


def test_indent_writer_bytes_is_utf8() -> None:
    w = IndentWriter()
    w.line("hello")
    assert w.bytes() == b"hello\n"


def test_indent_writer_empty_line_emits_newline() -> None:
    w = IndentWriter()
    w.line()
    assert w.text_str() == "\n"


# -- io / source enumeration ------------------------------------------


def test_io_list_protocols_nonempty() -> None:
    protocols = dx.codegen.io.list_protocols()
    assert len(protocols) > 0
    assert "avro" in protocols


def test_source_available_targets_nonempty() -> None:
    targets = dx.codegen.source.available_targets()
    assert len(targets) > 0
    # at least one major language should be present
    assert "python" in targets or "rust" in targets or "typescript" in targets


# -- io: emit / parse / round-trip smoke tests -----------------------


def test_io_emit_returns_bytes() -> None:
    """``io.emit`` round-trips a Model instance through a panproto codec."""
    u = JsonSchemaUser(id="u1", email="ada@example.org")
    payload = dx.codegen.io.emit("avro", u)
    assert isinstance(payload, bytes)
    assert len(payload) > 0


def test_io_parse_round_trips_through_avro() -> None:
    """``io.parse`` decodes bytes produced by ``io.emit`` back to a Model."""
    u = JsonSchemaUser(id="u1", email="ada@example.org")
    payload = dx.codegen.io.emit("avro", u)
    back = dx.codegen.io.parse("avro", payload, schema=JsonSchemaUser)
    assert isinstance(back, JsonSchemaUser)
    assert back == u


def test_io_check_round_trip_holds_for_avro() -> None:
    """``io.check_round_trip`` succeeds for a stable codec."""
    u = JsonSchemaUser(id="u1", email="ada@example.org")
    dx.codegen.io.check_round_trip("avro", u)


# -- source: emit_pretty / parse / detect_language / for_protocol ----


def test_source_emit_pretty_returns_python_source() -> None:
    """``emit_pretty(target="python")`` produces source bytes for the python grammar."""
    out = dx.codegen.source.emit_pretty(JsonSchemaUser, target="python")
    assert isinstance(out, bytes)


def test_source_detect_language_for_known_extension() -> None:
    """``detect_language`` resolves a Python file extension to ``"python"``."""
    assert dx.codegen.source.detect_language("foo.py") == "python"


def test_source_parse_then_emit_round_trips_python() -> None:
    """parse-then-emit produces source bytes for a trivial Python program."""
    src = b"x = 1\n"
    schema = dx.codegen.source.parse(src, protocol="python")
    out = dx.codegen.source.emit(schema, protocol="python")
    assert isinstance(out, bytes)
    assert len(out) > 0


def test_source_for_protocol_returns_callable() -> None:
    """``for_protocol`` returns a callable that parses bytes for the given grammar."""
    parser = dx.codegen.source.for_protocol("python")
    assert callable(parser)
    parser(b"x = 1\n")  # exercise the parse path; raises on failure


# -- write: bulk emission to disk ------------------------------------


class WriteUser(dx.Model):
    id: str
    email: str = ""


class CamelCaseModel(dx.Model):
    """A Model whose name exercises snake_case conversion."""

    x: int = 0


def test_write_emits_one_file_per_model_target_pair(tmp_path: Path) -> None:
    out_dir = tmp_path / "schemas"
    written = dx.codegen.write([WriteUser], targets={"json_schema": str(out_dir)})
    key = "json_schema/WriteUser"
    assert key in written
    path = written[key]
    assert path.exists()
    assert path.suffix == ".json"
    assert b"WriteUser" in path.read_bytes()


def test_write_creates_missing_target_directory(tmp_path: Path) -> None:
    """The target directory is created if it does not already exist."""
    out_dir = tmp_path / "nested" / "schemas"
    assert not out_dir.exists()
    dx.codegen.write([WriteUser], targets={"json_schema": str(out_dir)})
    assert out_dir.is_dir()


def test_write_filename_template_substitutes_snake_case(tmp_path: Path) -> None:
    """The ``{model_snake_case}`` placeholder lowercases CamelCase names."""
    out_dir = tmp_path / "schemas"
    written = dx.codegen.write(
        [CamelCaseModel],
        targets={"json_schema": str(out_dir)},
        filename="{model_snake_case}.{ext}",
    )
    path = written["json_schema/CamelCaseModel"]
    # the canonical extension for json_schema is "schema.json"
    assert path.name == "camel_case_model.schema.json"


def test_write_falls_back_to_target_name_for_unknown_extension(tmp_path: Path) -> None:
    """An unregistered target name doubles as its file extension."""
    out_dir = tmp_path / "schemas"

    @emitter("custom_marker_target")
    class _Marker:
        file_extension = "marker"

        def emit_class(self, cls: type[dx.Model]) -> bytes:
            return b"x"

        def emit_instance(self, instance: dx.Model) -> bytes:
            raise NotImplementedError

    del _Marker  # silence reportUnusedClass; registry holds it

    written = dx.codegen.write(
        [WriteUser],
        targets={"custom_marker_target": str(out_dir)},
    )
    path = written["custom_marker_target/WriteUser"]
    # the canonical extension table doesn't know this target, so the
    # extension falls back to the target name itself
    assert path.suffix == ".custom_marker_target"


if TYPE_CHECKING:
    from pathlib import Path
