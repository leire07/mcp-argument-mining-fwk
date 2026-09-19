from ..models import ArgumentSpan, ArgumentUnit, Claim, EvidenceRecord


def aif_part(xaif: dict) -> dict:
    value = xaif.get("AIF", xaif.get("aif"))
    if not isinstance(value, dict) or not isinstance(value.get("nodes"), list):
        raise ValueError("La respuesta no contiene AIF.nodes")
    return value


def evidence_xaif(evidence: EvidenceRecord) -> dict:
    return {
        "AIF": {"nodes": [{"nodeID": 0, "text": evidence.passage_text, "type": "L"}],
                "edges": [], "locutions": [], "participants": [],
                "schemefulfillments": None, "descriptorfulfillments": None},
        "dialog": False, "ova": [], "text": {"txt": evidence.passage_text},
    }


def spans_xaif(spans: list[ArgumentSpan]) -> dict:
    return {
        "AIF": {"nodes": [{"nodeID": index, "text": span.source_span.text, "type": "L"}
                           for index, span in enumerate(spans)],
                "edges": [], "locutions": [], "participants": [],
                "schemefulfillments": None, "descriptorfulfillments": None},
        "dialog": False, "ova": [], "text": {"txt": "\n".join(s.source_span.text for s in spans)},
    }


def claims_xaif(claims: list[Claim]) -> dict:
    # Relation modules do not all honour the minimal "I nodes only" contract.
    # DTERG, in particular, expects the canonical output of a propositionaliser:
    # one L -> YA -> I chain per claim.  Keep I-node order equal to claim order so
    # response parsing remains deterministic across modules.
    count = len(claims)
    nodes = [
        {"nodeID": index, "text": claim.source.source_span.text, "type": "L"}
        for index, claim in enumerate(claims)
    ]
    edges = []
    for index, claim in enumerate(claims):
        i_node_id = count + (2 * index)
        ya_node_id = i_node_id + 1
        nodes.extend([
            {"nodeID": i_node_id, "text": claim.proposition_text, "type": "I"},
            {"nodeID": ya_node_id, "text": "Default Illocuting", "type": "YA"},
        ])
        edges.extend([
            {"edgeID": len(edges), "fromID": index, "toID": ya_node_id},
            {"edgeID": len(edges) + 1, "fromID": ya_node_id, "toID": i_node_id},
        ])
    return {
        "AIF": {"nodes": nodes, "edges": edges, "locutions": [], "participants": [],
                "schemefulfillments": None, "descriptorfulfillments": None},
        "dialog": False, "ova": [], "text": {"txt": "\n".join(c.proposition_text for c in claims)},
    }


def argument_units_xaif(units: list[ArgumentUnit]) -> dict:
    """Build canonical L→YA→I input without pretending extractive units are gold claims."""
    count = len(units)
    nodes = [
        {"nodeID": index, "text": unit.source_span.text, "type": "L"}
        for index, unit in enumerate(units)
    ]
    edges = []
    for index, unit in enumerate(units):
        i_node_id = count + (2 * index)
        ya_node_id = i_node_id + 1
        nodes.extend([
            {"nodeID": i_node_id, "text": unit.source_span.text, "type": "I"},
            {"nodeID": ya_node_id, "text": "Default Illocuting", "type": "YA"},
        ])
        edges.extend([
            {"edgeID": len(edges), "fromID": index, "toID": ya_node_id},
            {"edgeID": len(edges) + 1, "fromID": ya_node_id, "toID": i_node_id},
        ])
    return {
        "AIF": {"nodes": nodes, "edges": edges, "locutions": [], "participants": [],
                "schemefulfillments": None, "descriptorfulfillments": None},
        "dialog": False, "ova": [],
        "text": {"txt": "\n".join(unit.source_span.text for unit in units)},
    }
