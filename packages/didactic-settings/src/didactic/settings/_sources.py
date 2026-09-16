"""Settings sources: the environment, a dotenv file, a config file, the CLI.

Each source turns what it can see into one :class:`~didactic.settings.Layer`
(a nested document tagged ``source:<name>``) that ``Settings.load`` merges
above the overlays and below the overrides. The environment, dotenv and
CLI sources are textual: their string values are decoded by the leaf
annotation when the merge writes them.
"""

from __future__ import annotations

import argparse
import os
from dataclasses import KW_ONLY, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

from didactic.settings._documents import load_document
from didactic.settings._errors import ConfigError
from didactic.settings._provenance import Layer, Origin
from didactic.settings._schema import (
    Leaf,
    ListOf,
    MapOf,
    Nested,
    Target,
    UnionOf,
    settable_paths,
)
from didactic.settings._values import dotted

if TYPE_CHECKING:
    from collections.abc import Mapping

    import didactic.api as dx
    from didactic.settings._values import ConfigValue, KeyPath


class Source:
    """Base class of every settings source.

    Subclasses are frozen dataclasses that declare their own parameters
    and a ``name`` (recorded as ``Origin.name`` on every leaf the source
    sets; distinct within one ``Settings`` class) and implement
    :meth:`layer`.
    """

    __slots__ = ()

    name: str

    def layer(self, schema: type[dx.Model]) -> Layer | None:
        """Return the layer this source contributes, or ``None`` when empty.

        Parameters
        ----------
        schema
            The settings class being loaded; textual sources enumerate
            its settable paths.
        """
        msg = f"{type(self).__name__} does not implement layer()"
        raise NotImplementedError(msg)


@dataclass(frozen=True, slots=True)
class EnvSource(Source):
    """Read settings from environment variables.

    Every settable path of the schema (each leaf, and each model, union
    and map slot) is looked up as ``prefix`` plus the path segments
    joined by ``separator``, upper-cased: ``EnvSource(prefix="APP_")``
    reads ``trainer.epochs`` from ``APP_TRAINER__EPOCHS`` and the whole
    ``model.type_encoder`` slot from ``APP_MODEL__TYPE_ENCODER`` (JSON
    object text). Below a map slot, variables continuing the slot's name
    set entries: ``APP_PATHS__DATA_DIR`` sets ``paths["data_dir"]`` (the
    key is lower-cased, since variable names are upper-cased) and the
    segments after the key address the entry's own fields. Variables that
    name no path are never read.

    Parameters
    ----------
    prefix
        Text prepended to every variable name.
    separator
        Text joining the path segments.
    name
        The source name for provenance.
    """

    prefix: str = ""
    _: KW_ONLY
    separator: str = "__"
    name: str = "env"

    def layer(self, schema: type[dx.Model]) -> Layer | None:
        """Return the layer of every set variable, or ``None`` when none is."""
        document = paths_document(
            schema,
            os.environ,
            prefix=self.prefix,
            separator=self.separator,
            what="Environment variables",
        )
        if not document:
            return None
        return Layer(
            origin=Origin("source", name=self.name), document=document, textual=True
        )


@dataclass(frozen=True, slots=True)
class DotEnvSource(Source):
    """Read settings from a dotenv file.

    Lines are ``KEY=value``, optionally prefixed by ``export``; blank
    lines and ``#`` comments are skipped; a value wrapped in matching
    single or double quotes is unquoted. Keys are looked up exactly as
    :class:`EnvSource` looks up variables. A missing file contributes
    nothing.

    Parameters
    ----------
    path
        The dotenv file.
    prefix
        Text prepended to every key.
    separator
        Text joining the path segments.
    name
        The source name for provenance.
    """

    path: str | Path = ".env"
    prefix: str = ""
    _: KW_ONLY
    separator: str = "__"
    name: str = "dotenv"

    def layer(self, schema: type[dx.Model]) -> Layer | None:
        """Return the layer of every key the file sets, or ``None``."""
        file = Path(self.path)
        if not file.is_file():
            return None
        entries = parse_dotenv(file.read_text(encoding="utf-8"))
        document = paths_document(
            schema,
            entries,
            prefix=self.prefix,
            separator=self.separator,
            what=f"Keys in {file}",
        )
        if not document:
            return None
        return Layer(
            origin=Origin("source", name=self.name, path=str(file)),
            document=document,
            textual=True,
        )


