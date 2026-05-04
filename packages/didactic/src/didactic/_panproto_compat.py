"""Typed wrappers around ``panproto`` API quirks.

Two functions in panproto's shipped ``_native.pyi`` (as of 0.43.0)
disagree with their runtime signatures. Calling them directly forces
either pyright suppressions or a sea of ``cast``s at every call site.
This module wraps each in a thin function whose static type matches
the runtime contract.

Tracked upstream as ``panproto/panproto#72``; once the stubs are
corrected and we bump the panproto pin, this module becomes a no-op
shim and can be deleted.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import panproto

if TYPE_CHECKING:
    from collections.abc import Mapping


def create_theory(spec: Mapping[str, object]) -> panproto.Theory:
    """Build a ``panproto.Theory`` from a spec mapping.

    The shipped panproto stub declares ``spec: dict[str, object]``,
    rejecting ``TypedDict`` instances (which ARE dicts at runtime,
    but pyright treats ``TypedDict`` and ``dict[str, object]`` as
    distinct). This wrapper widens the parameter to
    ``Mapping[str, object]`` (the runtime contract), so any
    ``TypedDict`` whose values are JSON-compatible passes through.
    """
    return panproto.create_theory(cast("dict[str, object]", spec))


def colimit_theories(
    t1: panproto.Theory,
    t2: panproto.Theory,
    shared: panproto.Theory,
) -> panproto.Theory:
    """Compute the colimit (pushout) of two theories over a shared sub-theory.

    The shipped panproto stub declares
    ``colimit_theories(theories: Sequence[Theory], /) -> Theory``,
    but the runtime function takes three positional ``Theory`` arguments
    (``t1``, ``t2``, ``shared``). This wrapper exposes the runtime
    contract.
    """
    fn = cast(
        "object", panproto.colimit_theories
    )  # widen so the call shape isn't checked against the stub
    return cast("panproto.Theory", fn(t1, t2, shared))  # type: ignore[operator]


__all__ = ["colimit_theories", "create_theory"]
