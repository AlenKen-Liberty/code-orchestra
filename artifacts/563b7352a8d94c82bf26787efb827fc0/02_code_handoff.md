# Handoff: plan -> code
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
- Current Stage: code (coder)
- Working Directory: /home/ubuntu/scripts/code-orchestra

## Previous Stage Output
### plan
Implement in three slices.

Slice 1: keep routing pure, but add an explicit Codex account activation step before Codex execution so feasibility checks do not mutate global auth state.

Slice 2: add a nohup-style daemon manager with PID metadata, stale PID detection, hidden worker entrypoint, and SIGTERM-driven graceful shutdown around `run_forever`.

Slice 3: add centralized logging plus JSONL stage events, then build `dashboard` aggregates from DB state and event history instead of mixing metrics into ad hoc CLI output.

Baseline before changes: `python3 -m pytest tests/harness/ -q` => `21 passed`.

## Current Stage Instructions
Implement all three features end-to-end. Keep the Codex account switch separate from pure model selection, prefer a portable nohup-style daemon path for tests, and add focused tests as each slice lands so the final `python3 -m pytest tests/harness/ -v` run is stable.

## Verification
Run: `python3 -m pytest tests/harness/ -v`