@dataclass(frozen=True, slots=True)
class FileSource(Source):
    """Read settings from a JSON, TOML or YAML file.

    The whole document is the layer, checked against the schema at every
    depth like any other file; the file's ``defaults`` key is an ordinary
    key here, since only the primary ``path`` of ``Settings.load``
    carries a selection list.

    Parameters
    ----------
    path
        The file; its suffix selects the reader.
    name
        The source name for provenance.
    required
        Whether a missing file is an error rather than an empty source.
    """

    path: str | Path = "config.toml"
    _: KW_ONLY
    name: str = "file"
    required: bool = False

    def layer(self, schema: type[dx.Model]) -> Layer | None:
        """Return the document as a layer, or ``None`` when the file is absent.

        Raises
        ------
        FileNotFoundError
            When the file is absent and ``required`` is set.
        """
        _ = schema
        file = Path(self.path)
        if not file.exists():
            if self.required:
                msg = f"Configuration file not found: {file}"
                raise FileNotFoundError(msg)
            return None
        return Layer(
            origin=Origin("source", name=self.name, path=str(file)),
            document=load_document(file),
        )


@dataclass(frozen=True, slots=True)
class CliSource(Source):
    """Read settings from parsed command-line arguments.

    Keys are dotted paths or paths joined by ``__``; a ``None`` value
    means the argument was not given and is skipped. String values are
    decoded by the leaf annotation; typed values pass through.

    Parameters
    ----------
    args
        An ``argparse.Namespace`` or a mapping of argument values.
    name
        The source name for provenance.
    """

    args: argparse.Namespace | Mapping[str, ConfigValue] | None = None
    _: KW_ONLY
    name: str = "cli"

    def layer(self, schema: type[dx.Model]) -> Layer | None:
        """Return the layer of every argument that was given, or ``None``."""
        _ = schema
        if self.args is None:
            return None
        if isinstance(self.args, argparse.Namespace):
            items = cast("dict[str, ConfigValue]", vars(self.args))
        else:
            items = dict(self.args)
        document: dict[str, ConfigValue] = {}
        for key, value in items.items():
            if value is None:
                continue
            path = tuple(key.replace("__", ".").split("."))
            insert_path(document, path, value, what="CLI arguments", label=key)
        if not document:
            return None
        return Layer(
            origin=Origin("source", name=self.name), document=document, textual=True
        )


def parse_dotenv(text: str) -> dict[str, str]:
    """Parse dotenv text into a mapping."""
    entries: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        line = line.removeprefix("export ").lstrip()
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        entries[key.strip()] = value
    return entries


def paths_document(
    schema: type[dx.Model],
    variables: Mapping[str, str],
    *,
    prefix: str,
    separator: str,
    what: str,
) -> dict[str, ConfigValue]:
    """Build a document from the variables that name the schema's paths.

    Every settable path is rendered as ``prefix`` plus the segments
    joined by ``separator``, upper-cased, and looked up in ``variables``.
    Below a map slot, every variable continuing the slot's name sets an
    entry: the next segment, lower-cased, is the key and the remaining
    segments address the entry's own fields.

    Raises
    ------
    ConfigError
        When both a slot and a path below it are set, since the slot's
        text cannot also hold the nested value.
    """
    document: dict[str, ConfigValue] = {}
    for path, target in settable_paths(schema):
        variable = f"{prefix}{separator.join(path)}".upper()
        value = variables.get(variable)
        if value is not None:
            insert_path(document, path, value, what=what, label=variable)
        if isinstance(target, MapOf):
            for entry_path, entry_value, label in _map_entries(
                variables, variable + separator.upper(), path, target.inner, separator
            ):
                insert_path(document, entry_path, entry_value, what=what, label=label)
    return document


