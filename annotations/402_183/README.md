# Posibles anotaciones futuras para CasiMedicos 402_183

Actualmente CasiMedicos se clasifica como `unannotated` y no se usa para seleccionar módulos ni calcular accuracy/F1. Si en el futuro se realiza una anotación humana independiente y adjudicada, este directorio podrá contener:

- `gold_spans.json`: array compatible con `ArgumentSpan`, con `input_kind: "gold"`;
- `gold_claims.json`: array compatible con `Claim`, enlazado mediante `evidence_id` y `span_id`;
- `gold_relations.json`: array compatible con `ArgumentRelation`, incluidas las clases `support`, `attack`, `rephrase` o `none`.

No se copian predicciones de DSG, TARGER, SPG u otros módulos para construir el gold, porque eso sesgaría la comparación. Los archivos deben pasar adjudicación experta y declarar una versión antes de ejecutar el benchmark.

La evaluación GOLD actual usa AbstRCT mediante `examples/abstrct_gold_benchmark.yaml`. No deben copiarse sus componentes a este caso ni presentarse predicciones automáticas como gold.
