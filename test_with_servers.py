#!/usr/bin/env python3
"""
Start all ACP servers and run the Gemini workflow.

Usage:
    python3 test_with_servers.py "Your task description here"

Or with the default task:
    python3 test_with_servers.py
"""
import asyncio
import json
import logging
import subprocess
import sys
import time
from pathlib import Path

from orchestrator.gemini_workflow_orchestrator import GeminiWorkflowOrchestrator

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def start_server(script_name: str, port: int, name: str) -> subprocess.Popen:
    """Start an ACP server in the background."""
    logger.info(f"🚀 Starting {name} server on port {port}...")
    # Get the project root directory
    project_root = Path(__file__).parent
    proc = subprocess.Popen(
        [sys.executable, f"scripts/{script_name}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(project_root),  # Run from project root
    )
    # Give server time to start
    time.sleep(2)
    return proc


async def check_server_ready(port: int, retries: int = 5) -> bool:
    """Check if a server is ready by trying to connect."""
    import socket

    for attempt in range(retries):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            result = sock.connect_ex(('localhost', port))
            sock.close()
            if result == 0:
                return True
        except Exception:
            pass
        await asyncio.sleep(1)
    return False


async def main():
    """Start servers and run workflow."""
    print("\n" + "=" * 70)
    print("Multi-LLM Pipeline Test: Opus → Gemini → Codex → Haiku")
    print("=" * 70)

    # Get task from command line or use default
    task = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else (
        "Create a Python CLI tool that converts Markdown files to HTML. "
        "The tool should support custom CSS styling and output to a specified directory."
    )

    logger.info(f"📝 Task: {task}\n")

    # Start servers
    servers = []
    try:
        # Start Claude Code Server (port 8001)
        claude_proc = start_server("run_claude_server.py", 8001, "Claude Code")
        servers.append(("Claude Code", claude_proc, 8001))

        # Start Codex Server (port 8002)
        codex_proc = start_server("run_codex_server.py", 8002, "Codex")
        servers.append(("Codex", codex_proc, 8002))

        # Start Gemini Server (port 8003)
        gemini_proc = start_server("run_gemini_server.py", 8003, "Gemini")
        servers.append(("Gemini", gemini_proc, 8003))

        # Wait for servers to be ready
        logger.info("\n⏳ Waiting for servers to be ready...")
        for name, proc, port in servers:
            logger.info(f"   Checking {name} on port {port}...")
            if await check_server_ready(port):
                logger.info(f"   ✅ {name} server ready")
            else:
                logger.error(f"   ❌ {name} server failed to start")
                raise RuntimeError(f"{name} server did not start")

        # Run the workflow
        logger.info("\n" + "=" * 70)
        logger.info("Starting Workflow Execution")
        logger.info("=" * 70 + "\n")

        orchestrator = GeminiWorkflowOrchestrator()
        result = await orchestrator.run_workflow(task)

        # Display results
        logger.info("\n" + "=" * 70)
        logger.info("Workflow Results")
        logger.info("=" * 70)

        logger.info(f"\nStatus: {result.status}")
        if result.error:
            logger.error(f"Error: {result.error}")

        logger.info(f"\n📋 Design Plan (first 500 chars):")
        logger.info(f"{result.plan[:500]}...\n" if result.plan else "N/A")

        logger.info(f"💻 Implementation (first 500 chars):")
        logger.info(f"{result.code[:500]}...\n" if result.code else "N/A")

        if result.reviews:
            logger.info(f"✅ Code Review Verdict: {result.reviews[0].verdict}")
            logger.info(f"📝 Review Comments:\n{result.reviews[0].comments[:300]}...")

        # Save full results
        output_file = "workflow_results.json"
        with open(output_file, "w") as f:
            json.dump({
                "status": result.status,
                "error": result.error,
                "plan": result.plan[:1000] if result.plan else None,
                "code": result.code[:1000] if result.code else None,
                "reviews": [
                    {"verdict": r.verdict, "comments": r.comments[:500]}
                    for r in result.reviews
                ],
            }, f, indent=2)

        logger.info(f"\n💾 Full results saved to {output_file}")

    except Exception as e:
        logger.error(f"\n❌ Workflow failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    finally:
        # Cleanup: stop all servers
        logger.info("\n" + "=" * 70)
        logger.info("Cleaning up servers...")
        logger.info("=" * 70)

        for name, proc, port in servers:
            try:
                proc.terminate()
                proc.wait(timeout=5)
                logger.info(f"✅ {name} server stopped")
            except Exception as e:
                logger.warning(f"⚠️  Failed to stop {name} server: {e}")
                proc.kill()


if __name__ == "__main__":
    asyncio.run(main())
