"""Checked extension lowering for externally owned typed cores."""

from didactic.extensions._lowering import (
    ExtensionLowerer,
    LoweringRoute,
    UnsupportedLoweringRouteError,
    lower_checked,
    supports_lowering,
)

__all__ = [
    "ExtensionLowerer",
    "LoweringRoute",
    "UnsupportedLoweringRouteError",
    "lower_checked",
    "supports_lowering",
]
