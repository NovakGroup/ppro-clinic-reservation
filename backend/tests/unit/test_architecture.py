"""Hlídá třívrstvou architekturu: závislosti vedou jen jedním směrem.

api (prezentace) → services (aplikační logika) → repositories / db (data)
domain (čistá pravidla) nesmí záviset na ničem z toho.
"""
import ast
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[2] / "app"


def imports_of(package: str) -> dict[str, set[str]]:
    result = {}
    for path in (APP / package).rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module)
            elif isinstance(node, ast.Import):
                names.update(a.name for a in node.names)
        result[str(path.relative_to(APP))] = names
    return result


FORBIDDEN = {
    "api": ("app.repositories", "app.db", "sqlalchemy"),
    "services": ("app.api", "app.repositories", "fastapi", "sqlalchemy"),
    "repositories": ("app.api", "app.services", "fastapi"),
    "domain": ("app.api", "app.services", "app.repositories", "app.db", "fastapi", "sqlalchemy"),
}


@pytest.mark.parametrize("layer", FORBIDDEN)
def test_vrstva_nezavisi_na_zakazanych_modulech(layer):
    violations = [
        f"{file}: {name}"
        for file, names in imports_of(layer).items()
        for name in names
        if any(name == f or name.startswith(f + ".") for f in FORBIDDEN[layer])
    ]
    assert not violations, "Porušení vrstev:\n" + "\n".join(violations)


def test_v_prezentacni_vrstve_neni_sql():
    for path in (APP / "api").rglob("*.py"):
        text = path.read_text(encoding="utf-8").upper()
        for keyword in ("SELECT ", "INSERT ", "UPDATE ", "DELETE FROM"):
            assert keyword not in text, f"{path.name} obsahuje SQL ({keyword.strip()})"
