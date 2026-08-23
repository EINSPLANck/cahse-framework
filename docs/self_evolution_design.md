# MewCode Self-Evolution Design Notes

本文档用于准备面试中的深度追问，重点解释 MewCode 当前的模型自进化部分如何设计、为什么这样设计、与相似方案的差异、数据格式是什么，以及当前实现边界。

## 1. 一句话定位

MewCode 当前的自进化部分不是重新实现 SkillOpt，而是解决 SkillOpt 上游最关键的数据来源问题：

> 如何从真实开发任务中自动采集行为轨迹，并把它转成 SkillOpt 可以 replay、judge、reflect 和 gate 的可优化经验样本。

也就是说：

- MewCode 负责从真实开发过程里发现任务、保存轨迹、重建问题和答案、归一化标签、导出经验样本。
- SkillOpt 负责基于这些经验样本做离线 replay、失败反思、候选 skill/memory 编辑和验证集门控。

这让项目的创新点落在“真实开发任务到可优化经验数据”的自动化闭环，而不是重复实现 SkillOpt 的优化器。

## 2. 总体架构

当前链路可以拆成六层：

```text
User task
  -> execution context builder
  -> trajectory collector
  -> post-execution experience synthesizer
  -> quality evaluator
  -> task taxonomy / unknown clustering
  -> SkillOpt adapter
  -> SkillOpt replay-reflect-gate loop
```

对应模块：

| 层级           | 作用                                                           | 关键文件                                                                |
| -------------- | -------------------------------------------------------------- | ----------------------------------------------------------------------- |
| 任务上下文构建 | 在任务开始前把用户任务、memory、skill、repo 信息拼成执行上下文 | `agent.py`, `evolution/task/task_analyzer.py`                       |
| 轨迹采集       | 记录工具调用、测试、文件修改、最终回复                         | `evolution/trajectory/manager.py`, `evolution/trajectory/schema.py` |
| 后验经验合成   | 任务结束后生成 problem、solution_answer、structured_experience | `evolution/task/task_analyzer.py`                                     |
| 质量过滤       | 判断轨迹是否真的成功，决定是否保存为 validated experience      | `evolution/evaluator.py`, `evolution/trajectory/storage.py`         |
| 任务标签化     | 把长问题压缩成稳定 problem signature，并匹配固定 taxonomy      | `evolution/task_taxonomy/*`                                           |
| SkillOpt 适配  | 把 MewCode trajectory 转成 SkillOpt TaskRecord                 | `evolution/skillopt_adapter.py`                                       |

## 3. 为什么采用“任务结束后再抽象”

### 3.1 问题

真实开发任务在开始时只有用户描述和已有 memory，通常不够精确：

- 用户可能只说“这个测试挂了，帮我看下”。
- 真正的问题组件要等查看代码、运行测试后才知道。
- 解法和验证命令只有执行完之后才有证据。
- 任务是否成功也要依赖测试结果和最终状态。

如果在任务开始时就抽象 problem/answer，会出现两个问题：

1. problem 过早抽象，可能和真实修改文件不一致。
2. answer 只能靠模型猜，而不是来自实际执行结果。

### 3.2 当前设计

当前设计把任务分成两个时间点：

```text
before execution:
  build_execution_context(task + memory + repo + active skills)

during execution:
  collect full trajectory(tool calls, file edits, test results)

after execution:
  synthesize problem, solution_answer, structured_experience
```

关键实现：

- `TaskAnalyzer.build_execution_context(...)` 在任务开始前构建上下文。
- `TrajectoryManager._start(...)` 用 execution_context 初始化 task metadata。
- `TrajectoryManager._finish(...)` 在任务结束时调用 `synthesize_experience(...)`。
- `TaskMetadata` 保存 `task_description`、`solution_answer`、`structured_experience`。

### 3.3 为什么这样更合理

这接近 SWE-bench 的样本结构：

```text
problem_statement
  + repo / component
  + changed_files or patch evidence
  + validation signal
```

MewCode 的经验样本不是孤立的一段自然语言，而是带有执行证据的任务记录：

- 问题来自用户任务和实际修改目标。
- 答案来自最终成功轨迹。
- 验证来自测试命令和退出状态。
- 组件来自实际修改文件。

因此它更适合传给 SkillOpt 做优化。

## 4. 轨迹采集层设计

### 4.1 采集什么

`TaskTrajectory` 是 MewCode 自进化样本的原始证据单元，主要字段包括：

```json
{
  "task_description": "...",
  "repository": {...},
  "session_id": "...",
  "trajectory_id": "...",
  "task_metadata": {...},
  "agent_actions": [],
  "tool_calls": [],
  "file_modifications": [],
  "test_results": [],
  "final_success_status": true,
  "final_message": "...",
  "metadata": {
    "execution_context": "..."
  }
}
```

采集的关键对象：

| 数据                           | 作用                                                   |
| ------------------------------ | ------------------------------------------------------ |
| `agent_actions`              | 记录任务开始、过程中 agent 的动作                      |
| `tool_calls`                 | 记录用了哪些工具、参数、输出、是否失败                 |
| `file_modifications`         | 记录改了哪些文件，作为 component 和 changed_files 证据 |
| `test_results`               | 记录验证命令、exit code、passed                        |
| `final_message`              | 保存最终给用户的解答                                   |
| `metadata.execution_context` | 保存任务开始前的上下文                                 |

### 4.2 为什么采集完整轨迹，而不是只采集最终 diff

只采集最终 diff 的问题：

- 看不到 agent 是怎么定位问题的。
- 看不到失败测试到成功测试的调试过程。
- 后续 SkillOpt 无法从失败原因里学习“应该怎么做”。
- 无法区分偶然成功和可复用策略。

完整轨迹的好处：

- 能重建任务上下文。
- 能保留验证证据。
- 能为未来的经验挖掘提供行为序列。
- 能支持后续更复杂的 skill mining，例如工具选择、测试策略、debug pattern。

