import hashlib
import json
from pathlib import Path

import pytest

from argument_mining.evaluation import evaluate_relations, evaluate_segmentation
from argument_mining.datasets import AbstRCTAdapter
from argument_mining.errors import SerializationError
from argument_mining.errors import ProvenanceError
from argument_mining.deployment import build_repo_plan
from argument_mining.models import (ArgumentRelation, ArgumentSpan, EndToEndConfig, EvidenceRecord,
                                    ModuleRun, ModuleSpec, PairGeneration, SourceSpan, StageSelection)
from argument_mining.pipeline import ArgumentMiningPipeline
from argument_mining.experiments.config import load_end_to_end_config
from argument_mining.experiments.config import load_frozen_config
from argument_mining.experiments.benchmark import (SelectionRule, inspect_benchmark,
                                                    load_benchmark_config, rank_stage_results)
from argument_mining.registry import ModuleRegistry
from argument_mining.xaif import claims_xaif, parse_spans


class FakeOAMFClient:
    def invoke(self, spec, xaif, experiment_id):
        aif = xaif["AIF"]
        if spec.stage == "segmentation":
            text = aif["nodes"][0]["text"]
            pieces = [piece.strip() + "." for piece in text.split(".") if piece.strip()]
            result = {**xaif, "AIF": {**aif, "nodes": [
                {"nodeID": index + 1, "text": piece, "type": "L"}
                for index, piece in enumerate(pieces)
            ]}}
        elif spec.stage == "propositionalisation":
            nodes, edges, next_id = list(aif["nodes"]), [], len(aif["nodes"])
            for lnode in aif["nodes"]:
                ya, inode = next_id, next_id + 1
                next_id += 2
                nodes.extend([{"nodeID": ya, "text": "Default Illocuting", "type": "YA"},
                              {"nodeID": inode, "text": lnode["text"], "type": "I"}])
                edges.extend([{"edgeID": len(edges), "fromID": lnode["nodeID"], "toID": ya},
                              {"edgeID": len(edges) + 1, "fromID": ya, "toID": inode}])
            result = {**xaif, "AIF": {**aif, "nodes": nodes, "edges": edges}}
        else:
            nodes = list(aif["nodes"])
            relation_id = len(nodes)
            nodes.append({"nodeID": relation_id, "text": "Default Inference", "type": "RA"})
            i_nodes = [node["nodeID"] for node in nodes if node["type"] == "I"]
            result = {**xaif, "AIF": {**aif, "nodes": nodes, "edges": [
                {"edgeID": 0, "fromID": i_nodes[0], "toID": relation_id},
                {"edgeID": 1, "fromID": relation_id, "toID": i_nodes[1]},
            ]}}
        encoded = json.dumps(result, sort_keys=True).encode()
        run = ModuleRun(
            experiment_id=experiment_id, stage=spec.stage, module_id=spec.module_id,
            module_version=spec.version, model=spec.model, endpoint=spec.endpoint,
            config=spec.config, input_sha256="0" * 64,
            response_sha256=hashlib.sha256(encoded).hexdigest(),
            started_at="2026-09-09T00:00:00+00:00", completed_at="2026-09-09T00:00:01+00:00",
        )
        return result, run


def spec(module, stage):
    return ModuleSpec(module_id=module, stage=stage, endpoint="https://example.test", version="test-1")


@pytest.fixture
def evidence():
    raw = [{
        "evidence_id": "ev_1", "document_id": "PMID:1", "title": "Original title",
        "passage_text": "Access empowers patients. Boundaries protect physicians.",
        "source": "europe_pmc", "retrieval_query": "original query",
        "provenance": [{"retrieved_by": "literature_agent", "tool": "fetch_full_text",
                        "raw_file": "agents/literature_agent/raw/1.xml"}],
        "assessments": [{"agent": "literature_agent", "relevance_score": 3}],
        "custom_upstream_field": {"must": "survive"},
    }]
    return raw, [EvidenceRecord.model_validate(raw[0])]


