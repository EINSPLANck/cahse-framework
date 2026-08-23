from __future__ import annotations

import argparse
import json
import random
import re
import sys
import urllib.parse
import urllib.request
from dataclasses import asdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_PARENT = ROOT.parent
if str(PACKAGE_PARENT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_PARENT))

from mewcode.evolution.task.task_analyzer import TaskAnalyzer  # noqa: E402


HF_ROWS_URL = "https://datasets-server.huggingface.co/rows"
DEFAULT_DATASET = "princeton-nlp/SWE-bench"
DEFAULT_CONFIG = "default"
DEFAULT_SPLIT = "test"


def fetch_rows(dataset: str, config: str, split: str, offset: int, length: int) -> dict[str, Any]:
    query = urllib.parse.urlencode(
        {
            "dataset": dataset,
            "config": config,
            "split": split,
            "offset": offset,
            "length": length,
        }
    )
    with urllib.request.urlopen(f"{HF_ROWS_URL}?{query}", timeout=60) as response:
        return json.load(response)


def fetch_one(dataset: str, config: str, split: str, offset: int) -> dict[str, Any]:
    payload = fetch_rows(dataset, config, split, offset, 1)
    rows = payload.get("rows") or []
    if not rows:
        raise RuntimeError(f"No row returned at offset {offset}")
    return rows[0]["row"]


def changed_files_from_patch(patch: str) -> list[str]:
    files: list[str] = []
    seen: set[str] = set()
    for match in re.finditer(r"^diff --git a/(.*?) b/(.*?)$", patch or "", flags=re.MULTILINE):
        path = match.group(2).strip()
        if path and path != "/dev/null" and path not in seen:
            seen.add(path)
            files.append(path)
    if files:
        return files
    for match in re.finditer(r"^\+\+\+ b/(.*?)$", patch or "", flags=re.MULTILINE):
        path = match.group(1).strip()
        if path and path != "/dev/null" and path not in seen:
            seen.add(path)
            files.append(path)
    return files


def dir_name(path: str) -> str:
    return str(Path(path).parent).replace("\\", "/")


def normalize_component(component: str, repo: str, changed_files: list[str]) -> str:
    component = (component or "").replace("\\", "/").strip()
    if not component:
        return ""

    repo = (repo or "").strip("/")
    if repo:
        escaped_repo = re.escape(repo)
        match = re.search(rf"github\.com/{escaped_repo}/blob/[^/]+/(.+)$", component)
        if match:
            return match.group(1)

    if component.startswith("a/") or component.startswith("b/"):
        component = component[2:]

    repo_name = repo.rsplit("/", 1)[-1] if repo else ""
    if repo_name:
        marker = f"/{repo_name}/"
        idx = component.rfind(marker)
        if idx >= 0:
            component = component[idx + 1 :]

    for path in changed_files:
        path = path.replace("\\", "/")
        if component.endswith(path):
            return path
    return component


def component_scores(component: str, repo: str, changed_files: list[str]) -> dict[str, Any]:
    component = (component or "").replace("\\", "/").strip()
    changed = [p.replace("\\", "/") for p in changed_files]
    normalized = normalize_component(component, repo, changed)
    if not component:
        return {
            "component_normalized": "",
            "component_exact": False,
            "component_dir": False,
            "component_present": False,
            "component_soft": 0.0,
        }
    exact = normalized in changed
    comp_dir = dir_name(normalized)
    dir_match = bool(comp_dir and any(dir_name(path) == comp_dir for path in changed))
    suffix_match = any(path.endswith(normalized) or normalized.endswith(path) for path in changed)
    soft = 1.0 if exact else 0.75 if suffix_match else 0.5 if dir_match else 0.0
    return {
        "component_normalized": normalized,
        "component_exact": exact,
        "component_dir": dir_match,
        "component_present": True,
        "component_soft": soft,
    }

