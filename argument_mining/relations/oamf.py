from .base import RelationIdentificationModule, RelationIdentificationOutput
from ..errors import ArgumentMiningError, RelationError
from ..models import Claim
from ..xaif import claims_xaif, parse_relations


class OAMFRelationIdentificationModule(RelationIdentificationModule):
    module_id: str

    def run(self, claims: list[Claim], experiment_id: str,
            input_kind: str) -> RelationIdentificationOutput:
        request = claims_xaif(claims)
        try:
            response, module_run = self.client.invoke(self.spec, request, experiment_id)
        except Exception as exc:
            exc.xaif_input = request
            raise
        try:
            relations = parse_relations(response, claims, module_run, input_kind)
        except ArgumentMiningError as exc:
            exc.xaif_input, exc.xaif_response, exc.module_run = request, response, module_run
            raise
        except (KeyError, TypeError, ValueError) as exc:
            error = RelationError(f"Respuesta xAIF inválida de {self.spec.module_id}: {exc}")
            error.xaif_input, error.xaif_response, error.module_run = request, response, module_run
            raise error from exc
        return RelationIdentificationOutput(relations, request, response, module_run)
