"""Filesystem-backed VCS for panproto schemas.

Wraps ``panproto.Repository`` with a didactic-shaped public surface.
The wrapper exists so that the public ``didactic`` namespace owns the
API contract: panproto's Repository is the storage implementation, but
downstream code never imports it directly. This mirrors the same
posture didactic takes elsewhere (Theory specs, fingerprints, lenses):
didactic owns the public shape, panproto is the runtime.

Surface
-------
The wrapper covers initialisation, staging (either a panproto
``Schema`` or a [Model][didactic.api.Model] subclass), committing, the
read-only introspection accessors (``head``, ``log``, ``working_dir``,
branch listing), field-level blame, and ref / branch / tag operations.
Staging a Model class synthesises a schema with one Model vertex and one
addressable vertex per declared field. Field vertices retain their type,
validation, usage, serialized-name, and identity metadata.

Notes
-----
Each [Repository][didactic.api.Repository] holds an open handle to the
underlying ``.panproto/`` directory. Two ``Repository`` instances over
the same path are independent handles to the same on-disk store.

See Also
--------
didactic.theory._theory : the Model-to-Theory bridge.
panproto.Repository : the wrapped runtime type.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from os import PathLike

    import panproto

    from didactic.models._model import Model
    from didactic.types._typing import JsonObject


@dataclass(frozen=True, slots=True)
class CommittedDataset:
    """A dataset as recorded at a committed revision.

    Returned by [data_at][didactic.api.Repository.data_at], one per
    dataset committed at the requested revision. The wrapper exposes a
    typed value rather than panproto's raw mapping so the public surface
    does not leak the binding's dict shape.

    Parameters
    ----------
    schema_id
        Object id of the schema the dataset was validated against when
        it was committed.
    data
        Panproto's canonical MessagePack encoding of the checked
        ``WInstance`` records. This is not the source file's JSON text:
        staging parses and validates each record before it enters the
        content-addressed store.
    record_count
        Number of records panproto counted in ``data`` at commit time.
    key
        Identifier recorded for the dataset: the key passed to
        [add_data][didactic.api.Repository.add_data], or the source
        path when none was given. A downstream that versions one record
        per dataset uses this to map a committed dataset back to its own
        key. ``None`` only if panproto recorded no identifier.
    """

    schema_id: str
    data: bytes
    record_count: int
    key: str | None = None


@dataclass(frozen=True, slots=True)
class Blame:
    """The commit that introduced a Model field.

    Returned by [blame_field][didactic.api.Repository.blame_field]. The
    wrapper gives callers a stable didactic type rather than exposing
    panproto's dict-shaped binding result.

    Parameters
    ----------
    commit_id
        Object id of the commit that introduced the field vertex.
    author
        Author recorded on that commit.
    timestamp
        Commit timestamp as Unix seconds.
    message
        Commit message.
    """

    commit_id: str
    author: str
    timestamp: int
    message: str


class Repository:
    """Filesystem-backed panproto repository.

    Wraps a ``panproto.Repository``. Construction is
    via the [Repository.init][didactic.api.Repository.init] and
    [Repository.open][didactic.api.Repository.open] class methods rather
    than the bare constructor; the constructor accepts an already-open
    handle and is mostly for internal use.

    Parameters
    ----------
    inner
        An already-constructed ``panproto.Repository``. Most callers
        should use [init][didactic.api.Repository.init] or
        [open][didactic.api.Repository.open] instead of constructing this
        class directly.

    Notes
    -----
    The wrapper delegates almost every operation to the inner panproto
    handle. The reason it exists, rather than re-exporting panproto's
    type, is to keep didactic's public API independent of panproto's
    Python binding details (attribute names, argument keywords, etc.)
    as panproto evolves.

    Examples
    --------
    >>> import didactic.api as dx
    >>> repo = dx.Repository.init("/tmp/my-repo")  # doctest: +SKIP
    >>> repo.head() is None  # doctest: +SKIP
    True
    """

    __slots__ = ("_inner",)

    def __init__(self, inner: panproto.Repository) -> None:
        self._inner = inner

    # construction --------------------------------------------------

    @classmethod
    def init(cls, path: str | PathLike[str]) -> Repository:
        """Initialise a new repository at ``path``.

        Parameters
        ----------
        path
            Directory in which to create the ``.panproto/`` store. The
            directory is created if it does not exist.

        Returns
        -------
        Repository
            A handle to the newly initialised repository.

        Raises
        ------
        panproto.VcsError
            If a repository already exists at ``path`` or the path is
            not writable.
        """
        import panproto  # noqa: PLC0415

        return cls(panproto.Repository.init(str(path)))

    @classmethod
    def open(cls, path: str | PathLike[str]) -> Repository:
        """Open an existing repository at ``path``.

        Parameters
        ----------
        path
            Directory containing a ``.panproto/`` store.

        Returns
        -------
        Repository
            A handle to the existing repository.

        Raises
        ------
        panproto.VcsError
            If no repository exists at ``path``.
        """
        import panproto  # noqa: PLC0415

        return cls(panproto.Repository.open(str(path)))

    # introspection -------------------------------------------------

    @property
    def working_dir(self) -> str:
        """Path to the repository's working directory."""
        return self._inner.working_dir

    def head(self) -> str | None:
        """Resolve ``HEAD`` to a commit object id.

        Returns
        -------
        str or None
            The commit id, or ``None`` if the repository has no
            commits yet.
        """
        return self._inner.head()

    def head_state(self) -> str:
        """Describe the current HEAD state.

        Returns
        -------
        str
            A descriptor string from panproto. For a freshly
            initialised repository this is typically
            ``"ref: refs/heads/main"``.
        """
        return self._inner.head_state()

    def has_staged(self) -> bool:
        """Return ``True`` if anything is staged for the next commit."""
        return self._inner.has_staged()

    def list_branches(self) -> list[tuple[str, str]]:
        """Return the list of branches.

        Returns
        -------
        list of (str, str)
            One ``(name, commit_id)`` tuple per branch.
        """
        return list(self._inner.list_branches())

    def list_tags(self) -> list[tuple[str, str]]:
        """Return the list of tags.

        Returns
        -------
        list of (str, str)
            One ``(name, target_id)`` tuple per tag.
        """
        return list(self._inner.list_tags())

    def log(self) -> list[JsonObject]:
        """List commits reachable from HEAD, newest first.

        Returns
        -------
        list of dict
            One commit-record dict per commit, in newest-first order.
            The exact shape is panproto-defined; callers that depend
            on specific keys should consult panproto's documentation.
        """
        return cast("list[JsonObject]", list(self._inner.log()))

    def resolve_ref(self, ref: str) -> str:
        """Resolve a ref expression to a commit id.

        Parameters
        ----------
        ref
            A branch name, tag name, or commit-id prefix.

        Returns
        -------
        str
            The full commit id.

        Raises
        ------
        panproto.VcsError
            If ``ref`` does not resolve to a commit, or returns ``None``.
        """
        result = self._inner.resolve_ref(ref)
        if result is None:
            import panproto  # noqa: PLC0415

            msg = f"ref {ref!r} did not resolve to a commit"
            raise panproto.VcsError(msg)
        return result

    def data_at(self, ref: str) -> list[CommittedDataset]:
        """Read the datasets committed at ``ref``.

        A read-only accessor for committed content: it resolves
        ``ref``, loads the datasets recorded at that revision, and
        returns their canonical Panproto encodings, leaving HEAD and the
        working tree untouched. This is the data-side counterpart to
        panproto's committed-schema lookup, so a downstream can identify
        and migrate the checked record set at an arbitrary revision
        without checking it out.

        Parameters
        ----------
        ref
            A branch name, tag name, ``HEAD``, or commit id naming the
            revision to read.

        Returns
        -------
        list of CommittedDataset
            One entry per dataset committed at ``ref``, in panproto's
            recorded order. Empty when the revision committed no data.

        Raises
        ------
        panproto.VcsError
            If ``ref`` does not resolve to a revision.
        """
        return [_committed_dataset(ds) for ds in self._inner.data_at(ref)]

    def blame_field(self, ref: str, model: type[Model], field: str) -> Blame:
        """Find the commit that introduced a declared Model field.

        Parameters
        ----------
        ref
            Branch name, tag, ``HEAD``, or commit id from which to walk
            first-parent history.
        model
            Model class whose schema was committed.
        field
            Python name of one of ``model``'s declared fields.

        Returns
        -------
        Blame
            Attribution for the commit that introduced the field vertex.

        Raises
        ------
        KeyError
            If ``field`` is not declared by ``model``.
        panproto.VcsError
            If ``ref`` does not resolve or the field vertex is absent from
            the reachable schema history.
        """
        if field not in model.__field_specs__:
            msg = f"{model.__name__} has no field {field!r}"
            raise KeyError(msg)
        commit_id = self.resolve_ref(ref)
        entry = self._inner.blame_vertex(commit_id, _field_vertex_id(model, field))
        return _blame(entry)

    # mutation ------------------------------------------------------

    def add(self, target: panproto.Schema | type) -> None:
        """Stage ``target`` for the next commit.

        Parameters
        ----------
        target
            Either a ``panproto.Schema`` or a [Model][didactic.api.Model]
            subclass. When given a Model class, didactic builds a
            schema using ``panproto.Protocol.from_theories`` over the
            Model's Theory.

        Notes
        -----
        Staging is additive: subsequent calls accumulate in the index
        until a [commit][didactic.api.Repository.commit] flushes it.
        """
        from didactic.models._model import Model  # noqa: PLC0415

        if isinstance(target, type) and issubclass(target, Model):
            self._inner.add(schema_from_model(target))
            return
        # already-narrowed by the isinstance branch above; only the
        # ``Schema`` arm of the union is left.
        self._inner.add(cast("panproto.Schema", target))

    def add_data(
        self,
        path: str | PathLike[str],
        *,
        key: str | None = None,
        schema_id: str | None = None,
        skip_verify: bool = False,
    ) -> None:
        """Stage a data file for the next commit.

        Reads the file at ``path``, parses and validates its records, and
        stages their canonical Panproto instances as a dataset bound to
        the staged schema, or to HEAD's schema when no schema is staged.
        The staged data is flushed by the next
        [commit][didactic.api.Repository.commit] and is then readable at
        that revision through
        [data_at][didactic.api.Repository.data_at]. This is the
        write-side counterpart to ``data_at``.

        Parameters
        ----------
        path
            Filesystem path to the JSON data file to stage. The file is
            read immediately; its records are checked against the active
            schema and captured in the repository's canonical encoding.
        key
            Identifier to record for the dataset, surfaced as
            [CommittedDataset.key][didactic.api.CommittedDataset]. A
            downstream that versions one record per dataset passes its
            own key (for example an AT-URI) so it can map the committed
            dataset back. When omitted, the dataset's key defaults to
            ``path``.
        schema_id
            Object id of a persisted schema to use when parsing, lifting,
            and validating this dataset. Supplying an id does not change
            HEAD or the staged schema. When omitted, panproto uses the
            staged schema, or HEAD's schema when no schema is staged.
        skip_verify
            If ``True``, skip panproto's dataset verification step.
            Defaults to ``False``.

        Notes
        -----
        Staging is additive: like [add][didactic.api.Repository.add],
        repeated calls accumulate in the index until a commit flushes
        it.

        Raises
        ------
        panproto.VcsError
            If ``schema_id`` is malformed, missing, or does not name a
            schema, or if no schema is staged and the repository has no
            commits yet, so the dataset has no schema to bind to.
        """
        self._inner.add_data(
            str(path),
            key=key,
            schema_id=schema_id,
            skip_verify=skip_verify,
        )

    def commit(
        self,
        message: str,
        *,
        author: str,
        skip_verify: bool = False,
    ) -> str:
        """Create a commit with ``message`` and ``author``.

        Parameters
        ----------
        message
            The commit message.
        author
            The commit author. Free-form string; the conventional
            shape is ``"Name <email>"``.
        skip_verify
            If ``True``, skip the panproto-side verification step.
            Defaults to ``False``.

        Returns
        -------
        str
            The new commit's object id.

        Raises
        ------
        panproto.VcsError
            If nothing is staged or panproto rejects the commit.
        """
        return self._inner.commit(message, author, skip_verify=skip_verify)

    def create_branch(self, name: str, commit_id: str) -> None:
        """Create a new branch ``name`` pointing at ``commit_id``."""
        self._inner.create_branch(name, commit_id)

    def checkout_branch(self, name: str) -> None:
        """Switch HEAD to branch ``name``."""
        self._inner.checkout_branch(name)

    # tags ----------------------------------------------------------

    def create_tag(self, name: str, target: str, *, force: bool = False) -> None:
        """Create a lightweight tag ``name`` pointing at ``target``.

        A lightweight tag is a named pointer to a commit, carrying no
        message or tagger. Use
        [create_annotated_tag][didactic.api.Repository.create_annotated_tag]
        for a tag object that records who tagged what, when, and why.

        Parameters
        ----------
        name
            The tag name.
        target
            The commit id to tag, as returned by
            [commit][didactic.api.Repository.commit],
            [head][didactic.api.Repository.head], or
            [resolve_ref][didactic.api.Repository.resolve_ref].
        force
            If ``True``, overwrite an existing tag of the same name.
            Defaults to ``False``, under which an existing ``name``
            is an error.

        Raises
        ------
        panproto.VcsError
            If a tag ``name`` already exists and ``force`` is ``False``.
        """
        if force:
            self._inner.create_tag_force(name, target)
        else:
            self._inner.create_tag(name, target)

    def create_annotated_tag(
        self,
        name: str,
        target: str,
        *,
        message: str,
        tagger: str,
    ) -> str:
        """Create an annotated tag ``name`` pointing at ``target``.

        An annotated tag is a first-class object recording a tagger,
        a timestamp, and a message, unlike a lightweight tag which is
        only a named pointer. The tag ref resolves to the annotated-tag
        object rather than to ``target`` directly.

        Parameters
        ----------
        name
            The tag name.
        target
            The commit id to tag (see
            [create_tag][didactic.api.Repository.create_tag] for the
            accepted forms).
        message
            The tag message.
        tagger
            The tagger identity. Free-form string; the conventional
            shape is ``"Name <email>"``.

        Returns
        -------
        str
            Object id of the created annotated-tag object, the id the
            tag ref resolves to.

        Raises
        ------
        panproto.VcsError
            If a tag ``name`` already exists or panproto rejects the
            tag.
        """
        return self._inner.create_annotated_tag(name, target, tagger, message)

    def delete_tag(self, name: str) -> None:
        """Delete the tag ``name``.

        Parameters
        ----------
        name
            The tag to delete.

        Raises
        ------
        panproto.VcsError
            If no tag ``name`` exists.
        """
        self._inner.delete_tag(name)

    # representation ------------------------------------------------

    def __repr__(self) -> str:
        return f"Repository(at={self._inner.working_dir!r})"


