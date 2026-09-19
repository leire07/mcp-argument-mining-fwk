from __future__ import annotations

from collections import defaultdict

from .errors import SerializationError
from .registry import ModuleRegistry


OAMF_REPOSITORY = "https://github.com/arg-tech/oAMF"
OAMF_COMMIT = "8184d39fbf7573940925718d5ab3736f7884f0bf"
OAMF_VERSION = "1.0.1.0"


def build_repo_plan(registry: ModuleRegistry, module_ids: list[str] | None = None) -> dict:
    """Build a locked oAMF repo plan without cloning, building or starting containers."""
    wanted = {value.upper() for value in module_ids} if module_ids else None
    specs = [spec for spec in registry.all_specs()
             if spec.backend_type == "repo" and (wanted is None or spec.module_id.upper() in wanted)]
    if wanted:
        found = {spec.module_id.upper() for spec in specs}
        missing = sorted(wanted - found)
        if missing:
            raise SerializationError(f"Módulos sin backend repo disponible: {', '.join(missing)}")
    checkouts = defaultdict(lambda: {"modules": [], "routes": []})
    modules = []
    for spec in specs:
        if not spec.repository or not spec.repository_commit or spec.route is None:
            raise SerializationError(f"Backend repo incompleto para {spec.module_id}")
        key = (spec.repository, spec.repository_commit)
        repository_name = spec.repository.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")
        checkouts[key]["checkout_directory"] = f"modules/{repository_name}"
        checkouts[key]["modules"].append(spec.module_id)
        checkouts[key]["routes"].append(spec.route)
        modules.append({
            "module_id": spec.module_id,
            "stage": spec.stage,
            "oamf_tuple": [spec.repository, "repo", spec.route, spec.module_id.lower()],
            "expected_endpoint": spec.endpoint,
            "backend_id": spec.backend_id,
            "repository_commit": spec.repository_commit,
            "model": spec.model,
            "model_revision": spec.model_revision,
            "config": spec.config,
        })
    return {
        "schema_version": "1.0",
        "action": "plan_only",
        "deploy_executed": False,
        "requires_docker": True,
        "deployment_executor": "oamf.oAMF.load_modules",
        "checkout_mode": "detached_commit_before_load_modules",
        "oamf": {"repository": OAMF_REPOSITORY, "commit": OAMF_COMMIT,
                 "package_version": OAMF_VERSION},
        "locked_checkouts": [
            {"repository": repository, "commit": commit,
             "checkout_directory": value["checkout_directory"],
             "modules": sorted(value["modules"]), "routes": sorted(set(value["routes"]))}
            for (repository, commit), value in sorted(checkouts.items())
        ],
        "modules": sorted(modules, key=lambda item: (item["stage"], item["module_id"])),
    }
