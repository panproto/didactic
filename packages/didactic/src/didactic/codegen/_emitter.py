"""Custom emitter framework.

A custom emitter is a Python class registered under a target name.
Once registered, the same target name dispatches through
[Model.emit_as][didactic.api.Model.emit_as], the bulk
[didactic.codegen.write][didactic.codegen.write] exporter, and the
``didactic emit`` CLI.

Three discovery paths, in priority order:

1. Decorator registration (``@dx.codegen.emitter("name")`` on a class).
2. Explicit registration (``dx.codegen.register_emitter("name", cls)``).
3. ``pyproject.toml`` entry points under
   ``[project.entry-points."didactic.emitters"]``.

Examples
--------
>>> import didactic.api as dx
>>> from didactic.codegen import emitter, IndentWriter
>>>
>>> @emitter("graphql_lite")
... class GraphQLEmitter:
...     file_extension = "graphql"
...
...     def emit_class(self, cls):
...         w = IndentWriter()
...         w.line(f"type {cls.__name__} {{")
...         with w.indent():
...             for name, spec in cls.__field_specs__.items():
...                 w.line(f"{name}: {spec.translation.sort}")
...         w.line("}")
...         return w.bytes()
>>>
>>> class User(dx.Model):
...     id: str
>>>
>>> User.emit_as("graphql_lite")  # doctest: +SKIP

See Also
--------
didactic.Model.emit_as : the unified emission entry point.
"""

from __future__ import annotations

from importlib import metadata
from typing import TYPE_CHECKING, Protocol, cast, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Callable

    from didactic.models._model import Model


@runtime_checkable
class Emitter(Protocol):
    """The protocol every custom emitter implements.

    Attributes
    ----------
    file_extension
        A class-level attribute naming the canonical filename
        extension for this emitter (``"avsc"``, ``"ts"``,
        ``"graphql"``). Used by
        [didactic.codegen.write][didactic.codegen.write] when no
        explicit filename template is given.

    Notes
    -----
    Implement either or both of [emit_class][didactic.codegen.Emitter.emit_class]
    (Model class -> bytes) and [emit_instance][didactic.codegen.Emitter.emit_instance]
    (Model instance -> bytes). Calls to the missing direction raise
    ``NotImplementedError``.
    """

    file_extension: str

    def emit_class(self, cls: type[Model]) -> bytes:
        """Emit a Model class as bytes (e.g. a schema declaration)."""
        ...

    def emit_instance(self, instance: Model) -> bytes:
        """Emit a Model instance as bytes (e.g. a serialised value)."""
        ...


# global registry; populated by @emitter and register_emitter, plus
# entry-point discovery on first lookup
_REGISTRY: dict[str, Emitter] = {}
_entry_points_loaded = False


def emitter[E: Emitter](name: str) -> Callable[[type[E]], type[E]]:
    """Register a class as the emitter for ``name``.

    Parameters
    ----------
    name
        The target name (e.g. ``"graphql_lite"``,
        ``"sql_postgres"``). Used in
        [Model.emit_as][didactic.api.Model.emit_as].

    Returns
    -------
    decorator
        A class decorator that calls
        [register_emitter][didactic.codegen.register_emitter] with
        an instance of the decorated class.

    Examples
    --------
    >>> from didactic.codegen import emitter
    >>>
    >>> @emitter("yaml_compact")
    ... class YamlCompactEmitter:
    ...     file_extension = "yaml"
    ...
    ...     def emit_class(self, cls):
    ...         return b""  # implementation
    """

    def _decorator(cls: type[E]) -> type[E]:
        register_emitter(name, cls())
        return cls

    return _decorator


