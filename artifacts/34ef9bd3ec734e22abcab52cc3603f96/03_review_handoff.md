# Handoff: code -> review
## Task
Phase 4: 健壮性 for code-orchestra harness

## Description
Phase 4: 健壮性 for code-orchestra harness

实现以下功能:

1. Codex 多账号轮换集成 — QuotaRouter 在选择 codex 模型时，自动轮换 5 个 OAuth 账号，
   优先使用配额即将过期的账号 (use-it-or-lose-it)。需要集成现有的 models/codex/account.py。

2. orchestra daemon 后台模式 — 新增 daemon start/stop/status 子命令，
   使用 systemd 或 nohup 在后台运行 run_forever 调度循环。
   支持 PID 文件管理和优雅停止 (SIGTERM handler)。

3. 日志 + 监控 + 错误报告 — 统一 logging 配置，
   每个 stage 执行记录结构化日志 (JSON lines)，
   支持 stage 执行耗时、token 用量、错误率的汇总统计。
   新增 orchestra dashboard 命令输出当前状态概览。

工作目录: ~/scripts/code-orchestra
验收: pytest tests/harness/ 全部通过 + 新测试覆盖新功能
User requested a CLI or management entrypoint.

## Goal
三个子功能全部实现，pytest tests/harness/ -v 全部通过，包括新增测试

## Context
- Complexity: complex
- Current Stage: review (reviewer)
- Working Directory: /home/ubuntu/scripts/code-orchestra

## Previous Stage Output
### plan
{"type":"thread.started","thread_id":"019d31df-21a1-78a3-8098-cc495ec45d16"} {"type":"turn.started"} {"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"先梳理 `harness` 相关代码和现有 CLI/调度结构，确认这三个子功能应落在哪些模块，再给出可执行的实现计划和交接说明。"}} {"type":"item.started","item":...

### code
{"type":"thread.started","thread_id":"019d31e4-1000-7831-b36c-8122b2317272"} {"type":"turn.started"} {"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"先定位 `harness`、现有 CLI、调度循环、`QuotaRouter` 和 `models/codex/account.py` 的接入点，再据此落三个子功能并补测试。"}} {"type"...

## Current Stage Instructions
Execute the `review` stage and leave a concise handoff for the next stage.

## Verification
Run: `python3 -m pytest tests/harness/ -v`
