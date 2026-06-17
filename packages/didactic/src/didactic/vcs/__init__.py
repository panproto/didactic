"""Filesystem-backed VCS for panproto schemas, plus Backref resolution."""

from didactic.vcs._backref import ModelPool, resolve_backrefs
from didactic.vcs._repo import CommittedDataset, Repository

__all__ = [
    "CommittedDataset",
    "ModelPool",
    "Repository",
    "resolve_backrefs",
]
