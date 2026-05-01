# Schema diff

[didactic.api.diff][didactic.api.diff] and
[didactic.api.classify_change][didactic.api.classify_change] compute the
structural difference between two Models. They wrap panproto's
`diff_schemas` and `diff_and_classify` and are useful in CI to catch
breaking schema changes before merge.

## diff

`dx.diff(old, new)` returns a dict whose keys describe what changed:

```python
import didactic.api as dx


class V1(dx.Model):
    id: str
    name: str


class V2(dx.Model):
    id: str
    name: str
    email: str = ""


dx.diff(V1, V2)
# {
#   'added_vertices': [...],
#   'removed_vertices': [...],
#   'added_edges': [...],
#   'modified_constraints': [...],
#   ...
# }
```

The full key set comes from panproto's `SchemaDiff` and includes
added/removed/modified vertices, edges, hyper-edges, recursion
points, spans, variants, plus kind, nominal, order, and usage-mode
changes.

## classify_change

`dx.classify_change(old, new)` runs the diff and groups each change
by whether it is breaking:

```python
report = dx.classify_change(V1, V2)
# {
#   'compatible': bool,
#   'breaking': [...changes...],
#   'non_breaking': [...changes...],
# }
```

A change is breaking when it would cause an old payload to fail
validation against the new Model. Adding a non-required field is
non-breaking; renaming a field, narrowing a type, or removing a
field is breaking.

## is_breaking_change

`dx.is_breaking_change(old, new)` is the boolean shorthand:

```python
if dx.is_breaking_change(UserV1, UserV2):
    # require a registered migration before merging
    ...
```

## CI integration

The `didactic check breaking` subcommand uses `classify_change` and
exits non-zero when the change is breaking:

```bash
didactic check breaking myapp.models:UserV1 myapp.models:UserV2
```

Drop this into a CI step that fires on pull requests. A typical
workflow keeps the previous Model definition under version control,
so the comparison is "current branch vs main".