def test_end_to_end_preserves_evidence_and_claim_traceability(tmp_path, evidence):
    raw, records = evidence
    pipeline = ArgumentMiningPipeline(FakeOAMFClient())
    spans = pipeline.segment(raw, records, spec("DSG", "segmentation"), tmp_path / "segments", "exp_test")
    claims = pipeline.propositionalise(raw, records, spans, spec("SPG", "propositionalisation"),
                                       tmp_path / "claims", "exp_test")
    relations = pipeline.identify_relations(
        raw, records, claims, spec("DAMG", "relation_identification"),
        PairGeneration(strategy="within_passage"), tmp_path / "relations", "exp_test",
    )

    assert json.loads((tmp_path / "segments" / "evidence.json").read_text(encoding="utf-8")) == raw
    assert [(s.source_span.start_char, s.source_span.end_char) for s in spans] == [(0, 25), (26, 56)]
    assert len(claims) == 2
    for claim in claims:
        assert claim.evidence_id == "ev_1"
        assert claim.source.passage_text == raw[0]["passage_text"]
        assert claim.source.retrieval_provenance == raw[0]["provenance"]
        span = claim.source.source_span
        assert raw[0]["passage_text"][span.start_char:span.end_char] == span.text
        assert claim.generated_by.module_id == "SPG"
    assert len(relations) == 1
    assert relations[0].relation == "support"
    xaif = json.loads((tmp_path / "relations" / "xaif.json").read_text(encoding="utf-8"))
    assert {n["type"] for n in xaif["AIF"]["nodes"]} == {"L", "YA", "I", "RA"}
    provenance = json.loads((tmp_path / "relations" / "provenance_map.json").read_text(encoding="utf-8"))
    assert provenance["claims"][0]["document"]["document_id"] == "PMID:1"
    assert provenance["claims"][0]["retrieval_provenance"][0]["raw_file"].endswith("1.xml")
    pairs = json.loads((tmp_path / "relations" / "candidate_pairs.json").read_text(encoding="utf-8"))
    assert len(pairs) == 2
    pipeline.export_xaif(raw, records, claims, relations, tmp_path / "export", "exp_export")
    assert (tmp_path / "export" / "xaif.json").exists()


def test_claim_with_changed_offsets_is_rejected(tmp_path, evidence):
    raw, records = evidence
    pipeline = ArgumentMiningPipeline(FakeOAMFClient())
    spans = pipeline.segment(raw, records, spec("DSG", "segmentation"), tmp_path / "segments", "exp_test")
    claims = pipeline.propositionalise(raw, records, spans, spec("SPG", "propositionalisation"),
                                       tmp_path / "claims", "exp_test")
    claims[0].source.source_span.text = "tampered"
    with pytest.raises(ProvenanceError):
        pipeline.identify_relations(raw, records, claims, spec("DAMG", "relation_identification"),
                                    PairGeneration(), tmp_path / "relations", "exp_test")


def test_relation_input_uses_canonical_l_ya_i_chains(tmp_path, evidence):
    raw, records = evidence
    pipeline = ArgumentMiningPipeline(FakeOAMFClient())
    spans = pipeline.segment(raw, records, spec("DSG", "segmentation"), tmp_path / "segments", "exp_test")
    claims = pipeline.propositionalise(raw, records, spans, spec("SPG", "propositionalisation"),
                                       tmp_path / "claims", "exp_test")

    xaif = claims_xaif(claims)
    nodes = {node["nodeID"]: node for node in xaif["AIF"]["nodes"]}
    edges = {(edge["fromID"], edge["toID"]) for edge in xaif["AIF"]["edges"]}
    assert [node["type"] for node in nodes.values()].count("L") == len(claims)
    assert [node["type"] for node in nodes.values()].count("YA") == len(claims)
    assert [node["type"] for node in nodes.values()].count("I") == len(claims)
    for index in range(len(claims)):
        i_node_id, ya_node_id = len(claims) + (2 * index), len(claims) + (2 * index) + 1
        assert (index, ya_node_id) in edges
        assert (ya_node_id, i_node_id) in edges


