"""didactic-settings: typed application settings and config composition.

Class-based settings:

[Settings][didactic.settings.Settings]
    Base class for application settings; subclasses declare fields
    just like a [didactic.api.Model][didactic.api.Model].
[EnvSource][didactic.settings.EnvSource]
    A source that reads from environment variables.
[DotEnvSource][didactic.settings.DotEnvSource]
    A source that reads from a ``.env`` file.
[FileSource][didactic.settings.FileSource]
    A source that reads from a TOML / YAML / JSON file.
[CliSource][didactic.settings.CliSource]
    A source that reads from CLI arguments (``argparse``-shaped).

Composition engine:

[load_document][didactic.settings.load_document]
    Read one JSON, TOML or YAML document (YAML through the ``yaml``
    extra).
[resolve][didactic.settings.resolve]
    Interpolate ``${...}`` expressions against a tree; resolvers are
    registered with [register_resolver][didactic.settings.register_resolver]
    and may read the tree through [lookup][didactic.settings.lookup].
[parse_override][didactic.settings.parse_override] and
[parse_scalar][didactic.settings.parse_scalar]
    The ``key=value`` override syntax and the schema-free scalar grammar.
[Origin][didactic.settings.Origin] and [Layer][didactic.settings.Layer]
    The provenance record a leaf carries, and a document tagged with one.
"""

from didactic.settings import _resolvers as _builtin_resolvers
from didactic.settings._documents import load_document
from didactic.settings._errors import (
    CoercionError,
    ConfigError,
    InterpolationError,
    MissingFragmentError,
    OverrideSyntaxError,
    UnknownKeyError,
    UnknownVariantError,
)
from didactic.settings._interpolation import (
    ResolverFn,
    active_root,
    list_resolvers,
    lookup,
    register_resolver,
    resolve,
    resolve_traced,
    unregister_resolver,
)
from didactic.settings._provenance import Layer, Origin, OriginKind
from didactic.settings._scalars import decode_text, parse_override, parse_scalar
from didactic.settings._settings import (
    CliSource,
    DotEnvSource,
    EnvSource,
    FileSource,
    Settings,
)
from didactic.settings._values import ConfigValue, KeyPath, nest_override

# the built-in resolvers register themselves when their module is imported;
# the alias keeps that import explicit rather than incidental
_ = _builtin_resolvers

__version__ = "0.16.0"

__all__ = [
    "CliSource",
    "CoercionError",
    "ConfigError",
    "ConfigValue",
    "DotEnvSource",
    "EnvSource",
    "FileSource",
    "InterpolationError",
    "KeyPath",
    "Layer",
    "MissingFragmentError",
    "Origin",
    "OriginKind",
    "OverrideSyntaxError",
    "ResolverFn",
    "Settings",
    "UnknownKeyError",
    "UnknownVariantError",
    "__version__",
    "active_root",
    "decode_text",
    "list_resolvers",
    "load_document",
    "lookup",
    "nest_override",
    "parse_override",
    "parse_scalar",
    "register_resolver",
    "resolve",
    "resolve_traced",
    "unregister_resolver",
]
