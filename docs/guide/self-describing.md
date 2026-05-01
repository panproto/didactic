# Self-describing JSON

A self-describing payload is one that names its own schema. didactic
uses content-addressed URIs of the form
`didactic://v1/<structural-fingerprint>`; a consumer that knows the
URI can look up the Theory and validate the payload without prior
knowledge of the producing class.

## schema_uri

[didactic.api.schema_uri][didactic.api.schema_uri] returns the canonical URI
for a Model class:

```python
import didactic.api as dx


class User(dx.Model):
    id: str
    email: str


dx.schema_uri(User)
# 'didactic://v1/06ac976d...e8e780c3d76bf3bec5f81ab3591aadfacb'
```

The suffix is the [structural fingerprint](../concepts/fingerprints.md):
two structurally identical Models share a URI regardless of class
name.

## embed_schema_uri

Wrap a Model dump with the `$schema` URI:

```python
u = User(id="u1", email="ada@example.org")
payload = dx.embed_schema_uri(u)
# {
#   '$schema': 'didactic://v1/06ac...',
#   'id': 'u1',
#   'email': 'ada@example.org',
# }
```

The `$schema` key is the first key in the resulting dict, which lets
JSON parsers that stream key-by-key dispatch on the schema before
processing the body.

## FingerprintRegistry

[didactic.api.FingerprintRegistry][didactic.api.FingerprintRegistry] is the
lookup side: register every Model your application understands, then
the registry resolves a URI back to a class.

```python
reg = dx.FingerprintRegistry()
reg.register(User)

dx.validate_with_uri_lookup(payload, reg)
# User(id='u1', email='ada@example.org')
```

`validate_with_uri_lookup` raises `KeyError` if the payload has no
`$schema` key, and `LookupError` if the URI is not registered.

## When to use this

The pattern is suited to:

- Event buses where each message carries its own schema id.
- Long-term storage where readers may post-date writers.
- Federated deployments where different services know different
  Models, but agree on URIs through a registry.

For request/response APIs where the consumer already knows the
expected shape, regular JSON without the `$schema` field is enough.
