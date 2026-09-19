# Capa de construcción de argumentos

Esta implementación comienza en un array `evidence.json` producido por los agentes MCP/RAG y termina en un grafo xAIF trazable. La recuperación, la decisión clínica y el razonamiento AF/QBAF están fuera de este componente.

## Diseño experimental

Las etapas se ejecutan y evalúan de forma independiente:

1. `segment`: evidencia cruda → spans argumentativos y nodos L.
2. `propositions`: spans gold o predichos → proposiciones y nodos I.
3. `relations`: proposiciones gold o predichas → relaciones RA/CA/MA.
4. `export`: claims y relaciones → xAIF y mapa de procedencia.
5. `run`: ejecución end-to-end con una selección declarada por etapa.

El registro [oamf_public_modules.yaml](../configs/oamf_public_modules.yaml) incluye estas alternativas:

| Etapa | Alternativas |
| --- | --- |
| Segmentación | DSG, TARGER, DSS |
| Proposicionamiento | SPG, CPJ |
| Relaciones | DAMG, SARIM, ARIR, DRIG, TARGER-AM, DSRM, DTERG |

No existe un comando que construya una cuadrícula cartesiana. Cada ejecución nombra explícitamente un módulo o una configuración completa. La selección científica debe hacerse por etapas: comparar segmentadores contra spans gold, congelar la decisión, comparar proposicionadores primero sobre spans gold y comparar relaciones primero sobre proposiciones gold. El archivo [argument_smoke_config.yaml](../examples/argument_smoke_config.yaml) sólo sirve para comprobar integración; no representa una configuración seleccionada.

La estructura del proyecto, las interfaces Python, contratos completos, reglas de IDs, YAML, errores y pseudocódigo están fijados en la [especificación técnica](argument-mining-technical-spec.md).

## Protocolo experimental sin anotadores propios

Los datos se clasifican siempre como `gold`, `silver` o `unannotated`. GOLD significa anotación humana externa; en esta implementación procede de AbstRCT. SILVER queda reservado para referencias débiles y nunca se mezcla con GOLD. La evidencia MCP/RAG de CasiMedicos es UNANNOTATED: sobre ella se miden proceso, trazabilidad, estructura, fallos y coste, pero no accuracy, precision, recall ni F1.

El adaptador fija el repositorio oficial de AbstRCT en el commit `f856f1ca7514caa4094194b5623e84c159d9bf1d`, copia los `.txt`/`.ann`, conserva sus hashes e IDs BRAT y genera `evidence.json`, `gold_spans.json`, `argument_units.json`, `gold_relations.json`, `unmapped_relations.json`, `mapping.json` y un manifiesto. `ArgumentUnit` representa el componente extractivo; no es un claim normalizado. `Partial-Attack` queda sin mapear en la tarea binaria Support/Attack.

```powershell
.\.venv\Scripts\python.exe -X utf8 -m argument_mining adapt-abstrct `
  --source data/external/abstrct/AbstRCT_corpus/data `
  --split dev --subset neoplasm_dev `
  --output data/processed/abstrct/dev_neoplasm
```

El protocolo [abstrct_gold_benchmark.yaml](../examples/abstrct_gold_benchmark.yaml) compara una etapa cada vez. `gold-benchmark-check` no ejecuta inferencia. `gold-benchmark` continúa tras fallos por documento, los mantiene en el denominador y produce CSV, métricas JSON, errores, respuestas originales y manifiestos por candidato.

```powershell
.\.venv\Scripts\python.exe -X utf8 -m argument_mining gold-benchmark-check `
  --config examples/abstrct_gold_benchmark.yaml `
  --output outputs/argument_mining_experiment/gold_benchmark_readiness.json

.\.venv\Scripts\python.exe -X utf8 -m argument_mining gold-benchmark `
  --config examples/abstrct_gold_benchmark.yaml `
  --stage segmentation `
  --output outputs/argument_mining_experiment/segmentation_dev_v1
```

Segmentación informa PRF exacto y por solapamiento, sobresegmentación, subsegmentación, fallos y latencia. Relaciones usa los mismos extremos extractivos anotados por AbstRCT y sólo mapea RA/CA cuando el YAML declara su semántica y justificación; informa PRF de Support/Attack, macro-F1, matriz de confusión, exactitud de aristas dirigidas, fallos y latencia.

