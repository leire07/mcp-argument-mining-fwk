from .base import SegmentationModule, SegmentationOutput
from ..errors import ArgumentMiningError, SegmentationError
from ..models import EvidenceRecord
from ..xaif import evidence_xaif, parse_spans


class OAMFSegmentationModule(SegmentationModule):
    module_id: str

    def run(self, evidence: EvidenceRecord, experiment_id: str) -> SegmentationOutput:
        request = evidence_xaif(evidence)
        try:
            response, module_run = self.client.invoke(self.spec, request, experiment_id)
        except Exception as exc:
            exc.xaif_input = request
            raise
        try:
            spans = parse_spans(response, evidence, module_run)
        except ArgumentMiningError as exc:
            exc.xaif_input, exc.xaif_response, exc.module_run = request, response, module_run
            raise
        except (KeyError, TypeError, ValueError) as exc:
            error = SegmentationError(f"Respuesta xAIF inválida de {self.spec.module_id}: {exc}")
            error.xaif_input, error.xaif_response, error.module_run = request, response, module_run
            raise error from exc
        return SegmentationOutput(spans, request, response, module_run)
