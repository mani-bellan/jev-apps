"""Break the demo dbt project in realistic ways and save each real failure as a triage sample.

    uv run --group dbt dbt_demo/run_scenarios.py

Each scenario copies the project to a temporary directory, makes one change, runs `dbt build`,
and writes samples/dbt/<scenario>.json from the real dbt output, run_results.json, and manifest.json.
When TYPESAFE_API_KEY is set, it then runs the triage app on each failure and compares the decision
with the scenario's expected cause and action.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

PROJECT = Path(__file__).parent
SAMPLES = PROJECT.parent / "samples" / "dbt"


def edit(path: str, old: str, new: str) -> Callable[[Path], None]:
    def apply(project: Path) -> None:
        file = project / path
        text = file.read_text()
        assert old in text, f"{old!r} not in {path}"
        file.write_text(text.replace(old, new, 1))

    return apply


def append(path: str, line: str) -> Callable[[Path], None]:
    def apply(project: Path) -> None:
        with (project / path).open("a") as file:
            file.write(line + "\n")

    return apply


SCENARIOS: dict[str, dict] = {
    # A payment is exported twice, so the payment_id unique test fails. Feeds finance and invoices.
    "duplicate_payment": {"change": append("data/payments.csv", "1007,107,card,7600"), "expect": ("data_quality", "page")},
    # New customers arrive without an email address. Feeds only the marketing list.
    "missing_email": {"change": append("data/customers.csv", "7,Grace Kim,,KR"), "expect": ("data_quality", "ticket")},
    # The CRM renamed a column in its export.
    "renamed_column": {
        "change": edit("data/customers.csv", "id,name,email,country", "id,name,email_address,country"),
        "expect": ("schema_change", "ticket"),
    },
    # Someone edited a model and left a syntax error.
    "sql_typo": {"change": edit("models/marts/dim_customers.sql", "group by all", "grop by all"), "expect": ("code_bug", "ticket")},
    # Today's orders export has not landed yet.
    "missing_partition": {"vars": {"run_date": "2026-10-12"}, "expect": ("upstream_delay", "retry")},
    # The worker has far less memory than the job needs.
    "out_of_memory": {"env": {"DUCKDB_MEMORY_LIMIT": "1MB"}, "expect": ("resources", "retry")},
    # The exports bucket is unreachable.
    "unreachable_source": {"vars": {"data_dir": "https://exports.shop-data.invalid"}, "expect": ("network", "retry")},
    # Held out: added after the questions were tuned on the scenarios above, to check they generalize.
    # An order arrives with a status the model does not know about.
    "new_order_status": {
        "change": append("data/orders/dt=2026-10-11/orders.csv", "111,4,2026-10-11,partially_refunded"),
        "expect": ("data_quality", "page"),
        "held_out": True,
    },
    # A payment points at an order that does not exist.
    "orphan_payment": {"change": append("data/payments.csv", "1011,999,card,2500"), "expect": ("data_quality", "page"), "held_out": True},
    # The payments export starts writing amounts as text with a currency.
    "amount_type_change": {
        "change": edit("data/payments.csv", "1010,110,card,5600", "1010,110,card,56.00 EUR"),
        "expect": ("schema_change", "page"),
        "held_out": True,
    },
}


def downstream(manifest: dict, node_ids: list[str]) -> list[str]:
    """Names of the models and exposures that depend on the failed nodes (or on the models a failed test checks)."""
    start = []
    for node_id in node_ids:
        node = manifest["nodes"][node_id]
        start += node["depends_on"]["nodes"] if node["resource_type"] == "test" else [node_id]
    seen, queue = set(start), list(start)
    while queue:
        for child in manifest["child_map"].get(queue.pop(), []):
            if child not in seen:
                seen.add(child)
                queue.append(child)
    names = [n.split(".")[-1] for n in seen - set(start) if n.startswith(("model.", "exposure."))]
    return sorted(names)


def run(name: str, scenario: dict) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        project = Path(tmp) / "shop"
        shutil.copytree(PROJECT, project, ignore=shutil.ignore_patterns("target", "logs", "*.duckdb*", "*.py"))
        if "change" in scenario:
            scenario["change"](project)
        command = ["dbt", "build", "--no-use-colors"]
        if "vars" in scenario:
            command += ["--vars", json.dumps(scenario["vars"])]
        result = subprocess.run(
            command, cwd=project, capture_output=True, text=True, env={**os.environ, **scenario.get("env", {})}
        )
        assert result.returncode != 0, f"{name}: dbt build unexpectedly succeeded"

        results = json.loads((project / "target" / "run_results.json").read_text())["results"]
        manifest = json.loads((project / "target" / "manifest.json").read_text())
        failed = [r["unique_id"] for r in results if r["status"] in ("error", "fail")]
        output = result.stdout.splitlines()
        # dbt prints the details of every failure after "Completed with N errors".
        summary = next((i for i, line in enumerate(output) if "Completed with" in line), len(output) - 20)
        return {
            "pipeline": "shop_dbt",
            "task": manifest["nodes"][failed[0]]["name"],
            "attempt": 1,
            "downstream": downstream(manifest, failed),
            "error_log": "\n".join(output[summary:]).strip(),
        }


def evaluate(failures: dict[str, dict]) -> None:
    """Run the triage app on every captured failure and compare with the expected cause and action."""
    sys.path.insert(0, str(PROJECT.parent))
    from triage import triage
    from typesafe_sdk import TypeSafeClient

    correct = 0
    with TypeSafeClient() as client:
        for name, failure in failures.items():
            decision = triage(client, failure)
            expected_cause, expected_action = SCENARIOS[name]["expect"]
            ok = (decision.cause, decision.action) == (expected_cause, expected_action)
            correct += ok
            print(
                f"{'OK ' if ok else 'BAD'} {'(held out) ' if SCENARIOS[name].get('held_out') else ''}{name:20} cause {decision.cause} ({decision.cause_confidence:.2f}), "
                f"impact {decision.impact:.1f} -> {decision.action}"
                + ("" if ok else f"  (expected {expected_cause} -> {expected_action})")
            )
    print(f"{correct}/{len(failures)} match the expected cause and action")


def main() -> None:
    SAMPLES.mkdir(parents=True, exist_ok=True)
    failures = {}
    for name, scenario in SCENARIOS.items():
        failures[name] = run(name, scenario)
        (SAMPLES / f"{name}.json").write_text(json.dumps(failures[name], indent=2) + "\n")
        print(f"captured {name}: {failures[name]['task']} failed, downstream {failures[name]['downstream']}")
    if os.environ.get("TYPESAFE_API_KEY"):
        print()
        evaluate(failures)


if __name__ == "__main__":
    main()
