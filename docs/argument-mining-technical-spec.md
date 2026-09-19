# Especificación técnica de la capa de minería de argumentos

Versión del contrato: `1.0`. Esta sección convierte la arquitectura experimental en una estructura implementable. La fuente de verdad del contrato son los modelos Pydantic de `argument_mining/models/`; este documento explica sus invariantes y fronteras.

Los contratos JSON Schema generados están en [docs/schemas/argument-mining](schemas/argument-mining/). Se regeneran con:

```powershell
.\.venv\Scripts\python.exe -X utf8 -m argument_mining schemas --output docs/schemas/argument-mining
```

Incluyen `benchmark.schema.json`, que valida candidatos, rutas gold y reglas de selección antes de ejecutar una comparación.

## 1. Estructura del proyecto

```text
argument_mining/
├── __main__.py                    # CLI: etapas, end-to-end y evaluación
├── client.py                      # transporte multipart hacia servicios oAMF
├── errors.py                      # taxonomía de fallos
├── pipeline.py                    # fachada/orquestación compatible
├── registry.py                    # resolución módulo → endpoint
├── models/
│   ├── evidence.py                # EvidenceRecord, entrada upstream inmutable
│   ├── claim.py                   # SourceSpan, ArgumentSpan, Claim
│   ├── relation.py                # ArgumentRelation, PairGeneration
│   ├── common.py                  # ModuleSpec y ModuleRun
│   └── experiment.py              # configuración y manifiesto
├── segmentation/
│   ├── base.py                    # SegmentationModule
│   ├── oamf.py                    # adaptador HTTP/xAIF común
│   ├── dsg.py
│   ├── targer.py
│   └── dss.py
├── propositionalisation/
│   ├── base.py                    # PropositionalisationModule
│   ├── oamf.py
│   ├── spg.py
│   └── cpj.py
├── relations/
│   ├── base.py                    # RelationIdentificationModule
│   ├── oamf.py
│   ├── damg.py
│   ├── sarim.py
│   ├── arir.py
│   ├── drig.py
│   ├── targer_am.py
│   ├── dsrm.py
│   └── dterg.py
├── provenance/
│   └── mapper.py                  # validación y sidecar de procedencia
├── xaif/
│   ├── input.py                   # Evidence/Span/Claim → xAIF de entrada
│   ├── parsers.py                 # respuesta oAMF → modelos internos
│   └── exporter.py                # claims/relaciones → xAIF final
├── evaluation/
│   ├── common.py
│   ├── segmentation.py
│   ├── propositions.py
│   ├── relations.py
│   └── end_to_end.py
└── experiments/
    ├── config.py                  # carga segura YAML/JSON
    ├── benchmark.py               # comparación secuencial y ranking preregistrado
    └── runner.py                  # import estable del orquestador

configs/
└── oamf_public_modules.yaml       # catálogo de alternativas

examples/
└── argument_smoke_config.yaml     # integración, no pipeline seleccionado
```

`pipeline.py` conserva una fachada única para la CLI y los consumidores existentes. La implementación de cada función experimental vive detrás de una interfaz de etapa; añadir un módulo no requiere modificar los contratos de las otras etapas.

## 2. Interfaces Python

### 2.1 Segmentación

```python
@dataclass(frozen=True)
class SegmentationOutput:
    spans: list[ArgumentSpan]
    xaif_input: dict
    xaif_response: dict
    module_run: ModuleRun

class SegmentationModule(ABC):
    @abstractmethod
    def run(
        self,
        evidence: EvidenceRecord,
        experiment_id: str,
    ) -> SegmentationOutput: ...
```

Precondición: `evidence_id` y `passage_text` son válidos. Postcondición: cada span contiene offsets exactos sobre ese mismo `passage_text`, un nodo L y la ejecución responsable.

### 2.2 Proposicionamiento

```python
@dataclass(frozen=True)
class PropositionalisationOutput:
    claims: list[Claim]
    xaif_input: dict
    xaif_response: dict
    module_run: ModuleRun

class PropositionalisationModule(ABC):
    @abstractmethod
    def run(
        self,
        evidence: EvidenceRecord,
        spans: list[ArgumentSpan],
        experiment_id: str,
        input_kind: Literal["gold", "predicted"],
    ) -> PropositionalisationOutput: ...
```

Postcondición: todo nodo I aceptado enlaza con un span de entrada; no se acepta un claim huérfano aunque el servicio haya producido texto plausible.

### 2.3 Identificación de relaciones

```python
@dataclass(frozen=True)
class RelationIdentificationOutput:
    relations: list[ArgumentRelation]
    xaif_input: dict
    xaif_response: dict
    module_run: ModuleRun

class RelationIdentificationModule(ABC):
    @abstractmethod
    def run(
        self,
        claims: list[Claim],
        experiment_id: str,
        input_kind: Literal["gold", "predicted"],
    ) -> RelationIdentificationOutput: ...
```

Las relaciones son dirigidas. El grupo de claims se construye antes de llamar al módulo según `PairGeneration`; todos los pares dirigidos habilitados quedan en `candidate_pairs.json`.

