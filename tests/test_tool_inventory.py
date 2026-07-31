import ast
import unittest
from pathlib import Path

from core.tools.builtins import build_builtin_registry


ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "docs" / "tool_migration_matrix.md"


def _declared_tools() -> list[dict]:
    tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "TOOL_DECLARATIONS"
            for target in node.targets
        ):
            value = ast.literal_eval(node.value)
            if isinstance(value, list):
                return value
    raise AssertionError("TOOL_DECLARATIONS must remain a literal list in main.py")


def _matrix_rows() -> dict[str, dict[str, str]]:
    lines = MATRIX.read_text(encoding="utf-8").splitlines()
    header_index = next(
        index for index, line in enumerate(lines)
        if line.startswith("| Tool | Risk |")
    )
    headers = [cell.strip() for cell in lines[header_index].strip("|").split("|")]
    rows: dict[str, dict[str, str]] = {}
    for line in lines[header_index + 2:]:
        if not line.startswith("| `"):
            break
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) != len(headers):
            raise AssertionError(f"Malformed tool matrix row: {line}")
        row = dict(zip(headers, cells))
        name = row["Tool"].strip("`")
        if name in rows:
            raise AssertionError(f"Duplicate tool matrix row: {name}")
        rows[name] = row
    return rows


class ToolInventoryTests(unittest.TestCase):
    def test_matrix_matches_effective_registry_metadata(self):
        declarations = _declared_tools()
        names = [item["name"] for item in declarations]
        handlers = {name: (lambda _args: None) for name in names}
        registry = build_builtin_registry(declarations, handlers)
        rows = _matrix_rows()

        self.assertEqual(len(names), 37)
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(set(rows), set(names))

        for tool in registry.enabled("windows"):
            with self.subTest(tool=tool.name):
                row = rows[tool.name]
                self.assertEqual(row["Risk"], tool.risk.value)
                self.assertEqual(
                    row["Route"],
                    "special" if tool.special else "executor",
                )
                self.assertEqual(float(row["Timeout s"]), tool.timeout)
                for field in (
                    "Current Policy",
                    "Current return",
                    "Verification",
                    "Rollback",
                    "Coverage",
                    "Pending migration",
                ):
                    self.assertTrue(row[field], f"{tool.name}: missing {field}")


if __name__ == "__main__":
    unittest.main()