def _map_entries(
    variables: Mapping[str, str],
    head: str,
    path: KeyPath,
    inner: Target,
    separator: str,
) -> list[tuple[KeyPath, str, str]]:
    """Variables continuing a map slot's name, as ``(path, value, variable)``."""
    entries: list[tuple[KeyPath, str, str]] = []
    upper_separator = separator.upper()
    for variable, value in variables.items():
        if not variable.startswith(head) or len(variable) == len(head):
            continue
        key, _, rest = variable[len(head) :].partition(upper_separator)
        entry_path = (*path, key.lower())
        if not rest:
            entries.append((entry_path, value, variable))
            continue
        below = _entry_path(inner, rest, upper_separator)
        if below is not None:
            entries.append(((*entry_path, *below), value, variable))
    return entries


def _entry_path(target: Target, rest: str, separator: str) -> KeyPath | None:
    """Match the segments after a map key against the entry's own paths."""
    if isinstance(target, Leaf | ListOf):
        return None
    if isinstance(target, MapOf):
        key, _, below = rest.partition(separator)
        if not below:
            return (key.lower(),)
        under = _entry_path(target.inner, below, separator)
        return None if under is None else (key.lower(), *under)
    for sub_path, sub_target in _paths_below(target):
        rendered = separator.join(sub_path).upper()
        if rendered == rest:
            return sub_path
        if isinstance(sub_target, MapOf) and rest.startswith(rendered + separator):
            under = _entry_path(
                sub_target, rest[len(rendered) + len(separator) :], separator
            )
            return None if under is None else (*sub_path, *under)
    return None


def _paths_below(target: Nested | UnionOf) -> list[tuple[KeyPath, Target]]:
    """Enumerate the settable paths under a model or union target."""
    if isinstance(target, Nested):
        return list(settable_paths(target.model))
    paths: list[tuple[KeyPath, Target]] = []
    seen: set[KeyPath] = set()
    for variant in target.root.__variants__.values():
        for sub_path, sub_target in settable_paths(variant):
            if sub_path not in seen:
                seen.add(sub_path)
                paths.append((sub_path, sub_target))
    return paths


def insert_path(
    document: dict[str, ConfigValue],
    path: KeyPath,
    value: ConfigValue,
    *,
    what: str,
    label: str,
) -> None:
    """Write a value at a path, creating the dicts on the way.

    Raises
    ------
    ConfigError
        When a value already sits on the way to ``path`` or below it, so
        the two settings cannot both hold.
    """
    node = document
    for depth, segment in enumerate(path[:-1]):
        child = node.get(segment)
        if child is None:
            child = {}
            node[segment] = child
        elif not isinstance(child, dict):
            msg = (
                f"{what} set both {dotted(path[: depth + 1])!r} and "
                f"{dotted(path)!r} ({label}); set the whole slot or its fields, "
                "not both"
            )
            raise ConfigError(msg, path=dotted(path))
        node = child
    existing = node.get(path[-1])
    if isinstance(existing, dict):
        if isinstance(value, dict):
            for key, entry in value.items():
                insert_path(
                    existing,
                    (key,),
                    entry,
                    what=what,
                    label=label,
                )
            return
        msg = (
            f"{what} set both {dotted(path)!r} ({label}) and a path below it; "
            "set the whole slot or its fields, not both"
        )
        raise ConfigError(msg, path=dotted(path))
    node[path[-1]] = value


__all__ = [
    "CliSource",
    "DotEnvSource",
    "EnvSource",
    "FileSource",
    "Source",
    "insert_path",
    "parse_dotenv",
    "paths_document",
]
