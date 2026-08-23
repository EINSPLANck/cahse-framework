# CAHSE Framework

> **Coding Agent Harness for Software Engineering Self-Evolution**

[简体中文](./README.zh-CN.md) | **English**

CAHSE is a coding-agent harness for long-horizon software engineering tasks. It captures real agent development trajectories, synthesizes benchmark-style task experiences after execution, and exports them as SkillOpt-compatible records for validation-gated self-evolution.

## Why CAHSE

Most agent memory systems store past conversations or retrieve similar snippets at inference time. That is useful, but it does not answer the harder question:

> Which real development experiences are reliable enough to become reusable skills?

CAHSE focuses on the upstream data problem for agent self-evolution:

```text
real coding task
  -> execution trajectory
  -> structured task experience
  -> normalized task taxonomy
  -> SkillOpt-compatible TaskRecord
  -> replay / judge / reflect / gate
```

The system does not directly overwrite long-term skills from raw summaries. Instead, it turns completed development work into structured, traceable, and verifiable training units that can be consumed by SkillOpt.

## Core Idea

CAHSE separates a concrete task instance from a reusable experience pattern.

- **Instance-level task:** concrete, traceable, and replayable. It keeps the problem statement, changed files, tests, and execution evidence.
- **Abstract-level experience:** normalized and reusable. It maps the instance to a task family, problem pattern, operation, and domain.

This design keeps SkillOpt inputs checkable while still enabling generalization across many similar real tasks.

## Architecture

```text
User request
  -> Execution context builder
  -> Trajectory collector
  -> Post-execution experience synthesizer
  -> Quality evaluator
  -> Task taxonomy and unknown clustering
  -> SkillOpt adapter
  -> SkillOpt replay-reflect-gate loop
```

| Layer | Responsibility | Key Modules |
|---|---|---|
| Execution context | Build task context from user request, memory, active skills, and repository information | `agent.py`, `evolution/task/task_analyzer.py` |
| Trajectory collection | Capture tool calls, file changes, tests, observations, and final response | `evolution/trajectory/*` |
| Experience synthesis | Reconstruct problem, solution answer, changed files, tests, and structured experience after task completion | `evolution/task/*` |
| Quality gate | Keep only successful and validated trajectories | `evolution/evaluator.py`, `evolution/trajectory/storage.py` |
| Task taxonomy | Encode short problem signatures, assign stable labels, cluster unknown tasks | `evolution/task_taxonomy/*` |
| SkillOpt export | Convert validated trajectories into SkillOpt-compatible TaskRecords | `evolution/skillopt_adapter.py` |

## Experience Schema

After a task finishes, CAHSE synthesizes a structured experience:

```json
{
  "schema_version": "mewcode.task_experience.v1",
  "problem": {
    "description": "Fix failing checkout validation in src/checkout.py",
    "task_type": "bug_fix",
    "component": "src/checkout.py"
  },
  "solution": {
    "answer": "Problem: ...\nChanged files: ...\nValidation: ...\nOutcome: success",
    "changed_files": ["src/checkout.py"],
    "tests": [
      {
        "command": "pytest tests/test_checkout.py",
        "passed": true,
        "exit_code": 0
      }
    ],
    "success": true
  },
  "trajectory": {
    "id": "...",
    "session_id": "...",
    "tool_sequence": [],
    "execution_context_excerpt": "..."
  },
  "skillopt": {
    "compatible": true,
    "intent_field": "problem.description",
    "attempted_solution_field": "solution.answer",
    "reference_field": "solution.tests"
  }
}
```

This is intentionally more structured than a pure LLM summary. The goal is to preserve evidence required for replay, validation, taxonomy assignment, and future skill optimization.

## SkillOpt Compatibility

CAHSE exports validated experiences as SkillOpt-style `TaskRecord` objects:

```json
{
  "id": "...",
  "project": "...",
  "intent": "Fix failing checkout validation in src/checkout.py",
  "context_excerpt": "files touched: ...\ntests: ...\nstructured_experience: ...",
  "system": "mewcode",
  "attempted_solution": "Problem: ...\nChanged files: ...\nValidation: ...",
  "outcome": "success",
  "reference_kind": "rubric",
  "reference": "A successful solution should: ...",
  "judge": {},
  "tags": ["coding", "trajectory", "skillopt-compatible", "bug_fix"],
  "origin": "real"
}
```

