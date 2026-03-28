# Output: plan
## Summary
本阶段只做实现规划，不改业务代码。当前 `tests/harness/` 基线已验证通过: `21 passed`.

## Implementation Plan
1. Codex 多账号轮换
- 修改 [harness/quota_router.py](/home/ubuntu/scripts/code-orchestra/harness/quota_router.py)，把 `codex` 候选从“按 provider 取一个最佳 snapshot”改成“按账号展开后逐个打分”，继续复用 `QuotaManager._score_account()` 的 use-it-or-lose-it 逻辑。
- 保持 `QuotaRouter.select_model()` / `can_run_stage()` 纯函数化，不在路由阶段切账号。
- 在 stage 上持久化被选中的 `account_email`。优先放到 `metadata`，并补一个 `TaskQueue` 的 metadata 更新接口，避免为此扩表。
- 在 [harness/main.py](/home/ubuntu/scripts/code-orchestra/harness/main.py) 的执行路径里增加 Codex 账号激活步骤，仅当 `assigned_provider == "codex"` 且目标账号与 `models.codex.account.get_active_email()` 不同时调用 `set_active_account()`。

2. daemon 后台模式
- 以 [harness/main.py](/home/ubuntu/scripts/code-orchestra/harness/main.py) 作为管理入口，新增 `daemon start|stop|status` 和一个内部 worker 子命令。
- 新增独立 daemon helper 模块，负责 PID 文件、metadata 文件、存活检测、stale PID 清理和后台拉起。
- 后台运行优先走可测试的 `subprocess.Popen(..., start_new_session=True)` / nohup 风格实现，不把 systemd 作为单元测试依赖。
- 给 `run_forever()` 增加 `SIGTERM` 可控退出路径，最好通过 shutdown flag / `asyncio.Event` 做出可测试 seam。

3. logging / telemetry / dashboard
- 新增统一 logging 配置，CLI 和 daemon 启动时共用。
- 在 harness runtime 发出结构化 JSONL stage 事件: `stage_started`、`stage_succeeded`、`stage_retry`、`stage_paused_quota`、`stage_paused_permission`、`stage_failed`、`task_finished`。
- `token_used` 和 `duration_sec` 继续复用现有表字段；在 [harness/stage_executor.py](/home/ubuntu/scripts/code-orchestra/harness/stage_executor.py) 里对 Codex JSON 输出做轻量 token 解析，拿不到时保持 `0`。
- 新增 `dashboard` 命令，聚合 tasks/stages、quota_events、permission_requests、daemon 状态和最近 JSONL 事件，输出当前概览。

## Key Constraints
- 不要让 quota 检查触发全局 Codex auth 切换。
- 不要把 daemon 管理接到旧的 [scripts/orchestra_cli.py](/home/ubuntu/scripts/code-orchestra/scripts/orchestra_cli.py)。
- 不要依赖真实 systemd 做测试。

## Test Additions
- 扩展 [tests/harness/test_quota_router.py](/home/ubuntu/scripts/code-orchestra/tests/harness/test_quota_router.py): 多 Codex 账号排序、`can_run_stage()` 无副作用。
- 扩展 [tests/harness/test_main.py](/home/ubuntu/scripts/code-orchestra/tests/harness/test_main.py): stage 选择账号后执行前激活。
- 新增 daemon 测试: PID 生命周期、stale PID、graceful stop/status。
- 新增 telemetry/dashboard 测试: JSONL 事件落盘与汇总统计。

## Verification
最终验收命令: `python3 -m pytest tests/harness/ -v`
