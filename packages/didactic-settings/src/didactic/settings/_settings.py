"""The ``Settings`` base class: a model loaded through the composition engine.

A ``Settings`` subclass declares fields like a regular
[didactic.api.Model][didactic.api.Model], plus a class-level
``__sources__`` tuple of sources to consult and an optional
``__search_path__`` of directories holding fragments and profiles.
``Settings.load()`` composes the primary file, its config groups, a
profile, overlays, the sources and the overrides in that precedence, and
attaches per-leaf provenance to the instance it returns.
"""

from __future__ import annotations

import annotationlib
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Final, Self

import didactic.api as dx
from didactic.settings._compose import assemble_layers, compose_layers
from didactic.settings._sources import FileSource, Source

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from didactic.settings._compose import Composed
    from didactic.settings._groups import Override
    from didactic.settings._interpolation import ResolverFn
    from didactic.settings._provenance import Layer, Provenance
    from didactic.settings._values import ConfigValue

RESERVED_FIELD_NAMES: Final = frozenset(
    {"path", "profile", "groups", "overlays", "overrides", "search_path", "resolvers"}
)
"""Field names a ``Settings`` subclass may not declare: ``load``'s keywords."""


class Settings(dx.Model):
    """Base class for application settings.

    Subclasses declare fields like any [didactic.api.Model][didactic.api.Model],
    plus a class-level ``__sources__`` tuple. Call
    [Settings.load][didactic.settings.Settings.load] to compose an
    instance from a primary file, its config groups, a profile, overlays,
    the sources and overrides.

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
    __sources__
        The sources consulted in declaration order; later sources win.
        Their names must be distinct.
    __search_path__
        Directories searched for fragments and profiles, after the
        primary file's parent and the first ``FileSource``'s parent.
    __provenance__
        The [Provenance][didactic.settings.Provenance] of an instance
        built by ``load``: one origin per leaf.

    Raises
    ------
    TypeError
        At class creation, when a field is named after one of ``load``'s
        keywords or two sources share a name.
    """

    __sources__: ClassVar[tuple[Source, ...]] = ()
    __search_path__: ClassVar[tuple[str, ...]] = ()

    # ``load`` attaches the record with ``object.__setattr__``; the
    # declaration is type-only so the metaclass does not see a field.
    if TYPE_CHECKING:

        @property
        def __provenance__(self) -> Provenance:
            """The per-leaf record; populated by ``load``."""
            ...

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Refuse reserved field names and duplicate source names."""
        super().__init_subclass__(**kwargs)
        for name in sorted(_declared_field_names(cls) & RESERVED_FIELD_NAMES):
            msg = (
                f"{cls.__name__} declares a field named {name!r}, which is a "
                "keyword of Settings.load(); rename the field and give it "
                f"alias={name!r} to keep the key in documents"
            )
            raise TypeError(msg)
        seen: set[str] = set()
        for source in cls.__sources__:
            if source.name in seen:
                msg = (
                    "Settings sources must have distinct names; "
                    f"{source.name!r} is used twice"
                )
                raise TypeError(msg)
            seen.add(source.name)

    @classmethod
    def load(
        cls,
        path: Path | str | None = None,
        *,
        profile: str | Mapping[str, ConfigValue] | None = None,
        groups: Mapping[str, str | None] | None = None,
        overlays: Sequence[Path | str | Mapping[str, ConfigValue]] = (),
        overrides: Sequence[Override] = (),
        search_path: Sequence[Path | str] | None = None,
        resolvers: Mapping[str, ResolverFn] | None = None,
        **values: ConfigValue,
    ) -> Self:
        """Compose an instance from the file, groups, profile, sources and overrides.

        Parameters
        ----------
        path
            The primary document; its ``defaults:`` list is honoured and
            its parent is the first search root.
        profile
            A profile name or mapping.
        groups
            Config-group selections by slot.
        overlays
            File paths or mappings merged above the profile.
        overrides
            ``key=value`` strings or ``(key, value)`` pairs, applied above
            the sources.
        search_path
            Directories searched for fragments and profiles;
            ``__search_path__`` when omitted.
        resolvers
            Interpolation resolvers for this call.
        **values
            Typed overrides applied last, keyed by dotted path with ``__``
            as the separator: ``model__type_encoder__num_heads=8``.

        Returns
        -------
        Settings
            The validated instance with ``__provenance__`` attached.
        """
        return cls.load_traced(
            path,
            profile=profile,
            groups=groups,
            overlays=overlays,
            overrides=overrides,
            search_path=search_path,
            resolvers=resolvers,
            **values,
        ).value

    @classmethod
    def load_traced(
        cls,
        path: Path | str | None = None,
        *,
        profile: str | Mapping[str, ConfigValue] | None = None,
        groups: Mapping[str, str | None] | None = None,
        overlays: Sequence[Path | str | Mapping[str, ConfigValue]] = (),
        overrides: Sequence[Override] = (),
        search_path: Sequence[Path | str] | None = None,
        resolvers: Mapping[str, ResolverFn] | None = None,
        **values: ConfigValue,
    ) -> Composed[Self]:
        """Load like :meth:`load` and return the value with its record and layers.

        Parameters are those of :meth:`load`.
        """
        sources: list[Layer] = []
        for source in cls.__sources__:
            layer = source.layer(cls)
            if layer is not None:
                sources.append(layer)
        roots: list[Path | str] = []
        for source in cls.__sources__:
            if isinstance(source, FileSource):
                roots.append(Path(source.path).parent)
                break
        roots.extend(cls.__search_path__ if search_path is None else search_path)
        typed: list[Override] = [
            (key.replace("__", "."), value) for key, value in values.items()
        ]
        layers = assemble_layers(
            path,
            groups=groups,
            profile=profile,
            overlays=overlays,
            overrides=[*overrides, *typed],
            search_path=roots,
            sources=sources,
        )
        return compose_layers(schema=cls, layers=layers, resolvers=resolvers)


def _declared_field_names(cls: type) -> set[str]:
    """Field names a class declares or inherits, read before the metaclass runs.

    ``__init_subclass__`` runs before ``__field_specs__`` is assigned, so
    the class's own names come from its annotations and inherited names
    from the bases' already-built field tables.
    """
    names: set[str] = set()
    annotations = annotationlib.get_annotations(
        cls, format=annotationlib.Format.FORWARDREF
    )
    names.update(name for name in annotations if not name.startswith("_"))
    for base in cls.__bases__:
        if issubclass(base, dx.Model):
            names.update(base.__field_specs__)
    return names


__all__ = ["RESERVED_FIELD_NAMES", "Settings"]
