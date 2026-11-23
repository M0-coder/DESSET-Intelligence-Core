"""CLI tests use only synthetic scenarios; no network or real locations."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from desset_core.__main__ import run


class CliTests(unittest.TestCase):
    def invoke(self, body, strategy="optimal"):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scenario.json"
            path.write_text(json.dumps(body), encoding="utf-8")
            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                patch("sys.argv", ["desset_core", "--input", str(path), "--strategy", strategy]),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                code = run()
            return code, stdout.getvalue(), stderr.getvalue()

    def scenario(self):
        return {
            "schema_version": 1,
            "couriers": [{"id": "C1", "capacity_units": 1}],
            "orders": [{"id": "O1", "load_units": 1}],
            "pickup_seconds": [{"courier_id": "C1", "order_id": "O1", "seconds": 20}],
        }

    def test_cli_success_contract(self):
        code, out, error = self.invoke(self.scenario())
        self.assertEqual(code, 0)
        self.assertEqual(error, "")
        result = json.loads(out)
        self.assertFalse(result["production_validated"])
        self.assertEqual(result["metrics"]["total_estimated_pickup_seconds"], 20)
        self.assertEqual(result["metrics"]["assigned_count"], 1)

    def test_cli_greedy(self):
        code, out, _ = self.invoke(self.scenario(), strategy="greedy")
        self.assertEqual(code, 0)
        self.assertIn(":greedy", json.loads(out)["algorithm_version"])

    def test_cli_invalid_schema(self):
        data = self.scenario()
        data["schema_version"] = 2
        code, _, error = self.invoke(data)
        self.assertEqual(code, 2)
        self.assertIn("unsupported schema_version", error)

    def test_cli_duplicate_matrix(self):
        data = self.scenario()
        data["pickup_seconds"] *= 2
        code, _, error = self.invoke(data)
        self.assertEqual(code, 2)
        self.assertIn("duplicate pickup matrix pair", error)

    def test_cli_missing_fields(self):
        code, _, error = self.invoke({"schema_version": 1})
        self.assertEqual(code, 2)
        self.assertIn("invalid scenario", error)


if __name__ == "__main__":
    unittest.main()
