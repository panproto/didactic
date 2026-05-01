"""Cross-vertex reference and embedding markers.

didactic distinguishes three ways a Model can name another Model in a
field:

[Ref][didactic.api.Ref]
    A non-owning reference, like a foreign key. Stored as the target
    model's primary id (a ``str``). The same target can be referenced
    by many Models. Maps to a panproto edge.
[Embed][didactic.api.Embed]
    An owned sub-vertex; the target's lifetime is bound to the parent.
    Embedded sub-vertices have ids prefixed by the parent's.

[Backref][didactic.api.Backref]
    A computed inverse derived from a ``Ref`` somewhere else. The
    marker is exposed but the resolution path through a Repository is
    not yet implemented.

``Ref`` and ``Embed`` are wired through the type translation, field
spec, and theory builder. ``Backref`` exposes the marker class but
resolution (looking up the inverse via a Repository) is not yet
implemented. Reading ``Ref[Foo]`` produces a field that stores a
string id and decodes back to a string id; resolving the id back to a
``Foo`` instance happens through a Repository on the panproto-VCS
side, and the Python attribute itself remains the id.

Notes
-----
``Ref[T]`` is a :pep:`695` type alias whose value is
``Annotated[str, _REF_MARKER, T]``. The trailing ``T`` is a phantom
metadata slot used by the metaclass to recover the target class after
the alias is subscripted; the type checker still sees the field as
``str`` (which is the runtime truth: it stores an id).

``Embed[T]`` is the alias ``Annotated[T, _EMBED_MARKER]`` so the type
checker sees ``T`` directly (the runtime value is a ``T`` instance).

The didactic metaclass detects the sentinel markers in the alias's
expanded metadata and treats the field as an edge for theory
derivation.

See Also
--------
didactic.types._types.classify : the entry that recognises Ref/Embed.
didactic.theory._theory : the bridge that emits Ref/Embed as theory edges.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, cast

if TYPE_CHECKING:
    from didactic.types._typing import ClassTarget, Opaque


@dataclass(frozen=True, slots=True)
class RefSentinel:
    """Sentinel singleton injected as ``Annotated`` metadata for ``Ref``.

    Module-public so ``didactic.types._types`` can ``isinstance``-check
    it without tripping pyright's ``reportPrivateUsage`` rule. End users
    interact with [Ref][didactic.api.Ref] directly, not the sentinel.
    """


@dataclass(frozen=True, slots=True)
class EmbedSentinel:
    """Sentinel singleton injected as ``Annotated`` metadata for ``Embed``.

    Same rationale as :class:`RefSentinel`.
    """


REF_MARKER = RefSentinel()
EMBED_MARKER = EmbedSentinel()


@dataclass(frozen=True, slots=True)
class RefMarker:
    """Compatibility wrapper exposing a Ref's target.

    Parameters
    ----------
    target
        The model class (or its forward-reference string) the field
        references. Recovered by the metaclass from the ``Annotated``
        form's phantom-T slot.
    """

    target: ClassTarget


@dataclass(frozen=True, slots=True)
class EmbedMarker:
    """Compatibility wrapper exposing an Embed's target.

    Parameters
    ----------
    target
        The model class to embed. Recovered by the metaclass from the
        ``Annotated`` form's base type.
    """

    target: ClassTarget


@dataclass(frozen=True, slots=True)
class BackrefMarker:
    """Metadata marker injected by [Backref][didactic.api.Backref]."""

    target: ClassTarget
    inverse_field: str


# ---------------------------------------------------------------------------
# Ref / Embed: PEP 695 type aliases
# ---------------------------------------------------------------------------
#
# ``Ref[T]`` resolves to ``str`` for type checkers (the storage shape)
# while keeping ``T`` available as phantom metadata for the metaclass.
# ``Embed[T]`` resolves to ``T`` directly so attribute access on the
# embedded model type-checks naturally.

type Ref[T] = Annotated[str, REF_MARKER, T]
"""A non-owning reference to another Model. Stored as the target's id (str).

See :class:`didactic.api.Ref` for usage.
"""

type Embed[T] = Annotated[T, EMBED_MARKER]
"""An owned sub-vertex. The runtime value is an instance of ``T``.

See :class:`didactic.api.Embed` for usage.
"""


class _Backref:
    """Implementation behind [Backref][didactic.api.Backref]."""

    def __class_getitem__(
        cls, params: tuple[ClassTarget, ClassTarget] | ClassTarget
    ) -> type:
        """Backref[T, "inverse_field"] -> Annotated[T, BackrefMarker(...)].

        Accepts either the documented 2-tuple ``(target, name)`` form
        or a single non-tuple value (which is rejected at runtime).
        """
        if not isinstance(params, tuple) or len(params) != 2:
            msg = "Backref expects two parameters: Backref[T, 'inverse_field']"
            raise TypeError(msg)
        target, inverse_field = params
        if not isinstance(inverse_field, str):
            msg = "Backref's second parameter must be a string field name"
            raise TypeError(msg)
        return cast(
            "type",
            Annotated[
                target,
                BackrefMarker(target=target, inverse_field=inverse_field),
            ],
        )


#: A computed inverse derived from a Ref elsewhere. Resolution is not
#: yet implemented; the marker is exposed for downstream tooling.
Backref = _Backref


def find_ref_marker(metadata: tuple[Opaque, ...]) -> RefMarker | None:
    """Locate a Ref sentinel in ``Annotated`` metadata and recover its target.

    Parameters
    ----------
    metadata
        The metadata tuple from a fully-expanded ``Annotated[T, ...]``
        annotation (i.e. after PEP 695 alias substitution).

    Returns
    -------
    RefMarker or None
        A wrapper exposing ``target`` (recovered from the trailing
        phantom-T slot), or ``None`` if the metadata does not include a
        Ref sentinel.
    """
    if not any(isinstance(m, RefSentinel) for m in metadata):
        return None
    # The Ref alias expands to ``Annotated[str, REF_MARKER, T]``; the
    # caller passes everything after the base type, so the target is the
    # last element that is not the sentinel itself.
    for m in metadata:
        if isinstance(m, RefSentinel):
            continue
        if isinstance(m, (type, str)):
            return RefMarker(target=cast("ClassTarget", m))
    return None


def find_embed_marker(base: type, metadata: tuple[Opaque, ...]) -> EmbedMarker | None:
    """Locate an Embed sentinel and recover the embedded target type.

    Parameters
    ----------
    base
        The base type of the surrounding ``Annotated[T, ...]`` form
        (i.e. ``T`` itself); the Embed alias places the target there.
    metadata
        The metadata tuple from the same ``Annotated[T, ...]`` form.

    Returns
    -------
    EmbedMarker or None
        A wrapper exposing ``target`` (which is ``base``), or ``None``
        if the metadata does not include an Embed sentinel.
    """
    if not any(isinstance(m, EmbedSentinel) for m in metadata):
        return None
    return EmbedMarker(target=cast("ClassTarget", base))


def find_backref_marker(metadata: tuple[Opaque, ...]) -> BackrefMarker | None:
    """Locate a BackrefMarker in Annotated metadata.

    See [BackrefMarker][didactic.fields._refs.BackrefMarker].
    """
    for m in metadata:
        if isinstance(m, BackrefMarker):
            return m
    return None


__all__ = [
    "EMBED_MARKER",
    "REF_MARKER",
    "Backref",
    "BackrefMarker",
    "Embed",
    "EmbedMarker",
    "EmbedSentinel",
    "Ref",
    "RefMarker",
    "RefSentinel",
    "find_backref_marker",
    "find_embed_marker",
    "find_ref_marker",
]
