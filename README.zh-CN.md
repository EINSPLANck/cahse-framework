# CAHSE Framework

> **Coding Agent Harness for Software Engineering Self-Evolution**  
> 面向长程软件工程任务的智能体执行与自进化框架

**简体中文** | [English](./README.en.md)

CAHSE 是一个面向长程软件工程任务的智能体执行与自进化框架。它从真实 agent 开发过程中采集完整行为轨迹，在任务结束后合成 benchmark-style 任务经验，并导出为 SkillOpt-compatible 数据，用于后续 replay、judge、reflect 和 validation-gated self-evolution。

## 项目动机

很多 agent memory 系统会保存历史对话，或者在推理时检索相似片段。这很有用，但它没有回答更关键的问题：

> 哪些真实开发经验足够可靠，值得沉淀成可复用 skill？

CAHSE 关注的是智能体自进化的上游数据构建问题：

```text
真实开发任务
  -> 执行轨迹
  -> 结构化任务经验
  -> 标准化任务标签
  -> SkillOpt-compatible TaskRecord
  -> replay / judge / reflect / gate
```

系统不会把一段 LLM 总结直接写进长期 skill，而是先把已完成的开发任务转成结构化、可追溯、可验证的优化样本，再交给 SkillOpt 做验证门控优化。

## 核心思想

CAHSE 区分两层数据：

- **具体任务实例**：具体、可验证、可追溯。保留问题描述、修改文件、测试命令、执行轨迹等证据。
- **抽象经验模式**：归一化、可聚合、可复用。把任务映射到 task family、problem pattern、operation 和 domain。

这样既能保证 SkillOpt 输入是可 replay / judge 的具体样本，又能通过 taxonomy 和聚合分析产生跨任务泛化。

## 系统架构

```text
用户请求
  -> 执行上下文构建
  -> 轨迹采集
  -> 任务结束后的经验合成
  -> 质量过滤
  -> 任务 taxonomy 与未知任务聚类
  -> SkillOpt adapter
  -> SkillOpt replay-reflect-gate loop
```

| 层级 | 职责 | 关键模块 |
|---|---|---|
| 执行上下文 | 从用户任务、memory、active skills、repo 信息构建上下文 | `agent.py`, `evolution/task/task_analyzer.py` |
| 轨迹采集 | 记录工具调用、文件修改、测试结果、观察和最终回复 | `evolution/trajectory/*` |
| 经验合成 | 任务结束后重建 problem、solution answer、changed files、tests 和 structured experience | `evolution/task/*` |
| 质量过滤 | 只保留真正完成且验证通过的轨迹 | `evolution/evaluator.py`, `evolution/trajectory/storage.py` |
| 任务标签化 | 编码短问题签名、匹配稳定标签、聚类未知任务 | `evolution/task_taxonomy/*` |
| SkillOpt 导出 | 把 validated trajectory 转成 SkillOpt-compatible TaskRecord | `evolution/skillopt_adapter.py` |

## 经验样本格式

任务结束后，CAHSE 会合成结构化经验：

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

这个格式故意比纯 LLM 总结更结构化。它的目标不是写一段好看的复盘，而是保留 replay、validation、taxonomy assignment 和后续 skill optimization 所需的证据。

## SkillOpt 兼容性

CAHSE 可以把 validated experience 导出为 SkillOpt-style `TaskRecord`：

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

这里选择 `reference_kind="rubric"`，因为真实软件工程任务通常没有唯一的文本标准答案。一次成功修复更适合用 rubric 表达：是否解决原任务、是否修改相关文件、是否通过验证命令、是否与采集到的解法证据一致。

## 与 Benchmark 的共通点

CAHSE 生成的经验样本最接近 SWE-bench、BugsInPy、Defects4J 这类 repository-level 软件工程 benchmark。