当前 SkillOpt adapter 主要用 problem、answer、tests、changed_files，但完整轨迹保留下来后，后续可以继续增强，不需要重新采集历史数据。

## 5. 经验合成层设计

### 5.1 输出格式

任务结束后，`TaskAnalyzer.synthesize_experience(...)` 生成：

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

### 5.2 字段设计理由

| 字段                         | 为什么需要                                          |
| ---------------------------- | --------------------------------------------------- |
| `schema_version`           | 经验格式可演进，避免后续改字段造成兼容性问题        |
| `problem.description`      | SkillOpt TaskRecord 的`intent` 来源               |
| `problem.task_type`        | 用于粗粒度任务筛选和标签                            |
| `problem.component`        | 对齐 SWE-bench 的 repo/component/changed_files 思路 |
| `solution.answer`          | SkillOpt TaskRecord 的`attempted_solution` 来源   |
| `solution.changed_files`   | 证明答案不是凭空生成，能关联到真实代码变化          |
| `solution.tests`           | 作为 validation evidence 和 rubric 依据             |
| `trajectory.tool_sequence` | 保留行为模式，为以后 skill mining 做准备            |
| `skillopt.compatible`      | 明确该样本可以导入 SkillOpt                         |

### 5.3 为什么不用纯 LLM 总结

替代方案：把整段 conversation 直接给 LLM，让它总结问题和经验。

没有采用的原因：

- LLM 总结可能遗漏文件修改和测试证据。
- 输出不稳定，不利于后续聚类和格式校验。
- 很难保证 SkillOpt 所需字段完整。
- 没有明确 schema，长期演进成本高。

当前方案是“规则化结构 + 证据字段 + 少量推断”，先保证数据契约稳定，再逐步增强推断能力。

## 6. 质量过滤设计

### 6.1 当前判定逻辑

MewCode 不会把所有轨迹都当作可优化经验。`TrajectoryEvaluator` 会检查：

- `task_success is True`
- 最新测试通过
- 没有 negative human feedback

满足条件才 `accepted=True`，并保存到 validated trajectory。

### 6.2 为什么需要质量过滤

SkillOpt 是从历史任务里学习规则，如果把失败轨迹也当成正样本，会污染优化过程：

- 失败解法可能被当成经验写入 skill。
- 没跑测试的任务无法作为可靠 validation evidence。
- 用户负反馈说明任务结果不应直接复用。

因此 MewCode 先做一层本地质量过滤，SkillOpt 再做一层 replay/gate。两层门控分别解决不同问题：

| 门控              | 解决的问题                                                   |
| ----------------- | ------------------------------------------------------------ |
| MewCode evaluator | 这个真实任务是否值得进入经验池                               |
| SkillOpt gate     | 基于这些经验产生的新 skill/memory 是否真的提升 held-out 表现 |

## 7. SkillOpt Adapter 设计

### 7.1 导出格式

MewCode 导出的 SkillOpt payload：

```json
{
  "format": "skillopt_sleep.tasks.v1",
  "project": "...",
  "transcript_source": "...",
  "n_sessions": 1,
  "target_skill_path": "...",
  "reviewed": true,
  "tasks": [
    {
      "id": "...",
      "project": "...",
      "intent": "problem.description",
      "context_excerpt": "files/tests/structured_experience",
      "system": "mewcode",
      "attempted_solution": "solution.answer",
      "outcome": "success",
      "reference_kind": "rubric",
      "reference": "A successful solution should: ...",
      "judge": {},
      "tags": ["coding", "trajectory", "skillopt-compatible", "bug_fix"],
      "source_sessions": ["..."],
      "origin": "real",
      "derived_from": "...",
      "skill_hint": ""
    }
  ]
}
```

### 7.2 为什么用 `reference_kind="rubric"`

SkillOpt 支持多种 reference：

| reference_kind | 特点                    | 是否适合 MewCode                                      |
| -------------- | ----------------------- | ----------------------------------------------------- |
| `exact`      | 要求输出包含精确答案    | 不适合，大多数开发任务没有唯一文本答案                |
| `rule`       | 需要结构化 judge checks | 适合可形式化任务，但真实开发任务不一定都有 rule judge |
| `rubric`     | 用 rubric 描述成功标准  | 适合真实开发经验，兼容 changed_files 和 tests         |
| `none`       | 只靠 outcome            | 信号太弱，不利于优化                                  |

MewCode 当前选择 `rubric`，原因是开发任务通常不是问答题，而是“修复一个代码行为”。成功标准更自然地表达为：

- 解决原始任务。
- 修改范围集中在相关文件。
- 通过或保留验证命令。
- 结果与已采集的解决证据一致。

### 7.3 为什么不直接把 MewCode 经验写入 SkillOpt skill

替代方案：MewCode 直接把总结出的经验追加到 skill 文件。

没有采用的原因：

- 缺少 held-out gate，容易把偶然经验写成错误规则。
- MewCode 自己做 skill 编辑会和 SkillOpt 职责重叠。
- 无法复用 SkillOpt 的 replay、judge、reflect 和 validation gate。
- 一旦写入错误经验，回滚和归因更困难。

当前设计让 MewCode 只负责提供真实任务样本，SkillOpt 负责“是否值得更新 skill”。职责边界更清楚。

## 8. Taxonomy 设计

### 8.1 问题背景

直接对完整问题文本 embedding 聚类有几个问题：

- 问题文本太长，包含很多上下文噪声。
- 相同任务类型可能因描述方式不同而距离很远。
- 聚类结果标签不稳定，不利于长期积累。
- 新任务边界模糊时，完全自动归类容易出错。

### 8.2 当前方案

先把长问题压缩成短的 problem signature：

```json
{
  "task_family": "authentication_debugging",
  "problem_pattern": "token_lifecycle_failure",
  "operation": "bug_fix",
  "domain": "web_security",
  "evidence_focus": ["token", "session", "expiration"],
  "failure_mode": "expired_token_reuse"
}
```

