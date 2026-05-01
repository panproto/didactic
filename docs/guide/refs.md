# References and embedding

Three field types relate one Model to another:

| marker | semantics |
| --- | --- |
| `Ref[T]` | a non-owning reference to another Model, stored as the target's id |
| `Embed[T]` | an owned sub-Model, stored as the embedded payload |
| `Backref[T, "field"]` | the inverse of a `Ref`, computed from a pool |

## Ref

`Ref[T]` is the foreign-key analogue. The field's runtime type is
`str`; the value stored is the target's id.

```python
class Author(dx.Model):
    id: str
    name: str


class Book(dx.Model):
    id: str
    title: str
    author: dx.Ref[Author]
```

Construction takes the id directly:

```python
ada = Author(id="a1", name="Ada Lovelace")
b = Book(id="b1", title="Notes", author="a1")
```

The Theory carries an edge from `Book` to `Author` so the
relationship is visible to schema-diff and code generation tools.

## Embed

`Embed[T]` stores the target Model in line. The field accepts either
a `T` instance or a dict:

```python
class Address(dx.Model):
    street: str
    city: str


class User(dx.Model):
    id: str
    home: dx.Embed[Address]


User(id="u1", home=Address(street="221b Baker", city="London"))
User(id="u1", home={"street": "221b Baker", "city": "London"})
```

Both calls produce the same `User`. JSON serialisation recurses
through the embed.

## Backref

`Backref[T, "field"]` declares the inverse direction of a `Ref`.
didactic does not auto-resolve backrefs at construction; the marker
lives on the field for schema-diff tooling and downstream code, and
resolution goes through one of the helpers below.

### Resolving against a list

[didactic.api.resolve_backrefs][didactic.api.resolve_backrefs] is the
direct path. Pass the target instance, an iterable of candidates,
and the field on each candidate that holds the `Ref`:

```python
ada = Author(id="a1", name="Ada Lovelace")
books = [
    Book(id="b1", title="Notes", author="a1"),
    Book(id="b2", title="Other", author="a2"),
    Book(id="b3", title="More", author="a1"),
]

dx.resolve_backrefs(ada, books, via="author")
# [Book(id='b1', ...), Book(id='b3', ...)]
```

The optional `key` keyword chooses the attribute on `target` whose
value the Ref stores; the default is `"id"`.

### Resolving against a pool

[didactic.api.ModelPool][didactic.api.ModelPool] is a small in-memory
registry of Model instances grouped by class. Use it when the
candidate set is longer-lived than a single function call:

```python
pool = dx.ModelPool()
pool.add(ada)
pool.add(Book(id="b1", title="Notes", author="a1"))
pool.add(Book(id="b2", title="Other", author="a2"))

pool.backrefs(ada, Book, via="author")
# [Book(id='b1', ...)]
```

Repository-backed backref resolution lands once panproto exposes
schema-vertex queries; the in-memory path covers everything that
fits in process memory.
