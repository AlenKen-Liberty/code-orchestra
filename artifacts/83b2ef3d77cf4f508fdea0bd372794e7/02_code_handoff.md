# Handoff: plan -> code
## Task
Phase 4: 健壮性 for code-orchestra harness

## Context Gathered
- [harness/quota_router.py](/home/ubuntu/scripts/code-orchestra/harness/quota_router.py) 当前按 provider 取单个最佳 quota snapshot；这会丢掉 Codex 的账号级选择空间。
- [harness/main.py](/home/ubuntu/scripts/code-orchestra/harness/main.py) 当前只持久化 `assigned_model` / `assigned_provider`，执行前没有 Codex 账号激活，也没有 daemon / telemetry hook。
- [harness/task_queue.py](/home/ubuntu/scripts/code-orchestra/harness/task_queue.py) 已经有 `metadata` 字段，但缺少单独的 metadata 更新接口；这是保存 `account_email` 的最小改动点。
- [harness/stage_executor.py](/home/ubuntu/scripts/code-orchestra/harness/stage_executor.py) 已经返回 `duration_sec` / `token_used`，其中 `token_used` 目前始终接近未使用状态，适合在这里补 provider 输出解析。
- [models/codex/account.py](/home/ubuntu/scripts/code-orchestra/models/codex/account.py) 已提供 `get_active_email()` 和 `set_active_account()`；账号切换副作用应放到 runtime，而不是 router。
- 当前基线: `python3 -m pytest tests/harness/ -v` 通过，结果是 `21 passed`。

## Recommended Order
1. 先做 Codex 轮换
- router 改成账号级候选。
- stage metadata 持久化 `selected_account_email`。
- `Harness._run_stage()` 在真正执行前切换 Codex 账号。
- 先补 router 和 harness 测试，再动实现。

2. 再做 daemon
- 新建 daemon helper 模块，不要把 PID/信号逻辑塞满 `main.py`。
- parser 增加 `daemon` 子命令和内部 worker 子命令。
- `run_forever()` 增加可优雅退出的 stop seam。

3. 最后做 telemetry 和 dashboard
- 统一 logging 配置。
- stage 生命周期事件写 JSONL。
- `dashboard` 聚合 DB + daemon + recent events。

## Concrete Guidance
- `QuotaRouter.can_run_stage()` 必须保持无副作用，因为它会在 paused quota 恢复逻辑中反复调用。
- `TaskQueue.assign_stage_model()` 很可能需要扩成同时支持 metadata patch，或者新增 `update_stage_metadata()`。
- daemon 测试应 mock `Popen`、`os.kill(pid, 0)` 或等价存活检查，避免真实后台进程依赖。
- `dashboard` 不必做复杂 TUI，先输出稳定 JSON/结构化文本即可。

## Verification Target
收尾时运行: `python3 -m pytest tests/harness/ -v`