El macro-F1 principal de relaciones promedia exclusivamente Support y Attack. La clase `none` se deriva de los pares candidatos sin relación humana y se informa aparte. Los pares anotados `Partial-Attack` se excluyen mediante `unmapped_relations.json`; no se convierten en negativos. Se conserva la dirección original de las aristas. Las salidas por documento usan nombres hash compatibles con Windows; `artifact_index.json` enlaza cada nombre con el `evidence_id` original.

La ejecución exploratoria del 19 de septiembre de 2026 utiliza los servicios públicos y está documentada en [el informe de resultados](../outputs/argument_mining_experiment/abstrct_dev_summary_20260919/report.md), con [tabla de segmentación](../outputs/argument_mining_experiment/abstrct_dev_summary_20260919/segmentation_benchmark.csv) y [tabla de relaciones](../outputs/argument_mining_experiment/abstrct_dev_summary_20260919/relation_benchmark.csv). Los directorios `abstrct_dev_segmentation_20260919` y `abstrct_dev_relations_20260919` conservan las entradas, respuestas y manifiestos por módulo. Es una comparación sobre desarrollo; el estado de la configuración final sigue siendo `not_frozen`.

AbstRCT no aporta proposiciones normalizadas humanas. Por ello SPG se documenta como baseline estructural y CPJ como alternativa, sin fabricar `gold_claims` ni declarar un ganador empírico. El informe se genera con `proposition-selection`.

La infraestructura no selecciona automáticamente un módulo. `selection-report` reúne rendimiento GOLD, disponibilidad, reproducibilidad, xAIF, procedencia, recursos y fallos. La decisión se registra después, manualmente, en [selected_oamf_configuration.yaml](../configs/selected_oamf_configuration.yaml), que inicialmente tiene `status: not_frozen`. Los datos CasiMedicos no se usan para ajustar esa decisión.

```powershell
.\.venv\Scripts\python.exe -X utf8 -m argument_mining audit-modules `
  --output outputs/argument_mining_experiment/module_availability.csv

.\.venv\Scripts\python.exe -X utf8 -m argument_mining proposition-selection `
  --config examples/abstrct_gold_benchmark.yaml `
  --output outputs/argument_mining_experiment/propositionalisation_selection.json

.\.venv\Scripts\python.exe -X utf8 -m argument_mining selection-report `
  --availability outputs/argument_mining_experiment/module_availability.csv `
  --segmentation-results path/segmentation/results.json `
  --relation-results path/relations/results.json `
  --propositionalisation outputs/argument_mining_experiment/propositionalisation_selection.json `
  --output outputs/argument_mining_experiment/selection_report.json
```

Una vez revisado el informe se completan los tres `StageSelection` y se cambia `status` a `frozen`. `run-frozen` rechaza una configuración incompleta, no congelada o que declare ajuste sobre los datos de aplicación. Después, `evaluate-application` genera `application_processing_results.csv`, `traceability_results.csv`, `graph_statistics.csv` y `error_analysis.json` sin métricas de exactitud.

```powershell
.\.venv\Scripts\python.exe -X utf8 -m argument_mining run-frozen `
  --evidence outputs/402_183/evidence.json `
  --config configs/selected_oamf_configuration.yaml `
  --experiment-id casimedicos_402_183_frozen_v1 `
  --output outputs/402_183/argument_mining/frozen_v1

.\.venv\Scripts\python.exe -X utf8 -m argument_mining evaluate-application `
  --run outputs/402_183/argument_mining/frozen_v1 `
  --output outputs/402_183/argument_mining/frozen_v1_evaluation
```

## Entrada y trazabilidad

La capa valida como mínimo `evidence_id` y `passage_text`, acepta campos adicionales y copia el objeto original completo a cada experimento. Nunca recalcula `evidence_id`.

Cada claim contiene:

- `claim_id`, estable para la combinación evidencia/span/texto proposicional;
- `evidence_id` y `span_id`;
- offsets `start_char`/`end_char` y el texto exacto del span;
- el `passage_text` original;
- datos del documento, DOI/PMID/PMCID y fuente cuando existan;
- la lista original de procedencia de recuperación;
- las valoraciones upstream separadas de la confianza de minería;
- módulo, versión, modelo, endpoint, configuración, experimento, tiempos y hashes de entrada/respuesta.

Antes de aceptar un claim se comprueba que `passage_text[start_char:end_char]` coincide exactamente con el span guardado. Los nodos I sin un nodo L de entrada trazable se rechazan. Una relación conserva source/target explícitos y sólo se acepta si ambos claims existen.

