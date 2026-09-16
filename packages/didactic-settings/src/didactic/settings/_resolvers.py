"""Built-in resolvers, registered when the package is imported.

The set mirrors OmegaConf's standard resolvers so configurations written
for OmegaConf load with minimal changes: ``oc.env``, ``oc.select``,
``oc.decode``, ``oc.deprecated``, ``oc.create``, ``oc.dict.keys`` and
``oc.dict.values``. ``oc.decode`` reads base64 text rather than
OmegaConf's typed decode; the typed reading is ``oc.create``.
"""

from __future__ import annotations

import base64
import binascii
import os
import warnings
from collections.abc import Mapping
from typing import TYPE_CHECKING, Final

from didactic.settings._errors import InterpolationError
from didactic.settings._interpolation import (
    MissingReferenceError,
    ResolverFn,
    active_path,
    lookup,
    register_resolver,
)
from didactic.settings._scalars import parse_scalar

if TYPE_CHECKING:
    from didactic.settings._values import ConfigValue


def _oc_env(*args: str) -> str:
    """``${oc.env:VAR}`` / ``${oc.env:VAR,default}``: an environment variable."""
    if not args:
        msg = "oc.env requires at least one argument"
        raise InterpolationError(msg)
    var = args[0]
    if var in os.environ:
        return os.environ[var]
    if len(args) >= 2:
        return ",".join(args[1:])
    msg = f"Environment variable {var!r} is not set and no default given"
    raise InterpolationError(msg)


def _oc_select(*args: str) -> ConfigValue:
    """``${oc.select:path}`` / ``${oc.select:path,default}``: a lenient lookup.

    Returns the value at ``path`` when it exists and is not ``None``;
    otherwise the default read with the scalar grammar, or ``None`` when
    no default is given.
    """
    if not args:
        msg = "oc.select requires a path and an optional default"
        raise InterpolationError(msg)
    try:
        value = lookup(args[0])
    except MissingReferenceError:
        value = None
    if value is not None:
        return value
    if len(args) >= 2:
        return parse_scalar(",".join(args[1:]))
    return None


def _oc_decode(*args: str) -> str:
    """``${oc.decode:value}`` / ``${oc.decode:value,encoding}``: decode text.

    ``base64`` (the default) decodes the value as base64-encoded UTF-8;
    ``ascii`` and ``utf-8`` pass the value through.
    """
    if not args:
        msg = "oc.decode requires at least a value"
        raise InterpolationError(msg)
    value = args[0]
    encoding = args[1] if len(args) >= 2 else "base64"
    if encoding == "base64":
        try:
            return base64.b64decode(value, validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError) as exc:
            msg = f"oc.decode: {value!r} is not base64-encoded UTF-8 text: {exc}"
            raise InterpolationError(msg) from exc
    if encoding in ("ascii", "utf-8"):
        return value
    msg = f"oc.decode: unknown encoding {encoding!r}"
    raise InterpolationError(msg)


_DEPRECATED_MESSAGE: Final = (
    "'$OLD_KEY' is deprecated. Change your code and config to use '$NEW_KEY'"
)


def _oc_deprecated(*args: str) -> ConfigValue:
    """``${oc.deprecated:new_path}`` / ``${oc.deprecated:new_path,message}``.

    Warns with ``DeprecationWarning`` and returns the value at
    ``new_path``. ``$OLD_KEY`` in the message is replaced by the path of
    the leaf holding the expression and ``$NEW_KEY`` by ``new_path``.
    """
    if not args:
        msg = "oc.deprecated requires a replacement path"
        raise InterpolationError(msg)
    new_path = args[0]
    template = ",".join(args[1:]) if len(args) >= 2 else _DEPRECATED_MESSAGE
    here = active_path()
    old_key = ".".join(str(segment) for segment in here) if here else "<root>"
    message = template.replace("$OLD_KEY", old_key).replace("$NEW_KEY", new_path)
    warnings.warn(message, DeprecationWarning, stacklevel=2)
    return lookup(new_path)


def _oc_create(*args: str) -> ConfigValue:
    """``${oc.create:text}``: read text with the scalar grammar.

    The plain-dict counterpart of OmegaConf's ``oc.create``: JSON lists
    and objects, numbers, booleans and ``null`` become typed values.
    """
    return parse_scalar(",".join(args))


def _mapping_at(name: str, args: tuple[str, ...]) -> Mapping[str, ConfigValue]:
    if not args:
        msg = f"{name} requires a path"
        raise InterpolationError(msg)
    value = lookup(args[0])
    if not isinstance(value, Mapping):
        msg = f"{name}: {args[0]!r} is not a mapping"
        raise InterpolationError(msg)
    return value


def _oc_dict_keys(*args: str) -> ConfigValue:
    """``${oc.dict.keys:path}``: the keys of the mapping at ``path``."""
    return list(_mapping_at("oc.dict.keys", args))


def _oc_dict_values(*args: str) -> ConfigValue:
    """``${oc.dict.values:path}``: the values of the mapping at ``path``."""
    return list(_mapping_at("oc.dict.values", args).values())


_BUILTINS: Final[dict[str, ResolverFn]] = {
    "oc.env": _oc_env,
    "oc.select": _oc_select,
    "oc.decode": _oc_decode,
    "oc.deprecated": _oc_deprecated,
    "oc.create": _oc_create,
    "oc.dict.keys": _oc_dict_keys,
    "oc.dict.values": _oc_dict_values,
}


def register_builtins(*, replace: bool = False) -> None:
    """Register every built-in resolver.

    Called at import with ``replace=True``; call it again to restore a
    built-in that was unregistered or shadowed.
    """
    for name, fn in _BUILTINS.items():
        register_resolver(name, fn, replace=replace)


register_builtins(replace=True)


__all__ = ["register_builtins"]
