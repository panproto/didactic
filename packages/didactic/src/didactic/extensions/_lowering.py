"""Versioned, fail-closed lowering for compiler extensions.

Didactic does not need to own every source language or typed core that passes
through it. An extension lowerer owns those semantics: it checks a source,
projects the checked result into its target core, and validates that target.
This module supplies the small orchestration boundary that keeps those three
stages ordered and rejects unsupported version pairs before any stage runs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class LoweringRoute:
    """Describe one exact source-to-target version pair.

    Parameters
    ----------
    source_version
        Exact version identifier for the source language.
    target_version
        Exact version identifier for the target representation.

    Raises
    ------
    ValueError
        If either version identifier is empty.
    """

    source_version: str
    target_version: str

    def __post_init__(self) -> None:
        if not self.source_version:
            msg = "a lowering source version cannot be empty"
            raise ValueError(msg)
        if not self.target_version:
            msg = "a lowering target version cannot be empty"
            raise ValueError(msg)


class UnsupportedLoweringRouteError(ValueError):
    """A lowerer was asked to accept an undeclared version pair."""


class ExtensionLowerer[SourceT, CheckedT, TargetT](Protocol):
    """A source-owned checker and lowering pass for one exact route.

    ``check`` and ``validate`` are deliberately part of the protocol. Didactic
    does not inspect or rewrite the checked and target values, so nominal
    identifiers, provenance, equality evidence, and effect information remain
    under the extension's typed representation.
    """

    @property
    def route(self) -> LoweringRoute:
        """Return the one version pair implemented by this lowerer.

        Returns
        -------
        LoweringRoute
            The exact source and target versions accepted by the lowerer.
        """
        ...

    def check(self, source: SourceT, /) -> CheckedT:
        """Check the source and return an extension-defined checked value.

        Parameters
        ----------
        source
            Source value owned by the extension.

        Returns
        -------
        CheckedT
            The extension's checked representation.
        """
        ...

    def lower(self, checked: CheckedT, /) -> TargetT:
        """Project a checked source into the extension-defined target core.

        Parameters
        ----------
        checked
            Checked source representation produced by
            [check][didactic.extensions.ExtensionLowerer.check].

        Returns
        -------
        TargetT
            The extension's target representation.
        """
        ...

    def validate(self, target: TargetT, /) -> None:
        """Reject a malformed target or an invariant lost during lowering.

        Parameters
        ----------
        target
            Target representation produced by
            [lower][didactic.extensions.ExtensionLowerer.lower].
        """
        ...


def supports_lowering[SourceT, CheckedT, TargetT](
    lowerer: ExtensionLowerer[SourceT, CheckedT, TargetT],
    /,
    *,
    source_version: str,
    target_version: str,
) -> bool:
    """Return whether a lowerer implements exactly the requested route.

    Parameters
    ----------
    lowerer
        Extension lowerer to inspect.
    source_version
        Required source-language version.
    target_version
        Required target-representation version.

    Returns
    -------
    bool
        Whether both requested versions exactly match the lowerer's route.
    """
    return lowerer.route == LoweringRoute(source_version, target_version)


def lower_checked[SourceT, CheckedT, TargetT](
    source: SourceT,
    lowerer: ExtensionLowerer[SourceT, CheckedT, TargetT],
    /,
    *,
    source_version: str,
    target_version: str,
) -> TargetT:
    """Check, lower, and validate one extension-owned source value.

    Version negotiation is exact and occurs before checking. Exceptions from
    any extension stage propagate unchanged, preserving the source checker's
    diagnostic type and preventing later stages from running after a failure.

    Parameters
    ----------
    source
        Extension-owned source value to check and lower.
    lowerer
        Lowerer that owns the source and target semantics.
    source_version
        Exact source-language version required by the caller.
    target_version
        Exact target-representation version required by the caller.

    Returns
    -------
    TargetT
        Validated target value returned by the lowerer.

    Raises
    ------
    UnsupportedLoweringRouteError
        If the requested version pair differs from the lowerer's route.
    """
    requested = LoweringRoute(source_version, target_version)
    if lowerer.route != requested:
        raise UnsupportedLoweringRouteError(
            f"unsupported lowering route {source_version!r} -> "
            f"{target_version!r}; lowerer provides "
            f"{lowerer.route.source_version!r} -> {lowerer.route.target_version!r}"
        )
    checked = lowerer.check(source)
    target = lowerer.lower(checked)
    lowerer.validate(target)
    return target


__all__ = [
    "ExtensionLowerer",
    "LoweringRoute",
    "UnsupportedLoweringRouteError",
    "lower_checked",
    "supports_lowering",
]