然后只对这个短 signature 编码、匹配和聚类。

### 8.3 normalized label 为什么必须固定

`normalized_label` 不应该由 LLM 每次动态生成，而应该来自稳定 taxonomy registry：

```json
{
  "label_id": "bug_fix.web_security.authentication_debugging.token_lifecycle_failure",
  "operation": "bug_fix",
  "domain": "web_security",
  "task_family": "authentication_debugging",
  "problem_pattern": "token_lifecycle_failure",
  "definition": "...",
  "status": "active"
}
```

原因：

- 稳定 label 才能做长期统计。
- 稳定 label 才能和 SkillOpt 优化结果关联。
- 动态 label 会导致同类任务被拆散。
- 面试追问里的关键点是 taxonomy drift，也就是标签漂移。固定 registry 是防止漂移的核心。

### 8.4 自动归类逻辑

当前 `TaxonomyAssigner` 的流程：

```text
ProblemSignature
  -> compatible labels by operation/domain
  -> score task_family + problem_pattern similarity
  -> if high score and enough margin: auto_assigned
  -> if medium score: needs_review
  -> otherwise: unassigned
```

当前状态：

- `auto_threshold = 0.82`
- `review_threshold = 0.70`
- `margin_threshold = 0.10`

状态含义：

| status            | 含义                                             |
| ----------------- | ------------------------------------------------ |
| `auto_assigned` | 高置信匹配，直接进入对应 label                   |
| `needs_review`  | 有候选 label，但分数或 margin 不够，需要人工确认 |
| `unassigned`    | 没有可靠 label，进入未知任务池                   |

### 8.5 为什么只聚类未知任务

如果所有任务都聚类，会浪费计算且引入不稳定性。当前选择：

```text
auto_assigned -> 直接按 label 统计和打分
needs_review / unassigned -> residual clustering
```

这样做的好处：

- 已知任务走稳定 taxonomy，不被聚类扰动。
- 只把不确定边界交给聚类。
- 人工审核集中在高价值未知区域。
- 新 label 的产生有证据和样本支持。

### 8.6 当前聚类实现

当前 `UnknownTaskClusterer`：

- 只接收 `unassigned` 和 `needs_review`。
- 先按 `bucket_key = operation::domain` 分桶。
- 在桶内基于 `family_pattern_text` 做 Jaccard 相似度聚类。
- 小于 `min_cluster_size` 的任务进入 noise。
- 聚类结果转成人工审核包。

这是一个轻量确定性实现，适合当前阶段验证数据流。

### 8.7 为什么暂时不用复杂 embedding/HDBSCAN

可选方案：

| 方案                                            | 优点                 | 问题                                 |
| ----------------------------------------------- | -------------------- | ------------------------------------ |
| full problem embedding + KMeans                 | 实现简单             | 长文本噪声大，K 值难定，标签不稳定   |
| embedding + HDBSCAN                             | 能发现任意形状簇     | 参数敏感，小样本不稳定，需要向量依赖 |
| LLM 直接生成 label                              | 语义强               | 标签漂移严重，难以长期统计           |
| supervised classifier                           | 稳定                 | 需要大量标注样本                     |
| 当前 signature + registry + residual clustering | 稳定、可解释、低成本 | 初期需要维护 taxonomy，语义召回有限  |

当前阶段选择轻量方案，是因为项目目标不是做最强 clustering，而是先保证：

- 标签稳定。
- 数据链路可解释。
- 未知任务能被发现。
- 人工审核闭环能成立。

后续可以把 `SignatureEncoder` 从字符串/Jaccard 替换成 embedding，而不改变上层数据结构。

## 9. Human Review 设计

对于未知聚类，系统生成 `HumanReviewPackage`：

```json
{
  "review_id": "...",
  "candidate_cluster_id": "...",
  "bucket_key": "bug_fix::web_security",
  "representative_signature": {...},
  "member_count": 5,
  "uncertainty_reason": "unassigned signatures formed a similar residual cluster",
  "suggested_actions": [
    "assign_to_existing_label",
    "create_new_label",
    "split_cluster",
    "mark_as_noise"
  ],
  "examples": [
    {
      "task_id": "...",
      "generated_problem": "...",
      "raw_problem_excerpt": "...",
      "changed_files": [],
      "tests": []
    }
  ]
}
```

为什么要保留 examples：

- 人工不能只看模型标签，要看原始问题和证据。
- 需要知道为什么系统不确定。
- 新建 label 时需要真实样本支撑定义。

## 10. SkillOpt 迭代机制

SkillOpt 的核心不是简单存经验，而是验证门控优化：

```text
TaskRecord batch
  -> split train / val / test
  -> replay current skill/memory
  -> judge each task
  -> collect failures and successes
  -> reflect proposes bounded edits
  -> apply edits to candidate skill/memory
  -> replay candidate on val
  -> accept only if val score improves
  -> stage proposal
  -> optional adopt
```

关键点：

- `train` 驱动反思。
- `val` 决定是否接受候选 skill/memory。
- `test` 可以做最终 held-out 评估。
- `dream` 任务只允许增强训练池，不允许进入 val/test。
- `gate_no_regression` 可以防止个别任务退化。

### 10.1 为什么需要 validation gate

如果没有 gate，LLM 反思会有几个风险：

- 把失败样本过拟合成非常窄的规则。
- 生成看似合理但实际降分的 skill。
- 破坏已有任务表现。
- 把噪声经验写入长期 memory。

SkillOpt 的 gate 让优化变成可验证更新：

```text
candidate_score > baseline_score -> accept
otherwise -> reject
```

这也是为什么 MewCode 不应该自己直接写 skill，而应该把经验交给 SkillOpt。

## 11. 当前已验证结果

本地已经跑过：

