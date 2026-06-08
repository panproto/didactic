"""Vertex-correspondence discovery via panproto's hom search.

Given two panproto Schemas, panproto can enumerate the structure-
preserving maps (schema morphisms) between them and score each one.
didactic wraps that search as
[find_correspondences][didactic.api.find_correspondences] and
[best_correspondence][didactic.api.best_correspondence], returning
plain [Correspondence][didactic.api.Correspondence] records.

The discovered ``vertex_map`` has exactly the shape that
[DependentLens.auto_generate_with_hints][didactic.api.DependentLens.auto_generate_with_hints]
takes as ``hints``, so the two compose into a discover-then-derive
pipeline: search for the best correspondence, then derive a chain
that respects it.

Examples
--------
>>> import didactic.api as dx
>>> import panproto
>>>
>>> proto = panproto.get_builtin_protocol("openapi")
>>> # ... build src_schema and tgt_schema via proto.schema() ...
>>>
>>> best = dx.best_correspondence(src_schema, tgt_schema)  # doctest: +SKIP
>>> best.vertex_map  # doctest: +SKIP
{'post:body.text': 'post:body.content', ...}
>>> chain = dx.DependentLens.auto_generate_with_hints(  # doctest: +SKIP
...     src_schema,
...     tgt_schema,
...     proto,
...     best.vertex_map,
... )

See Also
--------
didactic.lenses._dependent_lens : the hint-consuming chain derivation.
panproto.find_morphisms : the runtime search.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import panproto


@dataclass(frozen=True, slots=True)
class Correspondence:
    """One discovered schema morphism, scored.

    Parameters
    ----------
    vertex_map
        Mapping from source-schema vertex IDs to target-schema vertex
        IDs. Feed directly as the ``hints`` argument of
        [DependentLens.auto_generate_with_hints][didactic.api.DependentLens.auto_generate_with_hints].
    quality
        Alignment quality in ``[0.0, 1.0]``. Higher is better.
    """

    vertex_map: dict[str, str]
    quality: float


def find_correspondences(
    src_schema: panproto.Schema,
    tgt_schema: panproto.Schema,
    *,
    anchors: dict[str, str] | None = None,
    monic: bool = False,
    epic: bool = False,
    iso: bool = False,
    max_results: int = 0,
    relax_edge_name_pruning: bool = False,
) -> list[Correspondence]:
    """Enumerate scored vertex correspondences between two schemas.

    Parameters
    ----------
    src_schema
        Source schema.
    tgt_schema
        Target schema.
    anchors
        Vertex pairs (source ID to target ID) the search must respect.
        Use to pin known correspondences and let the search fill in
        the rest.
    monic
        Require the morphism to be injective on vertices (no two
        source vertices map to the same target vertex).
    epic
        Require the morphism to be surjective on vertices (every
        target vertex is hit).
    iso
        Require a bijection. Implies ``monic`` and ``epic``.
    max_results
        Upper bound on the number of morphisms returned. ``0`` means
        unbounded.
    relax_edge_name_pruning
        Keep kind-compatible candidate targets that share no outgoing
        edge name with the source vertex. By default the search prunes
        such candidates for object vertices with large candidate
        domains, which can discard a correct pairing when every child
        was renamed. Naturality is still enforced.

    Returns
    -------
    list of Correspondence
        Discovered correspondences. Empty when no structure-preserving
        map exists under the given constraints.

    Notes
    -----
    The schemas didactic builds from Model classes are single-vertex
    (the structure lives in the Theory), so searching between two
    Models degenerates to the root pairing. The search is informative
    on multi-vertex schemas: protocol schemas built by hand and
    schemas recovered by [didactic.codegen.source.parse][].
    """
    import panproto  # noqa: PLC0415

    found = panproto.find_morphisms(
        src_schema,
        tgt_schema,
        anchors=anchors,
        monic=monic,
        epic=epic,
        iso=iso,
        max_results=max_results,
        relax_edge_name_pruning=relax_edge_name_pruning,
    )
    return [
        Correspondence(vertex_map=m.vertex_map, quality=float(m.quality)) for m in found
    ]


def best_correspondence(
    src_schema: panproto.Schema,
    tgt_schema: panproto.Schema,
    *,
    anchors: dict[str, str] | None = None,
    monic: bool = False,
    epic: bool = False,
    iso: bool = False,
    relax_edge_name_pruning: bool = False,
) -> Correspondence | None:
    """Return the highest-quality correspondence, or ``None``.

    Parameters
    ----------
    src_schema
        Source schema.
    tgt_schema
        Target schema.
    anchors
        Vertex pairs (source ID to target ID) the search must respect.
    monic
        Require injectivity on vertices.
    epic
        Require surjectivity on vertices.
    iso
        Require a bijection. Implies ``monic`` and ``epic``.
    relax_edge_name_pruning
        Keep kind-compatible candidate targets that share no outgoing
        edge name with the source vertex. See
        [find_correspondences][didactic.api.find_correspondences].

    Returns
    -------
    Correspondence or None
        The best-scoring correspondence, or ``None`` when no
        structure-preserving map exists under the given constraints.

    See Also
    --------
    find_correspondences : the full enumeration.
    """
    import panproto  # noqa: PLC0415

    found = panproto.find_best_morphism(
        src_schema,
        tgt_schema,
        anchors=anchors,
        monic=monic,
        epic=epic,
        iso=iso,
        relax_edge_name_pruning=relax_edge_name_pruning,
    )
    if found is None:
        return None
    return Correspondence(vertex_map=found.vertex_map, quality=float(found.quality))


__all__ = [
    "Correspondence",
    "best_correspondence",
    "find_correspondences",
]
