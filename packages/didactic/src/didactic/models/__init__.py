"""Model machinery: ``Model``, ``BaseModel``, ``ModelConfig``, storage, metaclass."""

from didactic.models._config import DEFAULT_CONFIG, ExtraPolicy, ModelConfig
from didactic.models._meta import ModelMeta
from didactic.models._model import BaseModel, Model
from didactic.models._root import RootModel, TypeAdapter
from didactic.models._storage import DictStorage

__all__ = [
    "DEFAULT_CONFIG",
    "BaseModel",
    "DictStorage",
    "ExtraPolicy",
    "Model",
    "ModelConfig",
    "ModelMeta",
    "RootModel",
    "TypeAdapter",
]
