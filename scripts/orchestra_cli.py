#!/usr/bin/env python3
"""Interactive CLI for running multi-agent orchestrator workflows."""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
import time
from pathlib import Path

import uuid
import yaml

# Fix path to allow importing from the project root if run from anywhere
sys.path.insert(0, str(Path(__file__).parent.parent.absolute()))

from common.acp_client import ACPClient
from common.models import Message, MessagePart, RunStatus
from scripts.check_server_status import check_all_servers, StatusReport
from orchestrator.pipeline import PipelineDefinition, PipelineExecutor, PipelineError
from orchestrator.stage import StageDefinition, StageResult

# Setup minimal logging, only warning+ so it doesn't clutter CLI
logging.basicConfig(level=logging.WARNING, format="%(message)s")
logger = logging.getLogger(__name__)


def hide_code_blocks(text: str) -> str:
    """Replaces markdown code blocks and diffs with a hidden placeholder."""
    if not text:
        return ""
    # Regex to match ```language \n code... \n ```
    pattern = re.compile(r"```[a-zA-Z0-9_-]*\n[\s\S]*?\n```", re.MULTILINE)
    return pattern.sub("\n```\n[CODE DIFF/BLOCK HIDDEN]\n```\n", text)
    

class CLIExecutor(PipelineExecutor):
    """Custom executor that streams updates to the CLI interface and routes to ACP services."""
    
    def __init__(self, pipeline_def: PipelineDefinition, config_path: str):
        super().__init__(pipeline_def)
        self.session_id = uuid.uuid4().hex[:12]
        self.clients: dict[str, ACPClient] = {}
        
        with open(config_path, "r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
            for name, info in data.get("agents", {}).items():
                self.clients[name] = ACPClient(info["base_url"])
                
    async def cleanup(self):
        import asyncio
        await asyncio.gather(*(client.close() for client in self.clients.values()), return_exceptions=True)

    async def _invoke_model(self, stage_def: StageDefinition, prompt: str) -> str:
        agent_name = stage_def.metadata.get("agent")
        if not agent_name:
            return await super()._invoke_model(stage_def, prompt)
            
        client = self.clients.get(agent_name)
        if not client:
            raise ValueError(f"Unknown agent '{agent_name}' configured in metadata for stage {stage_def.stage_id}")
            
        message = Message(
            role="user",
            parts=[MessagePart(content=prompt)]
        )
        
        run = await client.create_run(agent_name, [message], session_id=self.session_id)
        if run.status != RunStatus.COMPLETED:
            raise RuntimeError(f"Agent {agent_name} failed: {run.error}")
            
        if not run.output_messages:
            return ""
        return run.output_messages[0].text
    
    async def _execute_stage(self, stage_def: StageDefinition) -> StageResult:
        """Override to provide CLI feedback before and after the stage."""
        print(f"\n========================================================")
        print(f"🔄 CURRENT STEP: {stage_def.name} ({stage_def.stage_id})")
        print(f"🤖 Agent Model:  {stage_def.model}")
        print(f"========================================================")
        
        # Prepare prompt to show user what is being asked
        prompt = self._prepare_prompt(stage_def)
        print("\n[Input] -> Sending to Agent:")
        print("-" * 40)
        # We don't hide code blocks in prompt for context, but we can limit size
        short_prompt = prompt if len(prompt) < 1000 else prompt[:500] + "\n...[TRUNCATED FOR DISPLAY]..." + prompt[-500:]
        print(short_prompt)
        print("-" * 40)
        print("\n⏳ Waiting for agent response...\n")
        
        start_time = time.time()
        try:
            output = await self._invoke_model(stage_def, prompt)
            execution_time = time.time() - start_time
            
            print(f"✅ Agent responded in {execution_time:.1f}s")
            print("\n[Output] <- Received from Agent:")
            print("-" * 40)
            
            # Hide code blocks for clean UI
            clean_output = hide_code_blocks(output)
            print(clean_output)
            print("-" * 40)
            
            return StageResult(
                stage_id=stage_def.stage_id,
                status="success",
                output=output,
                raw_output=output,
                execution_time=execution_time,
                model_used=stage_def.model,
            )
            
        except Exception as exc:
            execution_time = time.time() - start_time
            print(f"❌ Stage failed after {execution_time:.1f}s: {exc}")
            raise  # Let the base class intercept it and handle fail_fast


async def ensure_servers_running(config_path: str, timeout: float = 3.0) -> bool:
    """Check if required servers are healthy. Return True if all ok."""
    print("🔍 Checking ACP Server Status...")
    report = await check_all_servers(config_path, timeout)
    if report.unhealthy_count == 0:
        print(f"✅ All {report.total_servers} servers are healthy!")
        return True
    
    print("\n❌ SOME SERVERS ARE UNREACHABLE!")
    for server in report.servers:
        if not server.healthy:
            err = f" ({server.error})" if server.error else ""
            print(f"  - {server.base_url} is DOWN{err}")
    
    print("\nPlease start the required servers (e.g. using scripts/run_*_server.py).")
    return False


def get_available_workflows() -> list[Path]:
    """Return a list of workflow YAML files."""
    workflows_dir = Path(__file__).parent.parent / "workflows"
    if not workflows_dir.exists():
        return []
    return sorted(workflows_dir.glob("*.yaml"))


async def main_async(args: argparse.Namespace) -> None:
    # 1. Check Servers
    servers_ok = await ensure_servers_running(args.config, args.timeout)
    if not servers_ok:
        sys.exit(1)
        
    print("\n" + "="*60)
    print("               ORCHESTRA MULTI-AGENT CLI")
    print("="*60 + "\n")
    
    # 2. Select Workflow
    workflows = get_available_workflows()
    if not workflows:
        print("❌ No workflows found in the 'workflows/' directory.")
        sys.exit(1)
        
    workflow_path = None
    if args.workflow:
        workflow_path = Path(args.workflow)
        if not workflow_path.exists():
            print(f"❌ Workflow {workflow_path} not found.")
            sys.exit(1)
    else:
        print("Available Workflows:")
        for idx, wf in enumerate(workflows):
            print(f"  [{idx + 1}] {wf.name}")
            
        while True:
            try:
                choice = input("\nSelect a workflow (1-%d): " % len(workflows))
                idx = int(choice.strip()) - 1
                if 0 <= idx < len(workflows):
                    workflow_path = workflows[idx]
                    break
                else:
                    print("Invalid choice.")
            except ValueError:
                print("Please enter a number.")
            except KeyboardInterrupt:
                print("\nCanceled by user.")
                sys.exit(0)
                
    print(f"\n✅ Selected workflow: {workflow_path.name}")
    
    # Load pipeline
    try:
        pipeline_def = PipelineDefinition(workflow_path)
    except PipelineError as e:
        print(f"❌ Failed to load pipeline: {e}")
        sys.exit(1)
        
    # 3. Get Task
    task_description = args.task
    if not task_description:
        print("\nEnter task description (press Enter twice to finish):")
        lines = []
        while True:
            try:
                line = input()
                if not line and (not lines or not lines[-1]):
                    break
                lines.append(line)
            except KeyboardInterrupt:
                print("\nCanceled by user.")
                sys.exit(0)
        task_description = "\n".join(lines).strip()
        
    if not task_description:
        print("❌ Task description cannot be empty.")
        sys.exit(1)

    # 4. Execute Pipeline
    print("\n🚀 Starting Pipeline Execution...")
    executor = CLIExecutor(pipeline_def, args.config)
    
    try:
        # Also map user_task so it's available for workflows explicitly requesting it
        initial_state = {"user_task": task_description}
        results = await executor.execute(task_description, initial_state=initial_state)
        
        print("\n" + "="*60)
        print("🎉 PIPELINE EXECUTION COMPLETED")
        print("="*60)
        for stage_id, result in results.items():
            icon = "✅" if result.status == "success" else "❌"
            print(f"{icon} Stage '{stage_id}': {result.status.upper()} ({result.execution_time:.1f}s)")
            
        # Check for absolute failure
        if any(r.status == "failed" for r in results.values()):
            print("\n❌ Pipeline completed with ERRORS.")
            sys.exit(1)
            
    except Exception as e:
        print(f"\n❌ Pipeline execution failed due to an error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        await executor.cleanup()


def main() -> None:
    parser = argparse.ArgumentParser(description="Interactive Multi-Agent Orchestrator CLI")
    parser.add_argument("--config", default="config/agents.yaml", help="Path to agents.yaml")
    parser.add_argument("--timeout", type=float, default=3.0, help="Per-server health check timeout in seconds")
    parser.add_argument("--workflow", help="Path to a specific workflow YAML, bypasses selection")
    parser.add_argument("--task", help="Initial task description, bypasses input dialog")
    
    args = parser.parse_args()
    
    try:
        asyncio.run(main_async(args))
    except KeyboardInterrupt:
        print("\n\nExiting CLI...")
        sys.exit(0)


if __name__ == "__main__":
    main()
