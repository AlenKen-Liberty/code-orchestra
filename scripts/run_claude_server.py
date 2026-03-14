import argparse

from agents import claude_code_server


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Claude Code ACP server")
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args()
    claude_code_server.main(port=args.port)


if __name__ == "__main__":
    main()
