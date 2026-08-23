# SWE-bench x MewCode Task Analyzer Validation

## Setup

- Dataset: `princeton-nlp/SWE-bench`
- Config/split: `default/test`
- Sample size: `20`
- Random seed: `20260822`
- Execution: metadata-only; no Docker, no repo checkout, no SWE environment run.

## Aggregate Results

- Non-unknown task_type: `20/20`
- Analyzer emitted a component: `11/20`
- Exact changed-file component hit: `6/20`
- Same-directory component hit: `6/20`
- Mean component proxy score: `0.300`

## Interpretation

MewCode produces the required experience shell for SkillOpt: a stable task id, repo/project, task description, analyzer prediction, gold metadata, and a computable proxy score.

The current analyzer is intentionally shallow: it only predicts `target_component` when a path-like string appears in the issue text. Therefore component recall is expected to be low on raw SWE-bench `problem_statement` alone. The validation still demonstrates compatibility of the experience format, while also exposing the next optimization target: richer component inference from issue text.

## Rows

Comparison normalizes obvious GitHub `blob/<branch>/...`, diff `a`/`b`, and local traceback prefixes before scoring component overlap.

| # | instance_id | repo | task_type | component_normalized | component_score | changed_files |
|---:|---|---|---|---|---:|---|
| 1 | `astropy__astropy-12891` | `astropy/astropy` | `documentation` | `CONTRIBUTING.md` | 0.00 | astropy/units/quantity.py<br>astropy/utils/masked/core.py |
| 2 | `astropy__astropy-7746` | `astropy/astropy` | `bug_fix` | `astropy/wcs/wcs.py` | 1.00 | astropy/wcs/wcs.py |
| 3 | `django__django-11294` | `django/django` | `bug_fix` | `tests/defaultfilters/tests.py` | 0.00 | django/template/defaultfilters.py |
| 4 | `django__django-12193` | `django/django` | `code_modify` | `django/forms/widgets.py` | 1.00 | django/forms/widgets.py |
| 5 | `django__django-13220` | `django/django` | `bug_fix` | `(empty)` | 0.00 | django/core/exceptions.py |
| 6 | `django__django-13315` | `django/django` | `test_fix` | `(empty)` | 0.00 | django/forms/models.py |
| 7 | `django__django-13773` | `django/django` | `bug_fix` | `(empty)` | 0.00 | django/db/migrations/operations/fields.py |
| 8 | `django__django-13810` | `django/django` | `bug_fix` | `django/core/handlers/base.py` | 1.00 | django/core/handlers/base.py |
| 9 | `django__django-14315` | `django/django` | `bug_fix` | `(empty)` | 0.00 | django/db/backends/base/client.py<br>django/db/backends/postgresql/client.py |
| 10 | `django__django-14373` | `django/django` | `code_modify` | `(empty)` | 0.00 | django/utils/dateformat.py |
| 11 | `django__django-8630` | `django/django` | `code_modify` | `(empty)` | 0.00 | django/contrib/auth/views.py |
| 12 | `matplotlib__matplotlib-24026` | `matplotlib/matplotlib` | `bug_fix` | `matplotlib/__init__.py` | 0.00 | lib/matplotlib/stackplot.py |
| 13 | `matplotlib__matplotlib-26011` | `matplotlib/matplotlib` | `bug_fix` | `matplotlib/axes/_base.py` | 0.00 | lib/matplotlib/axis.py |
| 14 | `pytest-dev__pytest-11217` | `pytest-dev/pytest` | `bug_fix` | `src/_pytest/fixtures.py` | 1.00 | src/_pytest/fixtures.py |
| 15 | `pytest-dev__pytest-5550` | `pytest-dev/pytest` | `bug_fix` | `(empty)` | 0.00 | src/_pytest/junitxml.py |
| 16 | `pytest-dev__pytest-8124` | `pytest-dev/pytest` | `test_fix` | `changelog/README.rs` | 0.00 | src/_pytest/hookspec.py<br>src/_pytest/skipping.py |
| 17 | `scikit-learn__scikit-learn-11578` | `scikit-learn/scikit-learn` | `bug_fix` | `sklearn/linear_model/logistic.py` | 1.00 | sklearn/linear_model/logistic.py |
| 18 | `sympy__sympy-14575` | `sympy/sympy` | `bug_fix` | `sympy/functions/combinatorial/factorials.py` | 1.00 | sympy/functions/combinatorial/factorials.py |
| 19 | `sympy__sympy-16052` | `sympy/sympy` | `bug_fix` | `(empty)` | 0.00 | sympy/matrices/expressions/matexpr.py |
| 20 | `sympy__sympy-18351` | `sympy/sympy` | `bug_fix` | `(empty)` | 0.00 | sympy/printing/pycode.py |
