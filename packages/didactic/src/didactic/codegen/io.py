"""Instance-level parse and emit via ``panproto.IoRegistry``.

50+ panproto codecs (Avro, JSON Schema, OpenAPI, FHIR, Protobuf, BSON,
CDDL, Parquet, K8s CRD, GeoJSON, ...) emit and parse instances of any
[Model][didactic.api.Model]. This module is a thin facade: each call
synthesises a panproto schema from the Model class and dispatches to
the registry.

Examples
--------
>>> import didactic.api as dx
>>> from didactic.codegen import io
>>>
>>> class User(dx.Model):
...     id: str
...     email: str
>>>
>>> u = User(id="u1", email="ada@example.org")
>>> data = io.emit("avro", u)  # doctest: +SKIP
>>> back = io.parse("avro", data, schema=User)  # doctest: +SKIP
>>> back == u  # doctest: +SKIP
True

See Also
--------
didactic.codegen.source : source-code parse / emit for tree-sitter grammars.
didactic.Model.emit_as : the unified entry point.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    import panproto

    from didactic.models._model import Model
    from didactic.types._typing import FieldValue, JsonValue


def emit(protocol: str, instance: Model) -> bytes:
    """Encode ``instance`` as bytes in the named ``protocol``.

    Parameters
    ----------
    protocol
        A panproto protocol name (e.g. ``"avro"``, ``"json_schema"``,
        ``"openapi"``). Use [list_protocols][didactic.codegen.io.list_protocols]
        to enumerate.
    instance
        A [Model][didactic.api.Model] instance.

    Returns
    -------
    bytes
        The encoded bytes.

    Raises
    ------
    panproto.IoError
        If the codec rejects the instance (mismatch with the Model's
        Theory, value out of range, etc.).
    """
    import panproto  # noqa: PLC0415

    from didactic.vcs._repo import schema_from_model  # noqa: PLC0415

    registry = panproto.IoRegistry()
    schema = schema_from_model(type(instance))
    panproto_instance = _build_instance(schema, instance)
    return registry.emit(protocol, schema, panproto_instance)


def parse[M: Model](protocol: str, data: bytes, *, schema: type[M]) -> M:
    """Decode ``data`` from ``protocol`` back to a Model instance.

    Parameters
    ----------
    protocol
        A panproto protocol name.
    data
        The encoded bytes.
    schema
        The expected Model class. The decoded payload is validated
        against this class.

    Returns
    -------
    Model
        A new ``schema`` instance.

    Raises
    ------
    panproto.IoError
        If the codec cannot decode ``data`` against the schema.
    """
    import panproto  # noqa: PLC0415

    from didactic.vcs._repo import schema_from_model  # noqa: PLC0415

    registry = panproto.IoRegistry()
    panproto_schema = schema_from_model(schema)
    instance = registry.parse(protocol, panproto_schema, data)
    payload = _instance_to_payload(instance)
    coerced = _coerce_payload(schema, payload)
    return schema.model_validate(coerced)


def list_protocols() -> list[str]:
    """List the supported instance-protocol names.

    Returns
    -------
    list of str
        Every codec the running panproto build registers, sorted.
    """
    import panproto  # noqa: PLC0415

    return sorted(panproto.IoRegistry().list_protocols())


def check_round_trip(protocol: str, instance: Model) -> None:
    """Assert that ``parse(emit(instance)) == instance`` for ``protocol``.

    Parameters
    ----------
    protocol
        A panproto protocol name.
    instance
        A Model instance. The check round-trips it through the codec
        and asserts equality.

    Raises
    ------
    AssertionError
        If the round trip does not produce an equal Model.
    panproto.IoError
        If the codec rejects either direction.
    """
    payload = emit(protocol, instance)
    back = parse(protocol, payload, schema=type(instance))
    if back != instance:  # pragma: no cover
        msg = (
            f"round-trip mismatch through {protocol!r}: "
            f"parse(emit({instance!r})) == {back!r}"
        )
        raise AssertionError(msg)


# -- helpers ----------------------------------------------------------


def _build_instance(schema: panproto.Schema, model: Model) -> panproto.Instance:
    """Build a ``panproto.Instance`` from a Model instance.

    Parameters
    ----------
    schema
        The panproto schema produced by ``schema_from_model``.
    model
        The Model instance whose fields populate the instance.

    Returns
    -------
    panproto.Instance
        A panproto Instance suitable for passing to ``IoRegistry.emit``.

    Notes
    -----
    Calls ``panproto.Instance.from_json(schema, root_vertex, json_str)``
    where ``root_vertex`` is the Model class name (matching the vertex
    we synthesise in ``schema_from_model``) and ``json_str`` is the
    JSON-shaped dump of the Model.
    """
    import panproto  # noqa: PLC0415

    # ``model_dump_json`` routes each field through its declared
    # encoder, so non-JSON-native types (datetime, Decimal, UUID, ...)
    # come out as the wire-shape strings the schema expects, instead
    # of leaking through as raw Python objects that ``json.dumps``
    # cannot serialise.
    json_str = model.model_dump_json()
    return panproto.Instance.from_json(
        schema,
        type(model).__name__,
        json_str,
    )


def _instance_to_payload(instance: object) -> dict[str, object]:
    """Decode a ``panproto.Instance`` back to a dict suitable for ``model_validate``.

    ``Instance.to_dict()`` returns a graph-shaped record:

    .. code-block:: python

        {
            "nodes": {<root_id>: {"extra_fields": {<field>: {<sort>: <val>}}}},
            "root": <root_id>,
            ...
        }

    where each ``extra_fields`` value is wrapped in a single-key
    ``{<sort>: <value>}`` envelope (``"Str"``, ``"Int"``, ``"Bool"``,
    ``"Float"``, ``"Bytes"``, ...). This helper walks to the root node,
    unwraps each envelope, and returns a plain dict ready for
    ``Model.model_validate``.
    """
    raw = cast("panproto.Instance", instance).to_dict()
    nodes = raw.get("nodes", {})
    root_id = raw.get("root")
    if not isinstance(nodes, dict) or root_id is None:
        return {}
    root_node = cast("dict[object, object]", nodes).get(root_id)
    if not isinstance(root_node, dict):
        return {}
    extra = cast("dict[str, object]", root_node).get("extra_fields", {})
    if not isinstance(extra, dict):
        return {}
    payload: dict[str, object] = {}
    for name, wrapped in cast("dict[str, object]", extra).items():
        payload[name] = _unwrap_sort_envelope(wrapped)
    return payload


def _coerce_payload(
    schema: type[Model], payload: dict[str, object]
) -> dict[str, FieldValue]:
    """Run each payload value through its field's ``from_json`` coercer.

    Panproto returns wire-shape strings for non-JSON-native types
    (``datetime`` as ISO string, ``Decimal`` as string, ``UUID`` as
    string, ...). ``Model.model_validate`` re-runs each field's
    encoder, which expects the original Python type, so we coerce
    every value through ``FieldSpec.translation.from_json`` first.
    """
    out: dict[str, FieldValue] = {}
    specs = schema.__field_specs__
    for name, value in payload.items():
        spec = specs.get(name)
        if spec is None:
            # field is unknown to the schema; pass through as-is.
            # ``cast`` widens to ``FieldValue`` because the runtime
            # contract guarantees panproto only feeds JSON-shape leaves
            # (str/int/float/bool/None/list/dict) which all live in
            # ``FieldValue``.
            out[name] = cast("FieldValue", value)
            continue
        try:
            out[name] = spec.translation.from_json(cast("JsonValue", value))
        except TypeError, ValueError, AssertionError:
            # leave already-Python-shape values untouched
            out[name] = cast("FieldValue", value)
    return out


def _unwrap_sort_envelope(wrapped: object) -> object:
    """Strip the ``{<sort>: <value>}`` envelope panproto puts on field values.

    For scalars, the inner value is the decoded form. For containers,
    the inner value is itself a panproto-shaped structure, which we
    pass through; ``Model.model_validate`` re-runs each field's decoder
    on it.
    """
    if not isinstance(wrapped, dict):
        return wrapped
    envelope = cast("dict[object, object]", wrapped)
    if len(envelope) == 1:
        return next(iter(envelope.values()))
    return envelope


__all__ = [
    "check_round_trip",
    "emit",
    "list_protocols",
    "parse",
]