_FIELD_EDGE_KIND = "field"
_FIELD_VERTEX_KIND = "field"
_FIELD_SORT_CONSTRAINT = "didactic:sort"
_FIELD_KIND_CONSTRAINT = "didactic:kind"
_FIELD_REQUIRED_CONSTRAINT = "didactic:required"
_FIELD_USAGE_MODE_CONSTRAINT = "didactic:usage-mode"
_FIELD_AXIOM_CONSTRAINT = "didactic:axiom"


def protocol_from_model(
    cls: type[Model], *, name: str | None = None
) -> panproto.Protocol:
    """Build the panproto protocol shared by a Model's schema operations."""
    import panproto  # noqa: PLC0415

    from didactic.theory._theory import build_theory  # noqa: PLC0415

    return panproto.Protocol.from_theories(
        name=name or cls.__name__,
        schema_theory=build_theory(cls),
        obj_kinds=["object", _FIELD_VERTEX_KIND],
        edge_rules=[
            {
                "edge_kind": _FIELD_EDGE_KIND,
                "src_kinds": ["object"],
                "tgt_kinds": [_FIELD_VERTEX_KIND],
            }
        ],
        constraint_sorts=[
            _FIELD_SORT_CONSTRAINT,
            _FIELD_KIND_CONSTRAINT,
            _FIELD_REQUIRED_CONSTRAINT,
            _FIELD_USAGE_MODE_CONSTRAINT,
            _FIELD_AXIOM_CONSTRAINT,
        ],
        nominal_identity=True,
    )


