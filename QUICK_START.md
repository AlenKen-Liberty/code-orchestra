# 快速开始指南

## 一句话概括
多个 LLM 按顺序协作完成工作：Opus 设计 → Codex 编码 → Haiku 审核。

## 最简单的使用方法

```bash
# 运行3阶段流程：设计 → 编码 → 审核
python3 scripts/run_pipeline.py \
  --pipeline workflows/current_pipeline.yaml \
  --task "创建一个 Python CLI 工具，可以把 Markdown 文件转换为 HTML"
```

输出将显示 JSON 格式的结果：
- `planning` - Opus 的设计方案
- `coding` - Codex 生成的代码
- `code_review` - Haiku 的审核意见

## 关键特性

### 1. 数据自动流转
每个阶段的输出会自动注入到下一个阶段的 Prompt 中。无需手动复制粘贴。

```yaml
# current_pipeline.yaml 中：
- stage_id: coding
  input:
    source: planning.architecture_plan  # ← 自动注入
```

### 2. YAML 配置流程
易于修改流程、添加新阶段或改变模型：

```bash
# 想使用不同的Opus版本？
# 编辑 workflows/current_pipeline.yaml，改这一行：
model: "claude-opus-4-6"  # → 改为其他版本
```

### 3. 完整的制品保存
所有中间结果自动保存到 `./artifacts/` 目录：
- `artifacts/planning_output.txt` - 设计方案
- `artifacts/coding_output.txt` - 代码实现
- `artifacts/code_review_output.txt` - 审核反馈

### 4. 详细的执行日志

```bash
# 带详细日志运行
python3 scripts/run_pipeline.py \
  --pipeline workflows/current_pipeline.yaml \
  --task "..." \
  --verbose \
  --output results.json
```

## 工作流图解

```
┌─────────────────────────────────────────────────┐
│  输入: "创建一个 TODO 应用"                    │
└────────────────┬────────────────────────────────┘
                 │
        ┌────────▼─────────┐
        │  Stage 1: Opus   │
        │  (设计架构)      │
        └────────┬─────────┘
                 │
          [架构设计文档]
                 │
        ┌────────▼─────────┐
        │ Stage 2: Codex   │
        │ (编码实现)       │
        │ 输入: 设计文档   │
        └────────┬─────────┘
                 │
           [生成的代码]
                 │
        ┌────────▼──────────┐
        │ Stage 3: Haiku    │
        │ (代码审核)        │
        │ 输入: 设计+代码   │
        └────────┬──────────┘
                 │
        [审核意见和改进建议]
                 │
        ┌────────▼──────────┐
        │   JSON 输出       │
        └───────────────────┘
```

## 每个 Stage 的作用

### Stage 1: Planning (Claude Opus)
**职责**: 系统架构设计
- 模块和组件划分
- 技术栈选择
- 实现步骤规划
- 风险评估

**输出**: 结构化的架构设计文档

### Stage 2: Coding (GPT-5.2 Codex)
**职责**: 代码实现
- 根据架构设计生成代码
- 添加错误处理和日志
- 类型注解和文档字符串
- 包括测试框架

**输入**: Stage 1 的设计文档
**输出**: 完整的可运行代码

### Stage 3: Code Review (Claude Haiku)
**职责**: 代码质量审查
- 检查是否实现了设计
- 代码质量评估
- 安全性检查
- 测试覆盖验证

**输入**: Stage 1 的设计 + Stage 2 的代码
**输出**: 详细的审核反馈

## 实际例子

### 例 1: 简单任务
```bash
python3 scripts/run_pipeline.py \
  --pipeline workflows/current_pipeline.yaml \
  --task "实现一个函数，计算斐波那契数列的第 n 项" \
  --output fib_results.json
```

### 例 2: 完整应用
```bash
python3 scripts/run_pipeline.py \
  --pipeline workflows/current_pipeline.yaml \
  --task "设计并实现一个 REST API 服务，用于管理用户的任务列表。需要支持创建、更新、删除、列表查询等操作，使用 Python 和 SQLite。" \
  --output api_results.json \
  --verbose
```

### 例 3: 数据处理
```bash
python3 scripts/run_pipeline.py \
  --pipeline workflows/current_pipeline.yaml \
  --task "创建一个数据处理脚本，读取 CSV 文件，进行数据清洗（处理缺失值、重复）、数据转换（归一化、分类编码），最后保存为 JSON。" \
  --output data_pipeline_results.json
```

## 查看结果

### 1. JSON 格式输出
```bash
cat results.json | python3 -m json.tool
```

输出结构：
```json
{
  "planning": {
    "status": "success",
    "output": "...",
    "execution_time": 45.2,
    "model_used": "claude-opus-4-6"
  },
  "coding": {
    "status": "success",
    "output": "...",
    "execution_time": 78.5,
    "model_used": "gpt-5.2-codex"
  },
  "code_review": {
    "status": "success",
    "output": "...",
    "execution_time": 32.1,
    "model_used": "claude-haiku-4-5-20251001"
  }
}
```

### 2. 查看 artifacts（推荐）
```bash
# 查看设计文档
cat artifacts/planning_output.txt

# 查看生成的代码
cat artifacts/coding_output.txt

# 查看审核意见
cat artifacts/code_review_output.txt
```

## Haiku 的特殊优势

在代码审查阶段使用 Haiku（而不是 Opus）的原因：

1. **成本效益** - Haiku 价格更低
2. **速度快** - 响应速度快，适合审查任务
3. **足够聪慧** - Haiku 4.5 足以完成代码审查
4. **专注审查** - 不需要设计新方案，只需评价现有代码

## 扩展：从 3 阶段到 5 阶段（加入 Gemini）

当 `geminicli` 可用后，可以使用 `multi_llm_pipeline.yaml`：

```bash
python3 scripts/run_pipeline.py \
  --pipeline workflows/multi_llm_pipeline.yaml \
  --task "..." \
  --output full_results.json
```

这会使用：
1. Opus - 初始设计
2. **Gemini** - 设计审核（多轮讨论）
3. Codex - 编码
4. **Gemini** - 代码审查和测试
5. Haiku - 生成最终总结报告

## 常见问题

### Q: 可以修改提示词吗？
是的！编辑 YAML 文件中的 `prompt_template` 字段即可。

### Q: 可以添加新的 Stage 吗？
可以。在 YAML 中添加新的 stage 定义，指定模型和提示词。

### Q: 如何调整超时时间？
编辑 YAML 中的 `config.timeout_per_stage` 或设置环境变量：
```bash
export CLI_TIMEOUT=600  # 10 分钟
```

### Q: 会不会很贵？
取决于任务复杂度：
- 简单任务：Opus ~2-5 min, Codex ~2-5 min, Haiku ~1-2 min
- 复杂任务：成本会更高

建议先用小任务测试成本。

## 下一步

1. ✅ **现在可以使用** - 运行 `current_pipeline.yaml`
2. 🔜 **即将支持** - 当 geminicli 可用时，启用 `multi_llm_pipeline.yaml`
3. 🎯 **未来扩展** - 支持多轮对话、并行执行、自定义终止条件

---

📚 更多文档请参考 `PIPELINE_USAGE.md`
