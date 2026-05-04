# ``diff_and_classify`` returns a ``CompatReport`` whose ``.to_dict()``
# we re-emit as ``JsonObject``; pyright's stub doesn't narrow the
# panproto-side types tightly enough. Tracked in panproto/didactic#1.
"""Schema diff and breaking-change detection.

Two thin functions over panproto's ``diff_schemas`` and
``diff_and_classify``: [diff][didactic.api.diff] returns the structural
diff between two Models, and [classify_change][didactic.api.classify_change]
classifies the diff as compatible, breaking, or migration-required.

These help CI catch breaking schema changes before they ship. A
``didactic check breaking --base main`` integration runs
``classify_change(old, new)`` and exits non-zero if the result is
breaking and no registered migration covers the diff.

See Also
--------
didactic.register_migration : the registration path that closes a breaking diff.
panproto.diff_schemas : the runtime call.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, cast

if TYPE_CHECKING:
    import panproto

    from didactic.models._model import Model
    from didactic.types._typing import JsonObject


def diff(old: type[Model], new: type[Model]) -> JsonObject:
    """Compute a structural diff between two Models.

    Parameters
    ----------
    old
        The earlier Model.
    new
        The later Model.

    Returns
    -------
    dict
        The diff record from ``panproto.diff_schemas``, exposed as a
        dict. Keys describe added / removed / changed sorts, ops, and
        constraints.

    Examples
    --------
    >>> import didactic.api as dx
    >>> class V1(dx.Model):
    ...     id: str
    >>> class V2(dx.Model):
    ...     id: str
    ...     email: str = ""
    >>> d = dx.diff(V1, V2)  # doctest: +SKIP
    >>> "added" in d  # doctest: +SKIP
    True
    """
    import panproto  # noqa: PLC0415

    from didactic.vcs._repo import schema_from_model  # noqa: PLC0415

    old_schema = schema_from_model(old)
    new_schema = schema_from_model(new)
    schema_diff = panproto.diff_schemas(old_schema, new_schema)
    return cast("JsonObject", schema_diff.to_dict())


def classify_change(old: type[Model], new: type[Model]) -> JsonObject:
    """Diff and classify a Model change as compatible, breaking, or migrating.

    Parameters
    ----------
    old
        The earlier Model.
    new
        The later Model.

    Returns
    -------
    dict
        The compatibility report from
        ``panproto.diff_and_classify``: ``{"compatible": bool,
        "breaking_changes": [...], "non_breaking_changes": [...]}``.

    Examples
    --------
    >>> import didactic.api as dx
    >>> class V1(dx.Model):
    ...     id: str
    >>> class V2(dx.Model):
    ...     id: int  # type change is breaking
    >>> report = dx.classify_change(V1, V2)  # doctest: +SKIP
    >>> report["compatible"]  # doctest: +SKIP
    False
    """
    import panproto  # noqa: PLC0415

    from didactic.theory._theory import build_theory  # noqa: PLC0415
    from didactic.vcs._repo import schema_from_model  # noqa: PLC0415

    old_schema = schema_from_model(old)
    new_schema = schema_from_model(new)
    # the protocol carries the theory a Schema is validated against;
    # for diff_and_classify we synthesise a covering protocol over
    # the new theory (the new shape is the target of the diff)
    protocol = panproto.Protocol.from_theories(
        name=f"{old.__name__}_vs_{new.__name__}",
        schema_theory=build_theory(new),
        obj_kinds=["object"],
    )

    # ``panproto.diff_and_classify`` accepts a third positional ``protocol``
    # argument at runtime; the upstream stub still lists only two. Cast
    # to a Protocol that exposes the runtime arity and return shape.
    class _CompatReportLike(Protocol):
        def to_dict(self) -> JsonObject: ...

    class _DiffAndClassifyLike(Protocol):
        def __call__(
            self,
            old: panproto.Schema,
            new: panproto.Schema,
            protocol: panproto.Protocol,
            /,
        ) -> _CompatReportLike: ...

    diff_and_classify = cast("_DiffAndClassifyLike", panproto.diff_and_classify)
    compat = diff_and_classify(old_schema, new_schema, protocol)
    return compat.to_dict()


def is_breaking_change(old: type[Model], new: type[Model]) -> bool:
    """Return ``True`` when the change from ``old`` to ``new`` is breaking."""
    report = classify_change(old, new)
    return not bool(report.get("compatible", False))


__all__ = [
    "classify_change",
    "diff",
    "is_breaking_change",
]