def register_emitter(name: str, instance: Emitter) -> None:
    """Register ``instance`` as the emitter for ``name``.

    Parameters
    ----------
    name
        The target name.
    instance
        An object that satisfies the [Emitter][didactic.codegen.Emitter]
        protocol.

    Raises
    ------
    TypeError
        If ``instance`` does not satisfy the protocol.
    """
    # Defensive: callers from third-party plugin entry points may pass
    # any object. The cast disables narrowing for the runtime check that
    # guards the TypeError.
    if not isinstance(cast("object", instance), Emitter):
        msg = (
            f"register_emitter({name!r}, ...) expects an Emitter; got "
            f"{type(instance).__name__}"
        )
        raise TypeError(msg)
    _REGISTRY[name] = instance


def lookup_emitter(name: str) -> Emitter | None:
    """Return the emitter registered under ``name``, or ``None``.

    Parameters
    ----------
    name
        The target name.

    Returns
    -------
    Emitter or None
        The registered emitter; ``None`` if no emitter is registered
        for that name.

    Notes
    -----
    The first call also loads any
    ``[project.entry-points."didactic.emitters"]`` entries from
    installed distributions.
    """
    global _entry_points_loaded  # noqa: PLW0603
    if not _entry_points_loaded:
        _entry_points_loaded = True
        for ep in metadata.entry_points(group="didactic.emitters"):
            try:
                cls = ep.load()
                register_emitter(ep.name, cls() if isinstance(cls, type) else cls)
            except Exception:  # pragma: no cover
                # entry-point loading errors are non-fatal; the
                # caller can still register manually
                continue
    return _REGISTRY.get(name)


def list_emitters() -> list[str]:
    """List every registered emitter name."""
    # ensure entry points have been loaded
    lookup_emitter("__nonexistent__")
    return sorted(_REGISTRY.keys())


# -- IndentWriter ------------------------------------------------------


class IndentWriter:
    r"""A small buffer with managed indentation for emitter authors.

    Mirrors ``panproto_protocols::emit::IndentWriter`` from the
    panproto Rust crate. Use as the standard helper for emitting
    nested format text.

    Parameters
    ----------
    indent_str
        The string used for each indent level. Defaults to four
        spaces.

    Examples
    --------
    >>> w = IndentWriter()
    >>> w.line("class Foo:")
    >>> with w.indent():
    ...     w.line("x: int")
    >>> w.text_str()
    'class Foo:\\n    x: int\\n'
    """

    __slots__ = ("_buf", "_indent_str", "_level")

    def __init__(self, indent_str: str = "    ") -> None:
        self._buf: list[str] = []
        self._level: int = 0
        self._indent_str: str = indent_str

    def line(self, text: str = "") -> None:
        r"""Emit ``text`` at the current indent level, followed by ``\n``."""
        if text:
            self._buf.append(self._indent_str * self._level)
            self._buf.append(text)
        self._buf.append("\n")

    def text(self, text: str) -> None:
        """Emit ``text`` without trailing newline. No indentation applied."""
        self._buf.append(text)

    def indent(self) -> _IndentCtx:
        """Return a context manager that increases the indent level."""
        return _IndentCtx(self)

    def text_str(self) -> str:
        """Finalise the buffer to a string."""
        return "".join(self._buf)

    def bytes(self) -> bytes:
        """Finalise the buffer to UTF-8 bytes."""
        return self.text_str().encode("utf-8")

    def push_indent(self) -> None:
        """Increase the indent level by one. Prefer ``with w.indent():``."""
        self._level += 1

    def pop_indent(self) -> None:
        """Decrease the indent level by one. Prefer ``with w.indent():``."""
        self._level -= 1


class _IndentCtx:
    """Context manager that wraps a single indent step."""

    __slots__ = ("_writer",)

    def __init__(self, writer: IndentWriter) -> None:
        self._writer = writer

    def __enter__(self) -> IndentWriter:
        self._writer.push_indent()
        return self._writer

    def __exit__(self, *_: object) -> None:
        self._writer.pop_indent()


__all__ = [
    "Emitter",
    "IndentWriter",
    "emitter",
    "list_emitters",
    "lookup_emitter",
    "register_emitter",
]
