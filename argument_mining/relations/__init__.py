from .base import RelationIdentificationModule, RelationIdentificationOutput
from .arir import ARIRRelations
from .damg import DAMGRelations
from .drig import DRIGRelations
from .dsrm import DSRMRelations
from .dterg import DTERGRelations
from .sarim import SARIMRelations
from .targer_am import TARGERAMRelations


RELATION_MODULES = (DAMGRelations, SARIMRelations, ARIRRelations, DRIGRelations,
                    TARGERAMRelations, DSRMRelations, DTERGRelations)
RELATION_IDENTIFIERS = {cls.module_id: cls for cls in RELATION_MODULES}


def create_relation_identifier(spec, client) -> RelationIdentificationModule:
    try:
        return RELATION_IDENTIFIERS[spec.module_id.upper()](spec, client)
    except KeyError as exc:
        raise ValueError(f"Identificador de relaciones sin adaptador: {spec.module_id}") from exc


__all__ = ["RelationIdentificationModule", "RelationIdentificationOutput",
           "create_relation_identifier"]
