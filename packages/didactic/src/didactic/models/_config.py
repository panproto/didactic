"""Class-level configuration for Models.

A ``ModelConfig`` carries settings that change Model behaviour without
changing field declarations: extra-fields policy, alias resolution,
strict-vs-lax coercion, and so on. v0.0.1 ships only the fields the
metaclass currently consults; the rest are stubbed for forward
compatibility.

Configuration is supplied either through ``__model_config__`` on the
class body or as keyword arguments on the class header::

    class User(dx.Model, extra="forbid"):
        id: str


    class Account(dx.Model):
        __model_config__ = dx.ModelConfig(extra="forbid")
        id: str

Both forms are equivalent.

Notes
-----
The only currently supported ``extra`` value is ``"forbid"`` (the
default). ``"ignore"`` and ``"allow"`` are reserved for later phases
and raise ``NotImplementedError`` on use.

See Also
--------
didactic.models._meta : the metaclass that reads ``__model_config__``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ExtraPolicy = Literal["forbid", "ignore", "allow"]


@dataclass(frozen=True, slots=True)
class ModelConfig:
    """Class-level configuration for a [Model][didactic.api.Model] subclass.

    Parameters
    ----------
    extra
        How to handle keyword arguments that don't match a declared
        field. Only ``"forbid"`` is honoured currently; ``"ignore"`` and
        ``"allow"`` raise ``NotImplementedError``.
    strict
        If ``True``, type coercion is disabled; every field's value
        must already be the declared type. Default ``True``. ``False``
        raises ``NotImplementedError`` until coercion lands.
    populate_by_name
        If ``True``, fields with an alias accept both the alias and the
        Python attribute name as input keys. Default ``False``.
    title
        Optional human-readable name for documentation / codegen.
    description
        Optional description rendered into Theory metadata.
    """

    extra: ExtraPolicy = "forbid"
    strict: bool = True
    populate_by_name: bool = False
    title: str | None = None
    description: str | None = None

    def __post_init__(self) -> None:
        """Validate config values against what v0.0.1 supports."""
        if self.extra not in {"forbid", "ignore", "allow"}:
            msg = (
                f"ModelConfig.extra must be 'forbid', 'ignore', or 'allow'; "
                f"got {self.extra!r}"
            )
            raise ValueError(msg)
        # v0.0.1 only honours `forbid`; fail loud on the unsupported settings
        if self.extra != "forbid":
            msg = (
                f"ModelConfig.extra={self.extra!r} is not yet implemented; "
                "only 'forbid' is honoured."
            )
            raise NotImplementedError(msg)
        if not self.strict:
            msg = (
                "ModelConfig.strict=False is not yet implemented; "
                "v0.0.1 always validates strictly."
            )
            raise NotImplementedError(msg)
        if self.populate_by_name:
            msg = "ModelConfig.populate_by_name=True is not yet implemented."
            raise NotImplementedError(msg)


DEFAULT_CONFIG = ModelConfig()
"""The configuration applied to a Model that does not specify one."""

__all__ = [
    "DEFAULT_CONFIG",
    "ExtraPolicy",
    "ModelConfig",
]
