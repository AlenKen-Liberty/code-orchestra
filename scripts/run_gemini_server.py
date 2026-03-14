#!/usr/bin/env python3
"""Start the Gemini ACP server."""
import argparse
import sys
from pathlib import Path

# Ensure project root is in path
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from agents import gemini_server


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Gemini ACP server")
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args()
    gemini_server.main(port=args.port)


if __name__ == "__main__":
    main()
