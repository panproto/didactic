# Contributing

Thanks for considering a contribution.

## Setup

`didactic` targets Python 3.14 and uses [`uv`](https://github.com/astral-sh/uv)
for dependency management.

```sh
uv sync --all-packages --all-extras
```

## Running checks locally

The same tooling that runs in CI:

```sh
uv run pytest                  # tests
uv run ruff format --check     # formatting
uv run ruff check              # lint
uv run pyright                 # types
uv run mkdocs build --strict   # docs
```

A pull request should leave all five green.

## House style

- **Type hints**: modern syntax. Use `list[T]`, `dict[K, V]`,
  `T | None`, `collections.abc.Callable`, etc. No imports from `typing`
  for `List`, `Dict`, `Optional`, `Union`. PEP 695 (`class Box[T]:`)
  for new generics.
- **No `Any` or `object` in type hints.** If the actual type is
  unknown, use a Protocol or `_typing.Opaque`. Reach for the
  type-checker's `assert isinstance(...)` machinery to narrow.

  *Narrow exceptions* (each documented inline at every site):

  1. **Stub-style overloads of field-specifier constructors.** `Any`
     is permitted on the overload return type (never the
     implementation) for the required-without-default form, e.g.
     ``required: str = dx.field(description="…")``. The typeshed
     stubs for `dataclasses.field` use the same pattern. Today the
     only such function is `didactic.fields._fields.field`.
  2. **Python dunder conventions.** `__eq__(self, other: object) ->
     bool`, `__contains__(self, x: object) -> bool`, `__exit__(self,
     *_: object) -> None`. Typeshed mandates `object` for these;
     narrowing triggers `reportIncompatibleMethodOverride`.
  3. **Panproto-typed handles that didactic forwards without
     inspection.** Functions that take/return a `panproto.Schema`,
     `panproto.Instance`, or `panproto.Lens` purely as a token (e.g.
     `codegen.io._build_instance`, `codegen.source.emit`) annotate
     the parameter as `object` so panproto stays a `TYPE_CHECKING`
     import. The function body must not call methods on the value;
     it must hand the token straight back to panproto.
  4. **User-facing `**kwargs: object` on extensibility hooks.** Where
     callers register per-target emitters or per-protocol options
     under their own key namespace, `**kwargs: object` is the
     documented contract. Today the only site is
     `Model.emit_as(target, **opts: object)`.
  5. **`dict[str, object]` for opaque-leaf payloads from external
     sources.** The instance round-trip helpers in `codegen.io`
     (`_instance_to_payload`, `_coerce_payload`,
     `_unwrap_sort_envelope`) walk panproto's nested return shape
     where the leaf values are sort-discriminated wire-strings of
     indeterminate Python type until each field's `from_json` runs.
     The dict type captures "string keys, opaque values"; per-leaf
     narrowing happens at the boundary.

  Every site that uses a carve-out must carry an inline comment
  pointing back to the rule it relies on, so the suppression is
  reviewable.
- **Numpy docstrings.** Every public module, class, function, and
  method gets a docstring in numpy-doc style: a one-line summary,
  followed by `Parameters`, `Returns`, `Raises`, `Notes`, `See Also`,
  `Examples` sections as appropriate. Sentence case for the prose; no
  em dashes (use commas, semicolons, or colons).
- **Inline comments are lower-case.** No sentence-cased inline
  comments.
- **Cross-references in docstrings** use the mkdocs format
  ``[Name][module.path.Name]`` so the docs site renders them as
  links.
- **Tests.** Every new public surface ships with a test. Property-based
  tests (Hypothesis) for anything with an algebraic structure
  (lenses, fingerprints, migrations).

## Commit messages

Commit messages should describe the *change*, not the *file*. Prefer
"add structural fingerprint" over "edit `_fingerprint.py`". A single
commit should do one thing.

## Package layout

The four distributions (`didactic`, `didactic-pydantic`,
`didactic-settings`, `didactic-fastapi`) share the import root
`didactic.*` via PEP 420 implicit namespace packages: there is no
`__init__.py` at `didactic/` in any distribution. Each sibling
contributes a sub-package (`didactic.pydantic`, `didactic.settings`,
`didactic.fastapi`). The core distribution provides the API surface
under `didactic.api`; the conventional alias is:

```python
import didactic.api as dx
```

## Releases

All four distributions are published to PyPI from a single tag push.

1. Bump the version in every package's `pyproject.toml` to the same
   value (the four distributions ship in lockstep).
2. Update `CHANGELOG.md` with the new version and date.
3. Commit the version bump on `main`.
4. Tag the commit with `vX.Y.Z` and push:

   ```sh
   git tag v0.1.0
   git push origin v0.1.0
   ```

The `Release` workflow runs the full verification matrix (lint,
pyright, pytest, docs build), then builds and uploads each
distribution to PyPI via Trusted Publishing (OIDC).

PyPI authentication uses [Trusted Publishing][tp] (OIDC); no API
tokens are stored in this repository.

[tp]: https://docs.pypi.org/trusted-publishers/

## Reporting bugs

File an issue with:

- A minimal reproduction (a Python snippet that fails).
- The expected behaviour.
- The actual behaviour, including any traceback.
- Your Python version and the `panproto` version (`pip show panproto`).