def test_stage_evaluation_uses_gold_without_inference():
    run = ModuleRun(experiment_id="e", stage="segmentation", module_id="DSG", module_version="1",
                    endpoint="x", config={}, input_sha256="a", response_sha256="b",
                    started_at="x", completed_at="y", model=None)
    gold = [ArgumentSpan(span_id="g", evidence_id="ev", source_span=SourceSpan(start_char=0, end_char=5, text="hello"),
                         l_node_id="0", input_kind="gold")]
    pred = [ArgumentSpan(span_id="p", evidence_id="ev", source_span=SourceSpan(start_char=0, end_char=5, text="hello"),
                         l_node_id="1", generated_by=run)]
    assert evaluate_segmentation(pred, gold)["exact_span"]["f1"] == 1.0

    relation = ArgumentRelation(relation_id="r", source_claim_id="a", target_claim_id="b",
                                relation="attack", xaif_relation_type="CA", generated_by=run)
    scores = evaluate_relations([relation], [relation])
    assert scores["per_class"]["attack"]["f1"] == 1.0
    assert scores["macro_f1"] == pytest.approx(1.0)

    none_gold = ArgumentRelation(relation_id="n", source_claim_id="b", target_claim_id="a",
                                 relation="none", xaif_relation_type=None)
    scores = evaluate_relations([relation], [relation, none_gold], [
        {"source_claim_id": "a", "target_claim_id": "b"},
        {"source_claim_id": "b", "target_claim_id": "a"},
    ])
    assert scores["per_class"]["none"]["f1"] == 1.0


def test_yaml_configuration_declares_one_module_per_stage():
    config = load_end_to_end_config(Path("examples/argument_smoke_config.yaml"))
    repo_config = load_end_to_end_config(Path("examples/argument_repo_config.yaml"))
    registry = ModuleRegistry(Path("configs/oamf_public_modules.yaml"))
    assert config.segmentation.module == "DSG"
    assert config.propositionalisation.module == "SPG"
    assert config.relation_identification.module == "ARIR"
    assert repo_config.segmentation.backend_type == "repo"
    assert repo_config.relation_identification.backend_id == "official_repo_local"
    assert registry.choices("segmentation") == ["DSG", "DSS", "TARGER"]
    replacement = registry.get("ARIR", "relation_identification")
    assert replacement.backend_type == "ws"
    assert replacement.backend_id == "argtech_public_replacement"
    assert replacement.endpoint == "http://amf-ari.amfws.arg.tech/"

    local = ModuleRegistry(Path("configs/oamf_local_repo_modules.yaml"))
    local_arir = local.get("ARIR", "relation_identification")
    assert local_arir.backend_type == "repo"
    assert local_arir.endpoint == "http://127.0.0.1:5001/"
    assert local_arir.version == local_arir.repository_commit
    assert local_arir.model_revision == "009051ab375af4b470bf7477501e3331267ba493"
    plan = build_repo_plan(local, ["DSG", "ARIR"])
    assert plan["deploy_executed"] is False
    assert plan["deployment_executor"] == "oamf.oAMF.load_modules"
    assert plan["oamf"]["commit"] == "8184d39fbf7573940925718d5ab3736f7884f0bf"
    assert {item["module_id"] for item in plan["modules"]} == {"DSG", "ARIR"}
    arir_plan = next(item for item in plan["modules"] if item["module_id"] == "ARIR")
    assert arir_plan["model_revision"] == "009051ab375af4b470bf7477501e3331267ba493"


