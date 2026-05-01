"""Schema migrations as registered lenses, keyed by spec fingerprint.

didactic's migration story is "write a [Lens][didactic.api.Lens] (or
[Iso][didactic.api.Iso]) between two Model classes, register it, and let
the loader chase the registered chain when it sees an old payload".

Storage strategy
----------------
The registry stores each migration's **didactic-shape source/target
spec dicts** alongside the lens. Lookup is by a stable structural
fingerprint (SHA-256 of canonical-form JSON of the spec, with the
model's own display name normalised to a placeholder). The class
identities the user supplies at registration time are not stored as
keys; the structural shape of the spec is the source of truth.

This makes the registry robust to:

- Class identity churn (renaming, re-importing, two libraries that
  define structurally-identical Models).
- panproto Theory-representation changes (we never use panproto's
  internal hash; the fingerprint is computed from the didactic spec).
- panproto wire-format changes (the registry never deserialises
  panproto blobs; everything goes through the didactic spec).

Lookup is O(1) by fingerprint. If a class with the same shape but a
fresh module path appears, its spec hashes the same and finds the
existing migration. If didactic's own spec format changes (rare, and
under our control), a one-shot migration of stored fingerprints
re-hashes the registry under the new format.

User-facing surface
-------------------
[register_migration][didactic.api.register_migration]
    Register a migration ``Lens[V1, V2]`` (or its Iso/Mapping
    siblings) by passing the source and target Model classes. The
    function reads each class's ``__field_specs__`` to compute the
    spec and fingerprint at registration time.
[migrate][didactic.api.migrate]
    Apply registered migrations to a payload to bring it forward to
    a target Model class. Walks the spec-fingerprint graph
    breadth-first.

See Also
--------
didactic.migrations._fingerprint : the fingerprint algorithm.
didactic.theory._theory : the spec builder.
didactic.lenses._lens : the Lens / Iso / Mapping classes that migrations build on.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

from didactic.migrations._fingerprint import structural_fingerprint
from didactic.theory._theory import build_theory_spec

if TYPE_CHECKING:
    from os import PathLike

    from didactic.lenses._lens import Iso, Lens, Mapping
    from didactic.models._model import Model
    from didactic.theory._theory import TheorySpec
    from didactic.types._typing import JsonObject, JsonValue


@dataclass(frozen=True, slots=True)
class _MigrationRecord:
    """One entry in the migration registry.

    Stores both spec dicts (the source of truth) and their
    fingerprints (the lookup key). The class references at
    registration time are intentionally not retained: two classes
    with the same shape share one entry.
    """

    source_spec: TheorySpec
    target_spec: TheorySpec
    source_fp: str
    target_fp: str
    # Heterogeneous: each registered migration carries its own
    # source/target type pair, but the registry stores them all in
    # one container so the parameters can't be expressed at the
    # field declaration level. ``Model``/``Model`` covers the
    # variance for storage.
    lens: _AnyMigration


# global registry indexed by (source_fp, target_fp)
_REGISTRY: dict[tuple[str, str], _MigrationRecord] = {}


def register_migration[A: Model, B: Model](
    source: type[A],
    target: type[B],
    migration: Lens[A, B] | Iso[A, B] | Mapping[A, B],
) -> None:
    """Register a migration from ``source`` to ``target``.

    Parameters
    ----------
    source
        The older Model class.
    target
        The newer Model class.
    migration
        A [Lens][didactic.api.Lens], [Iso][didactic.api.Iso], or
        [Mapping][didactic.api.Mapping] that maps a source instance to a
        target instance.

    Raises
    ------
    TypeError
        If a migration is already registered for the same
        ``(source_spec, target_spec)`` pair.

    Notes
    -----
    The registry is process-global. The lookup key is a fingerprint
    of the didactic-shape spec, so a structurally-identical class
    re-imported from a different module shares one registry entry.

    Examples
    --------
    >>> import didactic.api as dx
    >>> class UserV1(dx.Model):
    ...     id: str
    ...     name: str
    >>> class UserV2(dx.Model):
    ...     id: str
    ...     given_name: str
    ...     family_name: str
    >>> class V1ToV2(dx.Iso[UserV1, UserV2]):
    ...     def forward(self, u: UserV1) -> UserV2:
    ...         first, _, last = u.name.partition(" ")
    ...         return UserV2(id=u.id, given_name=first, family_name=last)
    ...
    ...     def backward(self, u: UserV2) -> UserV1:
    ...         return UserV1(
    ...             id=u.id,
    ...             name=f"{u.given_name} {u.family_name}".rstrip(),
    ...         )
    >>> dx.register_migration(UserV1, UserV2, V1ToV2())
    """
    source_spec = build_theory_spec(source)
    target_spec = build_theory_spec(target)
    source_fp = structural_fingerprint(source_spec)
    target_fp = structural_fingerprint(target_spec)
    key = (source_fp, target_fp)
    if key in _REGISTRY:
        existing = _REGISTRY[key]
        msg = (
            f"a migration with the same source/target spec is already "
            f"registered ({existing.lens!r}); duplicate registrations "
            "are rejected to make ordering deterministic"
        )
        raise TypeError(msg)
    # ``Lens``/``Iso``/``Mapping`` are invariant in their type parameters,
    # so a typed ``Lens[A, B]`` cannot be assigned to a stored
    # ``Lens[Model, Model]`` slot even though ``A``/``B`` are both
    # ``Model`` subclasses. The registry stores migrations
    # heterogeneously and the per-entry types are recovered through
    # the (source_fp, target_fp) keys; cast at the boundary.
    stored = cast(
        "_AnyMigration",
        migration,
    )
    _REGISTRY[key] = _MigrationRecord(
        source_spec=source_spec,
        target_spec=target_spec,
        source_fp=source_fp,
        target_fp=target_fp,
        lens=stored,
    )


def migrate[B: Model](
    payload: Model | JsonObject,
    *,
    source: type[Model] | None = None,
    target: type[B],
) -> B:
    """Migrate a payload to the ``target`` Model class.

    Parameters
    ----------
    payload
        Either an instance of an older Model class or a dict produced
        by ``older.model_dump()``.
    source
        The source Model class. Required when ``payload`` is a dict;
        optional when it's already a Model instance.
    target
        The Model class to migrate to.

    Returns
    -------
    Model
        A ``target`` instance produced by walking the registered
        migration graph from ``source`` to ``target`` and composing
        the lenses along the way.

    Raises
    ------
    LookupError
        If no path exists in the registry. The error message includes
        the source and target fingerprints so the user can diagnose
        which migration is missing.
    TypeError
        If ``payload`` is a dict and ``source`` is not given.

    Notes
    -----
    Path search is breadth-first over fingerprints. Lens composition
    is associative, so any path produces the same result for
    round-trip-clean migrations.
    """
    from didactic.models._model import Model as _Model  # noqa: PLC0415

    if isinstance(payload, _Model):
        source = type(payload)
        instance: Model = payload
    else:
        if source is None:
            msg = "migrate(): when payload is a dict, `source=` is required"
            raise TypeError(msg)
        instance = source.model_validate(payload)

    if source is target:
        return instance  # type: ignore[return-value]

    source_fp = structural_fingerprint(build_theory_spec(source))
    target_fp = structural_fingerprint(build_theory_spec(target))

    chain = _find_path(source_fp, target_fp)
    if chain is None:
        msg = (
            f"no migration path from spec {source_fp[:12]}... "
            f"({source.__name__}) to spec {target_fp[:12]}... "
            f"({target.__name__}) is registered"
        )
        raise LookupError(msg)

    current: Model = instance
    for lens in chain:
        result = lens(current)
        # Lens.forward returns a tuple (view, complement); keep the view
        # and discard the complement (forward-only migration).
        current = result[0] if isinstance(result, tuple) else result

    return current  # type: ignore[return-value]


# The registry stores migrations heterogeneously; ``_AnyMigration`` is
# the union of all three lens flavours over the registry's storage
# pair ``Model``/``Model``. See the ``_MigrationRecord`` docstring for
# the variance carve-out.
type _AnyMigration = Lens[Model, Model] | Iso[Model, Model] | Mapping[Model, Model]


def _find_path(source_fp: str, target_fp: str) -> list[_AnyMigration] | None:
    """Breadth-first search over the fingerprint graph.

    Parameters
    ----------
    source_fp
        The starting fingerprint.
    target_fp
        The destination fingerprint.

    Returns
    -------
    list or None
        A list of lenses to apply in order, or ``None`` if no path
        exists.
    """
    if source_fp == target_fp:
        return []

    # adjacency map source_fp -> [(target_fp, lens), ...]
    adj: dict[str, list[tuple[str, _AnyMigration]]] = {}
    for (s_fp, t_fp), record in _REGISTRY.items():
        adj.setdefault(s_fp, []).append((t_fp, record.lens))

    queue: list[tuple[str, list[_AnyMigration]]] = [(source_fp, [])]
    seen: set[str] = {source_fp}
    while queue:
        node, path = queue.pop(0)
        for next_fp, lens in adj.get(node, []):
            if next_fp == target_fp:
                return [*path, lens]
            if next_fp in seen:
                continue
            seen.add(next_fp)
            queue.append((next_fp, [*path, lens]))
    return None


def lookup_migration[A: Model, B: Model](
    source: type[A], target: type[B]
) -> Lens[A, B] | Iso[A, B] | Mapping[A, B] | None:
    """Return the migration registered for ``(source, target)``, or ``None``.

    Parameters
    ----------
    source
        The source Model class.
    target
        The target Model class.

    Returns
    -------
    Lens or Iso or Mapping or None
        The registered migration, or ``None`` if no direct (single-hop)
        migration is registered. Multi-hop chains are found by
        [migrate][didactic.api.migrate], not by this function.

    Notes
    -----
    Lookup is by fingerprint of the didactic spec; class identity is
    not used. A structurally-identical class re-imported from a
    different module finds the same migration.
    """
    source_fp = structural_fingerprint(build_theory_spec(source))
    target_fp = structural_fingerprint(build_theory_spec(target))
    record = _REGISTRY.get((source_fp, target_fp))
    return record.lens if record is not None else None  # type: ignore[return-value]


def clear_registry() -> None:
    """Wipe the migration registry. Test-suite hygiene only."""
    _REGISTRY.clear()


def registered_fingerprints() -> list[tuple[str, str]]:
    """Return every registered ``(source_fp, target_fp)`` pair.

    Returns
    -------
    list of tuples
        One ``(source_fp, target_fp)`` tuple per registered migration.
        Useful for debugging "no migration path" errors.
    """
    return list(_REGISTRY.keys())


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def save_registry(path: str | PathLike[str]) -> None:
    """Persist the registry's metadata to a JSON file.

    Parameters
    ----------
    path
        Filesystem path to write. The parent directory must already
        exist; the file is created or truncated.

    Notes
    -----
    Lenses themselves are Python callables and do not serialise. What
    gets written is the metadata that lets a subsequent
    [load_registry][didactic.api.load_registry] call reconnect Python-side
    lenses to their entries: source spec, target spec, source
    fingerprint, target fingerprint, and the lens's class
    ``__qualname__`` for diagnostic purposes. After loading, the user
    must re-register the lens (typically by re-importing the module
    that called [register_migration][didactic.api.register_migration]),
    which is a no-op because the fingerprints already match.

    The on-disk shape is a JSON object with one top-level key
    ``"entries"``, mapping to a list of records:

    .. code-block:: json

        {
          "entries": [
            {
              "source_fp": "...",
              "target_fp": "...",
              "source_spec": {...},
              "target_spec": {...},
              "lens_qualname": "module.path.LensClass"
            }
          ]
        }
    """
    payload = cast(
        "JsonObject",
        {
            "entries": [
                {
                    "source_fp": rec.source_fp,
                    "target_fp": rec.target_fp,
                    "source_spec": rec.source_spec,
                    "target_spec": rec.target_spec,
                    "lens_qualname": _qualname_of(rec.lens),
                }
                for rec in _REGISTRY.values()
            ],
        },
    )

    with Path(path).open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, sort_keys=True, indent=2)


def load_registry(path: str | PathLike[str]) -> int:
    """Load registry metadata from a JSON file produced by ``save_registry``.

    Parameters
    ----------
    path
        Path to a JSON file written by
        [save_registry][didactic.api.save_registry].

    Returns
    -------
    int
        The number of entries cross-checked against the in-memory
        registry. The disk-side metadata is informational; it does not
        re-bind lenses (Python callables don't survive a process
        boundary). Entries whose fingerprints already exist in the
        in-memory registry are silently confirmed; entries whose
        fingerprints are missing are reported via the return value
        being smaller than the number of records on disk.

    Raises
    ------
    FileNotFoundError
        If ``path`` does not exist.
    ValueError
        If the file is not in the expected format.

    Notes
    -----
    The intended workflow is:

    1. Application starts.
    2. Each module that defines migration lenses runs its
       [register_migration][didactic.api.register_migration] calls at
       import time.
    3. ``load_registry(path)`` is called for diagnostic purposes:
       compare the registry on disk to what's been registered in the
       current process. The return value is the count of confirmed
       entries; a smaller-than-expected number is a signal that a
       migration module wasn't imported.

    The on-disk format is intentionally human-readable so that
    operators can audit a deployment's expected migrations.
    """
    with Path(path).open(encoding="utf-8") as fh:
        loaded: JsonValue = json.load(fh)

    if not isinstance(loaded, dict) or "entries" not in loaded:
        msg = f"{path}: not a didactic migration registry dump"
        raise ValueError(msg)

    payload = cast("dict[str, list[dict[str, str]]]", loaded)
    confirmed = 0
    for entry in payload["entries"]:
        key = (entry["source_fp"], entry["target_fp"])
        if key in _REGISTRY:
            confirmed += 1
    return confirmed


def _qualname_of(lens: _AnyMigration) -> str:
    """Render a lens's class qualname for the on-disk dump.

    Parameters
    ----------
    lens
        A migration lens instance.

    Returns
    -------
    str
        ``f"{module}.{qualname}"`` of the lens's class. Used for
        diagnostic output only; the load path matches by fingerprint,
        not by qualname.
    """
    cls = type(lens)
    return f"{cls.__module__}.{cls.__qualname__}"


__all__ = [
    "clear_registry",
    "load_registry",
    "lookup_migration",
    "migrate",
    "register_migration",
    "registered_fingerprints",
    "save_registry",
]