def schema_from_model(cls: type[Model]) -> panproto.Schema:
    """Build a field-addressable panproto Schema from a Model class.

    Parameters
    ----------
    cls
        A [Model][didactic.api.Model] subclass.

    Returns
    -------
    panproto.Schema
        A schema with the Model's Theory acting as both the schema-theory
        and instance-theory of a synthesised ``Protocol``. It contains one
        root vertex named after the class and one field vertex per
        ``FieldSpec``, connected to the root by a labelled ``field`` edge.
        Each field vertex records the didactic sort, structural kind,
        requiredness, usage mode, and axioms as constraints, plus an explicit
        nominal or structural identity flag.
    """
    protocol = protocol_from_model(cls)
    builder = protocol.schema()
    builder.vertex(cls.__name__, "object")
    for field_name, spec in cls.__field_specs__.items():
        vertex_id = _field_vertex_id(cls, field_name)
        builder.vertex(vertex_id, _FIELD_VERTEX_KIND)
        builder.nominal(vertex_id, spec.nominal)
        builder.edge(
            cls.__name__,
            vertex_id,
            _FIELD_EDGE_KIND,
            spec.alias or field_name,
        )
        builder.constraint(vertex_id, _FIELD_SORT_CONSTRAINT, spec.translation.sort)
        builder.constraint(
            vertex_id, _FIELD_KIND_CONSTRAINT, spec.translation.inner_kind
        )
        builder.constraint(
            vertex_id,
            _FIELD_REQUIRED_CONSTRAINT,
            str(spec.is_required).lower(),
        )
        builder.constraint(vertex_id, _FIELD_USAGE_MODE_CONSTRAINT, spec.usage_mode)
        for axiom in spec.axioms:
            builder.constraint(vertex_id, _FIELD_AXIOM_CONSTRAINT, axiom)
    return builder.build()


