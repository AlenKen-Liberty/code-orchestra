from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

import aiohttp
import yaml

from common.acp_client import ACPClient


@dataclass
class ServerStatus:
    base_url: str
    healthy: bool
    response_time_ms: float | None = None
    agents: list[str] = field(default_factory=list)
    configured_agents: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass
class StatusReport:
    timestamp: str
    servers: list[ServerStatus] = field(default_factory=list)
    total_servers: int = 0
    healthy_count: int = 0
    unhealthy_count: int = 0


def _format_error(exc: Exception) -> str:
    message = str(exc).strip()
    return message if message else exc.__class__.__name__


def _now_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_agent_config(config_path: str) -> dict[str, list[str]]:
    try:
        with open(config_path, "r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
    except FileNotFoundError:
        print(f"Config file not found: {config_path}", file=sys.stderr)
        sys.exit(2)
    except yaml.YAMLError as exc:
        print(f"Failed to parse YAML config: {exc}", file=sys.stderr)
        sys.exit(2)

    agents_section = data.get("agents", {}) if isinstance(data, dict) else {}
    grouped: dict[str, list[str]] = {}
    for agent_name, config in agents_section.items():
        if not isinstance(config, dict):
            continue
        base_url = config.get("base_url")
        if not base_url:
            continue
        grouped.setdefault(base_url, []).append(agent_name)
    return grouped


async def check_server(base_url: str, configured_agents: list[str], timeout: float) -> ServerStatus:
    client = ACPClient(base_url, timeout=timeout)
    try:
        start = time.monotonic()
        ping_ok = await client.ping()
        response_time_ms = (time.monotonic() - start) * 1000.0
        if not ping_ok:
            return ServerStatus(
                base_url=base_url,
                healthy=False,
                response_time_ms=response_time_ms,
                agents=[],
                configured_agents=configured_agents,
                error="Ping returned non-ok status",
            )
        agents = await client.list_agents()
        return ServerStatus(
            base_url=base_url,
            healthy=True,
            response_time_ms=response_time_ms,
            agents=[agent.name for agent in agents],
            configured_agents=configured_agents,
            error=None,
        )
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        return ServerStatus(
            base_url=base_url,
            healthy=False,
            response_time_ms=None,
            agents=[],
            configured_agents=configured_agents,
            error=_format_error(exc),
        )
    except Exception as exc:
        return ServerStatus(
            base_url=base_url,
            healthy=False,
            response_time_ms=None,
            agents=[],
            configured_agents=configured_agents,
            error=_format_error(exc),
        )
    finally:
        await client.close()


async def check_all_servers(config_path: str, timeout: float) -> StatusReport:
    grouped = load_agent_config(config_path)
    tasks = [
        check_server(base_url, configured_agents, timeout)
        for base_url, configured_agents in grouped.items()
    ]
    servers = await asyncio.gather(*tasks) if tasks else []
    healthy_count = sum(1 for server in servers if server.healthy)
    total_servers = len(servers)
    return StatusReport(
        timestamp=_now_timestamp(),
        servers=servers,
        total_servers=total_servers,
        healthy_count=healthy_count,
        unhealthy_count=total_servers - healthy_count,
    )


def format_text_report(report: StatusReport) -> str:
    lines: list[str] = [
        "ACP Server Status Report",
        "========================",
        f"Timestamp: {report.timestamp}",
        "",
    ]
    for server in report.servers:
        lines.append(f"Server: {server.base_url}")
        status_label = "HEALTHY" if server.healthy else "UNREACHABLE"
        lines.append(f"  Status:        {status_label}")
        if server.healthy and server.response_time_ms is not None:
            lines.append(f"  Response time: {server.response_time_ms:.0f}ms")
            agents = ", ".join(server.agents) if server.agents else "None"
            lines.append(f"  Agents:        {agents}")
        if server.error:
            lines.append(f"  Error:         {server.error}")
        configured = ", ".join(server.configured_agents) if server.configured_agents else "None"
        lines.append(f"  Configured:    {configured}")
        lines.append("")
    lines.append(
        f"Summary: {report.healthy_count}/{report.total_servers} servers healthy"
    )
    return "\n".join(lines)


def format_json_report(report: StatusReport) -> str:
    return json.dumps(asdict(report), indent=2)


def main() -> None:
    parser = argparse.ArgumentParser(description="Check ACP server health")
    parser.add_argument("--config", default="config/agents.yaml", help="Path to agents.yaml")
    parser.add_argument(
        "--format",
        default="text",
        choices=("text", "json"),
        help='Output format: "text" or "json"',
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="Per-server timeout in seconds",
    )
    args = parser.parse_args()

    report = asyncio.run(check_all_servers(args.config, args.timeout))
    output = (
        format_text_report(report)
        if args.format == "text"
        else format_json_report(report)
    )
    print(output)
    sys.exit(0 if report.unhealthy_count == 0 else 1)


if __name__ == "__main__":
    main()
