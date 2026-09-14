"""Architecture boundaries that must remain true as the MVP packages appear."""

from __future__ import annotations

import ast
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"

ACOLITE_SETTING_KEYS = (
    "inputfile",
    "output",
    "runid",
    "limit",
    "merge_tiles",
    "extract_inputfile",
    "s2_target_res",
    "l2w_parameters",
    "output_rhorc",
    "delete_extracted_input",
    "rgb_rhot",
    "rgb_rhos",
    "l2w_mask_threshold",
    "dsf_aot_estimate",
    "ancillary_type",
    "l1r_delete_netcdf",
    "netcdf_compression",
)
ACOLITE_SETTING_PATTERN = re.compile(
    rf"\b(?:{'|'.join(ACOLITE_SETTING_KEYS)})\s*=",
)
ACOLITE_SKIP_MESSAGE_FRAGMENTS = (
    "Processing of",
    "not supported",
    "File not recognised",
    "Multi granule files are no longer supported",
    "No footprint files found",
    "Longitude/Latitude limits outside",
    "Time difference too large",
    "Sensors do not match",
)
ACOLITE_VARIABLE_PATTERN = re.compile(r"\b(rhow|Rrs|rhos|rhot|rhorc)_\d{3,4}\b")


def _source_files() -> list[Path]:
    return sorted(SOURCE_ROOT.glob("oceanos/**/*.py"))


def _module_name(path: Path) -> str:
    parts = path.relative_to(SOURCE_ROOT).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _is_module_in_package(module_name: str, package: str) -> bool:
    return module_name == package or module_name.startswith(f"{package}.")


def _package_parts(path: Path) -> tuple[str, ...]:
    parts = list(path.relative_to(SOURCE_ROOT).with_suffix("").parts)
    return tuple(parts[:-1])


def _imported_modules(node: ast.Import | ast.ImportFrom, path: Path) -> tuple[str, ...]:
    if isinstance(node, ast.Import):
        return tuple(alias.name for alias in node.names)

    package = _package_parts(path)
    if node.level:
        base = package[: len(package) - node.level + 1]
        prefix = ".".join(base)
        module = f"{prefix}.{node.module}" if prefix and node.module else node.module or prefix
    else:
        module = node.module or ""

    return (module, *(f"{module}.{alias.name}" for alias in node.names if module))


def _imports(path: Path) -> tuple[ast.Import | ast.ImportFrom, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return tuple(node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom)))


def _imports_package(path: Path, package: str) -> bool:
    return any(
        imported == package or imported.startswith(f"{package}.")
        for node in _imports(path)
        for imported in _imported_modules(node, path)
    )


def test_acolite_and_processing_do_not_import_each_other() -> None:
    violations = [
        path.relative_to(PROJECT_ROOT)
        for path in _source_files()
        if (
            _is_module_in_package(_module_name(path), "oceanos.acolite")
            and _imports_package(path, "oceanos.processing")
        )
        or (
            _is_module_in_package(_module_name(path), "oceanos.processing")
            and _imports_package(path, "oceanos.acolite")
        )
    ]

    assert not violations, f"A1 acolite/processing import violations: {violations}"


def test_api_does_not_import_writers_or_processing_stages() -> None:
    forbidden_packages = ("oceanos.pipeline", "oceanos.acolite", "oceanos.publishing", "oceanos.index.writer")
    violations: list[Path] = []
    for path in _source_files():
        if not _is_module_in_package(_module_name(path), "oceanos.api"):
            continue
        imports = _imports(path)
        imports_forbidden_package = any(
            imported == package or imported.startswith(f"{package}.")
            for node in imports
            for imported in _imported_modules(node, path)
            for package in forbidden_packages
        )
        imports_index_writer = any(
            isinstance(node, ast.ImportFrom)
            and "oceanos.index" in _imported_modules(node, path)
            and any(alias.name == "IndexWriter" for alias in node.names)
            for node in imports
        )
        if imports_forbidden_package or imports_index_writer:
            violations.append(path.relative_to(PROJECT_ROOT))

    assert not violations, f"A2 API import violations: {violations}"


def test_domain_does_not_import_other_oceanos_packages() -> None:
    violations = [
        path.relative_to(PROJECT_ROOT)
        for path in _source_files()
        if _is_module_in_package(_module_name(path), "oceanos.domain")
        and any(
            imported == "oceanos" or (
                imported.startswith("oceanos.") and not _is_module_in_package(imported, "oceanos.domain")
            )
            for node in _imports(path)
            for imported in _imported_modules(node, path)
        )
    ]

    assert not violations, f"A3 domain import violations: {violations}"


def _a4_files() -> list[Path]:
    return sorted(
        [*(PROJECT_ROOT / "src").glob("**/*.py"), *(PROJECT_ROOT / "tests").glob("**/*.py"),
         *(PROJECT_ROOT / "configs").glob("**/*.yaml")],
    )


def _a4_is_allowlisted(path: Path) -> bool:
    relative_path = path.relative_to(PROJECT_ROOT)
    return (
        path.is_relative_to(SOURCE_ROOT / "oceanos" / "acolite")
        or path.is_relative_to(PROJECT_ROOT / "tests")
        or relative_path == Path("configs/products.yaml")
    )


def _a4_string_literals(path: Path) -> tuple[tuple[int, str], ...]:
    if path.suffix == ".py":
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        return tuple(
            (node.lineno, node.value)
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        )
    return tuple((line_number, line) for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1))


def test_only_acolite_uses_acolite_vocabulary() -> None:
    violations: list[str] = []
    for path in _a4_files():
        if _a4_is_allowlisted(path):
            continue
        relative_path = path.relative_to(PROJECT_ROOT)
        for line_number, value in _a4_string_literals(path):
            if value == "l2_flags":
                continue
            if (
                ACOLITE_SETTING_PATTERN.search(value)
                or any(fragment in value for fragment in ACOLITE_SKIP_MESSAGE_FRAGMENTS)
                or ACOLITE_VARIABLE_PATTERN.search(value)
            ):
                violations.append(f"{relative_path}:{line_number}: {value!r}")

    assert not violations, "A4 ACOLITE vocabulary violations:\n" + "\n".join(violations)
