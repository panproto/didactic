"""Schemas shared by the composition engine tests.

The tree mirrors the shape LoFI composes: tagged-union roots
(``discriminator="kind"``, ``extra="forbid"``) behind an optional slot, a
required slot with a variant as its default, a ``dict[str, Union]`` role map
and a ``tuple[Union, ...]`` sequence, all under plain model sections.

This module deliberately omits ``from __future__ import annotations``:
``TaggedUnion.__init_subclass__`` reads each variant's ``Literal[...]``
discriminator annotation at class-creation time and refuses a string.
"""

from collections.abc import Mapping
from typing import Literal

import didactic.api as dx
from didactic.settings import ConfigValue


def subtree(tree: Mapping[str, ConfigValue], *keys: str) -> dict[str, ConfigValue]:
    """Index a nested document, asserting each step lands on a mapping."""
    node: ConfigValue = tree
    for key in keys:
        assert isinstance(node, dict), f"{key!r}: expected a mapping, got {node!r}"
        node = node[key]
    assert isinstance(node, dict), f"expected a mapping at {keys}, got {node!r}"
    return node


class TypeEncoderSpec(dx.TaggedUnion, discriminator="kind", extra="forbid"):
    """Encoder root with no shared fields."""


class TransformerEncoder(TypeEncoderSpec):
    """A transformer encoder; carries a computed field like LoFI's components."""

    kind: Literal["transformer"] = "transformer"
    num_heads: int = 4
    width: int = 256

    @dx.computed
    def declared_output(self) -> int:
        """Output width, derived from the stored fields."""
        return self.num_heads * self.width


class LstmEncoder(TypeEncoderSpec):
    """An LSTM encoder."""

    kind: Literal["lstm"] = "lstm"
    hidden: int = 128
    dropout: float = 0.0


class AttentionSpec(dx.TaggedUnion, discriminator="kind", extra="forbid"):
    """A union nested inside a variant of another union."""


class DotAttention(AttentionSpec):
    """Dot-product attention."""

    kind: Literal["dot"] = "dot"
    scale: float = 1.0


class AdditiveAttention(AttentionSpec):
    """Additive attention."""

    kind: Literal["additive"] = "additive"
    hidden: int = 32


class HeadSpec(dx.Model, extra="forbid"):
    """A plain model nested inside a variant."""

    layers: int = 1
    dropout: float = 0.1


class GruEncoder(TypeEncoderSpec):
    """A variant with a nested model and a nested union among its fields."""

    kind: Literal["gru"] = "gru"
    dropout: float = 0.0
    head: HeadSpec = dx.field(default_factory=HeadSpec)
    attention: AttentionSpec = dx.field(default_factory=DotAttention)


class DecoderSpec(dx.TaggedUnion, discriminator="kind", extra="forbid"):
    """Decoder root with one shared field."""

    temperature: float = 1.0


class LinearDecoder(DecoderSpec):
    """A linear decoder."""

    kind: Literal["linear"] = "linear"
    bias: bool = True


class MlpDecoder(DecoderSpec):
    """An MLP decoder."""

    kind: Literal["mlp"] = "mlp"
    hidden: int = 64


class OptimizerSpec(dx.TaggedUnion, discriminator="kind", extra="forbid"):
    """Optimizer root with one shared field."""

    lr: float = 1e-3


class Adam(OptimizerSpec):
    """Adam optimizer."""

    kind: Literal["adam"] = "adam"
    betas: tuple[float, ...] = (0.9, 0.999)


class Sgd(OptimizerSpec):
    """SGD optimizer."""

    kind: Literal["sgd"] = "sgd"
    momentum: float = 0.9


class ModelSection(dx.Model, extra="forbid"):
    """The model section: an optional union slot and a union-valued map."""

    type_encoder: TypeEncoderSpec | None = None
    combinator_decoders: dict[str, DecoderSpec] = dx.field(
        default_factory=dict[str, DecoderSpec]
    )


class TrainerSpec(dx.Model, extra="forbid"):
    """Trainer section with a default expression on one leaf."""

    epochs: int = 1
    out_dir: str = "runs"
    log_dir: str = "${trainer.out_dir}/logs"


class RunSpec(dx.Model, extra="forbid"):
    """The root document."""

    model: ModelSection = dx.field(default_factory=ModelSection)
    optimizer: OptimizerSpec = dx.field(default_factory=Adam)
    trainer: TrainerSpec = dx.field(default_factory=TrainerSpec)
    paths: dict[str, str] = dx.field(default_factory=dict[str, str])
    encoders: tuple[TypeEncoderSpec, ...] = ()


class Stage(dx.TaggedUnion, discriminator="code", extra="forbid"):
    """A union discriminated by integer literals."""


class StageOne(Stage):
    """Stage tagged ``1``."""

    code: Literal[1] = 1
    a: int = 0


class StageTwo(Stage):
    """Stage tagged ``2``."""

    code: Literal[2] = 2
    b: int = 0


class Pipeline(dx.Model, extra="forbid"):
    """A document whose union is tagged by integers."""

    stage: Stage = dx.field(default_factory=StageOne)
