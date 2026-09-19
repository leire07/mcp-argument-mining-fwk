from .base import PropositionalisationModule, PropositionalisationOutput
from ..errors import ArgumentMiningError, PropositionError
from ..models import ArgumentSpan, EvidenceRecord
from ..xaif import parse_claims, spans_xaif


class OAMFPropositionalisationModule(PropositionalisationModule):
    module_id: str

    def run(self, evidence: EvidenceRecord, spans: list[ArgumentSpan], experiment_id: str,
            input_kind: str) -> PropositionalisationOutput:
        request = spans_xaif(spans)
        try:
            response, module_run = self.client.invoke(self.spec, request, experiment_id)
        except Exception as exc:
            exc.xaif_input = request
            raise
        try:
            claims = parse_claims(response, spans, evidence, module_run, input_kind)
        except ArgumentMiningError as exc:
            exc.xaif_input, exc.xaif_response, exc.module_run = request, response, module_run
            raise
        except (KeyError, TypeError, ValueError) as exc:
            error = PropositionError(f"Respuesta xAIF inválida de {self.spec.module_id}: {exc}")
            error.xaif_input, error.xaif_response, error.module_run = request, response, module_run
            raise error from exc
        return PropositionalisationOutput(claims, request, response, module_run)
