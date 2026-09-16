"""Exceptions raised by the composition engine.

Every subclass of :class:`ConfigError` carries structured attributes
(the dotted path, the allowed keys, the paths tried, and so on) so a
caller translating errors at a boundary never has to parse message text.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from didactic.settings._provenance import Origin


class ConfigError(ValueError):
    """A configuration is malformed or fails the engine's checks.

    Parameters
    ----------
    message
        The rendered error text.
    path
        Dotted path of the offending leaf, or ``None`` when the error is
        not about one leaf (a malformed ``defaults`` list, an unsupported
        file suffix, a missing config directory).
    """

    path: str | None

    def __init__(self, message: str, *, path: str | None = None) -> None:
        super().__init__(message)
        self.path = path


class UnknownKeyError(ConfigError):
    """A layer sets a key the schema does not declare at that path.

    Parameters
    ----------
    message
        The rendered error text.
    path
        Dotted path of the unknown key.
    allowed
        Sorted field names accepted at the enclosing node.
    declared_by
        Tags of the union variants that declare the key; empty when no
        variant does, or when the node is a plain model.
    set_by
        The origin of the layer that set the key.
    """

    allowed: tuple[str, ...]
    declared_by: tuple[str, ...]
    set_by: Origin | None

    def __init__(
        self,
        message: str,
        *,
        path: str,
        allowed: tuple[str, ...] = (),
        declared_by: tuple[str, ...] = (),
        set_by: Origin | None = None,
    ) -> None:
        super().__init__(message, path=path)
        self.allowed = allowed
        self.declared_by = declared_by
        self.set_by = set_by


class UnknownVariantError(ConfigError):
    """A discriminator names no registered variant, or is not a literal.

    Parameters
    ----------
    message
        The rendered error text.
    path
        Dotted path of the discriminator leaf.
    value
        The discriminator value as it arrived.
    registered
        The registered tags, rendered as strings and sorted.
    """

    value: object
    registered: tuple[str, ...]

    def __init__(
        self,
        message: str,
        *,
        path: str,
        value: object,
        registered: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message, path=path)
        self.value = value
        self.registered = registered


class MissingFragmentError(ConfigError):
    """A named fragment, root fragment or profile exists in no search root.

    Parameters
    ----------
    message
        The rendered error text.
    group
        The dotted slot of the config group; the empty string for a
        root-mounted ``defaults`` entry; ``"profiles"`` for a profile.
    name
        The fragment name that was looked for.
    tried
        Every path tried, in the order tried.
    available
        Sorted names that do exist for the group, across every root.
    """

    group: str
    name: str
    tried: tuple[Path, ...]
    available: tuple[str, ...]

    def __init__(
        self,
        message: str,
        *,
        group: str,
        name: str,
        tried: tuple[Path, ...],
        available: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message)
        self.group = group
        self.name = name
        self.tried = tried
        self.available = available


class OverrideSyntaxError(ConfigError):
    """A ``key=value`` override, or its value text, cannot be parsed."""


class CoercionError(ConfigError):
    """Text from a textual layer cannot be decoded for the leaf's annotation.

    Parameters
    ----------
    message
        The rendered error text.
    path
        Dotted path of the leaf.
    expected
        A rendering of the annotation the text had to satisfy.
    text
        The text that was refused.
    """

    expected: str
    text: str

    def __init__(self, message: str, *, path: str, expected: str, text: str) -> None:
        super().__init__(message, path=path)
        self.expected = expected
        self.text = text


class InterpolationError(ValueError):
    """An interpolation expression cannot be resolved.

    Raised for a reference to a path that does not exist in the composed
    tree, a call to an unregistered resolver, a resolver that raised, a
    cycle between references, or a syntax error in the expression.

    Parameters
    ----------
    message
        The rendered error text.
    path
        Path of the leaf whose text was being resolved when the error was
        raised; ``None`` when no leaf was being resolved (a direct call to
        :func:`~didactic.settings.lookup` outside an evaluation, a bare
        string passed to :func:`~didactic.settings.resolve`).
    """

    path: tuple[str | int, ...] | None

    def __init__(
        self, message: str, *, path: tuple[str | int, ...] | None = None
    ) -> None:
        super().__init__(message)
        self.path = path


__all__ = [
    "CoercionError",
    "ConfigError",
    "InterpolationError",
    "MissingFragmentError",
    "OverrideSyntaxError",
    "UnknownKeyError",
    "UnknownVariantError",
]