```text
python -m pytest tests\test_task_taxonomy.py tests\test_task_experience_synthesis.py -q
```

结果：

```text
8 passed
```

也跑过自进化相关模块编译：

```text
python -m py_compile evolution\task_taxonomy\*.py evolution\task\task_analyzer.py evolution\skillopt_adapter.py evolution\trajectory\manager.py evolution\trajectory\storage.py agent.py
```

结果：通过。

SkillOpt loader 读取 MewCode probe payload：

```text
1 skillopt_sleep.tasks.v1 True rubric dict True
```

含义：

- 读到 1 条任务。
- 格式是 `skillopt_sleep.tasks.v1`。
- `reviewed=True`。
- `reference_kind=rubric`。
- `judge` 是 dict。
- `context_excerpt` 包含 `mewcode.task_experience.v1`。

SkillOpt dry-run 单条 MewCode 任务：

```text
n_tasks=1
exit_code=0
```

SkillOpt dry-run 20 条 SWE-bench 对齐样本：

```text
n_tasks=20
exit_code=0
```

注意：dry-run 结果 `accepted=false` 不代表数据不可用。mock backend 下 baseline 和 candidate 分数相同，没有产生能提升验证集的新编辑，所以 gate reject 是正常结果。关键验证点是 payload 可以被 SkillOpt 加载、replay、judge 和 gate。

## 12. 与相似方法的对比

### 12.1 和普通 RAG memory 的区别

普通 RAG memory：

```text
past text -> embedding -> retrieve -> stuff into prompt
```

MewCode + SkillOpt：

```text
real task trajectory -> structured TaskRecord -> replay/judge -> reflect -> gated skill update
```

区别：

- RAG 是检索过去内容，不保证过去内容正确。
- SkillOpt 是用验证集决定是否把经验固化成 skill/memory。
- MewCode 的价值是把真实开发过程变成可 replay 的训练单元，而不是只存聊天记录。

### 12.2 和微调的区别

微调：

- 需要大量高质量数据。
- 成本高。
- 更新慢。
- 不容易回滚。
- 很难对单个项目做快速局部优化。

当前方案：

- 不改模型参数。
- 只更新 skill/memory 文档。
- 可 review、可 stage、可 rollback。
- 更适合个人项目和秋招项目场景。

### 12.3 和直接人工写经验的区别

人工写经验：

- 准确但成本高。
- 很难覆盖所有真实任务。
- 容易遗漏执行证据。

当前方案：

- 自动从真实任务采集样本。
- 成功任务才进入经验池。
- 不确定类别交给人工审核。
- 人工只处理边界问题，而不是全量标注。

### 12.4 和 SWE-bench 的关系

SWE-bench 是 benchmark dataset：

```text
issue/problem_statement + repo + patch/test evidence
```

MewCode 的目标不是复刻 SWE-bench 环境，而是借鉴它的数据形态：

```text
real user development task + repository context + changed_files + tests + answer
```

因此前期验证只需要 metadata-level 对齐和 SkillOpt dry-run，不需要 Docker 跑完整 SWE-bench 环境。

## 13. 当前边界和后续增强

### 13.1 已完成

- 真实任务轨迹采集。
- 任务结束后合成 problem/answer/structured_experience。
- 成功轨迹质量过滤。
- SkillOpt TaskRecord 导出。
- SWE-bench 20 条 metadata-level 兼容验证。
- taxonomy 独立模块拆分。
- unknown clustering 和 human review package。

### 13.2 当前边界

- taxonomy 模块已经拆出，但还没有完全接入 trajectory -> SkillOpt export 主流程。
- 当前 signature 生成仍偏规则/浅层推断，后续可以接 LLM structured extraction。
- 当前 clustering 是轻量 Jaccard，不是 embedding/HDBSCAN。
- normalized label registry 还需要持久化治理和版本管理。
- rubric judge 对真实开发任务是弱验证，未来可以增强为更强的 test-aware 或 repo-aware judge。

### 13.3 后续最值得做的增强

1. 把 `ProblemSignature` 生成接入 `synthesize_experience`。
2. 增加 taxonomy registry 文件和版本号。
3. 导出 SkillOpt TaskRecord 时带上 `normalized_label` 和 assignment status。
4. 对 `needs_review/unassigned` 自动生成 review package。
5. 人工确认后回写 taxonomy registry。
6. 用 embedding 替换 `SignatureEncoder` 内部相似度，但保持外部 schema 不变。
7. 对 accepted SkillOpt updates 反向关联到 label，统计哪些任务族最能产生优化收益。

## 14. 面试追问准备

### Q1: 为什么不直接对用户问题 embedding 聚类？

因为用户问题太长且噪声大，里面混有上下文、代码片段、错误日志、无关描述。直接 embedding 会导致同一类任务被描述风格影响。当前先抽取 `task_family/problem_pattern/operation/domain`，再对短 signature 编码，降低噪声，并保持 taxonomy 可解释。

### Q2: normalized label 为什么不能动态生成？

因为动态 label 会漂移。同一个问题今天叫 `auth_token_bug`，明天叫 `token_expiry_debugging`，长期统计和 SkillOpt 优化归因都会失效。固定 registry 可以保证 label 稳定，未知任务通过人工审核扩展 taxonomy。

### Q3: 为什么只聚类未知任务？

已知任务已经能稳定归类，继续聚类只会引入不稳定性。聚类的价值在 residual unknown set，也就是系统无法确定边界的任务。这样可以降低计算和人工审核成本。

### Q4: 为什么用 SkillOpt，而不是自己做经验抽象和规则写入？

自己写入经验缺少 held-out gate，容易把错误经验固化。SkillOpt 已经提供 replay、judge、reflect、gate、stage/adopt，MewCode 上游只需要生成高质量 TaskRecord。这样职责清晰，也避免重复造优化器。

### Q5: 真实开发任务没有标准答案，SkillOpt 怎么 judge？

