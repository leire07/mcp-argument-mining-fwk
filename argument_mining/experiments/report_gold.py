"""Summarise completed benchmark artifacts without repeating remote inference."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from collections import Counter
from pathlib import Path

from ..pipeline import write_json
from .selection_report import build_selection_report


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def summarise(segmentation: Path, relations: Path, output: Path, overwrite: bool = False):
    output.mkdir(parents=True, exist_ok=overwrite)
    seg, rel = read(segmentation / 'results.json'), read(relations / 'results.json')
    base = output.parent
    build_selection_report(
        output / 'selection_report.json', base / 'module_availability.csv',
        segmentation / 'results.json', relations / 'results.json',
        base / 'propositionalisation_selection.json')
    gold_relations = read(relations / 'gold_relations.json')
    evidence_count = len(read(segmentation / 'evidence.json'))
    gold_span_count = len(read(segmentation / 'gold_spans.json'))
    excluded_count = len(read(relations / 'excluded_pairs.json'))
    pairs = read(relations / 'candidate_pairs.json')
    gold_distribution = Counter(r['relation'] for r in gold_relations)
    no_relation_accuracy = (len(pairs) - len(gold_relations)) / len(pairs)
    provisional_reading = {
        'segmentation': {
            'candidate': 'DSG',
            'status': 'provisional_development_candidate',
            'reason': 'Higher exact-span F1 and lower observed latency; TARGER is higher only on relaxed overlap F1.',
        },
        'propositionalisation': {
            'candidate': 'SPG',
            'status': 'structural_baseline_only',
            'reason': 'Operational and traceable; no compatible human-normalised gold exists for an empirical ranking.',
        },
        'relation_identification': {
            'candidate': 'SARIM',
            'status': 'provisional_baseline_not_ready_to_freeze',
            'reason': 'Highest Support/Attack macro-F1, but very low precision and only one correct Attack prediction.',
        },
        'configuration_frozen': False,
        'required_before_freezing': [
            'Repeat shortlisted modules from pinned official deployments.',
            'Resolve the relation-stage suitability and sparse Attack reference limitation.',
            'Evaluate the frozen choice once on a held-out AbstRCT test split.',
        ],
    }
    lines = [
        '# Benchmark exploratorio oAMF sobre AbstRCT', '',
        f'{evidence_count} documentos de desarrollo (`dev/neoplasm_dev`); {gold_span_count} componentes humanos. '
        'Servicios públicos ARG-tech, sin congelar una configuración final.', '',
        '## Segmentación', '',
        '| Módulo | Precisión exacta | Recall exacto | F1 exacto | F1 solapamiento | Fallos | Tiempo total |',
        '| --- | ---: | ---: | ---: | ---: | ---: | ---: |',
    ]
    for row in seg['rows']:
        lines.append(f"| {row['module']} | {row['exact_precision']:.1%} | {row['exact_recall']:.1%} | "
                     f"{row['exact_f1']:.1%} | {row['overlap_f1']:.1%} | {row['failures']}/{evidence_count} | "
                     f"{row['wall_seconds']:.1f} s |")
    lines += ['', '## Relaciones sobre componentes humanos', '',
              '| Módulo | F1 Support | F1 Attack | Macro-F1 Support/Attack | Exactitud de pares | Fallos | Tiempo total |',
              '| --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    for row in rel['rows']:
        lines.append(f"| {row['module']} | {row['support_f1']:.1%} | {row['attack_f1']:.1%} | "
                     f"{row['macro_f1']:.1%} | {row['directed_edge_accuracy']:.1%} | "
                     f"{row['failures']}/{evidence_count} | {row['wall_seconds']:.1f} s |")
    lines += ['', f"Se evalúan {len(pairs)} pares dirigidos: {gold_distribution['support']} Support, "
              f"{gold_distribution['attack']} Attack y {len(pairs) - len(gold_relations)} sin relación. "
              f'Los {excluded_count} pares Partial-Attack se excluyen explícitamente de la evaluación; '
              'sus anotaciones originales y las predicciones se conservan.', '',
              f"Predecir siempre «sin relación» daría {no_relation_accuracy:.1%} de exactitud "
              'y 0 % de F1 Support/Attack. Por eso la exactitud de pares no basta para elegir.', '',
              '## Comportamiento observado', '']
    details = {}
    response_audits = []
    relation_config = read(relations / 'benchmark_config.json')
    for root, result in ((segmentation, seg), (relations, rel)):
        for row in result['rows']:
            folder = root / 'modules' / row['module'].lower().replace('-', '_')
            metrics = read(folder / 'metrics.json')
            errors = read(folder / 'errors.json')
            details[row['module']] = {'metrics': metrics, 'errors': errors}
            for raw_path in sorted((folder / 'raw').glob('*.json')):
                request = read(folder / 'inputs' / raw_path.name)
                response = read(raw_path)
                aif = response.get('AIF', response.get('aif', {}))
                nodes, edges = aif.get('nodes', []), aif.get('edges', [])
                ids = [str(n.get('nodeID')) for n in nodes]
                input_i_texts = Counter(' '.join(n.get('text', '').split())
                                       for n in request['AIF']['nodes'] if n.get('type') == 'I')
                output_i_texts = Counter(' '.join(n.get('text', '').split())
                                        for n in nodes if n.get('type') == 'I')
                response_audits.append({
                    'module': row['module'], 'file': str(raw_path),
                    'duplicate_node_ids': len(ids) - len(set(ids)),
                    'dangling_edges': sum(str(e.get('fromID')) not in ids or
                                          str(e.get('toID')) not in ids for e in edges),
                    'reference_i_texts_preserved': input_i_texts == output_i_texts,
                    'node_types': dict(Counter(n.get('type') for n in nodes)),
                })
            if 'exact_span' in metrics:
                lines.append(f"- {row['module']}: {metrics['exact_span']['predicted']} segmentos; "
                             f"{metrics['exact_span']['true_positive']} coincidencias exactas; "
                             f"sobresegmentación {metrics['over_segmentation']['count']}, "
                             f"subsegmentación {metrics['under_segmentation']['count']}.")
            else:
                distribution = metrics['predicted_distribution']
                allowed = relation_config['relation_semantics'][row['module']]['xaif_to_benchmark']
                unmapped_types = Counter()
                for audit in response_audits:
                    if audit['module'] == row['module']:
                        for kind, count in audit['node_types'].items():
                            if kind in {'RA', 'CA', 'MA'} and kind not in allowed:
                                unmapped_types[kind] += count
                details[row['module']]['unmapped_relation_nodes'] = dict(unmapped_types)
                gold_keys = {(r['source_claim_id'], r['target_claim_id'], r['relation'])
                             for r in gold_relations}
                predicted = read(folder / 'relations.json')
                reverse_matches = sum((r['target_claim_id'], r['source_claim_id'], r['relation'])
                                      in gold_keys for r in predicted)
                details[row['module']]['reverse_edge_diagnostic_matches'] = reverse_matches
                lines.append(f"- {row['module']}: {distribution.get('support', 0)} Support y "
                             f"{distribution.get('attack', 0)} Attack evaluadas; "
                             f"{metrics['per_class']['support']['true_positive']} y "
                             f"{metrics['per_class']['attack']['true_positive']} correctas respectivamente. "
                             f"Coincidencias en dirección contraria: {reverse_matches} "
                             '(diagnóstico; no se invierten aristas para puntuar).')
                if unmapped_types:
                    lines.append(f"  Tipos de relación fuera del mapeo declarado: {dict(unmapped_types)}. "
                                 'Se conservan en las respuestas originales y no se fuerzan a Support/Attack.')
            if errors:
                counts = Counter(error['error_class'] for error in errors)
                lines.append(f"  Fallos registrados: {dict(counts)}. Ejemplo: {errors[0]['message']}")
    lines += ['', '## Interpretación y límites', '',
              '- Las relaciones se evalúan sobre componentes humanos idénticos. Estas cifras no son las de un pipeline completo con segmentación predicha.',
              '- Sólo hay 8 ejemplos Attack; la conclusión sobre esta clase es especialmente frágil.',
              '- DTERG se ejecutó como baseline de Support: sus CA de contradicción no se mapean a Attack sin justificación semántica. Su F1 Attack=0 refleja esta restricción del protocolo; el macro-F1 no es una comparación de su capacidad nativa de contradicción.',
              '- El solapamiento usa emparejamiento uno a uno, voraz por IoU y cualquier intersección positiva. La normalización de offsets es la del adaptador existente y conserva texto original.',
              '- Los fallos de alineación son fallos de la integración módulo/adaptador y no demuestran por sí solos que el modelo sea incorrecto.',
              '- Son resultados de desarrollo con servicios públicos. El commit del repositorio es una referencia; no se verifica que el endpoint ejecute ese commit. Hardware/modelo del servidor no publicados.',
              '- Los tiempos son tiempos observados por el cliente, incluida red. Las dos etapas se ejecutaron en procesos concurrentes, cada uno con llamadas secuenciales.',
              '- DSS, CPJ, DAMG, DRIG y DSRM no se incluyeron como operativos en la configuración de partida. Su indisponibilidad no es una puntuación de calidad.',
              '- SPG conserva el papel de baseline estructural. No existe gold normalizado compatible para compararlo cuantitativamente.',
              '- No se ha modificado selected_oamf_configuration.yaml ni usado CasiMedicos para ajustar módulos.', '']
    lines += ['## Lectura provisional', '',
              '- **Segmentación:** DSG es el candidato provisional: duplica aproximadamente el F1 exacto de TARGER y fue unas 4,4 veces más rápido. TARGER sólo queda por delante con el criterio relajado de cualquier solapamiento.',
              '- **Proposicionamiento:** SPG se mantiene como baseline estructural reproducible. No se puede declarar empíricamente superior sin proposiciones normalizadas humanas.',
              '- **Relaciones:** SARIM logra el mayor macro-F1 Support/Attack, pero predice demasiados apoyos falsos y sólo acierta 1 de 8 ataques. Sirve como baseline provisional; estos resultados no justifican todavía congelarlo como solución final.',
              '- **Próximo control:** repetir los candidatos preseleccionados desde despliegues oficiales fijados y usar una sola vez un split de test retenido después de cerrar la decisión.', '',
              'La configuración continúa deliberadamente en `status: not_frozen`.', '']
    (output / 'report.md').write_text('\n'.join(lines), encoding='utf-8')
    for source in (segmentation / 'segmentation_benchmark.csv', relations / 'relation_benchmark.csv'):
        shutil.copyfile(source, output / source.name)
    shutil.copyfile('configs/oamf_public_modules.yaml', output / 'registry_snapshot.yaml')
    hashes = {}
    for source in [*Path('argument_mining').rglob('*.py'),
                   Path('examples/abstrct_gold_benchmark.yaml'), Path('configs/oamf_public_modules.yaml')]:
        hashes[source.as_posix()] = hashlib.sha256(source.read_bytes()).hexdigest()
    write_json(output / 'source_hashes.json', hashes)
    write_json(output / 'analysis.json', {
        'evaluation_reference': 'gold', 'modules': details,
        'no_relation_baseline': {'directed_edge_accuracy': no_relation_accuracy,
                                 'support_attack_macro_f1': 0.0},
        'provisional_reading': provisional_reading,
        'selected_configuration': None,
    })
    selection_path = output / 'selection_report.json'
    selection_report = read(selection_path)
    selection_report['provisional_reading'] = provisional_reading
    write_json(selection_path, selection_report)
    write_json(output / 'response_audit.json', response_audits)
    print(output / 'report.md')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--segmentation', type=Path, required=True)
    parser.add_argument('--relations', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--overwrite', action='store_true', help='Regenerate only the summary artifacts')
    args = parser.parse_args()
    summarise(args.segmentation, args.relations, args.output, args.overwrite)
