# Evaluación de despliegue de módulos oAMF

Auditoría realizada el **10 de septiembre de 2026**. Se tomó como índice el catálogo oficial oAMF fijado en el commit [`8184d39`](https://github.com/arg-tech/oAMF/tree/8184d39fbf7573940925718d5ab3736f7884f0bf) y como fuente técnica cada repositorio enlazado por ese catálogo. Los estados HTTP son observaciones de esta fecha. `Operativo` significa que la ruta respondió y existe al menos una ejecución POST correcta en este proyecto; no implica que el módulo haya superado una evaluación de calidad.

No se encontró un endpoint de reemplazo para DSS, CPJ, DAMG, DRIG o DSRM en el catálogo, los repositorios ni sus workflows públicos. Sí se encontró un host actualizado para ARIR en su workflow: `amf-ari.amfws.arg.tech`. El host antiguo continúa respondiendo, pero el registro utiliza el host del workflow actual.

## Fuente, endpoint y mecanismo oficial

| Módulo | Etapa | Repositorio oficial fijado | Endpoint público observado | Estado actual | Ejecución local oficial | Docker |
| --- | --- | --- | --- | --- | --- | --- |
| DSG | Segmentación | [`default_segmenter@fd9d965`](https://github.com/arg-tech/default_segmenter/tree/fd9d9657f4820d7c6bb20a7697a61017b454e627) | `http://default-segmenter.amfws.arg.tech/segmenter-01` | Operativo, POST probado | backend `repo`; Compose `5005:5005`; ruta `segmenter-01` | Sí |
| TARGER | Segmentación | [`targer@c7a75a9`](https://github.com/arg-tech/targer/tree/c7a75a99e488e3afe459e522ad77ce56752d1503) | `http://targer.amfws.arg.tech/targer-segmenter` | Operativo, POST probado | backend `repo`; Compose `10600:6000`; ruta `targer-segmenter` | Sí |
| DSS | Segmentación | [`oamf_llm@dcdb753`](https://github.com/arg-tech/oamf_llm/tree/dcdb753ff907c403a6c79b28387c9b3ff0a09e59) | `http://amf-llm.amfws.arg.tech/segmenter`; staging equivalente | 404 en producción y staging | backend `repo`; Compose `5030:5030`; ruta `segmenter` | Sí |
| SPG | Proposicionamiento | [`proposition-unitizer@ff12ab1`](https://github.com/arg-tech/proposition-unitizer/tree/ff12ab1041ab98a49e50c11e9230a28b5a5efbe4) | `http://default-proposition-unitiser.amfws.arg.tech/propositionUnitizer-01` | Operativo, POST probado | backend `repo`; Compose `5004:5004`; ruta `propositionUnitizer-01` | Sí |
| CPJ | Proposicionamiento | `https://github.com/arg-tech/cascading_propositionaliser` | `http://cascading-propositionunitiser.amfws.arg.tech/propositionaliser-cascading` | Endpoint 404; repositorio 404 | No puede prepararse desde una fuente oficial accesible | No verificable |
| DAMG | Relaciones | `https://github.com/arg-tech/dam` | `http://dam.amfws.arg.tech/dam-03` | Endpoint 404; repositorio 404 | No puede prepararse desde una fuente oficial accesible | No verificable |
| SARIM | Relaciones | [`AMF-RP@2582534`](https://github.com/arg-tech/AMF-RP/tree/2582534f512c02a5497d924ea142d9b81e9460e4) | `http://amfws-rp.arg.tech/somaye` | Operativo, POST probado | backend `repo`; Compose `8000:5000`; ruta `somaye` | Sí |
| ARIR | Relaciones | [`AMF_ARI@68a9868`](https://github.com/arg-tech/AMF_ARI/tree/68a9868a06a469c742f577a09c08ad54a6adda88) | `http://amf-ari.amfws.arg.tech/` | Reemplazo encontrado; POST probado | backend `repo`; Compose `5001:5001`; ruta raíz | Sí |
| DRIG | Relaciones | [`dialogpt-am-vanila@42a1a99`](https://github.com/arg-tech/dialogpt-am-vanila/tree/42a1a99cc2d23bdc7830e7107ea3b6ef606f3c05) | `http://vanilla-dialogpt-am.amfws.arg.tech/caasra` | 404 | backend `repo`; Compose `5015:5015`; ruta `caasra` | Sí |
| TARGER-AM | Relaciones | [`targer@c7a75a9`](https://github.com/arg-tech/targer/tree/c7a75a99e488e3afe459e522ad77ce56752d1503) | `http://targer.amfws.arg.tech/targer-am` | Operativo; POST probado; GET no admitido | mismo backend `repo` de TARGER; ruta `targer-am` | Sí |
| DSRM | Relaciones | [`oamf_llm@dcdb753`](https://github.com/arg-tech/oamf_llm/tree/dcdb753ff907c403a6c79b28387c9b3ff0a09e59) | `http://amf-llm.amfws.arg.tech/relation_identifier`; staging equivalente | 404 en producción y staging | mismo backend `repo` de DSS; ruta `relation_identifier` | Sí |
| DTERG | Relaciones | [`bert-te@553c1c1`](https://github.com/arg-tech/bert-te/tree/553c1c1be7ac061e4916f533d46ce4d7bff18552) | `http://bert-te.amfws.arg.tech/bert-te` | Operativo; POST canónico probado | backend `repo`; Compose `5002:5002`; ruta `bert-te` | Sí |

## Recursos aproximados

Las cifras siguientes son estimaciones de planificación, no benchmarks de ARG-tech. Se derivan de Dockerfiles, dependencias, arquitectura y tamaño de los artefactos oficiales. En esta tabla, un equipo de bajos recursos significa aproximadamente 4 núcleos, 8 GB de RAM y sin GPU; servidor/cluster significa al menos 16 GB de RAM y capacidad para asignar CPU o GPU por contenedor.

| Módulo | Modelo y tamaño aproximado | RAM | CPU | GPU/VRAM | CPU-only | Equipo bajo en recursos | Servidor GPU/cluster | Recomendación experimental |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| DSG | spaCy `en_core_web_sm 3.7.1`, decenas de MB | 0,5–1 GB | 1–2 núcleos | No requerida | Sí | Alta | Alta, sobredimensionado | Local CPU, commit fijado |
| TARGER | BiLSTM-CNN-CRF, `IBM.h5` 1,23 GB | 4–8 GB | 2–4 núcleos; CPU moderada | Opcional, ~3–5 GB VRAM | Sí | Baja–media | Alta | Servidor CPU con RAM suficiente o GPU validada; público sólo para desarrollo |
| DSS | Ollama `deepseek-r1:1.5b` Q4, 1,1 GB | 4–8 GB | 4+ núcleos; lento | Opcional, ~2–4 GB VRAM | Sí | Media para pruebas pequeñas | Alta | Servidor; fijar commit y digest del modelo Ollama |
| SPG | Sin modelo ML; transformación estructural | <0,5 GB | 1 núcleo | No requerida | Sí | Alta | Alta, sobredimensionado | Local CPU |
| CPJ | Desconocido: repositorio oficial inaccesible | ND | ND | ND | ND | No evaluable | No evaluable | Excluir hasta obtener repositorio/commit oficial |
| DAMG | Desconocido: repositorio oficial inaccesible | ND | ND | ND | ND | No evaluable | No evaluable | Excluir hasta obtener repositorio/commit oficial |
| SARIM | Pipeline SVM `joblib`, 0,42 MB; scikit-learn | 0,5–1,5 GB | 1–2 núcleos | No requerida | Sí | Alta | Alta | Local CPU; evaluar aparte el comportamiento saturado observado |
| ARIR | RoBERTa-large 1,42 GB FP32; OpenVINO INT8 357 MB | 2–4 GB | 4+ núcleos; coste cuadrático por pares | La imagen oficial usa CPU/OpenVINO | Sí, explícito | Media | Alta en nodo CPU | Servidor CPU reproducible; local sólo para corpus pequeño |
| DRIG | `dialogpt-am-medium-context`, 1,42 GB FP32 | 4–8 GB | 4+ núcleos; lento | ~3–6 GB si se habilita de forma oficial | Sí, pero lento | Baja | Alta | Servidor; validar primero que la imagen oficial utiliza la GPU asignada |
| TARGER-AM | Comparte `IBM.h5` de TARGER, 1,23 GB | 4–8 GB | 2–4 núcleos | Opcional, ~3–5 GB VRAM | Sí | Baja–media | Alta | Compartir despliegue con TARGER en servidor |
| DSRM | Ollama `deepseek-r1:1.5b` Q4, 1,1 GB; una inferencia por par | 4–8 GB | 4+ núcleos; muy lento con muchos pares | Opcional, ~2–4 GB VRAM | Sí | Baja | Alta | Servidor GPU o CPU potente; limitar y registrar pares candidatos |
| DTERG | BART-large-MNLI 0,4B; FP32 1,63 GB; OpenVINO INT8 410 MB | 2–4 GB | 4+ núcleos; OpenVINO | La imagen oficial usa CPU/OpenVINO | Sí, explícito | Media | Alta en nodo CPU | Servidor CPU reproducible; endpoint público válido para desarrollo |

Tamaños comprobados en los artefactos publicados: [`deepseek-r1:1.5b`](https://ollama.com/library/deepseek-r1:1.5b) ocupa 1,1 GB en Q4; [`facebook/bart-large-mnli`](https://huggingface.co/facebook/bart-large-mnli) declara 0,4B parámetros; los repositorios de modelos de ARG-tech contienen aproximadamente 357 MB para ARIR INT8 y 410 MB para DTERG INT8. TARGER publica un `IBM.h5` de 1.227.276.896 bytes y DRIG un `model.safetensors` de 1.419.339.344 bytes.

El registro `repo` fija también las revisiones de Hugging Face: TARGER `17843ac`, ARIR `009051a`, DRIG `5ee0474` y DTERG [`d581bac`](https://huggingface.co/arg-tech/bert-te-quantitized-model/commit/d581bac33ee1e96eff65de4509cadd2d703ffee2). Los repositorios oficiales de DSS/DSRM solicitan la etiqueta Ollama `deepseek-r1:1.5b`; como no fijan un digest, el plan la marca `resolve_and_lock_at_deployment` y exige registrar el digest efectivo antes del experimento.

## Resultado específico de DTERG

La primera llamada de DTERG falló porque nuestro adaptador construía un xAIF mínimo con nodos I aislados. El ejemplo oficial de `bert-te` contiene anclajes `L → YA → I`. El constructor ahora reproduce esa estructura. La prueba remota con dos claims terminó correctamente en un intento y generó un xAIF válido con cero relaciones: [manifest del probe](../outputs/402_183/argument_mining/dterg_contract_probe_v3/manifest.json). Su input conserva seis nodos de tipos L, YA e I y cuatro aristas de anclaje. Cero relaciones es una predicción válida; ya no es un error de contrato o de servicio.

## Selección de backend sin cambiar el pipeline

El pipeline siempre consume un endpoint HTTP xAIF. El lugar donde vive ese endpoint queda en el registro:

- [`oamf_public_modules.yaml`](../configs/oamf_public_modules.yaml): servicios `ws`, incluido el reemplazo de ARIR y el estado observado.
- [`oamf_local_repo_modules.yaml`](../configs/oamf_local_repo_modules.yaml): endpoints localhost esperados después de desplegar los repositorios oficiales fijados.
- Para un servidor, se usa el registro `repo` y se sustituye `endpoint` por la URL del nodo. El manifest conserva `backend_type=repo`, repositorio, commit, ruta, modelo y endpoint efectivo.

Ejemplo de ejecución contra un repositorio desplegado localmente:

```powershell
.\.venv\Scripts\python.exe -X utf8 -m argument_mining relations `
  --registry configs/oamf_local_repo_modules.yaml `
  --evidence outputs/402_183/evidence.json `
  --claims path/claims.json `
  --input-kind predicted `
  --module ARIR `
  --experiment-id arir_repo_locked_001 `
  --output path/arir_repo_locked_001
```

Para un despliegue en cluster sólo cambia el endpoint:

```powershell
  --endpoint http://oamf-cpu-node.internal:5001/ `
  --backend-type repo `
  --backend-id official_repo_cluster
```

oAMF representa un módulo como `(repository_url, "repo", route, tag)` y usa el `Dockerfile`/`docker-compose.yml` del repositorio. Su implementación actual clona la rama por defecto sin aceptar un commit en esa tupla. Para un experimento reproducible debe prepararse previamente `modules/<repo>` en detached HEAD sobre el SHA registrado; oAMF detecta el directorio existente, conserva ese checkout y construye el contenedor. No se ha ejecutado ese despliegue en este equipo.

El artefacto [`oamf_repo_plan.lock.json`](../configs/oamf_repo_plan.lock.json) contiene esas tuplas, directorios de checkout, commits, modelos y revisiones. Declara `deployment_executor: oamf.oAMF.load_modules` y `deploy_executed: false`. Docker tampoco está instalado actualmente en este equipo, por lo que la preparación no supone que el portátil pueda alojar los candidatos pesados.

## Decisión propuesta antes de desplegar

1. Ejecutar localmente DSG, SPG y SARIM en un nodo CPU ligero.
2. Ejecutar ARIR y DTERG INT8 en un servidor CPU con al menos 16 GB de RAM para absorber concurrencia y el crecimiento cuadrático de pares.
3. Alojar TARGER/TARGER-AM en un servidor separado con 8 GB de RAM como mínimo.
4. Alojar DSS/DSRM en servidor; preferir GPU si el número de pares es elevado.
5. Mantener DRIG fuera del portátil y validarlo en servidor antes de incluirlo en el protocolo.
6. Marcar CPJ y DAMG como candidatos bloqueados hasta que ARG-tech proporcione una fuente oficial accesible y versionable.

Estas decisiones son de despliegue. La selección científica de módulos continúa separada y requiere evaluación con gold.
