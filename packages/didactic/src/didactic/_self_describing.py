"""Self-describing JSON via fingerprint URIs.

A panproto-native form of self-describing data: an emitted JSON
payload carries a ``$schema`` URI of the form
``didactic://v1/<structural-fingerprint>``. A consumer that holds a
registry of known Theories (by fingerprint) can validate an unknown
payload by looking the URI up.

This is something Pydantic structurally cannot do, because Pydantic
has no content-addressed schema identity. didactic's structural
fingerprint already gives every Model a stable address; this module
just plumbs it through to JSON.

Examples
--------
>>> import didactic.api as dx
>>>
>>> class User(dx.Model):
...     id: str
...     email: str
>>>
>>> u = User(id="u1", email="ada@example.org")
>>> payload = dx.embed_schema_uri(u)
>>> payload["$schema"].startswith("didactic://v1/")
True

See Also
--------
didactic.migrations._fingerprint.structural_fingerprint : the underlying address.
"""

# Cross-translation between ``FieldValue`` and ``JsonValue`` shapes
# in the schema-URI registry layer.
from __future__ import annotations

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from didactic.models._model import Model
    from didactic.types._typing import JsonObject

#: URI scheme prefix didactic uses for self-describing payloads.
URI_PREFIX = "didactic://v1/"


def schema_uri(cls: type[Model]) -> str:
    """Return the canonical schema URI for a Model class.

    Parameters
    ----------
    cls
        A [Model][didactic.api.Model] subclass.

    Returns
    -------
    str
        ``"didactic://v1/<fingerprint>"`` where ``<fingerprint>`` is
        the Model's structural fingerprint.
    """
    from didactic.migrations._fingerprint import structural_fingerprint  # noqa: PLC0415
    from didactic.theory._theory import build_theory_spec  # noqa: PLC0415

    return f"{URI_PREFIX}{structural_fingerprint(build_theory_spec(cls))}"


def embed_schema_uri(instance: Model) -> JsonObject:
    """Return the JSON-shape dump of ``instance`` with a ``$schema`` URI prepended.

    Parameters
    ----------
    instance
        A Model instance.

    Returns
    -------
    dict
        The JSON-safe dump dict, with ``"$schema"`` set to the Model's
        canonical URI as the first key.

    Notes
    -----
    Routes through ``model_dump_json`` (not the bare ``model_dump``)
    so any nested ``tuple[Embed[T], ...]`` or ``dict[str, Embed[T]]``
    fields get the JSON-safe walk; the returned dict is always
    serialisable with ``json.dumps``.

    A consumer that knows how to resolve ``didactic://v1/<fp>`` URIs
    can fetch the Theory by fingerprint and validate the payload
    without knowing the original Python class.
    """
    import json  # noqa: PLC0415

    payload = cast("JsonObject", json.loads(instance.model_dump_json()))
    return {"$schema": schema_uri(type(instance)), **payload}


class FingerprintRegistry:
    """An in-memory mapping of structural fingerprint to Model class.

    Use as the lookup side of a self-describing JSON pipeline:
    register every Model your application understands, then
    [validate_with_uri_lookup][didactic.api.validate_with_uri_lookup]
    can resolve an unknown payload's ``$schema`` URI back to a class.

    Examples
    --------
    >>> import didactic.api as dx
    >>> class User(dx.Model):
    ...     id: str
    >>>
    >>> reg = dx.FingerprintRegistry()
    >>> reg.register(User)
    >>>
    >>> u = User(id="u1")
    >>> payload = dx.embed_schema_uri(u)
    >>> back = dx.validate_with_uri_lookup(payload, reg)
    >>> back == u
    True
    """

    __slots__ = ("_by_fingerprint",)

    def __init__(self) -> None:
        self._by_fingerprint: dict[str, type[Model]] = {}

    def register[M: Model](self, cls: type[M]) -> type[M]:
        """Register ``cls`` under its structural fingerprint."""
        from didactic.migrations._fingerprint import (  # noqa: PLC0415
            structural_fingerprint,
        )
        from didactic.theory._theory import build_theory_spec  # noqa: PLC0415

        fp = structural_fingerprint(build_theory_spec(cls))
        self._by_fingerprint[fp] = cls
        return cls

    def lookup(self, uri: str) -> type[Model] | None:
        """Resolve a ``didactic://v1/<fp>`` URI to a registered class."""
        if not uri.startswith(URI_PREFIX):
            return None
        fp = uri[len(URI_PREFIX) :]
        return self._by_fingerprint.get(fp)

    def __contains__(self, cls_or_uri: object) -> bool:
        if isinstance(cls_or_uri, str):
            return self.lookup(cls_or_uri) is not None
        if isinstance(cls_or_uri, type):
            from didactic.migrations._fingerprint import (  # noqa: PLC0415
                structural_fingerprint,
            )
            from didactic.theory._theory import build_theory_spec  # noqa: PLC0415

            return (
                structural_fingerprint(build_theory_spec(cls_or_uri))
                in self._by_fingerprint
            )
        return False

    def __len__(self) -> int:
        return len(self._by_fingerprint)


def validate_with_uri_lookup(
    payload: JsonObject,
    registry: FingerprintRegistry,
) -> Model:
    """Validate ``payload`` against the Model named by its ``$schema`` URI.

    Parameters
    ----------
    payload
        A dict that includes a ``$schema`` key.
    registry
        A [FingerprintRegistry][didactic.api.FingerprintRegistry] mapping
        URIs to Model classes.

    Returns
    -------
    Model
        A validated Model instance whose class came from the
        registry.

    Raises
    ------
    LookupError
        If the URI is not registered.
    KeyError
        If the payload has no ``$schema`` key.
    """
    if "$schema" not in payload:
        msg = "validate_with_uri_lookup: payload has no $schema key"
        raise KeyError(msg)

    uri = payload["$schema"]
    if not isinstance(uri, str):
        msg = "validate_with_uri_lookup: $schema value must be a string"
        raise TypeError(msg)
    cls = registry.lookup(uri)
    if cls is None:
        msg = f"validate_with_uri_lookup: no registered model for URI {uri!r}"
        raise LookupError(msg)

    body = {k: v for k, v in payload.items() if k != "$schema"}
    return cls.model_validate(body)


__all__ = [
    "URI_PREFIX",
    "FingerprintRegistry",
    "embed_schema_uri",
    "schema_uri",
    "validate_with_uri_lookup",
]
