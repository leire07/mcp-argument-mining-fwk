from __future__ import annotations

import hashlib
import re
from collections import defaultdict

from ..errors import PropositionError, RelationError, SegmentationError
from ..models import (ArgumentRelation, ArgumentSpan, ArgumentUnit, Claim, ClaimSource, EvidenceRecord,
                      ModuleRun, SourceSpan)
from .input import aif_part


DOCUMENT_FIELDS = ("document_id", "title", "source", "source_type", "url", "content_type",
                   "section", "publication_year", "publication_types", "doi", "pmid", "pmcid")


def stable_id(prefix: str, *parts: object) -> str:
    digest = hashlib.sha256("\n".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{digest}"


def _locate(text: str, segment: str, cursor: int) -> tuple[int, int]:
    clean = segment.strip()
    aligned_end = None
    start = text.find(clean, cursor)
    if start < 0:
        start = text.find(clean)
    if start < 0:
        pattern = r"\s+".join(re.escape(part) for part in clean.split())
        cursor_match = re.search(pattern, text[cursor:])
        match = cursor_match or re.search(pattern, text)
        if match:
            base = cursor if cursor_match else 0
            start, clean = base + match.start(), text[base + match.start():base + match.end()]
    if start < 0:
        # Algunos módulos eliminan comas o normalizan puntuación. Sólo aceptamos
        # la alineación si la secuencia completa de palabras permanece idéntica.
        wanted = [match.group(0).casefold() for match in re.finditer(r"\w+", clean)]
        source_tokens = list(re.finditer(r"\w+", text[cursor:]))
        for index in range(len(source_tokens) - len(wanted) + 1):
            observed = [match.group(0).casefold() for match in source_tokens[index:index + len(wanted)]]
            if wanted and observed == wanted:
                start = cursor + source_tokens[index].start()
                aligned_end = cursor + source_tokens[index + len(wanted) - 1].end()
                break
    if start < 0:
        raise SegmentationError(f"No se puede alinear el segmento con passage_text: {clean[:100]!r}")
    end = aligned_end if aligned_end is not None else start + len(clean)
    if clean.lstrip().startswith("%"):
        number = re.search(r"\d+(?:\.\d+)?\s*$", text[cursor:start])
        if number:
            start = cursor + number.start()
    while end < len(text) and text[end] in ".!?;:":
        end += 1
    return start, end


def parse_spans(xaif: dict, evidence: EvidenceRecord, run: ModuleRun,
                input_kind: str = "predicted") -> list[ArgumentSpan]:
    nodes = [n for n in aif_part(xaif)["nodes"]
             if n.get("type") == "L" and str(n.get("text", "")).strip()]
    full = evidence.passage_text.strip()
    if len(nodes) > 1:
        smaller = [n for n in nodes if str(n["text"]).strip() != full]
        if smaller:
            nodes = smaller
    result, cursor = [], 0
    for node in nodes:
        start, end = _locate(evidence.passage_text, str(node["text"]), cursor)
        exact = evidence.passage_text[start:end]
        span = SourceSpan(start_char=start, end_char=end, text=exact)
        result.append(ArgumentSpan(
            span_id=stable_id("sp", evidence.evidence_id, start, end, exact),
            evidence_id=evidence.evidence_id, source_span=span,
            l_node_id=str(node["nodeID"]), input_kind=input_kind, generated_by=run,
        ))
        cursor = end
    if not result:
        raise SegmentationError(f"El módulo no produjo nodos L para {evidence.evidence_id}")
    return result


def _document(evidence: EvidenceRecord) -> dict:
    data = evidence.model_dump()
    return {key: data.get(key) for key in DOCUMENT_FIELDS if key in data}


def parse_claims(xaif: dict, spans: list[ArgumentSpan], evidence: EvidenceRecord,
                 run: ModuleRun, input_kind: str = "predicted") -> list[Claim]:
    aif = aif_part(xaif)
    by_id = {str(n["nodeID"]): n for n in aif["nodes"]}
    incoming: dict[str, list[str]] = defaultdict(list)
    for edge in aif.get("edges", []):
        incoming[str(edge["toID"])].append(str(edge["fromID"]))
    input_l_ids = {str(index): span for index, span in enumerate(spans)}
    l_text_map: dict[str, list[ArgumentSpan]] = defaultdict(list)
    for span in spans:
        l_text_map[span.source_span.text.strip()].append(span)
    result = []
    for node in (n for n in aif["nodes"] if n.get("type") == "I"):
        inode = str(node["nodeID"])
        lnode = None
        for ya_id in incoming.get(inode, []):
            ya = by_id.get(ya_id)
            if ya and ya.get("type") == "YA":
                for candidate in incoming.get(ya_id, []):
                    if candidate in input_l_ids:
                        lnode = candidate
                        break
        if lnode is not None:
            span = input_l_ids[lnode]
        else:
            matches = l_text_map.get(str(node.get("text", "")).strip(), [])
            span = matches.pop(0) if matches else None
        if span is None:
            raise PropositionError(f"Nodo I huérfano {inode}: no enlaza con ningún nodo L de entrada")
        proposition = str(node.get("text", "")).strip()
        if not proposition:
            raise PropositionError(f"Nodo I vacío: {inode}")
        source = ClaimSource(
            evidence_id=evidence.evidence_id, passage_text=evidence.passage_text,
            source_span=span.source_span, document=_document(evidence),
            retrieval_provenance=evidence.provenance,
            upstream_assessments=evidence.assessments,
        )
        result.append(Claim(
            claim_id=stable_id("cl", evidence.evidence_id, span.span_id, proposition),
            evidence_id=evidence.evidence_id, span_id=span.span_id,
            l_node_id=span.l_node_id, i_node_id=inode, proposition_text=proposition,
            source=source, input_kind=input_kind, generated_by=run,
        ))
    if not result:
        raise PropositionError(f"El módulo no produjo nodos I para {evidence.evidence_id}")
    return result


RELATIONS = {"RA": "support", "CA": "attack", "MA": "rephrase"}


def parse_relations(xaif: dict, input_claims: list[Claim], run: ModuleRun,
                    input_kind: str = "predicted") -> list[ArgumentRelation]:
    aif = aif_part(xaif)
    nodes = {str(n["nodeID"]): n for n in aif["nodes"]}
    expected = {str(i): claim for i, claim in enumerate(input_claims)}
    text_queues: dict[str, list[Claim]] = defaultdict(list)
    for claim in input_claims:
        text_queues[" ".join(claim.proposition_text.split())].append(claim)
    claim_by_external = {}
    for node_id, node in nodes.items():
        if node.get("type") != "I":
            continue
        text = " ".join(str(node.get("text", "")).split())
        if node_id in expected and text == " ".join(expected[node_id].proposition_text.split()):
            claim_by_external[node_id] = expected[node_id]
            if expected[node_id] in text_queues[text]:
                text_queues[text].remove(expected[node_id])
        elif text_queues[text]:
            claim_by_external[node_id] = text_queues[text].pop(0)
    incoming: dict[str, list[str]] = defaultdict(list)
    outgoing: dict[str, list[str]] = defaultdict(list)
    for edge in aif.get("edges", []):
        source, target = str(edge["fromID"]), str(edge["toID"])
        incoming[target].append(source)
        outgoing[source].append(target)
    result = []
    for relation_node, node in nodes.items():
        kind = node.get("type")
        if kind not in RELATIONS:
            continue
        sources = [claim_by_external[n] for n in incoming.get(relation_node, []) if n in claim_by_external]
        targets = [claim_by_external[n] for n in outgoing.get(relation_node, []) if n in claim_by_external]
        if not sources or not targets:
            raise RelationError(f"Relación {relation_node} sin extremos I trazables")
        for source in sources:
            for target in targets:
                result.append(ArgumentRelation(
                    relation_id=stable_id("rel", run.module_id, source.claim_id, target.claim_id, kind),
                    source_claim_id=source.claim_id, target_claim_id=target.claim_id,
                    relation=RELATIONS[kind], xaif_relation_type=kind,
                    input_kind=input_kind, generated_by=run,
                ))
    return result


def parse_unit_relations(xaif: dict, units: list[ArgumentUnit], run: ModuleRun,
                         input_kind: str = "gold",
                         allowed_relation_types: set[str] | None = None) -> list[ArgumentRelation]:
    """Parse module edges against stable AbstRCT component endpoints."""
    aif = aif_part(xaif)
    nodes = {str(node["nodeID"]): node for node in aif["nodes"]}
    count = len(units)
    expected = {str(count + (2 * index)): unit for index, unit in enumerate(units)}
    text_queues: dict[str, list[ArgumentUnit]] = defaultdict(list)
    for unit in units:
        text_queues[" ".join(unit.source_span.text.split())].append(unit)
    unit_by_external = {}
    for node_id, node in nodes.items():
        if node.get("type") != "I":
            continue
        text = " ".join(str(node.get("text", "")).split())
        if node_id in expected and text == " ".join(expected[node_id].source_span.text.split()):
            unit_by_external[node_id] = expected[node_id]
            if expected[node_id] in text_queues[text]:
                text_queues[text].remove(expected[node_id])
        elif text_queues[text]:
            unit_by_external[node_id] = text_queues[text].pop(0)
    incoming: dict[str, list[str]] = defaultdict(list)
    outgoing: dict[str, list[str]] = defaultdict(list)
    for edge in aif.get("edges", []):
        source, target = str(edge["fromID"]), str(edge["toID"])
        incoming[target].append(source)
        outgoing[source].append(target)
    allowed = allowed_relation_types or {"RA", "CA"}
    result = []
    for relation_node, node in nodes.items():
        kind = node.get("type")
        if kind not in RELATIONS or kind not in allowed:
            continue
        sources = [unit_by_external[value] for value in incoming.get(relation_node, [])
                   if value in unit_by_external]
        targets = [unit_by_external[value] for value in outgoing.get(relation_node, [])
                   if value in unit_by_external]
        if not sources or not targets:
            raise RelationError(f"Relación {relation_node} sin extremos I trazables")
        for source in sources:
            for target in targets:
                result.append(ArgumentRelation(
                    relation_id=stable_id("rel", run.module_id, source.unit_id, target.unit_id, kind),
                    source_claim_id=source.unit_id, target_claim_id=target.unit_id,
                    relation=RELATIONS[kind], xaif_relation_type=kind,
                    input_kind=input_kind, endpoint_kind="argument_unit", generated_by=run,
                ))
    return result