### 2.4 Exportación

```python
def final_xaif(
    claims: list[Claim],
    relations: list[ArgumentRelation],
    experiment_id: str,
) -> dict: ...
```

La exportación no realiza inferencia. Construye L → YA → I y las relaciones I → RA/CA/MA → I. La clase `none` se conserva para evaluación pero no genera un nodo en xAIF.

## 3. Contratos exactos de datos

### 3.1 Evidencia de entrada

```json
{
  "evidence_id": "ev_e877aa7cebd76155201d4208",
  "passage_text": "Texto recuperado exacto...",
  "document_id": "PMID:42415828",
  "title": "Título",
  "provenance": [{"retrieved_by": "literature_agent", "tool": "fetch_full_text"}],
  "assessments": [{"agent": "literature_agent", "relevance_score": 2}]
}
```

Requeridos: `evidence_id`, `passage_text`. Los demás campos upstream son opcionales y se preservan porque `EvidenceRecord` permite campos adicionales. El archivo de entrada debe ser un array y no puede repetir `evidence_id`. Los modelos derivados y de configuración rechazan campos desconocidos (`extra="forbid"`) para detectar cambios accidentales de contrato.

### 3.2 Span / nodo L

```json
{
  "span_id": "sp_<24 hex>",
  "evidence_id": "ev_...",
  "source_span": {"start_char": 0, "end_char": 42, "text": "texto exacto"},
  "l_node_id": "1",
  "input_kind": "predicted",
  "generated_by": {"experiment_id": "exp_...", "stage": "segmentation", "module_id": "DSG"}
}
```

Para gold, `input_kind` vale `gold` y `generated_by` puede ser `null`. Se exige `0 <= start_char < end_char` y la igualdad exacta:

```python
evidence.passage_text[start_char:end_char] == source_span.text
```

### 3.3 Claim / nodo I

```json
{
  "claim_id": "cl_<24 hex>",
  "evidence_id": "ev_...",
  "span_id": "sp_...",
  "l_node_id": "1",
  "i_node_id": "3",
  "proposition_text": "Proposición autocontenida.",
  "source": {
    "evidence_id": "ev_...",
    "passage_text": "Texto recuperado exacto...",
    "source_span": {"start_char": 0, "end_char": 42, "text": "texto exacto"},
    "document": {"document_id": "PMID:...", "doi": "...", "url": "..."},
    "retrieval_provenance": [],
    "upstream_assessments": []
  },
  "input_kind": "predicted",
  "generated_by": {},
  "confidence": null,
  "quality_flags": []
}
```

`proposition_text` nunca sustituye `source_span.text` ni `passage_text`. Las confianzas de argument mining no se mezclan con `upstream_assessments`.

### 3.4 Relación

```json
{
  "relation_id": "rel_<24 hex>",
  "source_claim_id": "cl_a",
  "target_claim_id": "cl_b",
  "relation": "support",
  "xaif_relation_type": "RA",
  "input_kind": "predicted",
  "generated_by": {},
  "confidence": null
}
```

Mapeo cerrado: `support → RA`, `attack → CA`, `rephrase → MA`, `none → null`. Source y target no son intercambiables.

### 3.5 Metadatos de módulo

`ModuleSpec` registra lo declarado: `module_id`, etapa, endpoint, versión, modelo, repositorio/commit y configuración. `ModuleRun` añade `experiment_id`, instantes UTC, número de intentos y SHA-256 canónicos del xAIF enviado y recibido. Una versión no comunicada por un servicio público se registra literalmente como `public-service-unreported`.

## 4. Reglas de identificadores

Los IDs derivados usan SHA-256 y los primeros 24 caracteres hexadecimales:

```text
span_id     = "sp_"  + SHA256(evidence_id + start + end + exact_span_text)[:24]
claim_id    = "cl_"  + SHA256(evidence_id + span_id + proposition_text)[:24]
relation_id = "rel_" + SHA256(module_id + source_claim_id + target_claim_id + xAIF_type)[:24]
```

Las partes se concatenan con salto de línea UTF-8. `evidence_id` siempre viene de recuperación y jamás se recalcula. Los `nodeID` enteros de xAIF son identificadores de serialización y pueden cambiar al reconstruir el grafo; `claim_id` y `evidence_id` mantienen la identidad estable.

## 5. Configuración YAML

```yaml
experiment_id: exp_rel_arir_gold_001
dataset_version: casimedicos_retrieval_v1
gold_version: gold_v1
random_seed: 42

segmentation:
  module: TARGER
  endpoint: null       # null usa configs/oamf_public_modules.yaml
  version: null
  model: null
  config: {}

propositionalisation:
  module: CPJ
  endpoint: null
  version: null
  model: null
  config: {}

relation_identification:
  module: ARIR
  endpoint: null
  version: null
  model: null
  config: {}

pair_generation:
  strategy: within_passage  # within_passage | within_document | all
  thresholds: {}
  version: "1"
```

Cada archivo describe una ejecución, no un espacio de búsqueda. Para comparar módulos se crean experimentos separados con el mismo corpus, partición y gold. El runner no expande listas de módulos ni forma combinaciones.

