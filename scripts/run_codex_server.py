import argparse

from agents import codex_server


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Codex ACP server")
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args()
    codex_server.main(port=args.port)


if __name__ == "__main__":
    main()
