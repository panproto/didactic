<!--
Thanks for contributing to didactic. Fill out each section briefly so
reviewers can land your change quickly. Keep prose tight; link to
issues, designs, or upstream docs rather than re-explaining them here.
-->

## Summary

<!--
1-3 sentences: what does this PR change, and why? Lead with the user-
visible effect (a new feature, a bug fix, a docs improvement) before the
implementation details. Link the issue this resolves with `Closes #N`.
-->

## Motivation

<!--
What problem does this solve, and how did it surface? A bug report, a
user integration, a measurement, a follow-up to a previous PR. If the
"why" is in an issue, just link it — don't re-state.
-->

## Changes

<!--
Bullet list of the substantive changes, organised by package or layer.
Skip cosmetic edits (formatting, typos) unless they're load-bearing.
-->

- `packages/didactic/src/...` — ...
- `packages/didactic-pydantic/...` — ...
- `docs/...` — ...
- `tests/...` — ...

## Tests

<!--
Which tests cover the change, and what cases do they exercise? Note any
property-based or integration tests added. If you couldn't write a test
(e.g. it depends on an external service), explain why and what manual
validation you did instead.
-->

## Local CI

<!--
Confirm each gate passed locally. Match the CI matrix exactly so the
remote run isn't your first signal.
-->

- [ ] `uv run ruff format --check`
- [ ] `uv run ruff check`
- [ ] `uv run pyright`
- [ ] `uv run pytest -ra`
- [ ] `uv run mkdocs build --strict`

## Compatibility

<!--
Pick one. Delete the others.
-->

- **No user-visible change** — internal refactor, docs, tests, or CI.
- **Backwards-compatible addition** — new public symbols or new
  optional parameters; existing code keeps working.
- **Behaviour change** — existing public API behaves differently; call
  out the migration path for users.
- **Breaking change** — existing public API is removed or changes
  shape; bump the minor version (or major if post-1.0) and document
  the migration in the changelog.

## Changelog

<!--
Did you update `CHANGELOG.md`? Place the entry under `[Unreleased]` in
the appropriate Keep-a-Changelog section (Added / Changed / Deprecated
/ Removed / Fixed / Security). Link issues with `([#N])`.

If the change is internal (refactor, test, CI, docs), no entry is
needed; tick "no entry needed" below.
-->

- [ ] Added a `CHANGELOG.md` entry under `[Unreleased]`.
- [ ] No changelog entry needed.

## Pyright suppressions

<!--
Per `CONTRIBUTING.md`, every `# pyright: report*=false` or inline
`# pyright: ignore[...]` directive needs a documented reason and a
tracking issue. If this PR adds, removes, or modifies any suppression,
list each one and link the issue.
-->

- [ ] This PR does not introduce or modify any pyright suppression.
- [ ] Suppressions added/changed are listed below with a link to the
  tracking issue and a one-line rationale.

## Linked issues

<!--
- `Closes #N` for a bug or feature this PR resolves outright.
- `Refs #N` for an issue this PR makes progress on but doesn't close.
-->
