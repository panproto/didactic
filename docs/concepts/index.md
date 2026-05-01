# Concepts

Background on the model didactic uses internally. Read these when
you want to know why something is the way it is, not just how to use
it.

- [Architecture](architecture.md): how didactic and panproto fit
  together.
- [Theories](theories.md): what a panproto Theory is, why didactic
  builds one per Model class, and how the colimit on inheritance
  works.
- [Fingerprints](fingerprints.md): the structural fingerprint
  algorithm, what it identifies, and the stability guarantees the
  migration registry depends on.
- [Lens laws](lens-laws.md): GetPut, PutGet, composition,
  associativity, and how `dx.testing` checks them.