当前使用 `reference_kind=rubric`。rubric 不要求唯一文本答案，而是描述成功条件，例如解决任务、修改相关文件、通过测试、与采集到的解法证据一致。对代码任务来说，这比 exact answer 更合理。

### Q6: 如何防止失败经验污染系统？

两层过滤：

1. MewCode evaluator 只保留任务完成、测试通过、无负反馈的轨迹。
2. SkillOpt gate 只接受能提升验证集分数的候选 skill/memory。

### Q7: 为什么任务结束后再合成问题？

因为开始时不知道真实 component、changed_files、validation command 和成功状态。结束后有执行证据，问题描述和答案更可靠，也更像 SWE-bench 的数据结构。

### Q8: 如果测试没跑，经验还保留吗？

当前强 accepted 逻辑依赖 task_success 和 test_pass。没有测试的任务很难作为高置信训练样本。后续可以增加人工确认或弱标签通道，但默认不应把无验证任务直接作为正样本。

### Q9: 这个系统怎么持续迭代？

每完成真实任务，MewCode 都可能产生一个 validated experience。批量经验导入 SkillOpt 后，SkillOpt replay 当前 skill/memory，基于失败样本反思出候选编辑，再用 validation gate 决定是否接受。accepted update 可以继续影响未来任务表现，未来任务又继续产生新经验。

### Q10: 最大风险是什么？

最大风险是数据质量和标签漂移。解决方式是 schema version、质量过滤、固定 taxonomy registry、unknown review、人机协同扩展 label，以及 SkillOpt 的 validation gate。

## 15. 可以总结成的技术贡献

项目中自进化部分的技术贡献可以概括为：

1. 设计了从真实 agent 开发轨迹到 SkillOpt-compatible TaskRecord 的数据构建链路。
2. 使用任务结束后的后验合成，保证 problem/answer/validation evidence 来自真实执行结果。
3. 引入质量过滤，避免失败轨迹污染经验池。
4. 将长问题压缩为稳定 ProblemSignature，再通过固定 taxonomy registry 归类，降低 embedding 聚类噪声和标签漂移。
5. 对 unknown residual tasks 做聚类和人工审核，把人工成本集中在边界任务上。
6. 通过 SkillOpt 的 replay-reflect-gate 机制，把经验从“存储”推进到“验证过的 skill/memory 更新”。

## 16. 参考方法和项目坐标系

这一节用于回答面试官常见追问：你的方法有没有参考已有工作？和 RAG、Reflexion、DSPy、SWE-bench、Voyager、SkillOpt 的关系是什么？

简短定位：MewCode 自进化不是从零发明优化算法，而是把多个成熟方向组合到真实软件开发场景。它借鉴 SWE-bench 的真实软件工程任务数据形态，借鉴 ReAct/SWE-agent/OpenHands 的轨迹与环境交互思想，借鉴 Reflexion/Self-Refine 的反馈反思思想，借鉴 SkillOpt/DSPy 的验证驱动优化思想，借鉴 active learning 的不确定样本人工审核思想。

### 16.1 SkillOpt

参考项目：

