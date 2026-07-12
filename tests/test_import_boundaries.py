import ast
from pathlib import Path


SRC_ROOT = Path(__file__).parents[1] / "src"
LEGACY_MODULES = {
    "src.briefing_generation",
    "src.briefing_selection",
    "src.occurrences",
    "src.replay",
    "src.story_matching",
    "src.top10",
    "src.tracker_store",
}
SUPPORTED_CROSS_DOMAIN_MODULES = {
    "src.briefing.selection",
    "src.tracker.occurrences",
    "src.tracker.replay",
}
DOMAIN_ROOTS = {"briefing", "claims", "observability", "tracker"}


def _module_name(path):
    relative = path.relative_to(SRC_ROOT.parent).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _available_modules():
    return {_module_name(path) for path in SRC_ROOT.rglob("*.py")}


def _imported_modules(tree, available):
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
            for alias in node.names:
                candidate = f"{node.module}.{alias.name}"
                if candidate in available:
                    imported.add(candidate)
    return imported


def _domain(module):
    parts = module.split(".")
    if len(parts) >= 2 and parts[0] == "src" and parts[1] in DOMAIN_ROOTS:
        return parts[1]
    return None


def test_production_imports_use_domain_package_paths():
    available = _available_modules()
    violations = []

    for path in SRC_ROOT.rglob("*.py"):
        source_module = _module_name(path)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for imported in _imported_modules(tree, available):
            if imported in LEGACY_MODULES:
                violations.append(f"{source_module} imports removed {imported}")
                continue

            source_domain = _domain(source_module)
            target_domain = _domain(imported)
            is_internal_target = imported.count(".") >= 2
            if (
                target_domain
                and target_domain != source_domain
                and is_internal_target
                and imported not in SUPPORTED_CROSS_DOMAIN_MODULES
            ):
                violations.append(f"{source_module} imports internal {imported}")

    assert violations == []


def test_legacy_bridge_modules_are_removed():
    available = _available_modules()
    assert LEGACY_MODULES.isdisjoint(available)
