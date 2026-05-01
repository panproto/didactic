"""Migration synthesis via ``panproto.auto_generate_lens``.

Auto-derive a candidate lens between two Models. The resulting lens
is suitable for review by a human, then registration via
[didactic.api.register_migration][didactic.api.register_migration].

Examples
--------
>>> import didactic.api as dx
>>> class V1(dx.Model):
...     id: str
...     name: str
>>> class V2(dx.Model):
...     id: str
...     full_name: str
>>>
>>> # synthesise; returns a candidate Lens plus a confidence score
>>> candidate = dx.synthesise_migration(V1, V2)  # doctest: +SKIP
>>> candidate.score  # doctest: +SKIP
0.85
>>> # if happy, register it
>>> dx.register_migration(V1, V2, candidate.lens)  # doctest: +SKIP

See Also
--------
didactic.register_migration : the manual-authoring counterpart.
panproto.auto_generate_lens : the runtime call.
"""

# panproto's ``auto_generate_lens`` returns ``tuple[..., dict[str, object]]``
# and we re-emit as ``tuple[JsonObject, ...]``; dict invariance bites.
# Tracked in panproto/didactic#1.
# pyright: reportArgumentType=false

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from didactic.models._model import Model
    from didactic.types._typing import JsonObject


@dataclass(frozen=True, slots=True)
class SynthesisResult:
    """The output of [synthesise_migration][didactic.api.synthesise_migration].

    Parameters
    ----------
    lens
        A panproto lens object. Treat as opaque; pass to
        [didactic.api.register_migration][didactic.api.register_migration]
        wrapped in a [didactic.api.Lens][didactic.api.Lens] subclass that
        delegates to it.
    score
        Alignment quality in ``[0.0, 1.0]``. Higher is better.
    proposals
        Auxiliary coercion proposals emitted under
        ``"exploratory"`` stringency; empty for stricter levels.
        Each proposal documents a candidate value-coercion suggested
        by the synthesiser.
    """

    lens: object
    score: float
    proposals: tuple[JsonObject, ...]


def synthesise_migration(
    source: type[Model],
    target: type[Model],
    *,
    stringency: str | None = None,
) -> SynthesisResult:
    """Auto-generate a candidate migration lens from ``source`` to ``target``.

    Parameters
    ----------
    source
        The earlier Model class.
    target
        The later Model class.
    stringency
        One of ``"strict"``, ``"balanced"``, ``"lenient"``,
        ``"exploratory"`` (case-insensitive). ``None`` uses panproto's
        default (``"balanced"``).

    Returns
    -------
    SynthesisResult
        The generated lens, its quality score, and any coercion
        proposals (only at ``"exploratory"``).

    Notes
    -----
    The synthesiser's output is *a candidate*, not a guaranteed
    correct migration. Always review before registering. For
    high-stakes migrations, prefer authoring the lens by hand and
    using the synthesiser only as a starting point.
    """
    import panproto  # noqa: PLC0415

    from didactic.vcs._repo import schema_from_model  # noqa: PLC0415

    src_schema = schema_from_model(source)
    tgt_schema = schema_from_model(target)

    # build a Protocol that covers both Models; reuse source's
    # synthesised protocol for symmetry
    protocol = panproto.Protocol.from_theories(
        name=f"{source.__name__}_to_{target.__name__}",
        schema_theory=source.__theory__,
        obj_kinds=["object"],
    )

    if stringency is None:
        result = panproto.auto_generate_lens(src_schema, tgt_schema, protocol)
    else:
        result = panproto.auto_generate_lens(
            src_schema,
            tgt_schema,
            protocol,
            stringency,
        )

    lens, score, proposals = result
    return SynthesisResult(
        lens=lens,
        score=float(score),
        proposals=tuple(proposals),
    )


__all__ = [
    "SynthesisResult",
    "synthesise_migration",
]
