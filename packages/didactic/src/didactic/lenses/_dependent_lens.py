"""Dependent (schema-parametric) lenses backed by ``panproto.ProtolensChain``.

A [DependentLens][didactic.api.DependentLens] is a lens family parametrised
by a pair of [panproto Schemas][panproto.Schema]. Where a regular
[Lens][didactic.api.Lens] commits at construction time to a fixed source
and target type, a DependentLens commits only to a structural pattern
and produces a concrete Lens once the pattern is instantiated against
specific source and target schemas.

This is the same idea as panproto's ``ProtolensChain``: a chain of
schema-rewriting steps that can be specialised against many concrete
schemas. didactic's wrapper exists so users can stay inside the
``import didactic as dx`` namespace and so the public API remains
stable independent of panproto's internal binding shape.

Examples
--------
>>> import didactic.api as dx
>>>
>>> # build a chain that auto-generates a transformation between
>>> # two schemas under a given panproto protocol
>>> import panproto
>>> proto = panproto.get_builtin_protocol("openapi")
>>>
>>> # ... build src and tgt schemas via proto.schema().vertex(...).build()
>>> # then derive a chain:
>>> chain = dx.DependentLens.auto_generate(  # doctest: +SKIP
...     src_schema,
...     tgt_schema,
...     proto,
... )
>>>
>>> # chain can be composed, fused, serialised
>>> json_text = chain.to_json()  # doctest: +SKIP
>>>
>>> # to use the chain on a concrete pair of schemas, instantiate it:
>>> concrete = chain.instantiate(src_schema, proto)  # doctest: +SKIP

See Also
--------
didactic.Lens : the schema-fixed lens type.
didactic.Iso : the isomorphism subcase.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    import panproto


class DependentLens:
    """A schema-independent lens family.

    Wraps a ``panproto.ProtolensChain``. The wrapper carries the
    underlying chain and exposes the operations that are useful from
    didactic-shaped code:

    - construction via [auto_generate][didactic.api.DependentLens.auto_generate]
      or [auto_generate_with_hints][didactic.api.DependentLens.auto_generate_with_hints]
    - composition (``>>`` or [compose][didactic.api.DependentLens.compose])
    - fusion of all steps into one ([fuse][didactic.api.DependentLens.fuse])
    - JSON round-trip ([to_json][didactic.api.DependentLens.to_json] and
      [from_json][didactic.api.DependentLens.from_json])
    - instantiation against a concrete schema
      ([instantiate][didactic.api.DependentLens.instantiate])

    Parameters
    ----------
    inner
        An already-constructed ``panproto.ProtolensChain``. Most callers
        should use the [auto_generate][didactic.api.DependentLens.auto_generate]
        class method or [from_json][didactic.api.DependentLens.from_json]
        rather than constructing this class directly.

    Notes
    -----
    Equality compares the JSON-serialised form of the underlying
    chain; structurally identical chains are equal even if they were
    constructed by different code paths.
    """

    __slots__ = ("_inner",)

    def __init__(self, inner: panproto.ProtolensChain) -> None:
        self._inner = inner

    # construction --------------------------------------------------

    @classmethod
    def auto_generate(
        cls,
        src_schema: panproto.Schema,
        tgt_schema: panproto.Schema,
        protocol: panproto.Protocol,
        *,
        stringency: str | None = None,
    ) -> DependentLens:
        """Auto-generate a chain between two schemas under ``protocol``.

        Parameters
        ----------
        src_schema
            The source schema.
        tgt_schema
            The target schema.
        protocol
            The panproto protocol that both schemas conform to.
        stringency
            Optional stringency hint passed through to panproto. Use
            ``None`` for the default.

        Returns
        -------
        DependentLens
            A chain capturing the rewrites that take the source
            schema to the target.

        Raises
        ------
        panproto.LensError
            If panproto cannot derive a chain between the two
            schemas under the given protocol.
        """
        import panproto  # noqa: PLC0415

        if stringency is None:
            inner = panproto.ProtolensChain.auto_generate(
                src_schema,
                tgt_schema,
                protocol,
            )
        else:
            inner = panproto.ProtolensChain.auto_generate(
                src_schema,
                tgt_schema,
                protocol,
                stringency,
            )
        return cls(inner)

    @classmethod
    def auto_generate_with_hints(
        cls,
        src_schema: panproto.Schema,
        tgt_schema: panproto.Schema,
        protocol: panproto.Protocol,
        hints: object,
        *,
        stringency: str | None = None,
    ) -> DependentLens:
        """Auto-generate using vertex-correspondence hints.

        Parameters
        ----------
        src_schema
            Source schema.
        tgt_schema
            Target schema.
        protocol
            The panproto protocol both schemas conform to.
        hints
            Vertex-correspondence hints. Their exact shape is
            panproto-defined.
        stringency
            Optional stringency hint. ``None`` uses panproto's default.

        Returns
        -------
        DependentLens
            A chain that respects the given hints.
        """
        import panproto  # noqa: PLC0415

        if stringency is None:
            inner = panproto.ProtolensChain.auto_generate_with_hints(
                src_schema,
                tgt_schema,
                protocol,
                hints,
            )
        else:
            inner = panproto.ProtolensChain.auto_generate_with_hints(
                src_schema,
                tgt_schema,
                protocol,
                hints,
                stringency,
            )
        return cls(inner)

    @classmethod
    def from_json(cls, json_text: str) -> DependentLens:
        """Reconstruct a chain from its JSON form.

        Parameters
        ----------
        json_text
            A JSON string previously returned by
            [to_json][didactic.api.DependentLens.to_json].

        Returns
        -------
        DependentLens
            The reconstructed chain.

        Raises
        ------
        panproto.LensError
            If ``json_text`` is not a valid serialised chain.
        """
        import panproto  # noqa: PLC0415

        return cls(panproto.ProtolensChain.from_json(json_text))

    # operations ----------------------------------------------------

    def compose(self, other: DependentLens) -> DependentLens:
        """Vertically compose this chain with ``other``.

        Parameters
        ----------
        other
            Another [DependentLens][didactic.api.DependentLens] whose
            source matches this chain's target.

        Returns
        -------
        DependentLens
            The composed chain.

        Notes
        -----
        Composition is associative; identity is the empty chain.
        """
        return DependentLens(self._inner.compose(other._inner))

    def __rshift__(self, other: DependentLens) -> DependentLens:
        """Composition via ``self >> other``."""
        return self.compose(other)

    def fuse(self) -> object:
        """Fuse all steps into a single protolens.

        Returns
        -------
        object
            A panproto-side fused protolens. The exact return type is
            panproto-defined; treat it as opaque.
        """
        return self._inner.fuse()

    def instantiate(
        self,
        schema: panproto.Schema,
        protocol: panproto.Protocol,
    ) -> object:
        """Instantiate against a concrete schema to produce a ``panproto.Lens``.

        Parameters
        ----------
        schema
            The concrete source schema to specialise against.
        protocol
            The panproto protocol the schema conforms to.

        Returns
        -------
        object
            A ``panproto.Lens`` (treat as opaque from this side).

        Raises
        ------
        panproto.LensError
            If the chain cannot be instantiated against ``schema``.
        """
        # ``ProtolensChain.instantiate``'s shipped stub claims
        # ``(src: Schema, tgt: Schema)``; the runtime is
        # ``(schema, protocol)`` with the second arg being a
        # ``panproto.Protocol``. Cast at the boundary so we type-match
        # the stub while passing the runtime's expected value.
        return self._inner.instantiate(schema, cast("panproto.Schema", protocol))

    # serialisation -------------------------------------------------

    def to_json(self) -> str:
        """Serialise the chain to JSON.

        Returns
        -------
        str
            A JSON string suitable for round-tripping through
            [from_json][didactic.api.DependentLens.from_json].
        """
        return self._inner.to_json()

    # representation ------------------------------------------------

    def __eq__(self, other: object) -> bool:
        """Structural equality via JSON-serialised chains."""
        if not isinstance(other, DependentLens):
            return NotImplemented
        return self.to_json() == other.to_json()

    def __hash__(self) -> int:
        return hash(self.to_json())

    def __repr__(self) -> str:
        return f"DependentLens({self._inner!r})"


__all__ = [
    "DependentLens",
]
