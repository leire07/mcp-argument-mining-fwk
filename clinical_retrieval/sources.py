from __future__ import annotations

import asyncio
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4

import httpx
from bs4 import BeautifulSoup
from defusedxml import ElementTree as ET

from .models import Passage, evidence_id

EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest"
NCBI = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
Source = Literal["pubmed", "europe_pmc"]
Kind = Literal["guideline", "literature"]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def node_text(node) -> str:
    return "" if node is None else "".join(node.itertext()).strip()


def split_passage(text: str, size: int = 1800) -> list[str]:
    """Fragmentos contiguos del texto extraído, sin paráfrasis ni truncado silencioso."""
    result = []
    while text:
        end = len(text) if len(text) <= size else text.rfind(" ", 0, size)
        if end <= 0:
            end = min(size, len(text))
        fragment = text[:end].strip()
        if fragment:
            result.append(fragment)
        text = text[end:].lstrip()
    return result


def make_passages(meta: dict, sections: list[tuple[str, str]], **context) -> list[Passage]:
    result = []
    for label, text in sections:
        for fragment in split_passage(text):
            result.append(Passage(
                **meta, **context, section=label, passage_text=fragment,
                evidence_id=evidence_id(meta["document_id"], fragment),
            ))
    return result


def parse_pubmed(xml: str, query: str, raw_file: str, retrieved_at: str) -> list[Passage]:
    root = ET.fromstring(xml)
    if root.find(".//ERROR") is not None:
        raise ValueError("NCBI devolvió un error en la respuesta XML")
    result = []
    for rank, entry in enumerate(root.findall(".//PubmedArticle"), 1):
        citation = entry.find("MedlineCitation")
        article = entry.find("MedlineCitation/Article")
        if article is None or citation is None:
            continue
        pmid = node_text(citation.find("PMID"))
        ids = {n.get("IdType"): node_text(n) for n in entry.findall("PubmedData/ArticleIdList/ArticleId")}
        types = [node_text(n) for n in article.findall("PublicationTypeList/PublicationType")]
        is_guideline = any(t.lower() in {"guideline", "practice guideline"} for t in types)
        year = node_text(article.find("Journal/JournalIssue/PubDate/Year"))
        if not year:
            year = node_text(article.find("Journal/JournalIssue/PubDate/MedlineDate"))
        meta = dict(
            document_id=f"PMID:{pmid}", title=node_text(article.find("ArticleTitle")),
            source="pubmed", source_type="guideline" if is_guideline else "literature",
            url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/", publication_year=year,
            publication_types=types, doi=ids.get("doi", ""), pmid=pmid, pmcid=ids.get("pmc", ""),
        )
        sections = [(n.get("Label", "Abstract"), node_text(n)) for n in article.findall("Abstract/AbstractText")]
        result.extend(make_passages(meta, sections, content_type="abstract", retrieval_query=query,
                                    retrieved_at=retrieved_at, raw_file=raw_file, source_rank=rank))
    return result


def parse_epmc(data: dict, query: str, raw_file: str, retrieved_at: str) -> list[Passage]:
    result = []
    for rank, entry in enumerate(data.get("resultList", {}).get("result", []), 1):
        abstract = entry.get("abstractText", "")
        if not abstract:
            continue  # Un título o enlace no cuenta como fragmento de evidencia.
        text = BeautifulSoup(abstract, "html.parser").get_text(separator=" ").strip()
        pmid = entry.get("pmid", "") or (entry["id"] if entry.get("source") == "MED" else "")
        types = entry.get("pubTypeList", {}).get("pubType", [])
        is_guideline = any(t.lower() in {"guideline", "practice guideline"} for t in types)
        document_id = f"PMID:{pmid}" if pmid else f"{entry.get('source', 'PMC')}:{entry['id']}"
        meta = dict(
            document_id=document_id, title=entry.get("title", ""), source="europe_pmc",
            source_type="guideline" if is_guideline else "literature",
            url=f"https://europepmc.org/article/{entry.get('source', 'MED')}/{entry['id']}",
            publication_year=entry.get("pubYear", ""), publication_types=types,
            doi=entry.get("doi", ""), pmid=pmid, pmcid=entry.get("pmcid", ""),
        )
        result.extend(make_passages(meta, [("Abstract", text)], content_type="abstract",
                                    retrieval_query=query, retrieved_at=retrieved_at,
                                    raw_file=raw_file, source_rank=rank))
    return result


