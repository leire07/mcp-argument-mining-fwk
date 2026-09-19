from .base import SegmentationModule, SegmentationOutput
from .dsg import DSGSegmenter
from .dss import DSSSegmenter
from .targer import TARGERSegmenter


SEGMENTERS = {cls.module_id: cls for cls in (DSGSegmenter, TARGERSegmenter, DSSSegmenter)}


def create_segmenter(spec, client) -> SegmentationModule:
    try:
        return SEGMENTERS[spec.module_id.upper()](spec, client)
    except KeyError as exc:
        raise ValueError(f"Segmentador sin adaptador: {spec.module_id}") from exc


__all__ = ["SegmentationModule", "SegmentationOutput", "create_segmenter"]
