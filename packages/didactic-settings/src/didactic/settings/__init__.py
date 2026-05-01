"""didactic-settings: typed application settings.

Top-level surface:

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

Sources merge by lens-style precedence: later sources override
earlier ones, and each field's value records which source supplied
it via ``settings.__provenance__``.
"""

from didactic.settings._settings import (
    CliSource,
    DotEnvSource,
    EnvSource,
    FileSource,
    Settings,
)

__version__ = "0.1.1"

__all__ = [
    "CliSource",
    "DotEnvSource",
    "EnvSource",
    "FileSource",
    "Settings",
    "__version__",
]
