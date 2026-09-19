"""Respuestas sintéticas para pruebas; no son evidencia médica."""

PUBMED_XML = """<PubmedArticleSet><PubmedArticle>
<MedlineCitation><PMID>123</PMID><Article>
<ArticleTitle>Fixture guideline</ArticleTitle>
<Journal><JournalIssue><PubDate><Year>2024</Year></PubDate></JournalIssue></Journal>
<Abstract><AbstractText Label="RESULTS">Synthetic evidence about kidney outcomes.</AbstractText></Abstract>
<PublicationTypeList><PublicationType>Practice Guideline</PublicationType></PublicationTypeList>
</Article></MedlineCitation><PubmedData><ArticleIdList>
<ArticleId IdType="doi">10.0000/fixture</ArticleId><ArticleId IdType="pmc">PMC123</ArticleId>
</ArticleIdList></PubmedData></PubmedArticle></PubmedArticleSet>"""

EPMC_JSON = {"hitCount": 1, "resultList": {"result": [{
    "id": "123", "source": "MED", "pmid": "123", "pmcid": "PMC123",
    "title": "Fixture guideline", "pubYear": "2024", "doi": "10.0000/fixture",
    "abstractText": "Synthetic evidence about kidney outcomes.",
    "pubTypeList": {"pubType": ["Practice Guideline"]},
}]}}

FULL_TEXT = """<article><body><sec><title>Results</title>
<p>Synthetic kidney outcomes paragraph.</p><p>Synthetic unrelated paragraph.</p>
</sec></body></article>"""


def mock_response(request):
    import httpx
    if request.url.path.endswith("esearch.fcgi"):
        return httpx.Response(200, json={"esearchresult": {"count": "1", "idlist": ["123"]}})
    if request.url.path.endswith("efetch.fcgi"):
        return httpx.Response(200, text=PUBMED_XML)
    if request.url.path.endswith("fullTextXML"):
        return httpx.Response(200, text=FULL_TEXT)
    if request.url.path.endswith("/search"):
        return httpx.Response(200, json=EPMC_JSON)
    return httpx.Response(404)