| Benchmark-style 字段 | 公认 benchmark | CAHSE |
|---|---|---|
| 任务输入 | issue、bug report、problem statement | `problem.description` |
| 代码上下文 | repo snapshot、buggy version | `repository`, `component`, `execution_context` |
| 解法证据 | patch、fixed version、changed files | `solution.changed_files`, trajectory evidence |
| 验证方式 | failing/passing tests、hidden tests | `solution.tests`, validation command |
| 元数据 | repo、bug id、split、tags | `trajectory_id`, `session_id`, `task_type`, taxonomy label |

当前验证是 metadata-level 和 compatibility-focused：证明 CAHSE 风格的任务经验可以被 SkillOpt 加载、replay 和 gate，而不是依赖完整 SWE-bench Docker 环境。

## 任务标签化

长任务描述通常很噪，不适合直接 embedding 聚类。CAHSE 会先把任务压缩成短的 `ProblemSignature`：

```json
{
  "task_family": "authentication_debugging",
  "problem_pattern": "token_lifecycle_failure",
  "operation": "bug_fix",
  "domain": "web_security"
}
```

然后用固定 taxonomy registry 做归类：

- `auto_assigned`：高置信匹配稳定 normalized label。
- `needs_review`：有候选标签，但分数或 margin 不够，需要人工确认。
- `unassigned`：没有可靠标签，进入未知任务池。

只有不确定任务会进入聚类和人工审核。已知任务直接使用稳定标签，从而避免 label drift，并保证长期统计口径一致。

## 当前验证结果

当前本地验证覆盖了自进化数据链路的核心部分：

```powershell
python -m pytest tests\test_task_taxonomy.py tests\test_task_experience_synthesis.py -q
```

预期结果：

```text
8 passed
```

同时已经用 SkillOpt loader 和 dry-run 验证过：

- 一条已完成 CAHSE trajectory probe。
- 20 条 SWE-bench metadata alignment 样本。

已观察到：

- SkillOpt loader 可以读取生成的 payload。
- `reference_kind` 正确导出为 `rubric`。
- `context_excerpt` 包含 `mewcode.task_experience.v1`。
- SkillOpt dry-run exit code 为 `0`。

## 快速开始

运行核心测试：

```powershell
python -m pytest tests\test_task_taxonomy.py tests\test_task_experience_synthesis.py -q
```

运行自进化相关模块编译检查：

```powershell
python -m py_compile evolution\task_taxonomy\__init__.py evolution\task_taxonomy\schema.py evolution\task_taxonomy\encoder.py evolution\task_taxonomy\taxonomy.py evolution\task_taxonomy\assigner.py evolution\task_taxonomy\clustering.py evolution\task_taxonomy\review.py evolution\task\task_analyzer.py evolution\skillopt_adapter.py evolution\trajectory\manager.py evolution\trajectory\storage.py agent.py
```

运行已有 SWE-bench metadata validation 报告生成脚本：

```powershell
python validation\run_swebench_mewcode_validation.py --sample-size 20
```

## 目录结构

```text
evolution/
  task/                 # 任务分析与任务结束后的经验合成
  trajectory/           # 轨迹 schema、manager、collector、storage
  task_taxonomy/        # 问题签名、标签归类、未知任务聚类
  skillopt_adapter.py   # SkillOpt-compatible export
  evaluator.py          # 采集轨迹的质量过滤

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

- 将 `ProblemSignature` 生成正式接入任务结束后的经验合成链路。
- 持久化版本化 taxonomy registry，并建立 label governance 流程。
- 导出 SkillOpt TaskRecord 时带上 normalized label 和 assignment status。
- 增加 patch/base-commit 字段，提升 benchmark-grade reproducibility。
- 当数据量增长后，把当前轻量 residual clustering 替换为 embedding + HDBSCAN。
- 将 SkillOpt accepted/rejected updates 回流到 label-level improvement statistics。

## 技术文档

完整技术设计、方案取舍、相关工作和面试追问详见：

- [Self-Evolution Design Notes](./docs/self_evolution_design.md)

