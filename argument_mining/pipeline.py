from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from .client import OAMFClient
from .errors import ArgumentMiningError, ProvenanceError, SerializationError
from .models import (ArgumentRelation, ArgumentSpan, Claim, EndToEndConfig, EvidenceRecord,
                     ExperimentManifest, ModuleSpec, PairGeneration)
from .propositionalisation import create_propositionaliser
from .provenance import build_provenance_map, validate_claims
from .relations import create_relation_identifier
from .segmentation import create_segmenter
from .xaif import final_xaif


def read_evidence(path: Path) -> tuple[list[dict[str, Any]], list[EvidenceRecord]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise SerializationError(f"No se puede leer {path}: {exc}") from exc
    if not isinstance(raw, list):
        raise ProvenanceError("La evidencia debe ser un array JSON")
    records = [EvidenceRecord.model_validate(item) for item in raw]
    ids = [item.evidence_id for item in records]
    if len(ids) != len(set(ids)):
        raise ProvenanceError("evidence_id debe ser único")
    return raw, records


def read_models(path: Path, model_type):
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(raw, list):
            raise ValueError("se esperaba un array")
        return [model_type.model_validate(item) for item in raw]
    except (OSError, ValueError) as exc:
        raise SerializationError(f"No se puede leer {path}: {exc}") from exc


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    elif isinstance(value, list):
        value = [item.model_dump(mode="json") if hasattr(item, "model_dump") else item for item in value]
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def selected_spec(spec: ModuleSpec, endpoint: str | None = None, version: str | None = None,
                  model: str | None = None, config: dict | None = None,
                  backend_type: str | None = None, backend_id: str | None = None,
                  route: str | None = None, repository: str | None = None,
                  repository_commit: str | None = None,
                  model_revision: str | None = None) -> ModuleSpec:
    data = spec.model_dump()
    if endpoint is not None:
        data["endpoint"] = endpoint
    if version is not None:
        data["version"] = version
    if model is not None:
        data["model"] = model
    if model_revision is not None:
        data["model_revision"] = model_revision
    for key, value in {
        "backend_type": backend_type, "backend_id": backend_id, "route": route,
        "repository": repository, "repository_commit": repository_commit,
    }.items():
        if value is not None:
            data[key] = value
    data["config"] = config or {}
    return ModuleSpec.model_validate(data)


class ArgumentMiningPipeline:
    def __init__(self, client: OAMFClient | None = None):
        self.client = client or OAMFClient()

    def segment(self, raw_evidence: list[dict], evidence: list[EvidenceRecord], spec: ModuleSpec,
                output: Path, experiment_id: str, dataset_version: str = "unreported") -> list[ArgumentSpan]:
        output.mkdir(parents=True, exist_ok=False)
        write_json(output / "evidence.json", raw_evidence)
        manifest = ExperimentManifest(experiment_id=experiment_id, run_kind="segmentation",
                                      dataset_version=dataset_version,
                                      input_kind={"segmentation": "raw_evidence"},
                                      modules={"segmentation": spec})
        write_json(output / "manifest.json", manifest)
        spans: list[ArgumentSpan] = []
        module_runs = []
        try:
            module = create_segmenter(spec, self.client)
            for item in evidence:
                try:
                    result = module.run(item, experiment_id)
                except Exception as exc:
                    if hasattr(exc, "module_run"):
                        module_runs.append(exc.module_run)
                        write_json(output / "module_runs.json", module_runs)
                    self._write_failed_call(output, "segmentation", item.evidence_id, exc)
                    raise
                module_runs.append(result.module_run)
                write_json(output / "module_runs.json", module_runs)
                write_json(output / "segmentation" / "inputs" / f"{item.evidence_id}.json", result.xaif_input)
                write_json(output / "segmentation" / "raw" / f"{item.evidence_id}.json", result.xaif_response)
                spans.extend(result.spans)
            write_json(output / "argument_spans.json", spans)
            write_json(output / "l_nodes.json", [
                {"nodeID": span.l_node_id, "type": "L", "text": span.source_span.text,
                 "span_id": span.span_id, "evidence_id": span.evidence_id,
                 "source_span": span.source_span.model_dump(),
                 "generated_by": span.generated_by.model_dump() if span.generated_by else None}
                for span in spans
            ])
            manifest.outputs.update(argument_spans="argument_spans.json", l_nodes="l_nodes.json",
                                    evidence="evidence.json", module_runs="module_runs.json",
                                    raw="segmentation/raw/")
            manifest.status = "completed"
        except Exception as exc:
            self._fail(manifest, exc)
            raise
        finally:
            write_json(output / "manifest.json", manifest)
        return spans

    def propositionalise(self, raw_evidence: list[dict], evidence: list[EvidenceRecord],
                         spans: list[ArgumentSpan], spec: ModuleSpec, output: Path,
                         experiment_id: str, input_kind: str = "predicted",
                         dataset_version: str = "unreported", gold_version: str | None = None) -> list[Claim]:
        output.mkdir(parents=True, exist_ok=False)
        write_json(output / "evidence.json", raw_evidence)
        write_json(output / "argument_spans.json", spans)
        manifest = ExperimentManifest(
            experiment_id=experiment_id, run_kind="propositionalisation",
            dataset_version=dataset_version, gold_version=gold_version,
            input_kind={"propositionalisation": input_kind},
            modules={"propositionalisation": spec},
        )
        write_json(output / "manifest.json", manifest)
        evidence_by_id = {item.evidence_id: item for item in evidence}
        claims: list[Claim] = []
        module_runs = []
        try:
            module = create_propositionaliser(spec, self.client)
            grouped: dict[str, list[ArgumentSpan]] = defaultdict(list)
            for span in spans:
                if span.evidence_id not in evidence_by_id:
                    raise ProvenanceError(f"Span {span.span_id} referencia evidence_id inexistente")
                grouped[span.evidence_id].append(span)
            for evidence_id, item_spans in grouped.items():
                try:
                    result = module.run(evidence_by_id[evidence_id], item_spans, experiment_id, input_kind)
                except Exception as exc:
                    if hasattr(exc, "module_run"):
                        module_runs.append(exc.module_run)
                        write_json(output / "module_runs.json", module_runs)
                    self._write_failed_call(output, "propositionalisation", evidence_id, exc)
                    raise
                module_runs.append(result.module_run)
                write_json(output / "module_runs.json", module_runs)
                write_json(output / "propositionalisation" / "inputs" / f"{evidence_id}.json", result.xaif_input)
                write_json(output / "propositionalisation" / "raw" / f"{evidence_id}.json", result.xaif_response)
                claims.extend(result.claims)
            validate_claims(claims, evidence_by_id)
            write_json(output / "claims.json", claims)
            write_json(output / "i_nodes.json", [
                {"nodeID": claim.i_node_id, "type": "I", "text": claim.proposition_text,
                 "claim_id": claim.claim_id, "evidence_id": claim.evidence_id,
                 "span_id": claim.span_id, "generated_by": claim.generated_by.model_dump() if claim.generated_by else None}
                for claim in claims
            ])
            write_json(output / "provenance_map.json", self.provenance_map(claims, [], evidence_by_id))
            manifest.outputs.update(claims="claims.json", i_nodes="i_nodes.json",
                                    evidence="evidence.json", provenance_map="provenance_map.json",
                                    module_runs="module_runs.json",
                                    raw="propositionalisation/raw/")
            manifest.status = "completed"
        except Exception as exc:
            self._fail(manifest, exc)
            raise
        finally:
            write_json(output / "manifest.json", manifest)
        return claims

    def identify_relations(self, raw_evidence: list[dict], evidence: list[EvidenceRecord],
                           claims: list[Claim], spec: ModuleSpec, pair_generation: PairGeneration,
                           output: Path, experiment_id: str, input_kind: str = "predicted",
                           dataset_version: str = "unreported", gold_version: str | None = None
                           ) -> list[ArgumentRelation]:
        output.mkdir(parents=True, exist_ok=False)
        write_json(output / "evidence.json", raw_evidence)
        write_json(output / "claims.json", claims)
        manifest = ExperimentManifest(
            experiment_id=experiment_id, run_kind="relation_identification",
            dataset_version=dataset_version, gold_version=gold_version,
            input_kind={"relation_identification": input_kind},
            modules={"relation_identification": spec}, pair_generation=pair_generation,
        )
        write_json(output / "manifest.json", manifest)
        evidence_by_id = {item.evidence_id: item for item in evidence}
        relations: list[ArgumentRelation] = []
        module_runs = []
        try:
            module = create_relation_identifier(spec, self.client)
            validate_claims(claims, evidence_by_id)
            candidate_pairs = []
            for group_id, group in self._pair_groups(claims, evidence_by_id, pair_generation.strategy):
                if len(group) < 2:
                    continue
                candidate_pairs.extend(
                    {"group_id": group_id, "source_claim_id": source.claim_id,
                     "target_claim_id": target.claim_id}
                    for source in group for target in group if source.claim_id != target.claim_id
                )
                try:
                    result = module.run(group, experiment_id, input_kind)
                except Exception as exc:
                    if hasattr(exc, "module_run"):
                        module_runs.append(exc.module_run)
                        write_json(output / "module_runs.json", module_runs)
                    self._write_failed_call(output, "relation_identification", group_id, exc)
                    raise
                module_runs.append(result.module_run)
                write_json(output / "module_runs.json", module_runs)
                write_json(output / "relation_identification" / "inputs" / f"{group_id}.json", result.xaif_input)
                write_json(output / "relation_identification" / "raw" / f"{group_id}.json", result.xaif_response)
                relations.extend(result.relations)
            write_json(output / "candidate_pairs.json", candidate_pairs)
            write_json(output / "relations.json", relations)
            xaif = final_xaif(claims, relations, experiment_id)
            write_json(output / "xaif.json", xaif)
            write_json(output / "provenance_map.json", self.provenance_map(claims, relations, evidence_by_id))
            manifest.outputs.update(relations="relations.json", xaif="xaif.json",
                                    evidence="evidence.json", provenance_map="provenance_map.json",
                                    candidate_pairs="candidate_pairs.json",
                                    module_runs="module_runs.json",
                                    raw="relation_identification/raw/")
            manifest.status = "completed"
        except Exception as exc:
            self._fail(manifest, exc)
            raise
        finally:
            write_json(output / "manifest.json", manifest)
        return relations

    def export_xaif(self, raw_evidence: list[dict], evidence: list[EvidenceRecord], claims: list[Claim],
                    relations: list[ArgumentRelation], output: Path, experiment_id: str,
                    dataset_version: str = "unreported") -> dict:
        output.mkdir(parents=True, exist_ok=False)
        evidence_by_id = {item.evidence_id: item for item in evidence}
        exporter = ModuleSpec(module_id="TRACEABLE-XAIF", stage="xaif_export", endpoint="local://xaif",
                              version="1.0", config={"preserve_provenance_sidecar": True})
        manifest = ExperimentManifest(experiment_id=experiment_id, run_kind="xaif_export",
                                      dataset_version=dataset_version,
                                      input_kind={"xaif_export": "claims_and_relations"},
                                      modules={"xaif_export": exporter})
        write_json(output / "manifest.json", manifest)
        try:
            validate_claims(claims, evidence_by_id)
            claim_ids = {claim.claim_id for claim in claims}
            for relation in relations:
                if relation.source_claim_id not in claim_ids or relation.target_claim_id not in claim_ids:
                    raise ProvenanceError(f"Relación {relation.relation_id} con claim_id inexistente")
            xaif = final_xaif(claims, relations, experiment_id)
            write_json(output / "evidence.json", raw_evidence)
            write_json(output / "claims.json", claims)
            write_json(output / "relations.json", relations)
            write_json(output / "xaif.json", xaif)
            write_json(output / "provenance_map.json", self.provenance_map(claims, relations, evidence_by_id))
            manifest.outputs.update(evidence="evidence.json", claims="claims.json",
                                    relations="relations.json", xaif="xaif.json",
                                    provenance_map="provenance_map.json")
            manifest.status = "completed"
            return xaif
        except Exception as exc:
            self._fail(manifest, exc)
            raise
        finally:
            write_json(output / "manifest.json", manifest)

    def end_to_end(self, raw_evidence: list[dict], evidence: list[EvidenceRecord], config: EndToEndConfig,
                   specs: dict[str, ModuleSpec], output: Path) -> tuple[list[ArgumentSpan], list[Claim], list[ArgumentRelation]]:
        output.mkdir(parents=True, exist_ok=False)
        write_json(output / "evidence.json", raw_evidence)
        manifest = ExperimentManifest(
            experiment_id=config.experiment_id, run_kind="end_to_end",
            dataset_version=config.dataset_version, gold_version=config.gold_version,
            random_seed=config.random_seed,
            input_kind={"segmentation": "raw_evidence", "propositionalisation": "predicted",
                        "relation_identification": "predicted"},
            modules=specs, pair_generation=config.pair_generation,
        )
        write_json(output / "manifest.json", manifest)
        try:
            # Stage directories are complete, independently inspectable experiment artifacts.
            spans = self.segment(raw_evidence, evidence, specs["segmentation"],
                                 output / "segmentation", config.experiment_id, config.dataset_version)
            claims = self.propositionalise(raw_evidence, evidence, spans, specs["propositionalisation"],
                                           output / "propositionalisation", config.experiment_id,
                                           dataset_version=config.dataset_version)
            relations = self.identify_relations(
                raw_evidence, evidence, claims, specs["relation_identification"], config.pair_generation,
                output / "relation_identification", config.experiment_id,
                dataset_version=config.dataset_version,
            )
            write_json(output / "argument_spans.json", spans)
            write_json(output / "claims.json", claims)
            write_json(output / "relations.json", relations)
            candidate_pairs = json.loads(
                (output / "relation_identification" / "candidate_pairs.json").read_text(encoding="utf-8")
            )
            write_json(output / "candidate_pairs.json", candidate_pairs)
            write_json(output / "xaif.json", final_xaif(claims, relations, config.experiment_id))
            evidence_by_id = {item.evidence_id: item for item in evidence}
            write_json(output / "provenance_map.json", self.provenance_map(claims, relations, evidence_by_id))
            manifest.outputs.update(evidence="evidence.json", argument_spans="argument_spans.json",
                                    claims="claims.json", candidate_pairs="candidate_pairs.json",
                                    relations="relations.json", xaif="xaif.json",
                                    provenance_map="provenance_map.json")
            manifest.status = "completed"
            return spans, claims, relations
        except Exception as exc:
            self._fail(manifest, exc)
            raise
        finally:
            write_json(output / "manifest.json", manifest)

    @staticmethod
    def _fail(manifest: ExperimentManifest, exc: Exception):
        manifest.status = "failed"
        manifest.error = {"type": exc.error_type if isinstance(exc, ArgumentMiningError) else "unexpected",
                          "class": type(exc).__name__, "message": str(exc)}

    @staticmethod
    def _write_failed_call(output: Path, stage: str, item_id: str, exc: Exception):
        if hasattr(exc, "xaif_input"):
            write_json(output / stage / "inputs" / f"{item_id}.json", exc.xaif_input)
        if hasattr(exc, "xaif_response"):
            write_json(output / stage / "raw" / f"{item_id}.json", exc.xaif_response)

    @staticmethod
    def _validate_claims(claims: list[Claim], evidence_by_id: dict[str, EvidenceRecord]):
        validate_claims(claims, evidence_by_id)

    @staticmethod
    def _pair_groups(claims: list[Claim], evidence_by_id: dict[str, EvidenceRecord], strategy: str):
        groups: dict[str, list[Claim]] = defaultdict(list)
        if strategy == "all":
            return [("all", claims)]
        for claim in claims:
            if strategy == "within_passage":
                key = claim.evidence_id
            elif strategy == "within_document":
                key = evidence_by_id[claim.evidence_id].document_id or claim.evidence_id
            else:
                raise ValueError(f"Estrategia de pares no soportada: {strategy}")
            groups[key].append(claim)
        return [(str(index), group) for index, group in enumerate(groups.values())]

    @staticmethod
    def provenance_map(claims: list[Claim], relations: list[ArgumentRelation],
                       evidence_by_id: dict[str, EvidenceRecord]) -> dict:
        return build_provenance_map(claims, relations, evidence_by_id)