def test_stagewise_benchmark_is_not_cartesian_and_requires_gold():
    config = load_benchmark_config(Path("examples/oamf_stagewise_benchmark.yaml"))
    readiness = inspect_benchmark(config, ModuleRegistry(config.registry))
    assert readiness["cartesian_product"] is False
    assert readiness["evidence_exists"] is True
    assert readiness["stages"]["segmentation"]["gold_exists"] is False
    assert readiness["stages"]["segmentation"]["ready"] is False
    relation_candidates = readiness["stages"]["relation_identification"]["candidates"]
    assert next(item for item in relation_candidates if item["module"] == "DTERG")["runnable"] is True
    assert next(item for item in relation_candidates if item["module"] == "DSRM")["runnable"] is False


def test_stagewise_ranking_obeys_preregistered_metric_and_manual_gate():
    rows = [
        {"module": "A", "status": "completed", "metrics": {"score": {"f1": 0.6}}},
        {"module": "B", "status": "completed", "metrics": {"score": {"f1": 0.8}}},
    ]
    ranking = rank_stage_results(rows, SelectionRule(primary_metric="score.f1"))
    assert ranking["automatic_leader"] == "B"
    assert ranking["selected_module"] is None
    assert ranking["can_select_best_module"] is False
    gated = rank_stage_results(rows, SelectionRule(primary_metric="score.f1",
                                                    manual_review_required=True))
    assert gated["automatic_leader"] == "B"
    assert gated["selected_module"] is None


def test_abstrct_adapter_preserves_brat_ids_without_fabricating_gold_claims(tmp_path):
    corpus = tmp_path / "corpus" / "dev" / "sample"
    corpus.mkdir(parents=True)
    (corpus / "123.txt").write_text("Treatment helped. Control worsened.", encoding="utf-8")
    (corpus / "123.ann").write_text(
        "T1\tClaim 0 17\tTreatment helped.\n"
        "T2\tPremise 18 35\tControl worsened.\n"
        "R1\tSupport Arg1:T2 Arg2:T1\n"
        "R2\tPartial-Attack Arg1:T1 Arg2:T2\n", encoding="utf-8"
    )
    output = tmp_path / "adapted"
    manifest = AbstRCTAdapter(tmp_path / "corpus", version="test-commit").export(
        output, "dev", "sample"
    )
    assert manifest["counts"]["relations"] == 1
    assert manifest["counts"]["unmapped_relations"] == 1
    units = json.loads((output / "argument_units.json").read_text(encoding="utf-8"))
    assert units[0]["original_id"] == "T1"
    assert units[0]["evaluation_reference"] == "gold"
    assert not (output / "gold_claims.json").exists()
    mapping = json.loads((output / "mapping.json").read_text(encoding="utf-8"))
    assert mapping["normalised_gold_claims_created"] is False


def test_unfrozen_configuration_cannot_run(tmp_path):
    config = tmp_path / "not_frozen.yaml"
    config.write_text(
        "schema_version: '1.0'\nstatus: not_frozen\n"
        "dataset_used_for_selection: test\napplication_data_used_for_tuning: false\n",
        encoding="utf-8",
    )
    with pytest.raises(SerializationError, match="status=not_frozen"):
        load_frozen_config(config)


