"""Bulk export: write Models to disk under multiple targets.

The user-facing entry point [didactic.codegen.write][] takes an
iterable of Model classes and a mapping of ``target -> directory``,
and writes one file per (model, target) pair.

Examples
--------
>>> import didactic.api as dx
>>> class User(dx.Model):
...     id: str
>>> dx.codegen.write(  # doctest: +SKIP
...     [User],
...     targets={"avro": "schemas/avro/", "json_schema": "schemas/json/"},
... )
"""

# Defensive ``isinstance(payload, bytes)`` on a parameter pyright
# narrows to ``bytes`` already; runtime callers may bypass.
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from didactic.models._model import Model

# canonical filename extensions per target name
_DEFAULT_EXTENSIONS: dict[str, str] = {
    "avro": "avsc",
    "json_schema": "schema.json",
    "openapi": "openapi.yaml",
    "protobuf": "proto",
    "rust": "rs",
    "typescript": "ts",
    "python": "py",
    "go": "go",
    "java": "java",
    "javascript": "js",
    "cpp": "cpp",
    "c": "c",
    "bash": "sh",
    "graphql": "graphql",
    "yaml": "yaml",
    "toml": "toml",
}


def write(
    models: Iterable[type[Model]],
    targets: Mapping[str, str],
    *,
    filename: str = "{model_name}.{ext}",
) -> dict[str, Path]:
    """Emit each ``model`` under each ``target``, writing files to disk.

    Parameters
    ----------
    models
        The Model classes to emit.
    targets
        Mapping of ``target_name -> output_directory``. Each
        directory is created if it does not exist.
    filename
        A format string for filenames. Available placeholders:
        ``{model_name}`` (the class name as written),
        ``{model_snake_case}`` (snake-case of the class name), and
        ``{ext}`` (the canonical extension for the target).

    Returns
    -------
    dict
        Map of ``"{target}/{model_name}"`` to the absolute Path
        written.

    Raises
    ------
    LookupError
        If ``Model.emit_as`` does not know how to emit one of the
        ``(model, target)`` pairs.
    """
    written: dict[str, Path] = {}
    for target, out_dir in targets.items():
        out_path = Path(out_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        ext = _extension_for(target)
        for model in models:
            filename_str = filename.format(
                model_name=model.__name__,
                model_snake_case=_snake_case(model.__name__),
                ext=ext,
            )
            path = out_path / filename_str
            payload = model.emit_as(target)
            path.write_bytes(payload)
            written[f"{target}/{model.__name__}"] = path.resolve()
    return written


def _extension_for(target: str) -> str:
    """Return the canonical extension for ``target``.

    Falls back to ``target`` itself if no canonical mapping exists.
    """
    return _DEFAULT_EXTENSIONS.get(target, target)


def _snake_case(name: str) -> str:
    """Convert ``CamelCase`` to ``snake_case``."""
    out: list[str] = []
    for i, ch in enumerate(name):
        if ch.isupper() and i > 0 and not name[i - 1].isupper():
            out.append("_")
        out.append(ch.lower())
    return "".join(out)


__all__ = [
    "write",
]
