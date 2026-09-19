from __future__ import annotations

import csv
from pathlib import Path

from ..registry import ModuleRegistry
from .config import load_mapping


def export_module_availability(public_registry: Path, repo_registry: Path,
                               resources_config: Path, output: Path) -> list[dict]:
    public, local = ModuleRegistry(public_registry), ModuleRegistry(repo_registry)
    resources = load_mapping(resources_config)["modules"]
    rows = []
    module_ids = sorted({spec.module_id for spec in public.all_specs()} | set(resources))
    for module_id in module_ids:
        public_spec = public.modules.get(module_id.upper())
        repo_spec = local.modules.get(module_id.upper())
        resource = resources.get(module_id, {})
        spec = repo_spec or public_spec
        rows.append({
            "module": module_id, "stage": spec.stage if spec else "unknown",
            "official_repository": (spec.repository if spec else None),
            "repository_commit": (spec.repository_commit if spec else None),
            "public_endpoint": public_spec.endpoint if public_spec else None,
            "public_endpoint_status": public_spec.endpoint_status if public_spec else "unregistered",
            "local_endpoint_template": repo_spec.endpoint if repo_spec else None,
            "local_mechanism": resource.get("local_mechanism"), "docker": resource.get("docker"),
            "dependencies": f"official repository/container; {resource.get('model_size', 'unreported')}",
            "xaif_compatible": bool(spec),
            "operational_status": public_spec.endpoint_status if public_spec else "unregistered",
            "ram": resource.get("ram"), "cpu": resource.get("cpu"),
            "gpu_vram": resource.get("gpu_vram"), "model": spec.model if spec else None,
            "model_revision": spec.model_revision if spec else None,
            "model_size": resource.get("model_size"), "cpu_only": resource.get("cpu_only"),
            "low_resource_viability": resource.get("low_resource"),
            "cluster_viability": resource.get("cluster"),
            "deployment_recommendation": resource.get("recommendation"),
            "recommended_experimental_use": resource.get("recommendation"),
        })
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return rows
