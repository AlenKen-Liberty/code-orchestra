import argparse
import asyncio
import json

from orchestrator.multi_agent_orchestrator import MultiAgentOrchestrator


def _result_to_dict(result) -> dict:
    return {
        "plan": result.plan,
        "code": result.code,
        "final_code": result.final_code,
        "status": result.status,
        "error": result.error,
        "reviews": [
            {"verdict": review.verdict, "comments": review.comments}
            for review in result.reviews
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run multi-agent orchestrator")
    parser.add_argument("--task", required=True, help="Task description")
    parser.add_argument("--max-rounds", type=int, default=None)
    args = parser.parse_args()

    orchestrator = MultiAgentOrchestrator()
    result = asyncio.run(orchestrator.run_workflow(args.task, max_review_rounds=args.max_rounds))
    print(json.dumps(_result_to_dict(result), indent=2))


if __name__ == "__main__":
    main()
