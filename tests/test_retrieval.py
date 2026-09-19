import asyncio
import json

import httpx
import pytest
from pydantic import ValidationError

from clinical_retrieval.evidence import EvidenceStore, unpack_mcp_response
from clinical_retrieval.models import ClinicalCase
from clinical_retrieval.sources import SourceClient, parse_epmc, parse_pubmed, split_passage
from tests.fixtures import EPMC_JSON, PUBMED_XML, mock_response


def test_input_rejects_gold():
    with pytest.raises(ValidationError):
        ClinicalCase(case_id="x", clinical_case="case", question="question", gold_answer="A")


def test_preserves_original_and_cross_source_identity():
    pubmed = parse_pubmed(PUBMED_XML, "kidney", "a.xml", "now")[0]
    epmc = parse_epmc(EPMC_JSON, "kidney", "b.json", "now")[0]
    assert pubmed.passage_text == "Synthetic evidence about kidney outcomes."
    assert pubmed.evidence_id == epmc.evidence_id
    assert pubmed.source_type == "guideline"
    assert pubmed.content_type == "abstract"
    assert pubmed.pmcid == "PMC123"


def test_titles_are_not_evidence():
    data = {"resultList": {"result": [{"id": "1", "source": "MED", "title": "Title only"}]}}
    assert parse_epmc(data, "query", "raw", "now") == []


def test_chunks_are_original_contiguous_substrings():
    text = "first sentence. " * 300
    chunks = split_passage(text)
    assert len(chunks) > 1
    assert all(chunk in text and len(chunk) <= 1800 for chunk in chunks)
    assert " ".join(chunks) == text.strip()


def test_dedup_preserves_all_provenance_and_rejects_invented_ids(tmp_path):
    store = EvidenceStore(tmp_path)
    pubmed = parse_pubmed(PUBMED_XML, "q1", "a.xml", "now")[0]
    epmc = parse_epmc(EPMC_JSON, "q2", "b.json", "now")[0]
    store.ingest({"passages": [pubmed.model_dump()]}, "guideline_agent", "search_guidelines")
    store.ingest({"passages": [epmc.model_dump()]}, "literature_agent", "search_literature")
    assert len(store.items) == 1
    item = store.items[pubmed.evidence_id]
    assert len(item.provenance) == 2
    assert "error" in store.assess("guideline_agent", ["invented"], [3], ["reason"])
    assert "error" in store.assess("another_agent", [pubmed.evidence_id], [3], ["reason"])
    assert store.selected(10) == []
    store.assess("guideline_agent", [pubmed.evidence_id], [2], ["partial"])
    assert len(store.selected(10)) == 1
    store.export(10, {"status": "completed"})
    assert json.loads((tmp_path / "evidence.json").read_text())[0]["passage_text"] == pubmed.passage_text


def test_mcp_text_and_structured_responses():
    assert unpack_mcp_response({"content": [{"type": "text", "text": '{"passages": []}'}]}) == {"passages": []}
    assert unpack_mcp_response({"structuredContent": {"passages": []}}) == {"passages": []}
    with pytest.raises(ValueError):
        unpack_mcp_response({"content": [{"type": "text", "text": "not json"}]})


def test_final_json_cannot_invent_evidence(tmp_path):
    store = EvidenceStore(tmp_path)
    text = json.dumps({"evidence_ids": ["invented"], "relevance_scores": [3], "reasons": ["reason"]})
    assert not store.assess_final_json("guideline_agent", text)
    assert store.items == {}


def test_search_filters_and_full_text(tmp_path):
    requests = []

    def handler(request):
        requests.append(request)
        return mock_response(request)

    async def scenario():
        source = SourceClient(tmp_path, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        try:
            result = await source.search("kidney", "pubmed", "guideline", 3)
            assert "Guideline[pt]" in requests[0].url.params["term"]
            assert result["passages"][0]["content_type"] == "abstract"
            result = await source.search("kidney", "europe_pmc", "guideline", 3)
            assert 'PUB_TYPE:"Guideline"' in requests[-1].url.params["query"]
            from clinical_retrieval.models import Passage
            full = await source.full_text(Passage.model_validate(result["passages"][0]), "kidney", 1)
            assert full["total_passages"] == 2
            assert full["passages"][0]["passage_text"] == "Synthetic kidney outcomes paragraph."
            assert (tmp_path / full["raw_files"][0]).exists()
        finally:
            await source.close()

    asyncio.run(scenario())


def test_empty_results_and_http_failure_are_distinct(tmp_path):
    async def scenario():
        client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={
            "esearchresult": {"count": "0", "idlist": []}})))
        source = SourceClient(tmp_path, client=client)
        result = await source.search("unlikely", "pubmed", "literature", 1)
        assert result["hit_count"] == 0 and result["passages"] == []
        await source.close()
        source = SourceClient(tmp_path, client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(403))))
        with pytest.raises(httpx.HTTPStatusError):
            await source.search("kidney", "pubmed", "literature", 1)
        await source.close()

    asyncio.run(scenario())