def make_skillopt_experience(row: dict[str, Any], analysis: dict[str, Any], scores: dict[str, Any]) -> dict[str, Any]:
    changed_files = analysis["swe_changed_files"]
    prediction = {
        "task_type": analysis["mewcode_task_type"],
        "task_description": analysis["mewcode_task_description"],
        "component": analysis["mewcode_component"],
    }
    return {
        "id": row["instance_id"],
        "project": row["repo"],
        "intent": analysis["mewcode_task_description"],
        "context_excerpt": row.get("problem_statement", "")[:4000],
        "system": "mewcode_task_analyzer_metadata_validation.v1",
        "attempted_solution": json.dumps(prediction, ensure_ascii=False),
        "outcome": "success" if scores["component_soft"] > 0 else "unknown",
        "reference_kind": "rubric",
        "reference": (
            "Given the SWE-bench issue metadata, identify the task type, preserve "
            "the core issue description, and predict an affected component that is "
            f"consistent with one of these gold changed files: {changed_files}."
        ),
        "judge": {
            "kind": "swebench_metadata_proxy",
            "changed_files": changed_files,
            "metric": "component_exact_or_directory_overlap",
        },
        "tags": [
            "swebench",
            "metadata-only",
            "mewcode-task-analyzer",
            analysis["mewcode_task_type"],
        ],
        "source_sessions": [row["instance_id"]],
        "split": "train",
        "origin": "real",
        "derived_from": row["instance_id"],
        "skill_hint": "mewcode-task-analyzer",
    }


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_report(path: Path, rows: list[dict[str, Any]], metadata: dict[str, Any]) -> None:
    total = len(rows)
    known_type = sum(1 for row in rows if row["mewcode_task_type"] != "unknown")
    component_present = sum(1 for row in rows if row["component_present"])
    component_exact = sum(1 for row in rows if row["component_exact"])
    component_dir = sum(1 for row in rows if row["component_dir"])
    avg_soft = sum(float(row["component_soft"]) for row in rows) / total if total else 0.0

    lines = [
        "# SWE-bench x MewCode Task Analyzer Validation",
        "",
        "## Setup",
        "",
        f"- Dataset: `{metadata['dataset']}`",
        f"- Config/split: `{metadata['config']}/{metadata['split']}`",
        f"- Sample size: `{total}`",
        f"- Random seed: `{metadata['seed']}`",
        "- Execution: metadata-only; no Docker, no repo checkout, no SWE environment run.",
        "",
        "## Aggregate Results",
        "",
        f"- Non-unknown task_type: `{known_type}/{total}`",
        f"- Analyzer emitted a component: `{component_present}/{total}`",
        f"- Exact changed-file component hit: `{component_exact}/{total}`",
        f"- Same-directory component hit: `{component_dir}/{total}`",
        f"- Mean component proxy score: `{avg_soft:.3f}`",
        "",
        "## Interpretation",
        "",
        "MewCode produces the required experience shell for SkillOpt: a stable task id, repo/project, task description, analyzer prediction, gold metadata, and a computable proxy score.",
        "",
        "The current analyzer is intentionally shallow: it only predicts `target_component` when a path-like string appears in the issue text. Therefore component recall is expected to be low on raw SWE-bench `problem_statement` alone. The validation still demonstrates compatibility of the experience format, while also exposing the next optimization target: richer component inference from issue text.",
        "",
        "## Rows",
        "",
        "Comparison normalizes obvious GitHub `blob/<branch>/...`, diff `a`/`b`, and local traceback prefixes before scoring component overlap.",
        "",
        "| # | instance_id | repo | task_type | component_normalized | component_score | changed_files |",
        "|---:|---|---|---|---|---:|---|",
    ]
    for idx, row in enumerate(rows, start=1):
        changed = "<br>".join(row["swe_changed_files"][:4])
        if len(row["swe_changed_files"]) > 4:
            changed += "<br>..."
        lines.append(
            f"| {idx} | `{row['instance_id']}` | `{row['repo']}` | "
            f"`{row['mewcode_task_type']}` | `{row['component_normalized'] or '(empty)'}` | "
            f"{float(row['component_soft']):.2f} | {changed} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate MewCode task analyzer on SWE-bench metadata.")
    parser.add_argument("--dataset", default=DEFAULT_DATASET)
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--split", default=DEFAULT_SPLIT)
    parser.add_argument("--sample-size", type=int, default=20)
    parser.add_argument("--seed", type=int, default=20260822)
    parser.add_argument("--out-dir", default=str(ROOT / "validation" / "swebench_mewcode_20"))
    args = parser.parse_args()

    first_page = fetch_rows(args.dataset, args.config, args.split, 0, 1)
    total_rows = int(first_page["num_rows_total"])
    rng = random.Random(args.seed)
    offsets = sorted(rng.sample(range(total_rows), args.sample_size))
    analyzer = TaskAnalyzer()

    rows: list[dict[str, Any]] = []
    experiences: list[dict[str, Any]] = []
    raw_rows: list[dict[str, Any]] = []
    for offset in offsets:
        row = fetch_one(args.dataset, args.config, args.split, offset)
        raw_rows.append(row)
        analyzer_input = row.get("problem_statement", "")
        metadata = analyzer.analyze(analyzer_input)
        changed_files = changed_files_from_patch(row.get("patch", ""))
        changed_test_files = changed_files_from_patch(row.get("test_patch", ""))
        scores = component_scores(metadata.target_component, row["repo"], changed_files)
        result = {
            "offset": offset,
            "instance_id": row["instance_id"],
            "repo": row["repo"],
            "swe_problem_statement": row.get("problem_statement", ""),
            "swe_changed_files": changed_files,
            "swe_changed_test_files": changed_test_files,
            "mewcode_task_type": metadata.task_type,
            "mewcode_task_description": metadata.task_description,
            "mewcode_component": metadata.target_component,
            **scores,
        }
        rows.append(result)
        experiences.append(make_skillopt_experience(row, result, scores))

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    metadata = {
        "dataset": args.dataset,
        "config": args.config,
        "split": args.split,
        "sample_size": args.sample_size,
        "seed": args.seed,
        "total_rows": total_rows,
        "offsets": offsets,
    }
    write_json(out_dir / "metadata.json", metadata)
    write_json(out_dir / "raw_swebench_rows.json", raw_rows)
    write_jsonl(out_dir / "mewcode_swebench_analysis.jsonl", rows)
    write_json(
        out_dir / "skillopt_experiences.json",
        {
            "format": "mewcode.skillopt_experiences.v1",
            "metadata": metadata,
            "experiences": experiences,
        },
    )
    write_json(
        out_dir / "skillopt_tasks_payload.json",
        {
            "format": "skillopt_sleep.tasks.v1",
            "project": "swebench-metadata-validation",
            "transcript_source": args.dataset,
            "n_sessions": args.sample_size,
            "target_skill_path": "mewcode.evolution.task.TaskAnalyzer",
            "reviewed": True,
            "tasks": experiences,
        },
    )
    write_report(out_dir / "report.md", rows, metadata)

    summary = {
        "out_dir": str(out_dir),
        "sample_size": len(rows),
        "known_task_type": sum(1 for row in rows if row["mewcode_task_type"] != "unknown"),
        "component_present": sum(1 for row in rows if row["component_present"]),
        "component_exact": sum(1 for row in rows if row["component_exact"]),
        "component_dir": sum(1 for row in rows if row["component_dir"]),
        "mean_component_soft": round(
            sum(float(row["component_soft"]) for row in rows) / len(rows), 4
        )
        if rows
        else 0.0,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
