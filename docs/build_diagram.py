"""Genera un diagrama editable Excalidraw y su vista SVG, sin dependencias externas.

Ejecutar desde cualquier directorio: python -X utf8 docs/build_diagram.py
La regeneración sobrescribe los dos artefactos; conserva aparte las ediciones manuales.
"""
from __future__ import annotations

import hashlib
import json
from html import escape
from pathlib import Path

HERE = Path(__file__).resolve().parent
WIDTH, HEIGHT = 2300, 3280
INK = "#243247"
PALETTE = {
    "input": ("#e7f0ff", "#3264a5"),
    "agent": ("#eee8fb", "#7151a1"),
    "mcp": ("#e0f4f2", "#247f7a"),
    "source": ("#eaf3df", "#668243"),
    "data": ("#fff0d9", "#b67b28"),
    "output": ("#e6f3e9", "#3b8050"),
    "note": ("#f2f4f7", "#728096"),
}
elements: list[dict] = []
by_id: dict[str, dict] = {}


def base(key, kind, x, y, w, h, color=INK, fill="transparent", dashed=False):
    seed = int(hashlib.sha256(key.encode()).hexdigest()[:7], 16)
    element = dict(id=key, type=kind, x=x, y=y, width=w, height=h,
        angle=0, strokeColor=color, backgroundColor=fill, fillStyle="solid",
        strokeWidth=2, strokeStyle="dashed" if dashed else "solid", roughness=0,
        opacity=100, groupIds=[], frameId=None, index=None, roundness={"type": 3},
        seed=seed, version=1, versionNonce=seed, isDeleted=False, boundElements=[],
        updated=1788825600000, link=None, locked=False)
    assert key not in by_id, key
    elements.append(element)
    by_id[key] = element
    return element


def text(key, x, y, w, value, size=24, color=INK, align="left", container=None):
    h = len(value.splitlines()) * size * 1.25
    element = base(key, "text", x, y, w, h, color)
    element.update(text=value, originalText=value, fontSize=size, fontFamily=2,
        textAlign=align, verticalAlign="middle", containerId=container,
        autoResize=False, lineHeight=1.25, baseline=size, roundness=None, strokeWidth=1)
    if container:
        by_id[container]["boundElements"].append({"id": key, "type": "text"})
    return element


def box(key, x, y, w, h, value, kind="note", size=24, dashed=False):
    fill, stroke = PALETTE[kind]
    element = base(key, "rectangle", x, y, w, h, stroke, fill, dashed)
    text_h = len(value.splitlines()) * size * 1.25
    assert text_h + 20 <= h, (key, "text too tall")
    text(key + "_label", x + 20, y + (h - text_h) / 2, w - 40, value, size, INK, "center", key)
    return element


def connect(key, start, end, points, color=INK, dashed=False, double=False,
            start_side=(0.5, 1), end_side=(0.5, 0)):
    x, y = points[0]
    local = [[px - x, py - y] for px, py in points]
    element = base(key, "arrow", x, y,
        max(p[0] for p in local) - min(p[0] for p in local),
        max(p[1] for p in local) - min(p[1] for p in local), color, dashed=dashed)
    element.update(points=local, startBinding=None, endBinding=None,
        startArrowhead="arrow" if double else None, endArrowhead="arrow",
        elbowed=False, roundness=None)
    for name, target, fixed in (("startBinding", start, start_side), ("endBinding", end, end_side)):
        if target:
            # fixedPoint/mode: formato actual; focus/gap: compatibilidad con importadores anteriores.
            element[name] = dict(elementId=target, fixedPoint=list(fixed), mode="orbit", focus=0, gap=10)
            by_id[target]["boundElements"].append({"id": key, "type": "arrow"})
    return element


def down(key, first, second, **kwargs):
    a, b = by_id[first], by_id[second]
    connect(key, first, second,
            [(a["x"] + a["width"] / 2, a["y"] + a["height"] + 10),
             (b["x"] + b["width"] / 2, b["y"] - 10)], **kwargs)