## Comandos

Listar las alternativas:

```powershell
.\.venv\Scripts\python.exe -X utf8 -m argument_mining list-modules
```

Segmentación desde evidencia cruda:

```powershell
.\.venv\Scripts\python.exe -X utf8 -m argument_mining segment `
  --evidence outputs/402_183/evidence.json `
  --module TARGER `
  --experiment-id exp_seg_targer_001 `
  --dataset-version corpus_v1 `
  --output outputs/402_183/argument_mining/exp_seg_targer_001
```

Proposicionamiento desde spans gold:

```powershell
.\.venv\Scripts\python.exe -X utf8 -m argument_mining propositions `
  --evidence outputs/402_183/evidence.json `
  --spans annotations/gold_spans.json `
  --input-kind gold `
  --gold-version gold_v1 `
  --module CPJ `
  --experiment-id exp_prop_cpj_gold_001 `
  --output outputs/402_183/argument_mining/exp_prop_cpj_gold_001
```

Para spans predichos se usa el mismo comando con `--input-kind predicted` y el `argument_spans.json` de una ejecución de segmentación.

Relaciones desde proposiciones gold:

```powershell
.\.venv\Scripts\python.exe -X utf8 -m argument_mining relations `
  --evidence outputs/402_183/evidence.json `
  --claims annotations/gold_claims.json `
  --input-kind gold `
  --gold-version gold_v1 `
  --module ARIR `
  --pair-strategy within_passage `
  --experiment-id exp_rel_arir_gold_001 `
  --output outputs/402_183/argument_mining/exp_rel_arir_gold_001
```

`--pair-strategy` acepta `within_passage`, `within_document` o `all`. La estrategia y su versión quedan en el manifiesto, y `candidate_pairs.json` conserva todos los pares dirigidos presentados al grupo de inferencia.

El xAIF enviado a los identificadores de relaciones conserva la salida canónica del proposicionador: por cada claim incluye una cadena `L → YA → I`. Algunos servicios aceptan sólo nodos I, pero DTERG necesita los anclajes L/YA documentados en su contrato. El parser sigue vinculando los nodos I devueltos con los `claim_id` y `evidence_id` originales.

Exportación independiente, sin volver a inferir:

```powershell
.\.venv\Scripts\python.exe -X utf8 -m argument_mining export `
  --evidence outputs/402_183/evidence.json `
  --claims path/claims.json `
  --relations path/relations.json `
  --experiment-id exp_export_001 `
  --output outputs/402_183/argument_mining/exp_export_001
```

Ejecución completa declarada:

```powershell
.\.venv\Scripts\python.exe -X utf8 -m argument_mining run `
  --evidence outputs/402_183/evidence.json `
  --config examples/argument_smoke_config.yaml `
  --output outputs/402_183/argument_mining/smoke_full
```

Cada selección admite `endpoint`, `backend_type`, `backend_id`, `route`, `repository`, `repository_commit`, `version`, `model`, `model_revision` y `config`. En los comandos de una etapa pueden sustituirse con los argumentos homónimos. Esto permite cambiar un servicio público por localhost o por un servidor sin cambiar el pipeline. Los servicios oAMF exponen un contrato multipart con el xAIF en el campo `file`; su configuración interna no siempre es parametrizable. En ese caso `config` documenta el experimento y cualquier cambio real requiere un endpoint del módulo que lo implemente.

## Salidas

Cada experimento crea, según su etapa:

| Archivo | Contenido |
| --- | --- |
| `evidence.json` | copia íntegra de la evidencia upstream |
| `argument_spans.json` | spans tipados, offsets y módulo de segmentación |
| `l_nodes.json` | vista explícita de nodos L |
| `claims.json` | proposiciones con la cadena completa de procedencia |
| `i_nodes.json` | vista explícita de nodos I |
| `candidate_pairs.json` | pares dirigidos considerados por la agrupación |
| `relations.json` | support/attack/rephrase y RA/CA/MA |
| `xaif.json` | grafo xAIF interoperable con `oamfTrace` |
| `provenance_map.json` | sidecar claim → span → evidencia → documento/recuperación |
| `manifest.json` | módulos, versiones, modelos, configuración, experimento y estado |
| `module_runs.json` | una entrada por respuesta recibida, incluso cuando no genera elementos |
| `<stage>/inputs/*.json` | xAIF exacto enviado al módulo |
| `<stage>/raw/*.json` | respuesta original del servicio oAMF |