El catálogo de módulos también es YAML. Un endpoint local puede reemplazar al público sin cambiar la interfaz:

```yaml
- module_id: DSG
  stage: segmentation
  endpoint: http://localhost:5005/segmenter-01
  version: git-fd9d965
  model: en_core_web_sm
  repository_commit: fd9d9657f4820d7c6bb20a7697a61017b454e627
  config: {}
```

## 6. Manejo de errores

| Tipo estable | Condición |
| --- | --- |
| `provenance` | ID ausente/duplicado, claim huérfano, offsets alterados o relación con extremos inexistentes |
| `segmentation` | servicio de segmentación falla, no produce L-nodes o un span no se alinea |
| `proposition` | servicio falla, no produce I-nodes o un I-node no enlaza con un L-node |
| `relation` | servicio falla o un nodo RA/CA/MA no tiene extremos trazables |
| `serialization` | JSON/YAML/xAIF inválido o archivo ilegible |
| `unexpected` | excepción no clasificada; debe investigarse y tiparse antes de experimentos finales |

Una vez creado el directorio del experimento, un fallo deja `manifest.json` con `status: failed`, clase, tipo y mensaje. Los inputs y respuestas escritos antes del fallo no se eliminan. Los errores que impiden crear el experimento, como un YAML inválido, se devuelven por CLI como `serialization`. La CLI nunca convierte una salida parcial en resultado completo silenciosamente.

## 7. Pseudocódigo

### 7.1 Segmentación aislada

```text
load evidence.json
validate unique evidence_id and non-empty passage_text
write unchanged evidence.json into experiment directory
resolve exactly one segmentation module
for each evidence item:
    construct xAIF with one documentary L-node
    persist xAIF request
    invoke selected module
    persist raw response
    parse returned L-nodes
    map every node text to deterministic character offsets
    reject any unalignable span
write argument_spans.json, l_nodes.json and manifest.json
```

### 7.2 Proposicionamiento con entrada gold o predicha

```text
load evidence.json and argument_spans.json
record input_kind = gold | predicted
group spans by evidence_id
for each evidence group:
    construct xAIF L-nodes
    invoke exactly one propositionalisation module
    follow L -> YA -> I edges (exact-text fallback only when necessary)
    reject orphan I-nodes
    construct claim with full evidence/span/document lineage
validate all offsets again
write claims.json, i_nodes.json, provenance_map.json and manifest.json
```

### 7.3 Relaciones con entrada gold o predicha

```text
load evidence.json and claims.json
validate every claim against its original passage
apply one declared pair-generation strategy
persist every directed candidate pair
for each resulting claim group:
    construct xAIF I-nodes
    invoke exactly one relation module
    parse I -> RA|CA|MA -> I paths
    reject relations whose endpoints cannot map to stable claim_id values
write relations.json, xaif.json, provenance_map.json and manifest.json
```

### 7.4 Selección experimental por etapas

```text
for segmenter in preregistered_segmentation_candidates:
    run segmentation-only experiment against identical raw evidence
    evaluate against gold spans
record metrics, failures, latency and reproducibility evidence

for propositionaliser in preregistered_proposition_candidates:
    run on identical gold spans
    record availability, reproducibility, xAIF and provenance behaviour
# no normalised gold claims exist in AbstRCT; do not fabricate them

for relation_module in preregistered_relation_candidates:
    run on identical extractive AbstRCT argument units
    evaluate Support/Attack only under an explicit semantic mapping
    record Macro-F1, per-class directed F1, confusion and failures

generate multi-criteria selection report without automatic winner
manually freeze one configuration outside the benchmark runner
run that frozen configuration on unannotated application evidence
evaluate processing, traceability, structure, reliability and efficiency
```

Este procedimiento es secuencial. No evalúa DSG × TARGER × DSS × SPG × CPJ × todos los módulos de relaciones.

La CLI `gold-benchmark` implementa este pseudocódigo para segmentación o relaciones. Mantiene los fallos en el denominador y nunca fija un ganador. `gold-benchmark-check` valida datos, candidatos y mapeos sin llamar a los módulos. `proposition-selection` genera el informe estructural de proposicionamiento y `selection-report` reúne la evidencia multi-criterio antes de editar manualmente la configuración congelada.

## 8. Contrato de artefactos

Una etapa debe poder auditarse sin volver a consultar MCP/RAG ni repetir una etapa anterior. Por eso conserva `evidence.json`, el input xAIF enviado, la respuesta xAIF original, la representación normalizada y el manifiesto. La ejecución end-to-end copia además `argument_spans.json`, `claims.json`, `candidate_pairs.json`, `relations.json`, `xaif.json` y `provenance_map.json` cuando correspondan. Cada etapa guarda `module_runs.json` con una entrada por respuesta recibida, aunque produzca cero spans, claims o relaciones.

La evaluación vive en un paquete separado y recibe archivos gold/predichos. `evaluation/end_to_end.py` agrega métricas ya definidas; no ejecuta módulos, no elige configuraciones y no modifica las predicciones.
