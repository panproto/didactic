"""Document loading and the search-path lookup for fragments and profiles.

JSON and TOML are read with the standard library; YAML is read through
PyYAML, imported only when a ``.yaml`` or ``.yml`` file is opened, so a
composition over JSON and TOML never imports it.
"""

from __future__ import annotations

import importlib
import json
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, cast

from didactic.settings._errors import ConfigError, MissingFragmentError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from didactic.settings._values import ConfigValue

SUFFIXES: tuple[str, ...] = (".yaml", ".yml", ".toml", ".json")
"""Supported document suffixes, in the order a suffix-less name tries them."""


def load_document(path: Path | str) -> dict[str, ConfigValue]:
    """Load one JSON, TOML or YAML file as a document.

    Parameters
    ----------
    path
        The file; its suffix selects the reader.

    Returns
    -------
    dict[str, ConfigValue]
        The document. An empty file gives an empty document.

    Raises
    ------
    FileNotFoundError
        When ``path`` does not exist.
    ConfigError
        When the suffix is unsupported, when a YAML file is opened without
        PyYAML installed, or when the top-level value is not a mapping.
    """
    path = Path(path)
    if not path.exists():
        msg = f"Configuration file not found: {path}"
        raise FileNotFoundError(msg)
    suffix = path.suffix.lower()
    loaded: object
    if suffix == ".json":
        text = path.read_text(encoding="utf-8")
        loaded = json.loads(text) if text.strip() else None
    elif suffix == ".toml":
        with path.open("rb") as handle:
            loaded = tomllib.load(handle)
    elif suffix in (".yaml", ".yml"):
        try:
            yaml = importlib.import_module("yaml")
        except ImportError as exc:
            msg = f"Loading {path} requires PyYAML; install 'didactic-settings[yaml]'"
            raise ConfigError(msg) from exc
        with path.open(encoding="utf-8") as handle:
            loaded = cast("object", yaml.safe_load(handle))
    else:
        msg = (
            f"Unsupported config suffix {suffix!r} for {path}; "
            "expected .json, .toml, .yaml or .yml"
        )
        raise ConfigError(msg)
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        msg = f"Top-level config in {path} must be a mapping; got {_kind(loaded)}"
        raise ConfigError(msg)
    document = cast("dict[object, ConfigValue]", loaded)
    return {str(key): value for key, value in document.items()}


def _kind(value: object) -> str:
    return type(value).__name__


def candidate_paths(name: str, *, roots: Sequence[Path]) -> tuple[Path, ...]:
    """Every path a name may resolve to, in the order tried.

    A name carrying a supported suffix is tried verbatim under each root;
    a name without one is tried with each suffix in :data:`SUFFIXES`
    order under each root.
    """
    relative = Path(name)
    if relative.suffix.lower() in SUFFIXES:
        return tuple(root / relative for root in roots)
    return tuple(
        (root / relative).with_name(relative.name + suffix)
        for root in roots
        for suffix in SUFFIXES
    )


def locate(name: str, *, roots: Sequence[Path], subject: str) -> Path | None:
    """Find the file a name resolves to, or ``None`` when no root has it.

    Roots are searched in order and the first root holding a match wins.
    Within one root, two files sharing the stem with different suffixes
    are refused.

    Parameters
    ----------
    name
        A file name, with or without a supported suffix, relative to a
        root.
    roots
        The search roots, in order.
    subject
        How to name the thing being looked for in the ambiguity error
        (``"Fragment 'lstm' of config group 'model.type_encoder'"``).

    Raises
    ------
    ConfigError
        When one root holds more than one file for the name.
    """
    for root in roots:
        found = [
            candidate
            for candidate in candidate_paths(name, roots=[root])
            if candidate.is_file()
        ]
        if len(found) > 1:
            names = ", ".join(sorted(candidate.name for candidate in found))
            msg = f"{subject} is ambiguous: {names}"
            raise ConfigError(msg)
        if found:
            return found[0]
    return None


def find_fragment(entry: str, *, roots: Sequence[Path]) -> Path:
    """Resolve a root-mounted ``defaults`` entry against the search roots.

    Raises
    ------
    MissingFragmentError
        When no root holds the entry; the message lists every path tried.
    """
    found = locate(entry, roots=roots, subject=f"'defaults' entry {entry!r}")
    if found is not None:
        return found
    tried = candidate_paths(entry, roots=roots)
    msg = f"'defaults' entry {entry!r} not found; tried: " + ", ".join(
        str(candidate) for candidate in tried
    )
    raise MissingFragmentError(msg, group="", name=entry, tried=tried)


def find_profile(name: str, *, roots: Sequence[Path]) -> Path:
    """Resolve a profile name to ``profiles/<name>`` under the search roots.

    Raises
    ------
    MissingFragmentError
        When no root holds the profile; the message lists every path
        tried.
    """
    relative = str(Path("profiles") / name)
    found = locate(relative, roots=roots, subject=f"Profile {name!r}")
    if found is not None:
        return found
    tried = candidate_paths(relative, roots=roots)
    msg = f"Profile {name!r} not found; tried: " + ", ".join(
        str(candidate) for candidate in tried
    )
    raise MissingFragmentError(
        msg,
        group="profiles",
        name=name,
        tried=tried,
        available=list_stems([root / "profiles" for root in roots]),
    )


def list_stems(directories: Sequence[Path]) -> tuple[str, ...]:
    """Sorted, de-duplicated stems of the supported documents in directories."""
    stems = {
        candidate.stem
        for directory in directories
        if directory.is_dir()
        for candidate in directory.iterdir()
        if candidate.is_file() and candidate.suffix.lower() in SUFFIXES
    }
    return tuple(sorted(stems))


__all__ = [
    "SUFFIXES",
    "candidate_paths",
    "find_fragment",
    "find_profile",
    "list_stems",
    "load_document",
    "locate",
]
