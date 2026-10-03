import argparse
import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree


def escape(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def read_junit(path: Path, suite: str, catalog: list[dict]) -> list[dict]:
    root = ElementTree.fromstring(path.read_bytes())
    rows = []
    for case in root.iter("testcase"):
        name = case.get("name", "")
        classname = case.get("classname", "")
        identity = f"{suite}:{classname}:{name}"
        description = next((entry for entry in catalog if entry["match"] in identity), {})
        status = (
            "ERROR"
            if case.find("error") is not None
            else "FAIL"
            if case.find("failure") is not None
            else "SKIP"
            if case.find("skipped") is not None
            else "PASS"
        )
        rows.append(
            {
                "test_id": f"{suite.upper()}-{hashlib.sha256(identity.encode()).hexdigest()[:10]}",
                "module": description.get("module", classname),
                "scenario": description.get("scenario", name),
                "input": description.get(
                    "input", "Fixtures/parameters in the named automated test"
                ),
                "expected_result": description.get(
                    "expected", "Named automated test completes without failed assertions"
                ),
                "actual_result": {
                    "PASS": "Completed without failures",
                    "FAIL": "Test runner recorded an assertion failure",
                    "ERROR": "Test runner recorded an execution error",
                    "SKIP": "Test runner skipped this case",
                }[status],
                "status": status,
                "duration_seconds": float(case.get("time", "0")),
                "automation": f"{classname}::{name}",
                "source": str(path),
            }
        )
    return rows


def generate(paths: dict[str, Path], catalog_path: Path, directory: Path) -> dict:
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    rows = [row for suite, path in paths.items() for row in read_junit(path, suite, catalog)]
    counts = dict(Counter(row["status"] for row in rows))
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "counts": counts,
        "tests": rows,
        "source_sha256": {
            str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths.values()
        },
    }
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "test-cases.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        "# MCA automated test-case report",
        "",
        f"Generated: {payload['generated_at']}.",
        "",
        (
            "Actual results and statuses come only from the supplied pytest/Vitest "
            "JUnit files. Expected results describe test assertions, not unexecuted "
            "manual observations. Parametrized cases retain their individual "
            "automation identity. Skips are never reported as PASS."
        ),
        "",
        ", ".join(f"{status}: {count}" for status, count in sorted(counts.items())),
        "",
        (
            "| Test ID | Module | Test scenario / automation | Input | Expected "
            "result | Actual result | Status |"
        ),
        "|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        cells = [
            row["test_id"],
            row["module"],
            row["scenario"] + " — " + row["automation"],
            row["input"],
            row["expected_result"],
            row["actual_result"] + f" ({row['duration_seconds']:.3f}s)",
            row["status"],
        ]
        lines.append("| " + " | ".join(escape(cell) for cell in cells) + " |")
    lines += ["", "## Audit inputs", ""] + [
        f"- `{path}` SHA-256 `{fingerprint}`"
        for path, fingerprint in payload["source_sha256"].items()
    ]
    lines += [
        "",
        (
            "The mocked provider/database tests establish implemented behavior for "
            "their fixture inputs. They are not live-model accuracy or production "
            "performance measurements. The separate real-Neo4j E2E test uses mock AI "
            "providers; the real-provider manual procedure is in README."
        ),
        "",
    ]
    (directory / "test-cases.md").write_text("\n".join(lines), encoding="utf-8")
    return payload


def main():
    parser = argparse.ArgumentParser(description="Generate MCA report from executed JUnit results")
    parser.add_argument(
        "--backend-junit", type=Path, default=Path("evaluation/test-results/backend.xml")
    )
    parser.add_argument(
        "--frontend-junit", type=Path, default=Path("evaluation/test-results/frontend.xml")
    )
    parser.add_argument("--catalog", type=Path, default=Path("evaluation/test-catalog.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("evaluation"))
    args = parser.parse_args()
    try:
        report = generate(
            {"backend": args.backend_junit, "frontend": args.frontend_junit},
            args.catalog,
            args.output_dir,
        )
    except (OSError, ValueError, ElementTree.ParseError) as exc:
        parser.exit(
            2, f"Test results unavailable ({type(exc).__name__}); no PASS results generated.\n"
        )
    print("Executed test statuses:", report["counts"])


if __name__ == "__main__":
    main()