def test_gold_benchmark_portable_artifacts_and_excluded_partial_attack(tmp_path):
    from argument_mining.experiments.gold_benchmark import (
        DatasetReference, GoldBenchmarkConfig, RelationSemantics, run_gold_benchmark,
    )
    corpus = tmp_path / 'corpus' / 'dev' / 'sample'
    corpus.mkdir(parents=True)
    (corpus / '123.txt').write_text('Treatment helped. Control worsened.', encoding='utf-8')
    (corpus / '123.ann').write_text(
        'T1\tClaim 0 17\tTreatment helped.\n'
        'T2\tPremise 18 35\tControl worsened.\n'
        'R1\tAttack Arg1:T2 Arg2:T1\n'
        'R2\tPartial-Attack Arg1:T1 Arg2:T2\n', encoding='utf-8')
    adapted = tmp_path / 'adapted'
    AbstRCTAdapter(tmp_path / 'corpus', version='test').export(adapted, 'dev', 'sample')
    config = GoldBenchmarkConfig(
        benchmark_id='test', registry=Path('configs/oamf_public_modules.yaml'),
        dataset=DatasetReference(name='test', version='test', split='dev',
            evidence=adapted / 'evidence.json', gold_spans=adapted / 'gold_spans.json',
            argument_units=adapted / 'argument_units.json',
            gold_relations=adapted / 'gold_relations.json',
            unmapped_relations=adapted / 'unmapped_relations.json'),
        segmentation_candidates=['DSG'], relation_candidates=['ARIR'],
        relation_semantics={'ARIR': RelationSemantics(
            xaif_to_benchmark={'RA': 'support', 'CA': 'attack'}, justification='test')})
    seg = run_gold_benchmark(config, 'segmentation', tmp_path / 'seg', FakeOAMFClient())
    assert seg['rows'][0]['failures'] == 0
    assert len(list((tmp_path / 'seg/modules/dsg/raw').glob('*.json'))) == 1
    rel = run_gold_benchmark(config, 'relations', tmp_path / 'rel', FakeOAMFClient())
    assert rel['rows'][0]['failures'] == 0
    metrics = json.loads((tmp_path / 'rel/modules/arir/metrics.json').read_text())
    assert metrics['excluded_partial_attack_pairs'] == 1
    assert metrics['evaluated_directed_pairs'] == 1
    assert metrics['per_class']['support']['predicted'] == 0
    assert metrics['macro_f1_labels'] == ['support', 'attack']


def test_end_to_end_runner_keeps_stage_artifacts(tmp_path, evidence):
    raw, records = evidence
    config = EndToEndConfig(
        experiment_id="exp_full", segmentation=StageSelection(module="DSG"),
        propositionalisation=StageSelection(module="SPG"),
        relation_identification=StageSelection(module="ARIR"),
    )
    specs = {
        "segmentation": spec("DSG", "segmentation"),
        "propositionalisation": spec("SPG", "propositionalisation"),
        "relation_identification": spec("ARIR", "relation_identification"),
    }
    output = tmp_path / "full"
    ArgumentMiningPipeline(FakeOAMFClient()).end_to_end(raw, records, config, specs, output)
    assert (output / "segmentation" / "argument_spans.json").exists()
    assert (output / "propositionalisation" / "claims.json").exists()
    assert (output / "relation_identification" / "relations.json").exists()
    assert len(json.loads((output / "candidate_pairs.json").read_text(encoding="utf-8"))) == 2
    assert len(json.loads((output / "relation_identification" / "module_runs.json").read_text(encoding="utf-8"))) == 1
    assert json.loads((output / "manifest.json").read_text(encoding="utf-8"))["status"] == "completed"


def test_segment_alignment_tolerates_punctuation_normalisation(evidence):
    _, records = evidence
    source = records[0].model_copy(update={
        "passage_text": "Study 2 used two universities, enrolled in research."
    })
    run = ModuleRun(experiment_id="e", stage="segmentation", module_id="TARGER", module_version="1",
                    endpoint="x", config={}, input_sha256="a", response_sha256="b",
                    started_at="x", completed_at="y", model=None)
    result = parse_spans({"AIF": {"nodes": [{"nodeID": 1,
        "text": "Study 2 used two universities enrolled in research.", "type": "L"}]}}, source, run)
    assert result[0].source_span.text == source.passage_text

    source = records[0].model_copy(update={"passage_text": "A known researcher's profile. 49.6% accepted."})
    result = parse_spans({"AIF": {"nodes": [
        {"nodeID": 1, "text": "A known researcher 's profile", "type": "L"},
        {"nodeID": 2, "text": "% accepted", "type": "L"},
    ]}}, source, run)
    assert result[0].source_span.text == "A known researcher's profile."
    assert result[1].source_span.text == "49.6% accepted."