`reference_kind="rubric"` is used because real software engineering tasks rarely have a single exact text answer. A successful repair is better represented by a rubric involving task intent, relevant files, validation commands, and captured solution evidence.

## Benchmark-Style Alignment

CAHSE experiences are most similar to repository-level software engineering benchmarks such as SWE-bench, BugsInPy, and Defects4J.

| Benchmark-style field | Public benchmarks | CAHSE |
|---|---|---|
| Task input | issue, bug report, problem statement | `problem.description` |
| Code context | repository snapshot, buggy version | `repository`, `component`, `execution_context` |
| Solution evidence | patch, fixed version, changed files | `solution.changed_files`, trajectory evidence |
| Validation | failing/passing tests, hidden tests | `solution.tests`, validation command |
| Metadata | repo, bug id, split, tags | `trajectory_id`, `session_id`, `task_type`, taxonomy label |

The current validation is metadata-level and compatibility-focused: it checks whether CAHSE-style task experiences can be loaded and replayed by SkillOpt, without requiring a full SWE-bench Docker environment.

## Task Taxonomy

Long task descriptions are noisy and hard to cluster directly. CAHSE compresses each task into a short `ProblemSignature`:

```json
{
  "task_family": "authentication_debugging",
  "problem_pattern": "token_lifecycle_failure",
  "operation": "bug_fix",
  "domain": "web_security"
}
```

The signature is assigned against a fixed taxonomy registry:

- `auto_assigned`: high-confidence match to a stable normalized label.
- `needs_review`: plausible match but low score or small margin.
- `unassigned`: no reliable label; enters unknown-task clustering.

Only uncertain tasks are clustered and sent to human review. Stable tasks keep their normalized labels, which prevents label drift and keeps long-term statistics meaningful.

## Validation Results

The current local validation covers the core self-evolution data path:

```powershell
python -m pytest tests\test_task_taxonomy.py tests\test_task_experience_synthesis.py -q
```

Expected result:

```text
8 passed
```

SkillOpt loader and dry-run validation have also been run on:

- A completed CAHSE trajectory probe.
- A 20-task SWE-bench metadata alignment sample.

Observed results:

- SkillOpt loader accepted the generated payloads.
- `reference_kind` was correctly exported as `rubric`.
- `context_excerpt` included `mewcode.task_experience.v1`.
- SkillOpt dry-run completed with exit code `0`.

## Quick Start

Run the focused tests:

```powershell
python -m pytest tests\test_task_taxonomy.py tests\test_task_experience_synthesis.py -q
```

Run Python compile checks for the self-evolution modules:

```powershell
python -m py_compile evolution\task_taxonomy\__init__.py evolution\task_taxonomy\schema.py evolution\task_taxonomy\encoder.py evolution\task_taxonomy\taxonomy.py evolution\task_taxonomy\assigner.py evolution\task_taxonomy\clustering.py evolution\task_taxonomy\review.py evolution\task\task_analyzer.py evolution\skillopt_adapter.py evolution\trajectory\manager.py evolution\trajectory\storage.py agent.py
```

Run the existing SWE-bench metadata validation report generator:

```powershell
python validation\run_swebench_mewcode_validation.py --sample-size 20
```

## Repository Structure

```text
evolution/
  task/                 # task analysis and post-execution experience synthesis
  trajectory/           # trajectory schema, manager, collector, storage
  task_taxonomy/        # problem signatures, label assignment, unknown clustering
  skillopt_adapter.py   # SkillOpt-compatible export
  evaluator.py          # quality gate for collected trajectories

validation/
  run_swebench_mewcode_validation.py
  swebench_mewcode_20/

tests/
  test_task_experience_synthesis.py
  test_task_taxonomy.py

docs/
  self_evolution_design.md
```

## Roadmap

- Integrate `ProblemSignature` generation directly into the post-execution synthesis pipeline.
- Persist a versioned taxonomy registry and label governance workflow.
- Export normalized labels and assignment status into SkillOpt TaskRecords.
- Add patch/base-commit fields for stronger benchmark-grade reproducibility.
- Replace the current lightweight residual clustering with embedding + HDBSCAN when data volume grows.
- Feed SkillOpt accepted/rejected updates back into label-level improvement statistics.

## Documentation

For the full technical design, trade-offs, related work, and interview-level Q&A, see:

- [Self-Evolution Design Notes](./docs/self_evolution_design.md)

