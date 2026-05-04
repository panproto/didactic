# ``CliSource`` accepts either an ``argparse.Namespace`` or a Mapping,
# but pyright's ``Namespace`` stub ascribes a list-of-bytes shape to
# ``vars(ns)`` items and rejects the dict comprehension. ``ModelConfig``
# kwargs are constructed from a heterogeneous JSON dict and pyright
# can't narrow each kwarg-value to its own ``Literal`` parameter
# without per-key conditionals. Both are noise; tracked in
# panproto/didactic#1.
"""Settings sources and the ``Settings`` base class.

A ``Settings`` subclass declares fields like a regular
[didactic.api.Model][didactic.api.Model], plus a class-level
``__sources__`` tuple of sources to consult. ``Settings.load()``
walks the sources in order, collecting per-field overrides; later
sources win, and each field's resolved value records its provenance.

See Also
--------
didactic.Model : the base from which Settings inherits all field machinery.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Self, cast

import didactic.api as dx

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from didactic.fields._fields import FieldSpec
    from didactic.types._typing import FieldValue, JsonObject, JsonValue, Opaque


@dataclass(frozen=True, slots=True)
class _Source:
    """Base class marker for settings sources."""

    name: str

    def fetch(self, fields: Sequence[str]) -> JsonObject:
        """Return ``{field: value}`` for each field this source supplies.

        Subclasses override; the base raises to flag a misconfigured source.
        """
        msg = f"{type(self).__name__} does not implement fetch()"
        raise NotImplementedError(msg)


@dataclass(frozen=True, slots=True)
class EnvSource(_Source):
    """Read settings from environment variables.

    Parameters
    ----------
    prefix
        Prefix applied to each field name to compute the env var.
        ``EnvSource(prefix="APP_")`` reads ``port`` from ``APP_PORT``.
    name
        Optional source name for provenance reporting.
    """

    prefix: str = ""
    name: str = "env"

    def fetch(self, fields: Sequence[str]) -> JsonObject:
        """Return ``{field: env_value}`` for fields whose env var is set."""
        out: JsonObject = {}
        for fname in fields:
            key = f"{self.prefix}{fname}".upper()
            if key in os.environ:
                out[fname] = os.environ[key]
        return out


@dataclass(frozen=True, slots=True)
class DotEnvSource(_Source):
    """Read settings from a ``.env`` file.

    Parameters
    ----------
    path
        Path to the dotenv file.
    prefix
        Prefix applied to each field name.
    name
        Optional source name for provenance reporting.
    """

    path: str = ".env"
    prefix: str = ""
    name: str = "dotenv"

    def fetch(self, fields: Sequence[str]) -> JsonObject:
        """Return ``{field: value}`` from the file."""
        path = Path(self.path)
        if not path.exists():
            return {}
        env: dict[str, str] = {}
        for raw_line in path.read_text().splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip().strip("'\"")
        out: JsonObject = {}
        for fname in fields:
            key = f"{self.prefix}{fname}".upper()
            if key in env:
                out[fname] = env[key]
        return out


@dataclass(frozen=True, slots=True)
class FileSource(_Source):
    """Read settings from a structured config file (JSON / TOML / YAML).

    Parameters
    ----------
    path
        Path to the file. Format detected by suffix.
    name
        Optional source name for provenance reporting.
    """

    path: str = "config.toml"
    name: str = "file"

    def fetch(self, fields: Sequence[str]) -> JsonObject:
        """Return ``{field: value}`` from the file."""
        path = Path(self.path)
        if not path.exists():
            return {}
        text = path.read_text()
        suffix = path.suffix.lower()
        if suffix == ".json":
            data = json.loads(text)
        elif suffix == ".toml":
            import tomllib  # noqa: PLC0415

            data = tomllib.loads(text)
        elif suffix in (".yaml", ".yml"):
            import importlib  # noqa: PLC0415

            try:
                yaml_mod = importlib.import_module("yaml")
            except ImportError as exc:  # pragma: no cover
                msg = (
                    "FileSource cannot load YAML files without the optional "
                    "`yaml` extra; install didactic-settings[yaml]"
                )
                raise ImportError(msg) from exc
            data = cast("Opaque", yaml_mod.safe_load(text))
        else:
            msg = f"unsupported FileSource suffix: {suffix!r}"
            raise ValueError(msg)
        if not isinstance(data, dict):
            kind = type(data).__name__
            msg = f"FileSource expects a top-level mapping; got {kind}"
            raise TypeError(msg)
        # Each loader (``json.loads``, ``tomllib.loads``, ``yaml.safe_load``)
        # returns an opaque mapping at the type level; the values are
        # ``JsonValue``-shaped at runtime and forwarded as such.
        raw_dict = cast("dict[Opaque, Opaque]", data)
        typed_data: dict[str, JsonValue] = {
            str(k): cast("JsonValue", v) for k, v in raw_dict.items()
        }
        return {k: v for k, v in typed_data.items() if k in fields}


@dataclass(frozen=True, slots=True)
class CliSource(_Source):
    """Read settings from a parsed argparse ``Namespace`` (or dict).

    Parameters
    ----------
    args
        A mapping (or argparse.Namespace) supplying field values.
    name
        Optional source name for provenance reporting.
    """

    # ``argparse.Namespace`` and ``Mapping``s are both accepted at
    # runtime: ``fetch`` calls ``vars(self.args)`` for objects with
    # ``__dict__`` and ``dict(self.args)`` otherwise. The static type
    # is widened accordingly.
    args: argparse.Namespace | Mapping[str, FieldValue] | None = None
    name: str = "cli"

    def fetch(self, fields: Sequence[str]) -> JsonObject:
        """Return ``{field: value}`` from the args mapping."""
        if self.args is None:
            return {}
        # ``argparse.Namespace`` exposes its values via ``vars`` (``__dict__``);
        # plain mappings go through ``dict``. Either path lands at a
        # ``dict[str, object]`` view with JSON-shaped values.
        if isinstance(self.args, argparse.Namespace):
            raw_items: dict[str, Opaque] = vars(self.args)
        else:
            raw_items = {str(k): v for k, v in self.args.items()}
        return {
            k: cast("JsonValue", v)
            for k, v in raw_items.items()
            if k in fields and v is not None
        }


class Settings(dx.Model):
    """Base class for application settings.

    Subclasses declare fields like any [didactic.api.Model][didactic.api.Model],
    plus a class-level ``__sources__`` tuple. Call
    [Settings.load][didactic.settings.Settings.load] to populate from
    the configured sources.

    Examples
    --------
    >>> import didactic.api as dx
    >>> from didactic.settings import Settings, EnvSource
    >>>
    >>> class App(Settings):
    ...     debug: bool = False
    ...     port: int = 8080
    ...
    ...     __sources__ = (EnvSource(prefix="APP_"),)

    Attributes
    ----------
    __provenance__
        Per-instance dict mapping each field name to the name of the
        source that supplied its value. Fields that fell through to
        the declared default get ``"default"``.
    """

    __sources__: ClassVar[tuple[_Source, ...]] = ()

    # Per-instance attribute set by ``load`` via ``object.__setattr__``;
    # declared here at runtime (not as an annotation) so the
    # ``dataclass_transform`` metaclass does not see it as a Model field.
    if TYPE_CHECKING:

        @property
        def __provenance__(self) -> dict[str, str]:
            """Per-instance source map; populated by ``load``."""
            ...

    @classmethod
    def load(cls, **overrides: FieldValue) -> Self:
        """Construct a Settings instance by merging every source.

        Parameters
        ----------
        **overrides
            Per-field overrides that take final precedence over every
            registered source.

        Returns
        -------
        Settings
            The validated Settings instance, with ``__provenance__``
            populated.
        """
        field_names = tuple(cls.__field_specs__)
        merged: dict[str, FieldValue] = {}
        provenance: dict[str, str] = {}

        for source in cls.__sources__:
            chunk = source.fetch(field_names)
            for k, v in chunk.items():
                merged[k] = _coerce_value(v, cls.__field_specs__[k])
                provenance[k] = source.name

        for k, v in overrides.items():
            merged[k] = v
            provenance[k] = "override"

        # mark fields that fell through to the declared default
        for fname in field_names:
            provenance.setdefault(fname, "default")

        instance = cls(**merged)
        # bypass the frozen-by-design guard to attach provenance metadata
        object.__setattr__(instance, "__provenance__", provenance)
        return instance


def _coerce_value(raw: JsonValue, spec: FieldSpec) -> FieldValue:
    """Coerce string values from env / dotenv / cli into the spec's type.

    Notes
    -----
    Environment variables and dotenv lines arrive as strings even when
    the target field type is ``int`` / ``bool`` / ``float``. This
    helper does the obvious coercions; richer parsing (JSON-shaped
    values, comma-separated tuples, etc.) is the field-converter's
    responsibility.
    """
    if isinstance(raw, str):
        annotation = spec.annotation
        if annotation is bool:
            lowered = raw.strip().lower()
            return lowered in {"1", "true", "yes", "on"}
        if annotation is int:
            return int(raw)
        if annotation is float:
            return float(raw)
    # Non-string ``JsonValue`` payloads (booleans, numbers, nested
    # mappings / lists from JSON / TOML / YAML) are forwarded as-is. The
    # ``FieldValue`` union and the ``JsonValue`` union overlap on every
    # primitive shape and on nested dicts; ``list[...]`` arms are
    # converted to tuples downstream by the field translation.
    return cast("FieldValue", raw)


__all__ = [
    "CliSource",
    "DotEnvSource",
    "EnvSource",
    "FileSource",
    "Settings",
]