class SourceClient:
    def __init__(self, output: Path, timeout: int = 30, client: httpx.AsyncClient | None = None):
        self.output = output
        self.raw = output / "raw"
        self.raw.mkdir(parents=True, exist_ok=True)
        self.client = client or httpx.AsyncClient(timeout=timeout, follow_redirects=True,
                                                headers={"User-Agent": "FWK-MAS-retrieval/0.1"})
        self._ncbi_lock = asyncio.Lock()
        self._last_ncbi_request = 0.0

    async def close(self):
        await self.client.aclose()

    def log(self, record: dict):
        with (self.output / "http.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")

    async def request(self, url: str, params: dict | None = None, suffix: str = "json"):
        for attempt in range(3):
            started = time.monotonic()
            try:
                if url.startswith(NCBI):
                    # Ambos especialistas se ejecutan secuencialmente; <= 3 peticiones/s.
                    async with self._ncbi_lock:
                        await asyncio.sleep(max(0, 0.36 - (time.monotonic() - self._last_ncbi_request)))
                        self._last_ncbi_request = time.monotonic()
                        response = await self.client.get(url, params=params)
                else:
                    response = await self.client.get(url, params=params)
                self.log(dict(at=utc_now(), url=url, params=params, attempt=attempt + 1,
                              status=response.status_code, seconds=time.monotonic() - started))
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt < 2:
                        delay = response.headers.get("Retry-After", "")
                        await asyncio.sleep(min(float(delay), 10) if delay.isdigit() else 2 ** attempt)
                        continue
                response.raise_for_status()
                path = self.raw / f"{uuid4().hex}.{suffix}"
                path.write_bytes(response.content)
                return response, path.relative_to(self.output).as_posix()
            except httpx.RequestError as exc:
                self.log(dict(at=utc_now(), url=url, attempt=attempt + 1,
                              error=type(exc).__name__, seconds=time.monotonic() - started))
                if attempt == 2:
                    raise
                await asyncio.sleep(2 ** attempt)
        raise RuntimeError("No se pudo completar la petición")

    async def search(self, query: str, source: Source, kind: Kind, limit: int) -> dict:
        if not query.strip() or len(query) > 1000:
            raise ValueError("La consulta debe tener entre 1 y 1000 caracteres")
        if source not in {"pubmed", "europe_pmc"} or kind not in {"guideline", "literature"}:
            raise ValueError("Fuente o tipo de búsqueda no válido")
        if not 1 <= limit <= 10:
            raise ValueError("limit debe estar entre 1 y 10")
        at = utc_now()
        if source == "pubmed":
            actual = f'({query}) AND (Guideline[pt] OR Practice Guideline[pt])' if kind == "guideline" else query
            params = dict(db="pubmed", term=actual, retmode="json", retmax=limit,
                          sort="relevance", tool="FWK-MAS")
            if os.getenv("NCBI_EMAIL"):
                params["email"] = os.environ["NCBI_EMAIL"]
            response, search_raw = await self.request(f"{NCBI}/esearch.fcgi", params)
            search_data = response.json()
            if "esearchresult" not in search_data or search_data["esearchresult"].get("ERROR"):
                raise ValueError("Respuesta de búsqueda de NCBI no válida")
            search = search_data["esearchresult"]
            ids = search.get("idlist", [])
            if not ids:
                return dict(passages=[], hit_count=int(search.get("count", 0)), query=actual,
                            raw_files=[search_raw], warnings=search.get("warninglist", {}))
            response, raw = await self.request(f"{NCBI}/efetch.fcgi",
                dict(db="pubmed", id=",".join(ids), retmode="xml", tool="FWK-MAS"), "xml")
            passages = parse_pubmed(response.text, actual, raw, at)
            # EFetch puede cambiar el orden de los documentos.
            ranks = {pmid: rank for rank, pmid in enumerate(ids, 1)}
            for passage in passages:
                passage.source_rank = ranks.get(passage.pmid, passage.source_rank)
            hit_count, raws = int(search.get("count", 0)), [search_raw, raw]
        else:
            actual = f'({query}) AND (PUB_TYPE:"Guideline" OR PUB_TYPE:"Practice Guideline")' if kind == "guideline" else query
            response, raw = await self.request(f"{EPMC}/search",
                dict(query=actual, format="json", resultType="core", pageSize=limit))
            data = response.json()
            if "resultList" not in data:
                raise ValueError("Respuesta de Europe PMC no válida")
            passages = parse_epmc(data, actual, raw, at)
            hit_count, raws = int(data.get("hitCount", 0)), [raw]
        if kind == "guideline":
            passages = [p for p in passages if p.source_type == "guideline"]
        return dict(passages=[p.model_dump() for p in passages], hit_count=hit_count,
                    query=actual, raw_files=raws,
                    note="Se devuelven fragmentos de resúmenes disponibles; no todos los registros tienen resumen.")

    async def full_text(self, passage: Passage, query: str, limit: int = 8) -> dict:
        if not re.fullmatch(r"PMC\d+", passage.pmcid):
            return dict(passages=[], error="Este documento no tiene PMCID para recuperar texto completo")
        response, raw = await self.request(f"{EPMC}/{passage.pmcid}/fullTextXML", suffix="xml")
        root = ET.fromstring(response.text)
        meta = passage.model_dump(include={"document_id", "title", "source_type", "publication_year",
                                           "publication_types", "doi", "pmid", "pmcid"})
        meta.update(source="europe_pmc", url=f"https://europepmc.org/articles/{passage.pmcid}")
        sections = []
        for section in root.findall(".//body//sec"):
            label = node_text(section.find("title")) or "Body"
            sections.extend((label, node_text(p)) for p in section.findall("p"))
        body = root.find(".//body")
        if body is not None:
            sections.extend(("Body", node_text(p)) for p in body.findall("p"))
        items = make_passages(meta, sections, content_type="full_text", retrieval_query=query,
                              retrieved_at=utc_now(), raw_file=raw, source_rank=passage.source_rank)
        # Prefiltro léxico explícito para no enviar un artículo entero al LLM.
        words = set(re.findall(r"[a-z0-9]{3,}", query.lower()))
        items.sort(key=lambda p: len(words & set(re.findall(r"[a-z0-9]{3,}", p.passage_text.lower()))), reverse=True)
        return dict(passages=[p.model_dump() for p in items[:limit]], raw_files=[raw],
                    total_passages=len(items), selection="lexical_overlap", query=query)
