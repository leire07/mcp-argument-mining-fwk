from .base import PropositionalisationModule, PropositionalisationOutput
from .cpj import CPJPropositionaliser
from .spg import SPGPropositionaliser


PROPOSITIONALISERS = {cls.module_id: cls for cls in (SPGPropositionaliser, CPJPropositionaliser)}


def create_propositionaliser(spec, client) -> PropositionalisationModule:
    try:
        return PROPOSITIONALISERS[spec.module_id.upper()](spec, client)
    except KeyError as exc:
        raise ValueError(f"Proposicionador sin adaptador: {spec.module_id}") from exc


__all__ = ["PropositionalisationModule", "PropositionalisationOutput", "create_propositionaliser"]
