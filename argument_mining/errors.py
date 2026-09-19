class ArgumentMiningError(Exception):
    """Base error carrying the stage that failed."""

    error_type = "argument_mining"


class ProvenanceError(ArgumentMiningError):
    error_type = "provenance"


class SegmentationError(ArgumentMiningError):
    error_type = "segmentation"


class PropositionError(ArgumentMiningError):
    error_type = "proposition"


class RelationError(ArgumentMiningError):
    error_type = "relation"


class SerializationError(ArgumentMiningError):
    error_type = "serialization"