def build():
    text("title", 60, 45, 2170, "FWK-MAS  /  Evidencia clínica y argumentos trazables", 44)
    text("subtitle", 60, 110, 2160,
         "Google ADK + MCP + PoliGPT · Flujo implementado · Documentación: septiembre de 2026", 24, "#64748b")
    base("main_panel", "rectangle", 40, 185, 1400, 2920, "#d7dee8", "#ffffff")
    base("detail_panel", "rectangle", 1480, 185, 780, 2920, "#d7dee8", "#fafbfc")
    text("main_header", 85, 215, 1280, "01  RECORRIDO GENERAL", 28, "#3264a5")
    text("details_header", 1520, 215, 680, "02  EJECUCIÓN Y TRAZABILIDAD", 28, "#7151a1")

    box("input", 380, 280, 650, 110,
        "CASO CLÍNICO + PREGUNTA\noptions opcionales · entrada JSON\nEl ejemplo es sintético, no un paciente real", "input", 23)
    box("runner", 380, 445, 650, 125,
        "CLI + RUNNER DE GOOGLE ADK\nValidar ClinicalCase · cargar configuración\nCrear sesión y carpeta de ejecución", "input", 24)
    box("coordinator", 380, 625, 650, 125,
        "COORDINATOR AGENT\nIdentificar aspectos y generar RetrievalPlan\nValidar tareas y guardar plan.json", "agent", 24)
    text("routing_note", 85, 253, 1280,
        "Uno o ambos especialistas · ejecución SECUENCIAL en el orden del plan", 19, "#7151a1")
    box("guideline", 160, 865, 510, 125,
        "GUIDELINE AGENT\nGuías y recomendaciones indexadas\nFormular consultas y valorar fragmentos", "agent", 22)
    box("literature", 800, 865, 510, 125,
        "LITERATURE AGENT\nEstudios y revisiones\nFormular consultas y valorar fragmentos", "agent", 22)
    box("client_g", 160, 1055, 510, 95,
        "CLIENTE MCP / McpToolset\nHerramientas filtradas para guías", "mcp", 23)
    box("client_l", 800, 1055, 510, 95,
        "CLIENTE MCP / McpToolset\nHerramientas filtradas para literatura", "mcp", 23)
    box("server_g", 160, 1215, 510, 125,
        "SERVIDOR MCP · SUBPROCESO A\nsearch_guidelines\nfetch_full_text", "mcp", 23)
    box("server_l", 800, 1215, 510, 125,
        "SERVIDOR MCP · SUBPROCESO B\nsearch_literature\nfetch_full_text", "mcp", 23)
    text("stdio_note", 695, 1165, 90, "stdio", 19, "#247f7a", "center")
    box("source_g", 160, 1415, 510, 110,
        "PUBMED O EUROPE PMC\nFiltrar Guideline / Practice Guideline\nHTTP → JSON / XML", "source", 22)
    box("source_l", 800, 1415, 510, 110,
        "EUROPE PMC O PUBMED\nBúsqueda de literatura científica\nHTTP → JSON / XML", "source", 22)
    box("parser", 380, 1615, 650, 125,
        "EXTRACCIÓN EN EL SERVIDOR\nGuardar raw/ · separar texto y metadatos\nPassage[]: abstract o full_text", "data", 24)
    box("store", 380, 1800, 650, 125,
        "AFTER_TOOL + EVIDENCE STORE\nValidar y deduplicar; unir procedencias\nGuardar candidates.json", "data", 24)
    box("assessment", 380, 1990, 650, 135,
        "VALORACIÓN DE LOS AGENTES\nassess_evidence: IDs reales + score + motivo\nAlternativa: JSON final público validado", "agent", 23)
    box("export", 380, 2200, 650, 125,
        "SELECCIÓN GLOBAL + EXPORTACIÓN\nScore ≥ 2 · ordenar · máximo TOP_K\nevidence.json + report.md + summary.json", "output", 23)
    box("arg_segment", 380, 2380, 650, 105,
        "SEGMENTACIÓN oAMF\nDSG / TARGER / DSS → spans + nodos L", "agent", 23)
    box("arg_prop", 380, 2535, 650, 105,
        "PROPOSICIONAMIENTO oAMF\nSPG / CPJ → claims trazables + nodos I", "agent", 23)
    box("arg_rel", 380, 2690, 650, 115,
        "IDENTIFICACIÓN DE RELACIONES\nAlternativas oAMF → RA / CA / MA dirigidas", "agent", 23)
    box("arg_xaif", 380, 2855, 650, 120,
        "EXPORTACIÓN TRAZABLE\nxAIF + provenance_map + manifest\nLímite actual: sin razonamiento AF/QBAF", "output", 22)

    down("a_input", "input", "runner")
    down("a_runner", "runner", "coordinator")
    connect("route_g", "coordinator", "guideline", [(580, 760), (580, 830), (415, 830), (415, 855)], start_side=(0.3, 1))
    connect("route_l", "coordinator", "literature", [(840, 760), (840, 830), (1055, 830), (1055, 855)], start_side=(0.7, 1))
    for suffix in ("g", "l"):
        agent = "guideline" if suffix == "g" else "literature"
        down("agent_client_" + suffix, agent, "client_" + suffix, color="#247f7a", double=True)
        down("client_server_" + suffix, "client_" + suffix, "server_" + suffix, color="#247f7a", double=True)
        down("server_source_" + suffix, "server_" + suffix, "source_" + suffix, color="#668243", double=True)
    connect("source_parser_g", "source_g", "parser", [(415, 1535), (415, 1585), (600, 1585), (600, 1605)], end_side=(0.34, 0))
    connect("source_parser_l", "source_l", "parser", [(1055, 1535), (1055, 1585), (825, 1585), (825, 1605)], end_side=(0.68, 0))
    down("parser_store", "parser", "store")
    connect("return_g", "store", "guideline", [(370, 1860), (100, 1860), (100, 927), (150, 927)],
            color="#247f7a", dashed=True, start_side=(0, 0.48), end_side=(0, 0.5))
    connect("return_l", "store", "literature", [(1040, 1860), (1375, 1860), (1375, 927), (1320, 927)],
            color="#247f7a", dashed=True, start_side=(1, 0.48), end_side=(1, 0.5))
    text("return_note", 1060, 1710, 270, "Retorno al agente\npor MCP / after_tool\nTexto + IDs + presupuesto", 19, "#247f7a", "center")
    down("store_assessment", "store", "assessment")
    down("assessment_export", "assessment", "export")
    down("export_segment", "export", "arg_segment")
    down("segment_prop", "arg_segment", "arg_prop")
    down("prop_rel", "arg_prop", "arg_rel")
    down("rel_xaif", "arg_rel", "arg_xaif")

    box("model_note", 1520, 280, 700, 200,
        "MODELO COMPARTIDO\nADK → LiteLLM → PoliGPT / gpt-oss-120b\nVPN UPV · OPENAI_BASE_URL + API_KEY\nTemperatura 0 · claves en .env\nMCP accede a fuentes, no decide qué buscar", "agent", 23)
    box("budget_note", 1520, 530, 700, 185,
        "PRESUPUESTOS POR DEFECTO\n24 llamadas LLM globales, incluido coordinador\nPor especialista: 4 búsquedas + 2 full-text\n5 documentos / búsqueda · TOP_K global = 10\nPresupuesto restante visible en cada llamada", "input", 22)
    text("loop_heading", 1540, 770, 650, "CICLO DE CADA ESPECIALISTA", 25, "#247f7a")
    box("loop_decide", 1560, 835, 620, 95,
        "LLM: elegir la siguiente acción\nCaso + tarea + resultados del ciclo", "agent", 23)
    box("loop_gate", 1560, 990, 620, 110,
        "before_tool: verificar presupuesto\nSin saldo → devolver error recuperable\nCon saldo → invocar herramienta permitida", "mcp", 22)
    box("loop_http", 1560, 1160, 620, 110,
        "MCP → FUENTE → MCP\nBuscar o recuperar XML completo\nGuardar respuesta bruta y traza HTTP", "source", 23)
    box("loop_return", 1560, 1330, 620, 110,
        "after_tool: ingerir y devolver\nUna copia del resultado + saldo restante\nEl agente puede reformular o valorar", "data", 22)
    down("loop_1", "loop_decide", "loop_gate")
    down("loop_2", "loop_gate", "loop_http")
    down("loop_3", "loop_http", "loop_return")
    connect("loop_again", "loop_return", "loop_decide", [(2190, 1385), (2240, 1385), (2240, 882), (2190, 882)],
            color="#247f7a", dashed=True, start_side=(1, 0.5), end_side=(1, 0.5))
    box("validation_note", 1520, 1510, 700, 225,
        "VALIDACIÓN DE LAS VALORACIONES\nIDs recuperados por el mismo agente\nListas de igual longitud · enteros 0–3\nMotivos no vacíos · rechazo del lote inválido\nSi no guardó ninguna: validar JSON final público\nNunca generar texto de evidencia desde el LLM", "data", 22)
    box("traces_note", 1520, 1790, 700, 190,
        "TRAZAS CONSERVADAS\nplan.json · candidates.json · events.jsonl\ntools.jsonl · models.jsonl · agents/*/raw/\nHTTP, errores y reparaciones cuando ocurren\nprovenance une todas las rutas de recuperación", "note", 22)
    box("status_note", 1520, 2035, 700, 155,
        "ESTADO GLOBAL / CÓDIGO CLI\ncompleted / 0: sin incidencias registradas\npartial / 2: incidencias o candidatos tras fallo\nfailed / 2: fallo general sin candidatos", "output", 22)
    box("contract_note", 1520, 2240, 700, 125,
        "EVIDENCE ITEM\nFragmento original + documento + fuente\nprovenance[] + assessments[] separados", "data", 23)
    box("oamf_note", 1520, 2420, 700, 260,
        "EXPERIMENTOS oAMF POR ETAPAS\nsegment / propositions / relations / export\nEntradas gold o predichas por etapa\nSin cuadrícula cartesiana automática\nEndpoint, módulo, modelo, versión y config\nen manifest.json y en cada objeto derivado", "agent", 22)
    box("argument_trace_note", 1520, 2735, 700, 240,
        "TRAZABILIDAD DE ARGUMENTOS\nclaim_id → span_id → evidence_id\noffsets exactos → passage_text original\ndocumento + retrieval provenance\ninputs y respuestas oAMF originales conservados\ncandidate_pairs + claims + relations + xAIF", "data", 22)

    text("legend", 65, 3145, 2150,
        "LECTURA  → flujo / llamada    ↔ petición y respuesta    - - → retorno de datos", 23, "#526175")
    text("scope", 65, 3200, 2150,
        "Salida actual: grafo xAIF trazable. No decide la respuesta clínica ni ejecuta razonamiento AF/QBAF.", 23, "#526175")


