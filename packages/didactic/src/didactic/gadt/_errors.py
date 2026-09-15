"""Errors raised while declaring or reducing a generalized algebraic theory."""

from __future__ import annotations


class GADTDeclarationError(ValueError):
    """A locally detectable error in a GADT declaration."""


class GADTReductionError(RuntimeError):
    """A symbolic reduction could not make safe progress."""


__all__ = ["GADTDeclarationError", "GADTReductionError"]
