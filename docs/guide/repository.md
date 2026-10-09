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
