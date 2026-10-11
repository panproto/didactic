# VCS Repository

`dx.Repository` wraps panproto's filesystem-backed schema repository:
a content-addressed object store, refs, a staging index, and reflog
entries, all stored under `.panproto/` in a working directory.

## Initialising a repository

```python
import didactic.api as dx

repo = dx.Repository.init("/path/to/my-repo")
print(repo.working_dir)
print(repo.head())  # None for a freshly initialised repo
```

## Staging and committing

`Repository.add` accepts two shapes. The simplest is to pass a
`dx.Model` subclass directly. Didactic synthesises a schema with one
vertex for the Model and one deterministic `ModelName.field_name`
vertex for every declared field. Each field vertex records its didactic
sort, structural kind, requiredness, usage mode, axioms, and nominal or
structural identity; the edge from the Model records the serialized field
name:

```python
import didactic.api as dx

class User(dx.Model):
    id: str
    email: str

repo = dx.Repository.init("/path/to/repo")
repo.add(User)
commit_id = repo.commit("initial user schema", author="Ada <ada@example.org>")
```

You can also stage a panproto `Schema` you constructed yourself:

```python
import panproto

proto = panproto.get_builtin_protocol("openapi")
builder = proto.schema()
builder.vertex("ping", "string")
schema = builder.build()

repo.add(schema)
repo.commit("openapi ping schema", author="Ada <ada@example.org>")
```

## Staging data against a persisted schema

`Repository.add_data` normally validates a dataset against the staged schema,
or HEAD's schema when no schema is staged. Pass `schema_id` to reuse an exact
persisted schema without changing either of those schema pointers:

```python
repo.add_data(
    "run-config.json",
    key="configuration",
    schema_id=config_schema_id,
)
repo.add_data("run-record.json", key="record")
repo.commit("record run", author="Ada <ada@example.org>")
```

The committed configuration dataset records `config_schema_id`; the record
dataset records the staged or HEAD schema id. This permits one commit to carry
datasets governed by distinct persisted schemas while leaving field blame on
the HEAD schema stable.

## Reading committed data

`Repository.data_at` returns the canonical Panproto MessagePack bytes for each
dataset at a revision. Use `Repository.decoded_data_at` when the caller needs
ordinary JSON-like records instead:

```python
datasets = repo.decoded_data_at("release-candidate")
for dataset in datasets:
    print(dataset.key, dataset.schema_id, dataset.record_count)
    users = [User.model_validate(record) for record in dataset.records]
```

The result retains each dataset's key, persisted schema id, and record count.
Dataset order and record order match the commit. Maps, lists, strings,
booleans, nulls, integers, and finite floats are decoded to their ordinary
Python JSON shapes; validation against a current Model remains an explicit
caller decision.

Both accessors accept `HEAD`, a branch, a tag, a full commit id, or an accepted
commit-id prefix. They traverse history without checking out the revision or
changing HEAD, the working tree, or the staged schema. Missing or malformed
refs, absent or tampered objects, and malformed canonical data raise Panproto's
typed `VcsError`. The raw `CommittedDataset.data` bytes remain available for
callers that need the canonical representation.

## Blaming a field

`blame_field` attributes one declared field without exposing panproto's
repository handle:

```python
blame = repo.blame_field("HEAD", User, "email")
print(blame.commit_id)
print(blame.author)
print(blame.message)
```

The walk follows first-parent history. A committed schema migration that
maps an old field vertex to a renamed one preserves the original field's
attribution. Fields added without a migration preimage are attributed to
the adding commit.

## Branches and refs

```python
repo.create_branch("feature", commit_id)
repo.checkout_branch("feature")

# resolve any ref expression to a commit id
cid = repo.resolve_ref("HEAD")
```

## See also

- [Repository reference](../reference/repository.md) for the full API.
