"""didactic-settings: typed application settings and config composition.

Composition:

[compose][didactic.settings.compose] and
[compose_traced][didactic.settings.compose_traced]
    Compose a validated model from a primary file with its ``defaults:``
    list, config-group fragments, a profile, overlays, and dotted
    overrides; the traced form returns the tree, the per-leaf
    [Provenance][didactic.settings.Provenance] and the ladder of
    [Layer][didactic.settings.Layer] records as a
    [Composed][didactic.settings.Composed].
[compose_layers][didactic.settings.compose_layers] and
[strict_merge][didactic.settings.strict_merge]
    The engine over an assembled ladder, and the schema-aware merge of
    one mapping over another.
[provenance_of][didactic.settings.provenance_of]
    Read the record attached to an instance built by the engine.

Class-based settings:

[Settings][didactic.settings.Settings]
    Base class for application settings; subclasses declare fields
    just like a [didactic.api.Model][didactic.api.Model] and load
    through the engine.
[EnvSource][didactic.settings.EnvSource]
    A source that reads from environment variables.
[DotEnvSource][didactic.settings.DotEnvSource]
    A source that reads from a ``.env`` file.
[FileSource][didactic.settings.FileSource]
    A source that reads from a TOML / YAML / JSON file.
[CliSource][didactic.settings.CliSource]
    A source that reads from CLI arguments (``argparse``-shaped).

Building blocks:

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
[Origin][didactic.settings.Origin]
    The provenance record a leaf carries.
"""

from didactic.settings import _resolvers as _builtin_resolvers
from didactic.settings._compose import (
    Composed,
    compose,
    compose_layers,
    compose_traced,
)
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
from didactic.settings._merge import strict_merge
from didactic.settings._provenance import (
    Layer,
    Origin,
    OriginKind,
    Provenance,
    provenance_of,
)
from didactic.settings._scalars import decode_text, parse_override, parse_scalar
from didactic.settings._settings import Settings
from didactic.settings._sources import (
    CliSource,
    DotEnvSource,
    EnvSource,
    FileSource,
    Source,
)
from didactic.settings._values import ConfigValue, KeyPath, nest_override

# the built-in resolvers register themselves when their module is imported;
# the alias keeps that import explicit rather than incidental
_ = _builtin_resolvers

__version__ = "0.16.0"

__all__ = [
    "CliSource",
    "CoercionError",
    "Composed",
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
    "Provenance",
    "ResolverFn",
    "Settings",
    "Source",
    "UnknownKeyError",
    "UnknownVariantError",
    "__version__",
    "active_root",
    "compose",
    "compose_layers",
    "compose_traced",
    "decode_text",
    "list_resolvers",
    "load_document",
    "lookup",
    "nest_override",
    "parse_override",
    "parse_scalar",
    "provenance_of",
    "register_resolver",
    "resolve",
    "resolve_traced",
    "strict_merge",
    "unregister_resolver",
]