def _field_vertex_id(cls: type[Model], field: str) -> str:
    """Return the deterministic schema vertex id for a Model field."""
    return f"{cls.__name__}.{field}"


def _committed_dataset(ds: dict[str, str | bytes | int | None]) -> CommittedDataset:
    """Narrow one panproto dataset mapping to a ``CommittedDataset``.

    panproto types each committed dataset as a mapping with union-typed
    values; the keys carry fixed types, so each is narrowed at the
    boundary.
    """
    schema_id = ds["schema_id"]
    data = ds["data"]
    record_count = ds["record_count"]
    key = ds["key"]
    assert isinstance(schema_id, str)
    assert isinstance(data, bytes)
    assert isinstance(record_count, int)
    assert key is None or isinstance(key, str)
    return CommittedDataset(
        schema_id=schema_id,
        data=data,
        record_count=record_count,
        key=key,
    )


def _blame(entry: JsonObject) -> Blame:
    """Narrow panproto's blame mapping to the public ``Blame`` record."""
    commit_id = entry["commit_id"]
    author = entry["author"]
    timestamp = entry["timestamp"]
    message = entry["message"]
    assert isinstance(commit_id, str)
    assert isinstance(author, str)
    assert isinstance(timestamp, int)
    assert isinstance(message, str)
    return Blame(
        commit_id=commit_id,
        author=author,
        timestamp=timestamp,
        message=message,
    )


__all__ = [
    "Blame",
    "CommittedDataset",
    "Repository",
]