- [SkillOpt GitHub](https://github.com/microsoft/SkillOpt)
- [SkillOpt Documentation](https://microsoft.github.io/SkillOpt/docs/guideline.html)
- [SkillOpt project page](https://microsoft.github.io/SkillOpt/)

SkillOpt 的核心思想是：不更新模型参数，而是把自然语言 skill 文档当成可训练对象。系统 replay 一批任务，收集成功和失败，优化器根据这些证据生成候选 skill/memory 编辑，然后用 held-out validation gate 判断是否接受。

MewCode 借鉴它的地方：

- 不做 fine-tuning，而是优化外部 skill/memory。
- 经验不能只靠模型总结，必须能 replay 和 judge。
- skill 更新必须经过 validation gate，而不是直接写入长期记忆。
- TaskRecord 需要包含 intent、context、attempted_solution、reference/judge 等字段。

MewCode 不直接复刻 SkillOpt 的原因：

- SkillOpt 假设已经有可 replay 的 TaskRecord。
- MewCode 要解决的是 TaskRecord 从哪里来。
- 真实开发任务没有标准 benchmark judge，所以要从 trajectory 后验合成 problem、solution、changed_files、tests 和 rubric。

因此两者是上下游关系：

```text
MewCode: real coding task -> structured experience -> SkillOpt TaskRecord
SkillOpt: TaskRecord -> replay / reflect / gate -> better skill or memory
```

面试中可以强调：我没有重新实现 SkillOpt 的优化器，而是把重点放在更难落地的数据问题上，即真实开发任务如何自动变成 SkillOpt-compatible experience。

### 16.2 SWE-bench

参考项目：

- [SWE-bench GitHub](https://github.com/SWE-bench/SWE-bench)
- [SWE-bench Princeton blog](https://pli.princeton.edu/blog/2023/swe-bench-can-language-models-resolve-real-world-github-issues)

SWE-bench 的任务结构大致是：

```text
GitHub issue / problem_statement
  + repository
  + changed files or patch evidence
  + tests that verify the fix
```

它给 MewCode 的启发不是一定要跑 Docker，而是软件工程经验样本应该包含真实问题、仓库上下文、修改证据和验证信号。

MewCode 借鉴它的地方：

- `problem.description` 对应 `problem_statement`。
- `repository` 对应真实项目上下文。
- `solution.changed_files` 对应 patch/changing files evidence。
- `solution.tests` 对应 validation signal。
- `task_type/component` 用于把自然语言任务映射到代码区域。

MewCode 没有完全照搬 SWE-bench：

- 不要求公开 GitHub issue。
- 不要求 gold patch。
- 不强依赖 Docker 环境。
- 任务来自本地真实 agent 开发过程。

所以当前的 SWE-bench 20 条验证是 metadata-level compatibility validation：证明 MewCode 产出的问题、组件、答案证据和 SkillOpt 输入结构是同一类数据形态。

### 16.3 SWE-agent 和 OpenHands

参考项目：

- [SWE-agent GitHub](https://github.com/SWE-agent/SWE-agent)
- [OpenHands GitHub](https://github.com/OpenHands/OpenHands)

SWE-agent 和 OpenHands 代表的是 software engineering agent 方向：让 agent 在真实代码仓库里浏览文件、编辑代码、运行命令、修复问题。

MewCode 借鉴它们的地方：

- 软件开发 agent 不是一次性问答，而是持续和环境交互。
- tool call、file edit、test result 是任务解决过程的核心证据。
- 轨迹比最终回复更重要，因为轨迹能解释 agent 如何定位、尝试、验证。

差异是：

```text
SWE-agent / OpenHands: how to solve a software engineering task
MewCode self-evolution: how to turn solved tasks into reusable optimization data
```

也就是说，MewCode 的关注点不是只提升单次解题能力，而是把每次成功开发沉淀为后续 SkillOpt 可利用的数据资产。

### 16.4 ReAct

参考方法：

- [ReAct project page](https://react-lm.github.io/)

ReAct 的核心范式是 reasoning + acting：模型交替进行思考、行动、观察，再继续行动。对 MewCode 有启发的是“行为轨迹”而不是“最终答案”。

MewCode 借鉴点：

- agent 行为要和环境反馈绑定。
- observation/test output 可以减少幻觉。
- 轨迹应该成为后续学习的原始材料。

MewCode 没有直接保存或依赖完整 chain-of-thought，而是保存更可审计的工程证据：

```text
task_start -> tool_call -> tool_result -> file_modification -> test_result -> task_end
```

这样更适合工程系统，也更容易做隐私和安全控制。

### 16.5 Reflexion

参考项目：

- [Reflexion GitHub](https://github.com/noahshinn/reflexion)
- [Reflexion arXiv](https://doi.org/10.48550/arXiv.2303.11366)

Reflexion 的思想是：语言 agent 可以根据任务反馈生成 verbal reflection，并把 reflection 放进 memory，影响后续尝试。

MewCode 借鉴点：

- 不更新模型参数，也能通过外部语言经验提升表现。
- 失败反馈可以转成可读经验。
- memory 可以作为跨任务学习载体。

MewCode 不直接采用 Reflexion 的地方：

- Reflexion 的 reflection 往往直接进入 memory，质量不一定有 gate。
- reflection memory 容易膨胀，也可能沉淀错误经验。
- 它更像 trial-level self-improvement，而 MewCode 要做 project-level experience mining。

核心差异：

```text
Reflexion:
  feedback -> reflection text -> memory

MewCode + SkillOpt:
  real trajectory -> structured TaskRecord -> replay / gate -> accepted skill or memory update
```

面试中可以说：MewCode 借鉴了“语言经验可以作为学习对象”，但用结构化任务样本和 SkillOpt gate 来控制经验质量。

### 16.6 Self-Refine

参考项目：

- [Self-Refine GitHub](https://github.com/madaan/self-refine)
- [Self-Refine project page](https://selfrefine.info/)

Self-Refine 的循环是：

```text
generate -> feedback -> refine -> repeat
```

它主要提升单次输出质量。

MewCode 借鉴点：

- LLM 可以生成反馈并迭代改进。
- 反馈文本可以约束下一轮输出。

差异：

- Self-Refine 关注当前答案如何变好。
- MewCode 关注一次成功开发任务如何变成后续可复用经验。
- Self-Refine 不天然包含 repo、changed_files、tests 和 SkillOpt TaskRecord 契约。

一句话区别：Self-Refine 优化 one answer，MewCode 抽取 one completed development task 中的 reusable experience。

### 16.7 Voyager

参考项目：

- [Voyager GitHub](https://github.com/MineDojo/Voyager)

Voyager 是 lifelong learning agent 的代表项目，在 Minecraft 环境中通过自动课程、环境反馈和 skill library 持续积累能力。

MewCode 借鉴点：

- 不微调模型，也能通过外部 skill library 积累能力。
- 技能应该可解释、可组合、可复用。
- 环境反馈和执行错误可以驱动技能改进。

MewCode 不照搬 Voyager：

- Voyager 的任务空间是开放世界探索。
- MewCode 的任务空间是真实代码仓库和开发任务。
- Voyager 更偏 executable code skill library，MewCode 当前更偏 SkillOpt-compatible natural-language skill/memory optimization。

对比：

```text
Voyager: environment exploration -> executable skill library
MewCode: real coding sessions -> structured experience -> natural-language skill optimization
```

### 16.8 DSPy

参考项目：

- [DSPy](https://dspy.ai/)
- [DSPy GitHub](https://github.com/stanfordnlp/dspy)

DSPy 的核心思想是把 prompt/program 优化变成可声明、可评估、可优化的问题。它用 Signature 描述输入输出，用 metric 评估，用 optimizer 自动改 prompt 或 few-shot examples。

MewCode 借鉴点：

- 不手写所有 prompt，而是让系统基于数据和 metric 优化。
- 结构化 signature 比任意长 prompt 更适合优化。
- 没有数据和评估指标，就没有可靠优化。

为什么没有直接用 DSPy：

- DSPy 更适合已有 trainset 和 metric 的 LLM program 优化。
- MewCode 当前最难的是从真实开发历史构造 trainset。
- SkillOpt 的 skill/memory 文档优化和 validation gate 更贴合当前项目。

三者关系可以这样讲：

```text
DSPy asks: given data and metric, how to optimize an LLM program?
SkillOpt asks: given replayable tasks, how to optimize a skill document?
MewCode asks: how do real development tasks become replayable tasks?
```

### 16.9 RAG 和长期记忆系统

参考项目：

- [MemGPT project page](https://research.memgpt.ai/)

典型 RAG/long-term memory 的方式是：

```text
store text chunks -> embed -> retrieve -> inject into prompt
```

MewCode 会借鉴 retrieval 的思想，但不采用纯 RAG 作为自进化核心。

原因：

- RAG 解决的是“找回过去内容”，不是“判断过去内容是否应该固化为经验”。
- RAG 可能取回错误、过时或一次性的经验。
- RAG 没有 validation gate。
- RAG 不会自动把多次失败/成功归纳成稳定 skill。

更合理的位置是：

```text
validated structured experiences -> taxonomy / embedding retrieval -> context construction
validated repeated patterns -> SkillOpt consolidation -> stable skill/memory
```

所以 MewCode 不是不用 RAG，而是不把 RAG 当成最终学习机制。

### 16.10 Active Learning 和 Reject Option

参考方法：

- [Active Learning Literature Survey](https://minds.wisconsin.edu/handle/1793/60660)
- [Classification with reject option](https://academic.oup.com/bioinformatics/article/24/17/1889/263502)

Active learning 的核心是：人工标注成本高，系统应该把最不确定、最有价值的样本交给人。

Reject option 的核心是：模型不确定时可以拒绝预测，而不是强行输出一个可能错误的 label。

MewCode taxonomy 设计正是这个思想：

```text
auto_assigned -> 直接使用固定 label
needs_review -> 给出候选 label 和原因，交给人工确认
unassigned -> 进入 unknown pool，聚类后人工判断
```

为什么这样设计：

- 全量人工标注成本太高。
- 全量自动标注会产生错误标签。
- 只审核未知边界，可以降低成本并控制 taxonomy drift。

### 16.11 Snorkel / Weak Supervision

参考项目：

- [Snorkel paper](https://pmc.ncbi.nlm.nih.gov/articles/PMC7075849/)
- [Snorkel GitHub](https://github.com/snorkel-team/snorkel)

Snorkel 的启发是：训练数据构建本身是系统瓶颈，可以用弱监督、人机协作和规则信号来构造数据。

MewCode 当前也在做类似事情，只是目标不是训练分类模型，而是构造 SkillOpt TaskRecord。

MewCode 的弱信号包括：

- 用户任务文本。
- memory 和 repo context。
- changed_files。
- test command 和 passed 状态。
- final answer。
- task_type/component 推断。
- taxonomy assignment score。

对比：

```text
Snorkel: weak signals -> labels -> supervised model training data
MewCode: execution signals -> structured experiences -> SkillOpt training data
```

### 16.12 HDBSCAN 和 unknown clustering

参考方法：

- [hdbscan JOSS paper](https://joss.theoj.org/papers/10.21105/joss.00205)

HDBSCAN 适合 unknown discovery，因为它不需要预先指定 K，也可以把孤立点标为 noise。

为什么当前没有直接用 HDBSCAN：

- 当前样本量还小，优先保证 schema 和 review flow 稳定。
- 直接对长问题 embedding 后做 HDBSCAN，仍会受文本噪声影响。
- 引入 embedding、距离度量、参数调优会增加复杂度。
- 面试项目阶段，更需要可解释、可测试、可演示的确定性链路。

未来推荐升级方式：

```text
ProblemSignature
  -> embedding(family + pattern + evidence)
  -> HDBSCAN only on needs_review / unassigned
  -> candidate clusters
  -> human review
```

也就是说，HDBSCAN 可以替换当前 clustering 内部实现，但不应该替换“固定 taxonomy + reject option + unknown review”的外层设计。

## 17. 更完整的设计取舍矩阵

| 方案                | 能解决什么                | 不足                                   | MewCode 当前选择                                    |
| ------------------- | ------------------------- | -------------------------------------- | --------------------------------------------------- |
| Fine-tuning         | 把经验写入模型参数        | 成本高、不可解释、难回滚、小样本不适合 | 不选，改用 SkillOpt 优化外部 skill/memory           |
| RAG memory          | 检索历史经验              | 不验证经验对错，容易注入噪声           | 可作为 retrieval 层，但不能替代 gate                |
| Reflexion           | 从反馈生成语言反思        | reflection 质量不稳定，容易膨胀        | 借鉴反馈反思，但用结构化经验和 SkillOpt gate 固化   |
| Self-Refine         | 单次输出迭代改进          | 不形成跨任务经验                       | 可用于执行阶段，不替代经验沉淀                      |
| Voyager             | lifelong skill library    | 场景是 Minecraft，技能形式不同         | 借鉴 skill library 思想，不照搬任务体系             |
| DSPy                | 优化 LLM program/prompt   | 需要已有 trainset/metric               | MewCode 构造 trainset，SkillOpt 优化 skill document |
| SWE-bench           | 真实软件工程任务数据形态  | benchmark 运行成本高                   | 借鉴 schema 思想，不强依赖 Docker                   |
| SWE-agent/OpenHands | 工程 agent 解题与环境交互 | 重点是完成任务，不是经验资产治理       | 借鉴轨迹和环境反馈                                  |
| HDBSCAN             | unknown clustering        | 需要向量和参数，小样本不稳定           | 后续替换 residual clustering 内核                   |
| Snorkel             | weak supervision 数据构建 | 偏分类训练数据，不是 SkillOpt task     | 借鉴弱信号和人机协作数据构建                        |
| Active learning     | 人工只标最有价值样本      | 需要不确定性估计                       | 已用于 needs_review / unassigned 设计               |

## 18. 推荐的后续增强路线

### 18.1 把 taxonomy 接入主链路

目标：

```text
TaskTrajectory
  -> structured_experience
  -> ProblemSignature
  -> LabelAssignment
  -> SkillOpt TaskRecord tags/context
```

建议在 `structured_experience` 中新增：

```json
{
  "taxonomy": {
    "signature": {
      "task_family": "...",
      "problem_pattern": "...",
      "operation": "...",
      "domain": "..."
    },
    "assignment": {
      "status": "auto_assigned",
      "normalized_label": "...",
      "score": 0.91,
      "taxonomy_version": "2026-08-23"
    }
  }
}
```

这样 SkillOpt 后续可以按 normalized_label 分组统计优化收益。

### 18.2 用 LLM 做 structured extraction，但不让它直接决定 label

LLM 可以输入：

```text
problem.description
changed_files
tests
final answer
execution_context_excerpt
```

输出：

```text
task_family
problem_pattern
operation
domain
evidence_focus
failure_mode
```

但是 normalized_label 仍必须由 registry assignment 决定。原因是 label 是长期统计主键，不能让 LLM 每次动态命名。

### 18.3 建立版本化 taxonomy registry

建议格式：

```json
{
  "taxonomy_version": "2026-08-23",
  "labels": [
    {
      "label_id": "bug_fix.web_security.authentication_debugging.token_lifecycle_failure",
      "operation": "bug_fix",
      "domain": "web_security",
      "task_family": "authentication_debugging",
      "problem_pattern": "token_lifecycle_failure",
      "definition": "...",
      "status": "active"
    }
  ]
}
```

治理规则：

- `label_id` 创建后不要随意改名。
- 废弃 label 用 `status=deprecated`，不要物理删除。
- 合并 label 要保留 alias。
- 新 label 必须带 examples 和人工审核理由。

### 18.4 将 unknown clustering 升级为 embedding + HDBSCAN

当前是确定性 Jaccard，适合早期验证。后续可以升级为：

```text
operation/domain bucket
  -> signature embedding
  -> HDBSCAN
  -> cluster confidence
  -> human review package
```

但保持外层不变：只有 `needs_review` 和 `unassigned` 进入聚类，`auto_assigned` 不参与聚类。

### 18.5 SkillOpt 反馈回流

当前主要是：

```text
MewCode -> SkillOpt
```

后续可以做：

```text
SkillOpt accepted/rejected edits
  -> associated normalized_label
  -> label-level improvement statistics
  -> prioritize future mining/review
```

这样可以回答更高阶的问题：

- 哪些任务族最容易产生可复用经验？
- 哪些 label 经常导致 SkillOpt reject？
- 哪些 domain 的经验质量差，需要更多人工审核？
- 哪类开发任务最值得优先优化？

## 19. 更强的面试追问回答

### Q11: 你这个和 RAG-based memory 最大区别是什么？

RAG 是 retrieval-time memory，解决的是“过去有没有相关内容”。MewCode + SkillOpt 是 training-time consolidation，解决的是“过去的经验是否应该变成稳定规则”。RAG 可能取回错误经验，SkillOpt gate 会拒绝没有带来验证收益的候选经验。

### Q12: 为什么不把每次成功任务都直接存进向量库？

可以存，但不能只存。向量库适合召回，不适合治理经验质量。成功任务也可能是一次性修复，不一定能成为通用 skill。当前设计先结构化、质量过滤、taxonomy 归类，再决定如何用于 SkillOpt 优化。

### Q13: 你的标签体系和传统分类器有什么区别？

传统分类器通常输入文本直接输出 label。MewCode 是两段式：

```text
long problem -> short ProblemSignature -> fixed taxonomy assignment
```

这样可以减少长文本噪声和 label drift。并且系统有 reject option，低置信任务不会强行分类。

### Q14: 为什么不直接让 LLM 判断 normalized_label？

LLM 可以辅助生成 signature，但不应该直接创造 normalized_label。normalized_label 是长期数据主键，如果动态生成，会导致统计口径漂移。正确做法是 LLM 生成候选语义，registry 决定最终标签。

### Q15: 如果 taxonomy 初始很少，会不会效果不好？

初始 taxonomy 少是正常的，所以设计了 `unassigned`、`needs_review` 和 unknown clustering。系统不是假设一开始 taxonomy 完整，而是让 taxonomy 随真实任务增长，并通过人工审核保证新 label 质量。

### Q16: 为什么当前聚类用简单 Jaccard，不直接用 embedding？

因为当前项目阶段更需要可解释和稳定的数据流。Jaccard 方便测试和调参，不依赖外部 embedding 服务。后续可以把 encoder 内部替换成 embedding + HDBSCAN，但不改变外部 schema。

### Q17: 真实代码任务的答案不是自然语言，为什么 SkillOpt 的 attempted_solution 可以是文本？

SkillOpt 的 `attempted_solution` 不是代码 patch 本身，而是任务经验的可读解答：问题是什么、改了哪些文件、验证命令是什么、最终结论是什么。真正的代码证据保存在 changed_files、trajectory 和 tests 里。对 SkillOpt 来说，它需要的是能 replay/judge/reflect 的任务记录，而不是完整 patch 文件。

### Q18: 如何避免模型自己生成的经验互相污染？

三层控制：

1. 经验来自真实执行轨迹，不只是模型编造。
2. MewCode evaluator 过滤失败或无验证任务。
3. SkillOpt validation gate 只接受 held-out 提升的 skill/memory 编辑。

### Q19: 这个系统的核心难点不是优化，而是数据吗？

是的。优化器可以复用 SkillOpt，但真实开发任务如何转成可优化数据，是当前项目的核心难点。难点包括任务边界识别、后验问题重建、答案证据绑定、标签稳定性、未知类别发现和人工审核闭环。

### Q20: 如果面试官问创新点怎么落地？

可以回答：

> 我做的是一个真实开发任务的经验数据引擎。它把 agent 在项目里的每次成功开发轨迹转成结构化 TaskRecord，带有 problem、solution、changed_files、tests 和 taxonomy label。然后这些样本可以输入 SkillOpt，通过 replay-reflect-gate 机制优化长期 skill/memory。相比只做 RAG memory，它有质量过滤和验证门控；相比微调，它低成本、可解释、可回滚；相比直接聚类问题文本，它通过固定 taxonomy 和 unknown review 避免 label drift。
