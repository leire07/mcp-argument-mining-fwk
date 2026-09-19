from __future__ import annotations

import json
import re
from pathlib import Path

from .models import Assessment, EvidenceItem, Passage, Provenance


def unpack_mcp_response(value) -> dict:
    if hasattr(value, "model_dump"):
        value = value.model_dump(by_alias=True, mode="json")
    if not isinstance(value, dict):
        raise ValueError("Respuesta MCP no estructurada")
    if "passages" in value or "error" in value:
        return value
    for key in ("structuredContent", "structured_content"):
        if isinstance(value.get(key), dict):
            return value[key]
    for block in value.get("content", []):
        if isinstance(block, dict) and block.get("type") == "text":
            try:
                parsed = json.loads(block["text"])
                if isinstance(parsed, dict):
                    return parsed
            except (ValueError, KeyError):
                continue
    raise ValueError("La respuesta MCP no contiene JSON de evidencia")


class EvidenceStore:
    def __init__(self, output: Path):
        self.output = output
        self.items: dict[str, EvidenceItem] = {}
        self.errors: list[dict] = []
        self.agent_status: dict[str, str] = {}
        self.tool_calls: dict[str, int] = {}
        self.llm_calls = 0
        self.usage: dict[str, int] = {}

    def log(self, filename: str, data: dict):
        with (self.output / filename).open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(data, ensure_ascii=False, default=str) + "\n")

    def error(self, agent: str, message: str):
        entry = {"agent": agent, "message": message}
        self.errors.append(entry)
        self.log("errors.jsonl", entry)

    def ingest(self, response, agent: str, tool: str):
        payload = unpack_mcp_response(response)
        if payload.get("error"):
            self.error(agent, str(payload["error"]))
        for raw in payload.get("passages", []):
            passage = Passage.model_validate(raw)
            passage.raw_file = f"agents/{agent}/{passage.raw_file}"
            provenance = Provenance(
                retrieved_by=agent, tool=tool, retrieval_query=passage.retrieval_query,
                source=passage.source, url=passage.url, retrieved_at=passage.retrieved_at,
                source_rank=passage.source_rank, raw_file=passage.raw_file,
            )
            existing = self.items.get(passage.evidence_id)
            if existing is None:
                existing = EvidenceItem(**passage.model_dump())
                self.items[passage.evidence_id] = existing
            if provenance not in existing.provenance:
                existing.provenance.append(provenance)
        self.save_candidates()

    def assess(self, agent: str, evidence_ids: list[str], relevance_scores: list[int], reasons: list[str]) -> dict:
        if not len(evidence_ids) == len(relevance_scores) == len(reasons):
            return {"error": "Las tres listas deben tener la misma longitud"}
        pending = []
        for key, score, reason in zip(evidence_ids, relevance_scores, reasons):
            item = self.items.get(key)
            if item is None or not any(p.retrieved_by == agent for p in item.provenance):
                return {"error": f"{key} no fue recuperado por este agente; usa sólo IDs de tus herramientas",
                        "available_evidence_ids": [i.evidence_id for i in self.items.values()
                                                   if any(p.retrieved_by == agent for p in i.provenance)]}
            if type(score) is not int or not 0 <= score <= 3 or not reason.strip():
                return {"error": "Se requiere puntuación entera 0-3 y motivo no vacío"}
            pending.append((item, Assessment(agent=agent, relevance_score=score, reason=reason)))
        for item, assessment in pending:
            item.assessments = [a for a in item.assessments if a.agent != agent] + [assessment]
        self.save_candidates()
        return {"recorded": len(pending)}

    def save_candidates(self):
        self.write_json("candidates.json", [item.model_dump() for item in self.items.values()])

    def assess_final_json(self, agent: str, text: str) -> bool:
        """Aceptar sólo un lote JSON explícito de la salida final pública, con validación idéntica."""
        candidates = [text.strip(), *re.findall(r"```(?:json)?\s*\n(.*?)```", text, flags=re.DOTALL)]
        for candidate in candidates:
            try:
                data = json.loads(candidate)
            except ValueError:
                continue
            fields = {"evidence_ids", "relevance_scores", "reasons"}
            if not isinstance(data, dict) or set(data) != fields:
                continue
            if not all(isinstance(data[key], list) for key in fields):
                continue
            if not data["evidence_ids"] or not all(isinstance(v, str) for v in data["evidence_ids"] + data["reasons"]):
                continue
            result = self.assess(agent, **data)
            self.log("assessment_fallbacks.jsonl", {"agent": agent, "method": "validated_final_json", "result": result})
            if "error" not in result:
                return True
        return False

    def write_json(self, filename: str, data):
        (self.output / filename).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def selected(self, top_k: int) -> list[EvidenceItem]:
        items = [i for i in self.items.values() if any(a.relevance_score >= 2 for a in i.assessments)]
        # Heurística explícita: valoración LLM, después posición de la fuente, luego ID estable.
        return sorted(items, key=lambda i: (
            -max(a.relevance_score for a in i.assessments),
            min(p.source_rank for p in i.provenance), i.evidence_id,
        ))[:top_k]

    def export(self, top_k: int, summary: dict):
        self.save_candidates()
        selected = self.selected(top_k)
        self.write_json("evidence.json", [i.model_dump() for i in selected])
        summary.update(candidate_count=len(self.items), selected_count=len(selected),
                       agent_status=self.agent_status, errors=self.errors, llm_calls=self.llm_calls,
                       tool_calls=self.tool_calls, token_usage=self.usage, monetary_cost=None,
                       ranking="max_agent_relevance_then_source_rank; uncalibrated LLM scores")
        self.write_json("summary.json", summary)
        lines = ["# Evidencia recuperada", "", f"Estado: {summary['status']}",
                 f"Candidatos únicos: {len(self.items)}. Seleccionados: {len(selected)}.", "",
                 "La relevancia es una valoración del agente, pendiente de revisión humana.", ""]
        for i, item in enumerate(selected, 1):
            lines.extend([f"## {i}. {item.title}", "", f"ID: `{item.evidence_id}` · {item.content_type} · {item.source_type}",
                          f"Documento: {item.document_id} · Año: {item.publication_year}",
                          f"Fuente: [{item.source}]({item.url})", "", "Fragmento original:", ""])
            lines.extend("> " + line for line in item.passage_text.splitlines())
            lines.append("")
            for assessment in item.assessments:
                lines.extend([f"- {assessment.agent}: {assessment.relevance_score}/3. {assessment.reason}"])
            lines.append("")
            for provenance in item.provenance:
                lines.append(f"- Consulta ({provenance.retrieved_by}, {provenance.source}): {provenance.retrieval_query}")
                lines.append(f"- Respuesta original: [{provenance.raw_file}]({provenance.raw_file})")
            lines.append("")
        if not selected:
            lines.extend(["No hay fragmentos seleccionados. Revisa candidates.json y los errores registrados.", ""])
        if self.errors:
            lines.extend(["## Incidencias", ""])
            lines.extend(f"- {error['agent']}: {error['message']}" for error in self.errors)
        (self.output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
