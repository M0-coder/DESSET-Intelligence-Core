"""Offline, JSON-only CLI for the experimental dispatch matching engine."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from .dispatch import Courier, Order, dispatch


def run() -> int:
    parser = argparse.ArgumentParser(description="DESSET offline dispatch simulation")
    parser.add_argument("--input", type=Path, required=True, help="Versioned scenario JSON")
    parser.add_argument("--strategy", choices=("greedy", "optimal"), default="optimal")
    args = parser.parse_args()
    try:
        data = json.loads(args.input.read_text(encoding="utf-8"))
        if type(data) is not dict or type(data.get("schema_version")) is not int:
            raise ValueError("missing integer schema_version")
        if data["schema_version"] != 1:
            raise ValueError("unsupported schema_version")
        couriers = [Courier(**row) for row in data["couriers"]]
        orders = [Order(**row) for row in data["orders"]]
        matrix = {}
        for row in data["pickup_seconds"]:
            pair = (row["courier_id"], row["order_id"])
            if pair in matrix:
                raise ValueError("duplicate pickup matrix pair")
            matrix[pair] = row["seconds"]
        result = dispatch(couriers, orders, matrix, strategy=args.strategy)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        print(f"invalid scenario: {error}", file=sys.stderr)
        return 2
    output = {
        "schema_version": 1,
        "algorithm_version": result.strategy,
        "source_of_travel_times": "caller_supplied_estimates_not_verified",
        "production_validated": False,
        "assignments": [asdict(item) for item in result.assignments],
        "unassigned": [asdict(item) for item in result.unassigned],
        "metrics": {
            "assigned_count": len(result.assignments),
            "unassigned_count": len(result.unassigned),
            "total_estimated_pickup_seconds": result.total_estimated_pickup_seconds,
        },
    }
    print(json.dumps(output, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(run())
