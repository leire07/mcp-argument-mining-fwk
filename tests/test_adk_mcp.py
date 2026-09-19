import asyncio
import json
import sys

from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from google.genai import types
from mcp import StdioServerParameters
from pydantic import Field, PrivateAttr

from clinical_retrieval import agents
from clinical_retrieval.__main__ import run_case
from clinical_retrieval.config import ROOT, Settings
from clinical_retrieval.evidence import unpack_mcp_response
from clinical_retrieval.models import ClinicalCase


class ScriptedModel(BaseLlm):
    """Modelo simulado; Runner, agentes, callbacks, MCP y exportación sí son reales."""
    model: str = "scripted-test"
    routes: list[str] = Field(default_factory=lambda: ["guideline_agent", "literature_agent"])
    fail_planner: bool = False
    malformed_names: bool = False
    final_assessments: bool = False
    _calls: dict = PrivateAttr(default_factory=dict)

    async def generate_content_async(self, llm_request, stream=False):
        instruction = str(llm_request.config.system_instruction)
        if "Eres el coordinador" in instruction:
            if self.fail_planner:
                raise RuntimeError("Synthetic planner failure")
            plan = {"clinical_aspects": ["kidney"], "rationale": "Test routing", "tasks": [
                {"agent": name, "objective": "Retrieve test passages", "queries": ["kidney"]}
                for name in self.routes]}
            yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text=json.dumps(plan))]))
            return
        guideline = "GuidelineAgent" in instruction
        role = "guideline" if guideline else "literature"
        step = self._calls.get(role, 0)
        self._calls[role] = step + 1
        search_tool = "search_guidelines" if guideline else "search_literature"
        assert search_tool in llm_request.tools_dict
        assert ("search_literature" if guideline else "search_guidelines") not in llm_request.tools_dict
        if step == 0:
            part = types.Part(function_call=types.FunctionCall(name=search_tool, args={
                "query": "kidney", "source": "pubmed" if guideline else "europe_pmc", "limit": 1}))
        elif step == 1:
            responses = [part.function_response for content in llm_request.contents
                         for part in content.parts or [] if part.function_response]
            payload = unpack_mcp_response(responses[-1].response)
            key = payload["passages"][0]["evidence_id"]
            if self.final_assessments:
                data = {"evidence_ids": [key], "relevance_scores": [2], "reasons": ["Synthetic test reason"]}
                yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text="```json\n" + json.dumps(data) + "\n```")]))
                return
            part = types.Part(function_call=types.FunctionCall(name="assess_evidence", args={
                "evidence_ids": [key], "relevance_scores": [3], "reasons": ["Synthetic test reason"]}))
        else:
            part = types.Part(text="Retrieval complete for test.")
        if self.malformed_names and part.function_call:
            part.function_call.name += "<|channel|>commentary"
        yield LlmResponse(content=types.Content(role="model", parts=[part]))


def configure_test_pipeline(monkeypatch, model):
    def test_toolset(name, output, settings):
        return McpToolset(connection_params=StdioConnectionParams(server_params=StdioServerParameters(
            command=sys.executable, args=["-m", "tests.fixture_server", str(output / "agents" / name)],
            cwd=str(ROOT), env={"PYTHONUTF8": "1"}), timeout=30),
            tool_filter=["search_guidelines" if name == "guideline_agent" else "search_literature", "fetch_full_text"])

    monkeypatch.setattr(agents, "mcp_toolset", test_toolset)
    monkeypatch.setattr(agents, "make_model", lambda settings: model)


def test_adk_agents_through_real_mcp_subprocess(tmp_path, monkeypatch):
    configure_test_pipeline(monkeypatch, ScriptedModel())
    output = tmp_path / "run"
    case = ClinicalCase(case_id="fixture", clinical_case="Synthetic case", question="Synthetic question")
    status = asyncio.run(run_case(case, output, Settings()))
    summary = json.loads((output / "summary.json").read_text())
    assert status == "completed", summary
    assert summary["llm_calls"] == 7
    evidence = json.loads((output / "evidence.json").read_text())
    assert len(evidence) == 1
    assert len(evidence[0]["provenance"]) == 2
    assert len(evidence[0]["assessments"]) == 2
    assert (output / evidence[0]["raw_file"]).exists()


def test_coordinator_can_route_to_one_specialist(tmp_path, monkeypatch):
    configure_test_pipeline(monkeypatch, ScriptedModel(routes=["guideline_agent"]))
    output = tmp_path / "run"
    case = ClinicalCase(case_id="fixture", clinical_case="Synthetic case", question="Synthetic question")
    assert asyncio.run(run_case(case, output, Settings())) == "completed"
    summary = json.loads((output / "summary.json").read_text())
    assert summary["agent_status"]["literature_agent"] == "skipped_by_coordinator"
    assert "literature_agent" not in summary["tool_calls"]


def test_global_llm_budget_preserves_candidates(tmp_path, monkeypatch):
    configure_test_pipeline(monkeypatch, ScriptedModel())
    output = tmp_path / "run"
    case = ClinicalCase(case_id="fixture", clinical_case="Synthetic case", question="Synthetic question")
    status = asyncio.run(run_case(case, output, Settings(max_llm_calls=2)))
    summary = json.loads((output / "summary.json").read_text())
    assert status == "partial"
    assert summary["llm_calls"] <= 2
    assert summary["candidate_count"] == 1
    assert summary["selected_count"] == 0


def test_planner_failure_exports_failed_run(tmp_path, monkeypatch):
    configure_test_pipeline(monkeypatch, ScriptedModel(fail_planner=True))
    output = tmp_path / "run"
    case = ClinicalCase(case_id="fixture", clinical_case="Synthetic case", question="Synthetic question")
    assert asyncio.run(run_case(case, output, Settings())) == "failed"
    summary = json.loads((output / "summary.json").read_text())
    assert summary["agent_status"]["coordinator_agent"] == "failed"
    assert json.loads((output / "evidence.json").read_text()) == []


def test_gpt_oss_channel_suffix_does_not_abort_tools(tmp_path, monkeypatch):
    configure_test_pipeline(monkeypatch, ScriptedModel(routes=["literature_agent"], malformed_names=True))
    output = tmp_path / "run"
    case = ClinicalCase(case_id="fixture", clinical_case="Synthetic case", question="Synthetic question")
    assert asyncio.run(run_case(case, output, Settings())) == "completed"
    repairs = (output / "tool_name_repairs.jsonl").read_text().splitlines()
    assert len(repairs) == 2
    assert len(json.loads((output / "evidence.json").read_text())) == 1


def test_tool_repair_keeps_unknown_names_unmodified():
    allowed = {"search_literature"}
    assert agents.clean_tool_name("search_literature<|channel|>commentary", allowed) == "search_literature"
    for name in ("search_guidelines<|channel|>commentary", "search_literature_extra", "search_literature<|channel|>other"):
        assert agents.clean_tool_name(name, allowed) == name


def test_final_assessment_json_is_validated_and_saved(tmp_path, monkeypatch):
    configure_test_pipeline(monkeypatch, ScriptedModel(routes=["guideline_agent"], final_assessments=True))
    output = tmp_path / "run"
    case = ClinicalCase(case_id="fixture", clinical_case="Synthetic case", question="Synthetic question")
    assert asyncio.run(run_case(case, output, Settings())) == "completed"
    assert len(json.loads((output / "evidence.json").read_text())) == 1
    assert (output / "assessment_fallbacks.jsonl").exists()
