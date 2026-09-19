from ..models import ArgumentRelation, Claim


def final_xaif(claims: list[Claim], relations: list[ArgumentRelation], experiment_id: str) -> dict:
    nodes, edges, mappings = [], [], []
    next_node = next_edge = 0
    claim_nodes: dict[str, int] = {}
    for claim in claims:
        l_id, ya_id, i_id = next_node, next_node + 1, next_node + 2
        next_node += 3
        nodes.extend([
            {"nodeID": l_id, "text": claim.source.source_span.text, "type": "L"},
            {"nodeID": ya_id, "text": "Default Illocuting", "type": "YA"},
            {"nodeID": i_id, "text": claim.proposition_text, "type": "I"},
        ])
        edges.extend([
            {"edgeID": next_edge, "fromID": l_id, "toID": ya_id},
            {"edgeID": next_edge + 1, "fromID": ya_id, "toID": i_id},
        ])
        next_edge += 2
        claim_nodes[claim.claim_id] = i_id
        mappings.append({"claim_id": claim.claim_id, "evidence_id": claim.evidence_id,
                         "span_id": claim.span_id, "l_node_id": l_id, "i_node_id": i_id})
    for relation in relations:
        if relation.relation == "none":
            continue
        relation_node_id = next_node
        next_node += 1
        nodes.append({
            "nodeID": relation_node_id,
            "text": {"RA": "Default Inference", "CA": "Default Conflict",
                     "MA": "Default Rephrase"}[relation.xaif_relation_type],
            "type": relation.xaif_relation_type,
        })
        edges.extend([
            {"edgeID": next_edge, "fromID": claim_nodes[relation.source_claim_id],
             "toID": relation_node_id},
            {"edgeID": next_edge + 1, "fromID": relation_node_id,
             "toID": claim_nodes[relation.target_claim_id]},
        ])
        next_edge += 2
    return {
        "AIF": {"nodes": nodes, "edges": edges, "locutions": [], "participants": [],
                "schemefulfillments": None, "descriptorfulfillments": None},
        "dialog": False, "ova": [], "text": {"txt": "\n".join(c.proposition_text for c in claims)},
        "oamfTrace": {"schemaVersion": "1.0", "experiment_id": experiment_id,
                      "claim_mappings": mappings},
    }