def validate():
    for element in elements:
        assert element["width"] >= 0 and element["height"] >= 0
        if element["type"] != "arrow":
            assert 0 <= element["x"] <= WIDTH - element["width"], element["id"]
            assert 0 <= element["y"] <= HEIGHT - element["height"], element["id"]
        for binding in element.get("boundElements", []):
            assert binding["id"] in by_id
        if element.get("containerId"):
            container = by_id[element["containerId"]]
            assert element["y"] >= container["y"] and element["y"] + element["height"] <= container["y"] + container["height"]
        for key in ("startBinding", "endBinding"):
            if element.get(key):
                assert element[key]["elementId"] in by_id


def svg():
    result = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-labelledby="title description">',
        '<title id="title">FWK-MAS: recuperación clínica y construcción trazable de argumentos</title>',
        '<desc id="description">Caso, agentes de recuperación, MCP, evidencia, etapas oAMF intercambiables, relaciones y exportación xAIF con procedencia.</desc>',
        '<rect width="100%" height="100%" fill="#f6f8fb"/>',
        '<defs><marker id="arrow" markerWidth="10" markerHeight="10" refX="8" refY="5" orient="auto-start-reverse" markerUnits="userSpaceOnUse"><path d="M1 1 L8 5 L1 9" fill="none" stroke="context-stroke" stroke-width="2"/></marker></defs>']
    for e in elements:
        color = e["strokeColor"]
        if e["type"] == "rectangle":
            dash = ' stroke-dasharray="9 7"' if e["strokeStyle"] == "dashed" else ""
            result.append(f'<rect x="{e["x"]}" y="{e["y"]}" width="{e["width"]}" height="{e["height"]}" rx="16" fill="{e["backgroundColor"]}" stroke="{color}" stroke-width="2"{dash}/>')
        elif e["type"] == "text":
            centered = e["textAlign"] == "center"
            x = e["x"] + e["width"] / 2 if centered else e["x"]
            anchor = "middle" if centered else "start"
            for i, line in enumerate(e["text"].splitlines()):
                y = e["y"] + e["fontSize"] + i * e["fontSize"] * e["lineHeight"]
                result.append(f'<text x="{x}" y="{y}" font-family="Arial, Helvetica, sans-serif" font-size="{e["fontSize"]}" fill="{color}" text-anchor="{anchor}">{escape(line)}</text>')
        elif e["type"] == "arrow":
            points = " ".join(f'{e["x"] + p[0]},{e["y"] + p[1]}' for p in e["points"])
            dash = ' stroke-dasharray="9 7"' if e["strokeStyle"] == "dashed" else ""
            start = ' marker-start="url(#arrow)"' if e["startArrowhead"] else ""
            result.append(f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="2" stroke-linejoin="round" marker-end="url(#arrow)"{start}{dash}/>')
    result.append('</svg>')
    return "\n".join(result) + "\n"


def main():
    build()
    validate()
    scene = dict(type="excalidraw", version=2, source="https://excalidraw.com", elements=elements,
                 appState={"viewBackgroundColor": "#f6f8fb", "gridSize": 20, "theme": "light"}, files={})
    (HERE / "flujo-funcionamiento.excalidraw").write_text(json.dumps(scene, ensure_ascii=False, indent=2), encoding="utf-8")
    (HERE / "flujo-funcionamiento.svg").write_text(svg(), encoding="utf-8")
    print(f"Diagrama generado y validado: {len(elements)} elementos editables.")


if __name__ == "__main__":
    main()
