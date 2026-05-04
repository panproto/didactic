# ``structural_spec`` and friends shape ``TheorySpec`` (a TypedDict)
# back into ``JsonObject`` (``dict[str, JsonValue]``); the dict
# invariance bites. ``_default`` narrowing on tuple inputs is
# pyright-flagged as redundant. Tracked in panproto/didactic#1.
"""Stable fingerprints for didactic Theory specs.

didactic stores migration registry entries by a fingerprint that is
computed from the **didactic-shape spec dict** (the same dict
[didactic.theory._theory.build_theory_spec][] produces), not from any
panproto-internal representation. The fingerprint is therefore
independent of panproto's Theory ``Serialize`` impl, msgpack settings,
or the ``hash_theory`` algorithm: drift in any of those does not
invalidate the registry.

What we trust
-------------
Stable: the didactic-side canonicalisation in
[canonical_json_bytes][didactic.migrations._fingerprint.canonical_json_bytes],
which is content-addressed JSON with sorted keys and deterministic
tuple-as-list encoding. didactic owns this format.

What we do not trust
--------------------
panproto's internal hash, panproto's Theory ``Serialize`` impl, the
msgpack wire format, the blake3 vs other-hash choice, the
``ScopeTag`` numbering, or anything else we don't control.

What we accept as a residual risk
---------------------------------
The spec format in [didactic.theory._theory][] (sort kind names, operation
shape, etc.) tracks panproto's accepted ``create_theory`` input. If
panproto changes the shape it accepts, we update ``_theory.py`` to
emit the new shape, AND we add a translation pass for old
fingerprints stored against the old shape. That migration is a
didactic-side concern and stays internal to didactic.

See Also
--------
didactic.theory._theory : the spec builder.
didactic.migrations._migrations : the consumer of fingerprints.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from didactic.theory._theory import TheorySpec
    from didactic.types._typing import JsonObject, JsonValue, Opaque

# canonical placeholder for the model's own display name; chosen to be
# unambiguous and unlikely to clash with any user-supplied identifier
_SELF = "<self>"


def canonical_json_bytes(spec: JsonValue) -> bytes:
    """Render a didactic Theory spec to its canonical JSON byte form.

    Parameters
    ----------
    spec
        A didactic-shape Theory spec (the dict produced by
        [didactic.theory._theory.build_theory_spec][]).

    Returns
    -------
    bytes
        UTF-8-encoded JSON with sorted dict keys, no insignificant
        whitespace, and ASCII-safe escaping. Two specs that compare
        equal as Python values produce identical bytes.

    Notes
    -----
    Tuples in the input are encoded as JSON arrays, matching
    didactic's spec convention (operation ``inputs`` carry tuple-shaped
    rows). Floats use the default JSON encoder; the spec format does
    not currently include float values.
    """
    return json.dumps(
        spec,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=_default,
    ).encode("utf-8")


def _default(obj: Opaque) -> JsonValue:
    """Fallback encoder for tuples (json default would already accept them).

    The callback runs on every non-JSON-native value ``json.dumps``
    encounters; in didactic specs the only such value is
    ``tuple[JsonValue, ...]`` (we never feed sets/Decimals/Models into
    ``canonical_json_bytes``). Anything else is a programmer bug and
    raises so the spec author sees it immediately.
    """
    if isinstance(obj, tuple):
        return list(cast("tuple[JsonValue, ...]", obj))
    msg = f"non-JSON-encodable value in didactic spec: {type(obj).__name__}"
    raise TypeError(msg)


def fingerprint(spec: JsonValue) -> str:
    """Compute a stable fingerprint for a didactic Theory spec.

    Parameters
    ----------
    spec
        A didactic-shape Theory spec.

    Returns
    -------
    str
        Hex-encoded SHA-256 of
        [canonical_json_bytes][didactic.migrations._fingerprint.canonical_json_bytes]
        of ``spec``. 64 lowercase hex characters.

    Notes
    -----
    SHA-256 is chosen for ubiquity (every Python install ships it via
    ``hashlib``) rather than for cryptographic strength: this is a
    content-addressing hash, not a security primitive. Collision
    resistance is more than adequate for any plausible registry size.
    """
    return hashlib.sha256(canonical_json_bytes(spec)).hexdigest()


def structural_spec(spec: JsonObject) -> JsonObject:
    """Return a copy of ``spec`` with the model's own display name normalised.

    Parameters
    ----------
    spec
        A didactic-shape Theory spec. Must be a top-level dict produced by
        [didactic.theory._theory.build_theory_spec][].

    Returns
    -------
    dict
        A new dict in which every occurrence of the model's display name
        is replaced by the placeholder ``"<self>"``. The replacement
        covers the top-level ``name`` field, the matching sort name, the
        per-field sort prefixes ``{ModelName}_{field}``, and any
        operation input that references the model name.

    Notes
    -----
    Two Models with identical fields but different class names produce
    the same structural spec, so they hash to the same fingerprint. This
    is the property the migration registry relies on for robustness to
    class-identity churn (renames, re-imports, structurally-identical
    Models defined in two libraries).

    The placeholder ``"<self>"`` is chosen to be unambiguous; it is not
    a legal Python identifier and so cannot collide with a user-supplied
    sort name.
    """
    name = spec["name"]
    if not isinstance(name, str):
        msg = "structural_spec(): spec['name'] must be a string"
        raise TypeError(msg)
    rewritten = _replace_model_name(spec, name)
    if not isinstance(rewritten, dict):
        msg = "structural_spec(): top-level rewrite must remain a dict"
        raise TypeError(msg)
    return rewritten


def _replace_model_name(value: JsonValue, name: str) -> JsonValue:
    """Recursively rewrite occurrences of ``name`` to the ``<self>`` placeholder.

    Substitution rules: an exact match maps to ``<self>``; a string with
    the prefix ``f"{name}_"`` keeps its suffix and gets the placeholder
    swapped in (so ``UserA1_id`` becomes ``<self>_id``). All other
    strings, lists, and dicts are walked structurally.
    """
    prefix = f"{name}_"
    if isinstance(value, str):
        if value == name:
            return _SELF
        if value.startswith(prefix):
            return f"{_SELF}_{value[len(prefix) :]}"
        return value
    if isinstance(value, list | tuple):
        return [_replace_model_name(item, name) for item in value]
    if isinstance(value, dict):
        return {k: _replace_model_name(v, name) for k, v in value.items()}
    return value


def structural_fingerprint(spec: TheorySpec) -> str:
    """Compute a class-name-independent fingerprint for a Theory spec.

    Parameters
    ----------
    spec
        A didactic-shape Theory spec.

    Returns
    -------
    str
        Hex-encoded SHA-256 of the canonical JSON of
        [structural_spec][didactic.migrations._fingerprint.structural_spec] applied
        to ``spec``.

    Notes
    -----
    Use this fingerprint for the migration registry, where two
    structurally-identical Models should share one entry regardless of
    their class names.
    """
    return fingerprint(structural_spec(cast("JsonObject", spec)))


__all__ = [
    "canonical_json_bytes",
    "fingerprint",
    "structural_fingerprint",
    "structural_spec",
]
