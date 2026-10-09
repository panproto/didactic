# Repository

`Repository.add(Model)` commits a field-addressable schema. The Model is an
`object` vertex, and every declared field is a `field` vertex named
`ModelName.field_name`. A labelled edge records the serialized field name;
constraints record the didactic sort, structural kind, requiredness, usage
mode, and axioms. The schema's nominal map records `FieldSpec.nominal`
explicitly for every field.

This representation makes field history available without exposing panproto's
repository handle:

```python
import didactic.api as dx


class RunSpec(dx.Model):
    run_id: str = dx.field(nominal=True)
    seed: int


repo = dx.Repository.open("experiment-schema")
blame = repo.blame_field("main", RunSpec, "run_id")
print(blame.commit_id, blame.author, blame.message)
```

Blame walks first-parent history. When a committed schema migration maps an old
field vertex to a renamed vertex, attribution follows that mapping to the
commit that introduced the original field.

::: didactic.api.Repository

::: didactic.api.CommittedDataset

::: didactic.api.Blame
