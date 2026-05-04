"""Source-level parse and emit via ``panproto.AstParserRegistry``.

For every tree-sitter grammar panproto bundles, didactic can:

- **De-novo emit** a [Model][didactic.api.Model] class as fresh source via
  [emit_pretty][didactic.codegen.source.emit_pretty]. Walks the
  grammar's production rules; output is syntactically valid for any
  grammar that ships a ``grammar.json``.
- **Edit-pipeline emit**: parse real source, transform the schema,
  re-emit the bytes. Uses [emit][didactic.codegen.source.emit].
- **Parse** source bytes into a panproto Schema for inspection.
- Expose the parse-emit law as a [didactic.api.Lens][didactic.api.Lens] via
  [for_protocol][didactic.codegen.source.for_protocol].

Examples
--------
>>> import didactic.api as dx
>>> from didactic.codegen import source
>>>
>>> class User(dx.Model):
...     id: str
...     email: str
>>>
>>> rust_src = source.emit_pretty(User, target="rust")  # doctest: +SKIP

See Also
--------
didactic.codegen.io : instance-level codecs.
didactic.Model.emit_as : the unified entry point.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Callable

    from didactic.models._model import Model


def emit_pretty(model: type[Model], *, target: str) -> bytes:
    """Render ``model`` as fresh source in the named target language.

    Parameters
    ----------
    model
        A [Model][didactic.api.Model] subclass.
    target
        A panproto grammar name (e.g. ``"rust"``, ``"typescript"``,
        ``"python"``). Use
        [available_targets][didactic.codegen.source.available_targets]
        to enumerate.

    Returns
    -------
    bytes
        Source code that the target grammar accepts as syntactically
        valid.

    Raises
    ------
    panproto.PanprotoError
        If the grammar rejects the schema (typically because the
        grammar lacks a ``grammar.json`` for de-novo emission).

    Notes
    -----
    The output is *syntactically* valid; idiomatic formatting (rustfmt
    spacing rules, gofmt conventions) is left to a post-processor.
    Configure one in ``pyproject.toml`` under
    ``[tool.didactic.emit.targets.{target}.post_process]``.
    """
    import panproto  # noqa: PLC0415

    from didactic.vcs._repo import schema_from_model  # noqa: PLC0415

    registry = panproto.AstParserRegistry()
    schema = schema_from_model(model)
    return registry.emit_pretty(target, schema)


def emit(schema: object, *, protocol: str) -> bytes:
    """Re-emit a parse-recovered ``schema`` as source bytes.

    Parameters
    ----------
    schema
        A ``panproto.Schema`` previously returned by
        [parse][didactic.codegen.source.parse]. The schema must carry
        byte-position fragments from the parse step.
    protocol
        The grammar name to emit under (typically the same as the
        parse step).

    Returns
    -------
    bytes
        The reconstructed source.

    Notes
    -----
    Use this for edit pipelines (parse, transform, emit). For fresh
    emission from a Model class, use
    [emit_pretty][didactic.codegen.source.emit_pretty].
    """
    import panproto  # noqa: PLC0415

    registry = panproto.AstParserRegistry()
    # ``schema`` is typed ``object`` in the public signature (carve-out
    # for the opaque panproto handle); the runtime contract is that it
    # came from a previous ``parse`` call and is a real ``Schema``.
    return registry.emit(protocol, cast("panproto.Schema", schema))


def parse(source: bytes, *, protocol: str, file_path: str = "<source>") -> object:
    """Parse source bytes into a ``panproto.Schema``.

    Parameters
    ----------
    source
        The source bytes to parse.
    protocol
        The grammar name (e.g. ``"rust"``, ``"typescript"``).
    file_path
        A filename for error messages. Does not need to exist.

    Returns
    -------
    panproto.Schema
        The parsed schema with byte-position fragments. Pass to
        [emit][didactic.codegen.source.emit] to re-emit, or to
        [didactic.codegen.source.for_protocol][] for lens-style
        round-trip checks.
    """
    import panproto  # noqa: PLC0415

    registry = panproto.AstParserRegistry()
    return registry.parse_with_protocol(protocol, source, file_path)


def available_targets() -> list[str]:
    """List every grammar the running panproto build supports.

    Returns
    -------
    list of str
        Grammar names, sorted. ``"rust"``, ``"typescript"``, ``"go"``,
        ``"python"``, etc.
    """
    import panproto  # noqa: PLC0415

    return sorted(panproto.available_grammars())


def detect_language(path: str) -> str | None:
    """Return the grammar name that handles ``path``'s extension, if any."""
    import panproto  # noqa: PLC0415

    registry = panproto.AstParserRegistry()
    return registry.detect_language(path)


def for_protocol(protocol: str) -> Callable[[bytes], object]:
    """Build a parse function bound to ``protocol``.

    Parameters
    ----------
    protocol
        The grammar name.

    Returns
    -------
    Callable
        A function that takes source bytes and returns a Schema. Use
        in lens compositions or as a partial-application helper.
    """
    import panproto  # noqa: PLC0415

    registry = panproto.AstParserRegistry()
    lens = registry.lens(protocol)

    def _parse(data: bytes) -> object:
        return lens.parse(data)

    return _parse


__all__ = [
    "available_targets",
    "detect_language",
    "emit",
    "emit_pretty",
    "for_protocol",
    "parse",
]