Las respuestas originales se conservan antes de normalizar los resultados. Los hashes SHA-256 del input y la respuesta permiten comprobar qué llamada produjo cada elemento.

## Evaluación separada

La evaluación no llama a oAMF:

```powershell
.\.venv\Scripts\python.exe -X utf8 -m argument_mining evaluate `
  --stage segmentation `
  --predicted path/predicted_spans.json `
  --gold path/gold_spans.json `
  --output path/segmentation_metrics.json
```

Para evaluar una ejecución completa, `--predicted` y `--gold` señalan directorios que contienen `argument_spans.json`, `claims.json` y `relations.json`:

```powershell
.\.venv\Scripts\python.exe -X utf8 -m argument_mining evaluate `
  --stage end_to_end `
  --predicted outputs/402_183/argument_mining/pipeline_selected `
  --gold annotations/gold_v1 `
  --output outputs/402_183/argument_mining/pipeline_selected/metrics.json
```

La segmentación calcula span exacto y solapamiento; proposicionamiento calcula coincidencia exacta ligada al span y completitud de trazabilidad; relaciones calcula Macro-F1 y métricas por clase sobre aristas dirigidas. En relaciones, `--candidate-pairs path/candidate_pairs.json` permite derivar como `none` los pares candidatos sin arista positiva; el gold puede contener etiquetas `none` con `xaif_relation_type: null`. Fidelidad, atomicidad, autosuficiencia, modalidad, negación y contenido no sustentado quedan marcados para revisión/anotación experta: una similitud textual no los sustituye.

Sin gold se puede generar una comparación descriptiva de ejecuciones ya realizadas:

```powershell
.\.venv\Scripts\python.exe -X utf8 -m argument_mining describe `
  --runs path/seg_dsg path/seg_targer path/rel_arir `
  --output path/module_comparison
```

Este comando informa de disponibilidad, cobertura, número de elementos, densidad de relaciones, trazabilidad y tiempo observado. También detecta patrones estructurales como un grafo vacío o una relación para cada par. Genera `summary.json` y `report.md`, pero marca explícitamente que estas cifras no seleccionan el mejor módulo sin gold.

## Servicios públicos y reproducibilidad

Al usar el [registro público](../configs/oamf_public_modules.yaml), `passage_text` se envía a servicios alojados por ARG-tech. El manifiesto registra backend y endpoint. Cuando el servicio no informa versión o modelo, se guarda explícitamente `public-service-unreported`; un commit del repositorio sólo documenta el código oficial inspeccionado y no se presenta como versión garantizada del despliegue remoto.

El [registro repo](../configs/oamf_local_repo_modules.yaml) contiene los endpoints esperados y commits oficiales fijados. Puede generarse un artefacto revisable antes de cualquier despliegue:

```powershell
.\.venv\Scripts\python.exe -X utf8 -m argument_mining repo-plan `
  --registry configs/oamf_local_repo_modules.yaml `
  --output configs/oamf_repo_plan.lock.json
```

El comando sólo crea el plan: `deploy_executed` queda en `false`; no clona repositorios, descarga modelos ni inicia Docker. La [evaluación de despliegue](oamf-deployment-assessment.md) contiene el estado observado de cada endpoint y las estimaciones de recursos. Para un servidor, se usa el registro `repo` y se sustituye `endpoint`; el manifest sigue registrando el repositorio y SHA responsables de la salida.

La configuración [argument_repo_config.yaml](../examples/argument_repo_config.yaml) muestra una ejecución completa contra esos endpoints `repo`. Debe usarse después de desplegar los commits del lock:

```powershell
.\.venv\Scripts\python.exe -X utf8 -m argument_mining run `
  --registry configs/oamf_local_repo_modules.yaml `
  --evidence outputs/402_183/evidence.json `
  --config examples/argument_repo_config.yaml `
  --output outputs/402_183/argument_mining/repo_candidate_001
```

Los fallos se clasifican como `provenance`, `segmentation`, `proposition`, `relation` o `serialization` en el manifiesto. Un experimento fallido conserva los inputs y respuestas que llegaron a escribirse.
Las llamadas con errores de transporte o respuestas HTTP 5xx se reintentan hasta tres veces; los HTTP 4xx no se reintentan. `module_runs.json` registra cuántos intentos necesitó cada respuesta aceptada.
