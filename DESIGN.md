● ACP Multi-Agent Orchestration - Detailed Design Document

  ---
  0. Open Questions

  1. ACP server framework: The prompt mentions @server.agent() decorators. I'm assuming we'll use a lightweight ACP
  server implementation built on top of aiohttp or FastAPI. Do you have a preferred HTTP framework, or should I design
  around a minimal custom ACPServer class that Codex implements from scratch?
  - Design below assumes: custom lightweight ACPServer on aiohttp, since we control the full stack and don't need a
  third-party ACP SDK.
  2. CLI availability: I assume claude, codex, and gemini CLIs are already installed and on $PATH on the target VM.
  Correct?
  3. Persistence backend for Session state: For this prototype, is an in-memory dict sufficient for session
  history/state, or do you want file-based persistence (e.g. JSON files in a data/ directory) so sessions survive server
   restarts?
  - Design below assumes: in-memory with an optional JSON-file dump, toggled by config.
  4. Max review iterations: The plan→implement→review→revise loop could theoretically run forever. Should we cap it
  (e.g. max 3 review rounds), or leave it to the orchestrator caller to decide?
  - Design below assumes: configurable max_review_rounds defaulting to 3.

  ---
  1. Overall Design (One-Page Summary)

  System Components

  The system consists of three process-level components running on one VM:

  ┌───────────────────┬───────────────┬─────────────────────────────────────────────────────────────────────────────┐
  │     Component     │     Port      │                               Responsibility                                │
  ├───────────────────┼───────────────┼─────────────────────────────────────────────────────────────────────────────┤
  │ Claude Code ACP   │               │ Hosts two ACP agents: claude_planner (opus4.6) and claude_reviewer          │
  │ Server            │ 8001          │ (haiku4.5). Both invoke the claude CLI under the hood with different        │
  │                   │               │ --model flags.                                                              │
  ├───────────────────┼───────────────┼─────────────────────────────────────────────────────────────────────────────┤
  │ Codex ACP Server  │ 8002          │ Hosts one ACP agent: codex_coder (gpt-5.2-codex xhigh). Invokes the codex   │
  │                   │               │ CLI.                                                                        │
  ├───────────────────┼───────────────┼─────────────────────────────────────────────────────────────────────────────┤
  │ Multi-Agent       │ 8000 (or      │ A Python program that drives the workflow: plan → implement → review →      │
  │ Orchestrator      │ CLI-only)     │ revise. Acts as an ACP client to the two servers above.                     │
  └───────────────────┴───────────────┴─────────────────────────────────────────────────────────────────────────────┘

  A future Gemini ACP Server (port 8004) slots in without changing the orchestrator's core architecture - just register
  a new agent entry in config and add a workflow step.

  Model Routing Decision: Two Agents, One Server (Approach A-hybrid)

  Decision: Claude Code's two roles (planner vs. reviewer) are exposed as two distinct ACP agents (claude_planner and
  claude_reviewer), both hosted within the same server process on port 8001.

  Rationale:
  - The orchestrator routes by agent_name only - no need to inspect or inject metadata. This keeps the orchestrator
  logic clean and the ACP contract pure.
  - Both agents share the same server process, session store, and codebase, so there's zero deployment overhead vs. a
  single-agent approach.
  - It maps naturally to ACP semantics: each agent has its own AgentManifest with distinct name, description, and
  metadata.model.
  - If we later want to run planner on a different machine from reviewer, we just move one agent registration to a
  different server - no code change.

  Codex is a single agent codex_coder with gpt-5.2-codex xhigh hardcoded in its wrapper config.

  Data Flow (Single Task Lifecycle)

  User / CLI
      │
      ▼
  Orchestrator.run_workflow(task="implement feature X")
      │
      │  ① POST /runs → claude_planner (port 8001)
      │     session_id = S1, role = "user"
      │     ← plan (text)
      │
      │  ② POST /runs → codex_coder (port 8002)
      │     session_id = S1, role = "agent/claude_planner"
      │     ← code (text)
      │
      │  ③ POST /runs → claude_reviewer (port 8001)
      │     session_id = S1, role = "agent/codex_coder"
      │     ← review (text, includes verdict: "approved" | "revise")
      │
      │  ④ If verdict == "revise":
      │     POST /runs → codex_coder (port 8002)
      │        session_id = S1, role = "agent/claude_reviewer"
      │        ← revised code
      │     Loop back to ③ (up to max_review_rounds)
      │
      ▼
  WorkflowResult { plan, code, reviews[], final_code, status }

  All steps share session S1, so every agent can see the full conversation history when its wrapper prepends
  context.session.load_history() to the CLI prompt.

  ---
  2. Directory / File Layout

  ~/scripts/acp/
  ├── config/
  │   ├── settings.py              # Central configuration: ports, URLs, timeouts, model params
  │   └── agents.yaml              # Agent endpoint registry (name → base_url mapping)
  │
  ├── common/
  │   ├── __init__.py
  │   ├── models.py                # Shared data classes: Message, MessagePart, Run, AgentManifest, Session,
  WorkflowResult
  │   ├── session_store.py         # In-memory (+ optional file-backed) session history & state store
  │   ├── acp_server.py            # Lightweight ACP HTTP server (aiohttp-based), agent registration, REST endpoints
  │   └── acp_client.py            # ACP HTTP client: create_run, get_run, get_agents, session context manager
  │
  ├── agents/
  │   ├── __init__.py
  │   ├── claude_code_server.py    # Server process for claude_planner + claude_reviewer agents
  │   ├── claude_code_wrapper.py   # Core logic: build prompt from history, call `claude` CLI, parse JSON output
  │   ├── codex_server.py          # Server process for codex_coder agent
  │   └── codex_wrapper.py         # Core logic: build prompt, call `codex` CLI, parse JSON/text output
  │
  ├── orchestrator/
  │   ├── __init__.py
  │   └── multi_agent_orchestrator.py  # MultiAgentOrchestrator class with run_workflow / plan / implement / review
  methods
  │
  ├── scripts/
  │   ├── run_claude_server.py     # Entry point: starts Claude Code ACP server on port 8001
  │   ├── run_codex_server.py      # Entry point: starts Codex ACP server on port 8002
  │   └── run_orchestrator.py      # Entry point: CLI to invoke the orchestrator with a task string
  │
  └── tests/                       # (Future: Gemini-generated tests)
      ├── __init__.py
      └── test_orchestrator.py     # Placeholder / smoke tests

  File Responsibilities

  ┌──────────────────────────────────────────┬───────────────────────────────────────────────────────────────────────┐
  │                   File                   │                                Purpose                                │
  ├──────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────┤
  │                                          │ All tunable constants: CLAUDE_PORT=8001, CODEX_PORT=8002,             │
  │ config/settings.py                       │ ORCHESTRATOR_PORT=8000, base URLs, CLI paths, timeouts (default       │
  │                                          │ 120s), retry config (max 2, backoff 1s), MAX_REVIEW_ROUNDS=3, model   │
  │                                          │ identifiers, SESSION_PERSIST_TO_DISK=False.                           │
  ├──────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────┤
  │                                          │ Declarative agent registry. Maps agent names to base_url for the      │
  │ config/agents.yaml                       │ orchestrator client. Example: claude_planner: http://localhost:8001,  │
  │                                          │ codex_coder: http://localhost:8002.                                   │
  ├──────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────┤
  │ common/models.py                         │ Python dataclass definitions for all ACP domain objects (see §3).     │
  │                                          │ Single source of truth for serialization/deserialization.             │
  ├──────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────┤
  │                                          │ SessionStore class. get_or_create(session_id) → Session,              │
  │ common/session_store.py                  │ append_message(session_id, Message), load_history(session_id) →       │
  │                                          │ List[Message], load_state/store_state. Thread/async-safe via          │
  │                                          │ asyncio.Lock.                                                         │
  ├──────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────┤
  │                                          │ ACPServer class. server.agent(name, description, metadata) decorator  │
  │ common/acp_server.py                     │ registers handler functions. On start(), spins up aiohttp app with    │
  │                                          │ routes: GET /ping, GET /agents, GET /agents/{name}, POST /runs, GET   │
  │                                          │ /runs/{run_id}. Manages SessionStore internally.                      │
  ├──────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────┤
  │                                          │ ACPClient class. Async HTTP client wrapping aiohttp.ClientSession.    │
  │ common/acp_client.py                     │ Methods: ping(), list_agents(), create_run(agent_name, messages,      │
  │                                          │ session_id, mode="sync") → Run, get_run(run_id) → Run. Includes       │
  │                                          │ session() async context manager that generates/shares a session_id.   │
  ├──────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────┤
  │                                          │ async def invoke_claude(prompt, model, allowed_tools, timeout) → str. │
  │ agents/claude_code_wrapper.py            │  Builds CLI args, runs subprocess, captures stdout, parses JSON,      │
  │                                          │ returns content string. Raises CLIError on non-zero exit or parse     │
  │                                          │ failure.                                                              │
  ├──────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────┤
  │                                          │ Creates an ACPServer, registers two agents (claude_planner with       │
  │ agents/claude_code_server.py             │ model=opus4.6 and claude_reviewer with model=haiku4.5). Each agent's  │
  │                                          │ handler: loads session history → builds prompt → calls invoke_claude  │
  │                                          │ → returns MessagePart.                                                │
  ├──────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────┤
  │                                          │ async def invoke_codex(prompt, timeout) → str. Calls codex --quiet    │
  │ agents/codex_wrapper.py                  │ --json, attempts JSON parse, falls back to raw stdout. Raises         │
  │                                          │ CLIError on failure.                                                  │
  ├──────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────┤
  │                                          │ Creates an ACPServer on port 8002, registers codex_coder agent.       │
  │ agents/codex_server.py                   │ Handler: loads history → builds prompt → calls invoke_codex → returns │
  │                                          │  MessagePart.                                                         │
  ├──────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────┤
  │                                          │ MultiAgentOrchestrator class. Holds ACPClient instances for each      │
  │ orchestrator/multi_agent_orchestrator.py │ agent server. Implements run_workflow(task) and sub-methods           │
  │                                          │ plan_task, implement_plan, review_code, apply_review_feedback.        │
  │                                          │ Returns WorkflowResult.                                               │
  ├──────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────┤
  │ scripts/run_*.py                         │ Thin entry points: parse CLI args (optional port override),           │
  │                                          │ instantiate server/orchestrator, call asyncio.run().                  │
  └──────────────────────────────────────────┴───────────────────────────────────────────────────────────────────────┘

  ---
  3. Core Components & Interfaces

  3.1 Data Models (common/models.py)

  from dataclasses import dataclass, field
  from typing import Optional
  from enum import Enum
  import uuid, time

  class RunStatus(str, Enum):
      CREATED = "created"
      IN_PROGRESS = "in-progress"
      COMPLETED = "completed"
      FAILED = "failed"
      CANCELLED = "cancelled"
      AWAITING = "awaiting"

  @dataclass
  class MessagePart:
      content_type: str = "text/plain"          # MIME type
      content: Optional[str] = None             # inline content (mutually exclusive with content_url)
      content_url: Optional[str] = None
      metadata: Optional[dict] = None           # arbitrary k/v (e.g. {"model": "opus4.6"})

  @dataclass
  class Message:
      role: str                                 # "user" | "agent" | "agent/{agent_name}"
      parts: list[MessagePart] = field(default_factory=list)

      @property
      def text(self) -> str:
          """Convenience: concatenate all text/plain parts."""
          return "\n".join(p.content for p in self.parts
                           if p.content and p.content_type == "text/plain")

  @dataclass
  class Run:
      run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
      agent_name: str = ""
      session_id: Optional[str] = None
      status: RunStatus = RunStatus.CREATED
      input_messages: list[Message] = field(default_factory=list)
      output_messages: list[Message] = field(default_factory=list)
      created_at: float = field(default_factory=time.time)
      completed_at: Optional[float] = None
      error: Optional[str] = None

  @dataclass
  class AgentManifest:
      name: str
      description: str
      metadata: dict = field(default_factory=dict)   # e.g. {"model": "opus4.6"}
      input_content_types: list[str] = field(default_factory=lambda: ["text/plain"])
      output_content_types: list[str] = field(default_factory=lambda: ["text/plain"])

  @dataclass
  class Session:
      session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
      history: list[Message] = field(default_factory=list)
      state: dict = field(default_factory=dict)

  @dataclass
  class WorkflowResult:
      task: str
      plan: str
      code: str
      reviews: list[str]            # one entry per review round
      final_code: str
      status: str                   # "approved" | "max_rounds_reached" | "error"
      session_id: str
      rounds: int                   # how many review iterations occurred

  3.2 Session Store (common/session_store.py)

  class SessionStore:
      """In-memory session storage with optional JSON file persistence."""

      def __init__(self, persist_to_disk: bool = False, data_dir: str = "./data/sessions"):
          ...

      async def get_or_create(self, session_id: str | None = None) -> Session:
          """Return existing session or create new one. If session_id is None, generate one."""

      async def append_message(self, session_id: str, message: Message) -> None:
          """Append a message to the session history."""

      async def load_history(self, session_id: str) -> list[Message]:
          """Return full ordered history for a session."""

      async def load_state(self, session_id: str) -> dict:
          ...

      async def store_state(self, session_id: str, state: dict) -> None:
          ...

  3.3 ACP Server (common/acp_server.py)

  class AgentContext:
      """Passed to agent handler functions, provides access to session and run metadata."""
      session: Session
      run: Run

      @property
      def session_history_as_prompt(self) -> str:
          """Format session history as a text block suitable for CLI prompt injection."""

  class ACPServer:
      def __init__(self, host: str = "0.0.0.0", port: int = 8001):
          ...

      def agent(self, name: str, description: str, metadata: dict | None = None):
          """Decorator to register an agent handler.

          The handler signature must be:
              async def handler(input_messages: list[Message], context: AgentContext) -> list[MessagePart]
          """

      async def start(self) -> None:
          """Start the aiohttp server. Registers these routes:
              GET  /ping                → {"status": "ok"}
              GET  /agents              → [AgentManifest, ...]
              GET  /agents/{name}       → AgentManifest
              POST /runs                → Run (sync mode: blocks until completion)
              GET  /runs/{run_id}       → Run
          """

      # Internal: _handle_create_run parses the request body:
      #   {
      #     "agent_name": "claude_planner",
      #     "input": [{"role": "user", "parts": [{"content_type": "text/plain", "content": "..."}]}],
      #     "session_id": "abc123",   // optional
      #     "mode": "sync"            // "sync" | "async"
      #   }
      # Creates a Run, calls the registered handler, populates output_messages, returns Run as JSON.

  3.4 ACP Client (common/acp_client.py)

  class ACPClient:
      def __init__(self, base_url: str, timeout: float = 120.0):
          ...

      async def ping(self) -> bool: ...

      async def list_agents(self) -> list[AgentManifest]: ...

      async def create_run(
          self,
          agent_name: str,
          messages: list[Message],
          session_id: str | None = None,
          mode: str = "sync"
      ) -> Run:
          """POST /runs. Returns completed Run with output_messages populated."""

      async def get_run(self, run_id: str) -> Run: ...

      @asynccontextmanager
      async def session(self) -> AsyncIterator[str]:
          """Yields a session_id. Usage:
              async with client.session() as sid:
                  run1 = await client.create_run("agent_a", msgs, session_id=sid)
                  run2 = await client.create_run("agent_b", msgs, session_id=sid)
          """

  3.5 Claude Code Wrapper (agents/claude_code_wrapper.py)

  class CLIError(Exception):
      """Raised when CLI invocation fails (non-zero exit, timeout, parse error)."""
      def __init__(self, message: str, exit_code: int | None = None, stderr: str = ""):
          ...

  async def invoke_claude(
      prompt: str,
      model: str = "opus4.6",
      allowed_tools: list[str] | None = None,      # default: ["Read", "Write", "Bash"]
      timeout: float = 120.0,
      working_dir: str | None = None
  ) -> str:
      """
      Call `claude -p --output-format json [--model <model>] [--allowedTools ...]`.

      Steps:
      1. Build arg list: ["claude", "-p", "--output-format", "json", "--model", model]
         + optional --allowedTools joined by comma.
      2. Run via asyncio.create_subprocess_exec, pass prompt via stdin.
      3. Wait with timeout. On timeout → raise CLIError.
      4. If exit code != 0 → raise CLIError with stderr.
      5. Parse stdout as JSON. Extract the "result" or "content" field (depending on claude CLI output schema).
         On parse failure → raise CLIError.
      6. Return the extracted text content.
      """

  3.6 Codex Wrapper (agents/codex_wrapper.py)

  async def invoke_codex(
      prompt: str,
      timeout: float = 180.0,
      working_dir: str | None = None
  ) -> str:
      """
      Call `codex --quiet --json`.

      Steps:
      1. Build args: ["codex", "--quiet", "--json"].
      2. Run subprocess, pass prompt via stdin.
      3. Wait with timeout.
      4. If exit code != 0 → raise CLIError.
      5. Try JSON parse of stdout:
         - If valid JSON with a "result"/"content"/"output" key → extract text.
         - If valid JSON but unexpected shape → json.dumps it back as string.
         - If not valid JSON → use raw stdout as-is (Codex sometimes outputs plain text).
      6. Return the content string.
      """

  3.7 Agent Server Handlers (agents/claude_code_server.py, agents/codex_server.py)

  Claude Code Server (hosts two agents on one port):

  server = ACPServer(port=settings.CLAUDE_PORT)  # 8001

  @server.agent(
      name="claude_planner",
      description="Generates detailed implementation plans and architectural designs",
      metadata={"model": "opus4.6", "role": "planner"}
  )
  async def handle_planner(messages: list[Message], context: AgentContext) -> list[MessagePart]:
      # 1. history_text = context.session_history_as_prompt  (prior messages formatted as text)
      # 2. user_input = messages[-1].text  (latest input)
      # 3. prompt = f"{history_text}\n\n{user_input}" if history_text else user_input
      # 4. result = await invoke_claude(prompt, model="opus4.6", allowed_tools=["Read","Bash"])
      # 5. return [MessagePart(content=result)]

  @server.agent(
      name="claude_reviewer",
      description="Reviews code for correctness, style, security, and completeness",
      metadata={"model": "haiku4.5", "role": "reviewer"}
  )
  async def handle_reviewer(messages: list[Message], context: AgentContext) -> list[MessagePart]:
      # Same pattern as planner but:
      # - model="haiku4.5"
      # - Prepend a system instruction: "You are a code reviewer. Analyze the code below.
      #   Respond with a JSON block: {\"verdict\": \"approved\" | \"revise\", \"comments\": \"...\"}
      #   followed by your detailed review."
      # - Parse the output to extract verdict for the orchestrator.

  Codex Server (single agent):

  server = ACPServer(port=settings.CODEX_PORT)  # 8002

  @server.agent(
      name="codex_coder",
      description="Implements code based on plans and specifications, revises based on review feedback",
      metadata={"model": "gpt-5.2-codex", "tier": "xhigh"}
  )
  async def handle_coder(messages: list[Message], context: AgentContext) -> list[MessagePart]:
      # 1. history_text = context.session_history_as_prompt
      # 2. user_input = messages[-1].text
      # 3. prompt = f"{history_text}\n\n{user_input}"
      # 4. result = await invoke_codex(prompt)
      # 5. return [MessagePart(content=result)]

  3.8 Multi-Agent Orchestrator (orchestrator/multi_agent_orchestrator.py)

  import logging

  logger = logging.getLogger("orchestrator")

  class MultiAgentOrchestrator:
      def __init__(self, agent_config_path: str = "config/agents.yaml"):
          """
          Load agent config, create ACPClient instances:
              self.clients = {
                  "claude_planner": ACPClient("http://localhost:8001"),
                  "claude_reviewer": ACPClient("http://localhost:8001"),
                  "codex_coder":    ACPClient("http://localhost:8002"),
              }
          Note: planner and reviewer share the same base_url (same server, different agent_name).
          """

      async def run_workflow(self, task: str, max_review_rounds: int = 3) -> WorkflowResult:
          """
          Full lifecycle:
          1. Generate a shared session_id.
          2. plan = await self.plan_task(task, session_id)
          3. code = await self.implement_plan(plan, session_id)
          4. Loop up to max_review_rounds:
             a. review = await self.review_code(code, session_id)
             b. If review.verdict == "approved": break
             c. code = await self.apply_review_feedback(review, session_id)
          5. Return WorkflowResult.
          """

      async def plan_task(self, task: str, session_id: str) -> str:
          """
          Call claude_planner with:
              Message(role="user", parts=[MessagePart(content=
                  f"Create a detailed implementation plan for the following task:\n\n{task}"
              )])
          Returns: the plan text from the run's output.
          Logs: agent_name, session_id, run_id, elapsed_ms.
          """

      async def implement_plan(self, plan: str, session_id: str) -> str:
          """
          Call codex_coder with:
              Message(role="agent/claude_planner", parts=[MessagePart(content=
                  f"Implement the following plan. Output the complete code.\n\n{plan}"
              )])
          Returns: the code text.
          """

      async def review_code(self, code: str, session_id: str) -> ReviewResult:
          """
          Call claude_reviewer with:
              Message(role="agent/codex_coder", parts=[MessagePart(content=
                  f"Review the following code. Provide verdict (approved/revise) and detailed feedback.\n\n{code}"
              )])
          Returns: ReviewResult(verdict="approved"|"revise", comments="...")
          Parses verdict from the reviewer's structured output.
          """

      async def apply_review_feedback(self, review: ReviewResult, session_id: str) -> str:
          """
          Call codex_coder with:
              Message(role="agent/claude_reviewer", parts=[MessagePart(content=
                  f"Revise your code based on this review feedback:\n\n{review.comments}"
              )])
          Returns: the revised code text.
          """


  @dataclass
  class ReviewResult:
      verdict: str    # "approved" | "revise"
      comments: str   # detailed review text

  ---
  4. Multi-Agent Workflow, Session & Role Usage

  4.1 Session Lifecycle

  run_workflow("implement feature X") called
      │
      ├─ session_id = uuid4().hex[:12]     ← generated once per workflow invocation
      │
      ├─ plan_task(...)          uses session_id  → server appends to Session.history
      ├─ implement_plan(...)     uses session_id  → server appends to Session.history
      ├─ review_code(...)        uses session_id  → server appends to Session.history
      ├─ apply_review_feedback() uses session_id  → server appends to Session.history
      └─ ...

  Rule: One session_id per high-level task. If the user kicks off a new, unrelated task, the orchestrator generates a
  fresh session_id.

  4.2 Session History Accumulation (Server-Side)

  When ACPServer._handle_create_run processes a request:

  1. Look up (or create) the Session by session_id.
  2. Append all input_messages to Session.history.
  3. Call the agent handler.
  4. Wrap handler output in a Message(role="agent/{agent_name}", parts=output_parts).
  5. Append that output message to Session.history.
  6. Return the Run with output_messages.

  This means by the time claude_reviewer runs (step 3), Session.history already contains:
  - The user's original task (role="user")
  - The planner's output (role="agent/claude_planner")
  - The coder's implementation (role="agent/codex_coder")

  The reviewer sees full context without the orchestrator manually forwarding everything.

  4.3 Role Tagging Convention

  ┌──────────────────────────┬────────────────────────────────────┬────────────────────────────────┐
  │           Step           │ Orchestrator sends Message.role as │ Agent appends output with role │
  ├──────────────────────────┼────────────────────────────────────┼────────────────────────────────┤
  │ 1. plan_task             │ "user"                             │ "agent/claude_planner"         │
  ├──────────────────────────┼────────────────────────────────────┼────────────────────────────────┤
  │ 2. implement_plan        │ "agent/claude_planner"             │ "agent/codex_coder"            │
  ├──────────────────────────┼────────────────────────────────────┼────────────────────────────────┤
  │ 3. review_code           │ "agent/codex_coder"                │ "agent/claude_reviewer"        │
  ├──────────────────────────┼────────────────────────────────────┼────────────────────────────────┤
  │ 4. apply_review_feedback │ "agent/claude_reviewer"            │ "agent/codex_coder"            │
  └──────────────────────────┴────────────────────────────────────┴────────────────────────────────┘

  This chain makes it trivially easy to reconstruct who-said-what from the session history.

  4.4 Cross-Server Session Sharing

  Critical design point: claude_planner and codex_coder run on different servers (ports 8001 and 8002) with separate
  SessionStore instances. They do not share memory.

  Solution: The orchestrator is the source of truth for session context. Each agent server maintains its own session
  store, but the orchestrator ensures continuity by:

  1. Always passing the same session_id to both servers.
  2. Each server independently accumulates the messages it receives and produces.
  3. The agent wrapper's context.session_history_as_prompt includes all messages that server has seen for that session.

  However, since server A doesn't see messages that only went through server B, the orchestrator must relay context:
  when calling codex after the planner, the orchestrator includes the planner's output in the input message (as shown in
   the implement_plan method). The server then appends this to its own session history.

  This is already handled by the orchestrator's design: each step sends the previous step's output as input content, and
   the server records both input and output in its session store.

  4.5 Logging

  Every ACPServer._handle_create_run logs:

  [2026-03-14T10:23:45Z] agent=claude_planner session=a1b2c3 run=x9y8z7 status=completed elapsed_ms=4523

  The orchestrator additionally logs each workflow step:

  [2026-03-14T10:23:45Z] workflow step=plan_task agent=claude_planner session=a1b2c3 run=x9y8z7 elapsed_ms=4523
  [2026-03-14T10:23:50Z] workflow step=implement_plan agent=codex_coder session=a1b2c3 run=p5q4r3 elapsed_ms=8912

  Use standard logging module, configured in settings.py with LOG_LEVEL=INFO.

  ---
  5. Implementation Checklist for Codex

  Below is the ordered task list. Each file should be implemented in the order listed (dependencies flow top-down). All
  code must use Python 3.11+, type annotations, asyncio, and aiohttp for HTTP.

  ---
  Task 1: config/settings.py

  Create the central configuration module.

  - Define constants:
    - CLAUDE_PORT = 8001, CODEX_PORT = 8002, ORCHESTRATOR_PORT = 8000
    - CLAUDE_BASE_URL = "http://localhost:8001"
    - CODEX_BASE_URL = "http://localhost:8002"
    - CLI_TIMEOUT = 120.0 (seconds)
    - HTTP_TIMEOUT = 180.0 (seconds)
    - MAX_REVIEW_ROUNDS = 3
    - MAX_RETRIES = 2, RETRY_BACKOFF = 1.0
    - LOG_LEVEL = "INFO"
    - SESSION_PERSIST_TO_DISK = False
    - SESSION_DATA_DIR = "./data/sessions"
    - CLAUDE_PLANNER_MODEL = "opus4.6"
    - CLAUDE_REVIEWER_MODEL = "haiku4.5"
    - CODEX_MODEL = "gpt-5.2-codex"
    - CODEX_TIER = "xhigh"
  - All values should be overridable via environment variables (use os.environ.get with the constant as default).

  ---
  Task 2: config/agents.yaml

  Create the agent endpoint registry.

  agents:
    claude_planner:
      base_url: "http://localhost:8001"
      description: "Planning and architectural design agent"
    claude_reviewer:
      base_url: "http://localhost:8001"
      description: "Code review agent"
    codex_coder:
      base_url: "http://localhost:8002"
      description: "Code implementation agent"

  ---
  Task 3: common/models.py

  Create all shared data classes as specified in §3.1.

  - Implement MessagePart, Message, Run, AgentManifest, Session, WorkflowResult, ReviewResult, RunStatus.
  - Message.text property: concatenate all text/plain parts.
  - Add to_dict() and from_dict(cls, data) class methods on Run, Message, MessagePart, AgentManifest for JSON
  serialization.
  - RunStatus as str, Enum.

  ---
  Task 4: common/session_store.py

  Create the session store as specified in §3.2.

  - SessionStore.__init__(persist_to_disk, data_dir).
  - All public methods must be async and use asyncio.Lock for thread safety.
  - get_or_create: if session_id is None, generate one via uuid4().hex[:12].
  - append_message: appends Message to Session.history.
  - load_history: returns list[Message] (copy, not reference).
  - load_state / store_state: get/set Session.state dict.
  - If persist_to_disk is True: after every mutation, write the session to {data_dir}/{session_id}.json.

  ---
  Task 5: common/acp_server.py

  Create the lightweight ACP HTTP server as specified in §3.3.

  - ACPServer.__init__(host, port): create internal aiohttp.web.Application, SessionStore, agent registry dict.
  - server.agent(name, description, metadata) decorator: registers handler in the agent registry. Handler signature:
  async def handler(messages: list[Message], context: AgentContext) -> list[MessagePart].
  - AgentContext class with session: Session, run: Run, and session_history_as_prompt property.
    - session_history_as_prompt: formats history as "[{role}]: {text}\n\n" blocks.
  - REST routes:
    - GET /ping → {"status": "ok"}
    - GET /agents → JSON array of AgentManifest.to_dict().
    - GET /agents/{name} → single manifest or 404.
    - POST /runs → Parse request body (agent_name, input (list of message dicts), session_id (optional), mode (default
  "sync")). Look up agent handler. Create Run. Get/create session. Append input messages to session. Build AgentContext.
   Call handler. Wrap output in Message(role="agent/{agent_name}"). Append output to session. Update Run status to
  completed. Return Run.to_dict().
    - GET /runs/{run_id} → look up run from internal dict, return JSON or 404.
  - Error handling: if handler raises, set Run.status = "failed", Run.error = str(e), return Run with HTTP 200 (ACP
  convention: errors in Run object, not HTTP status).
  - async start(): run the aiohttp app.
  - Log each run: agent_name, session_id, run_id, status, elapsed_ms.

  ---
  Task 6: common/acp_client.py

  Create the ACP HTTP client as specified in §3.4.

  - ACPClient.__init__(base_url, timeout): store config, create aiohttp.ClientSession lazily.
  - async ping() → bool.
  - async list_agents() → list[AgentManifest].
  - async create_run(agent_name, messages, session_id, mode) → Run: POST to /runs, deserialize response to Run.
  - async get_run(run_id) → Run.
  - async close(): close the underlying aiohttp.ClientSession.
  - session() async context manager: generates a session_id (uuid4().hex[:12]), yields it. No cleanup needed - sessions
  are server-side.
  - Retry logic: on connection error or HTTP 5xx, retry up to MAX_RETRIES with RETRY_BACKOFF sleep between attempts.

  ---
  Task 7: agents/claude_code_wrapper.py

  Create the Claude CLI wrapper as specified in §3.5.

  - CLIError exception class with message, exit_code, stderr.
  - async invoke_claude(prompt, model, allowed_tools, timeout, working_dir) → str.
  - Build CLI args: ["claude", "-p", "--output-format", "json", "--model", model]. If allowed_tools is provided, append
  "--allowedTools" and ",".join(allowed_tools).
  - Use asyncio.create_subprocess_exec with stdin=PIPE, stdout=PIPE, stderr=PIPE.
  - Pass prompt via stdin (proc.communicate(input=prompt.encode())).
  - Apply timeout via asyncio.wait_for. On timeout → kill process, raise CLIError.
  - On non-zero exit → raise CLIError with stderr.
  - Parse stdout as JSON. Try keys "result", "content", "response" to extract text. If none found, use
  json.dumps(parsed). On JSONDecodeError → use raw stdout as-is (CLI may output plain text).
  - Return the extracted text.

  ---
  Task 8: agents/codex_wrapper.py

  Create the Codex CLI wrapper as specified in §3.6.

  - Reuse CLIError from claude_code_wrapper.py (import it).
  - async invoke_codex(prompt, timeout, working_dir) → str.
  - Build CLI args: ["codex", "--quiet", "--json"].
  - Same subprocess pattern as Claude wrapper.
  - JSON parsing with fallback: try parse → extract known keys → fall back to json.dumps → fall back to raw stdout.
  - Return content string.

  ---
  Task 9: agents/claude_code_server.py

  Create the Claude Code ACP server as specified in §3.7.

  - Instantiate ACPServer(port=settings.CLAUDE_PORT).
  - Register claude_planner agent:
    - Load session history via context.session_history_as_prompt.
    - Construct prompt with history prefix + latest user input.
    - Call invoke_claude(prompt, model=settings.CLAUDE_PLANNER_MODEL, allowed_tools=["Read", "Bash"]).
    - Return [MessagePart(content=result)].
  - Register claude_reviewer agent:
    - Same history/prompt pattern.
    - Prepend a system instruction to the prompt: "You are a code reviewer. Evaluate the code provided. Start your
  response with a JSON line: {\"verdict\": \"approved\" | \"revise\"}\nThen provide detailed review comments."
    - Call invoke_claude(prompt, model=settings.CLAUDE_REVIEWER_MODEL).
    - Return [MessagePart(content=result, metadata={"role": "reviewer"})].
  - Add a __main__ block or main() that calls server.start().

  ---
  Task 10: agents/codex_server.py

  Create the Codex ACP server.

  - Instantiate ACPServer(port=settings.CODEX_PORT).
  - Register codex_coder agent:
    - Load session history.
    - Construct prompt.
    - Call invoke_codex(prompt).
    - Return [MessagePart(content=result)].
  - Add main() / __main__ block.

  ---
  Task 11: orchestrator/multi_agent_orchestrator.py

  Create the orchestrator as specified in §3.8.

  - MultiAgentOrchestrator.__init__(config_path):
    - Load agents.yaml.
    - Create ACPClient per agent entry.
  - async run_workflow(task, max_review_rounds) → WorkflowResult:
    - Generate session_id.
    - Call plan_task → implement_plan → loop (review_code → check verdict → apply_review_feedback).
    - Build and return WorkflowResult.
    - Catch exceptions, set status="error" if any step fails.
    - finally: close all clients.
  - async plan_task(task, session_id) → str:
    - Send Message(role="user", ...) to claude_planner.
    - Extract and return plan text from Run.output_messages.
    - Log step.
  - async implement_plan(plan, session_id) → str:
    - Send Message(role="agent/claude_planner", ...) to codex_coder.
    - Return code text.
  - async review_code(code, session_id) → ReviewResult:
    - Send Message(role="agent/codex_coder", ...) to claude_reviewer.
    - Parse output to extract verdict and comments. Try JSON parsing first line; if that fails, look for keywords
  "approved"/"revise" in text.
    - Return ReviewResult.
  - async apply_review_feedback(review, session_id) → str:
    - Send Message(role="agent/claude_reviewer", ...) to codex_coder.
    - Return revised code text.
  - async close(): close all ACPClient instances.

  ---
  Task 12: scripts/run_claude_server.py

  - Parse optional --port arg (default from settings).
  - Import and call claude_code_server.main().

  ---
  Task 13: scripts/run_codex_server.py

  - Same pattern for codex server.

  ---
  Task 14: scripts/run_orchestrator.py

  - Parse --task arg (required, string).
  - Parse optional --max-rounds (default 3).
  - Instantiate MultiAgentOrchestrator.
  - Call asyncio.run(orchestrator.run_workflow(task)).
  - Pretty-print the WorkflowResult to stdout.

  ---
  Task 15: tests/test_orchestrator.py

  - Create a placeholder test file with at least:
    - A test that imports all modules without error.
    - A test that constructs Message, MessagePart, Run and verifies to_dict() / from_dict() roundtrip.
    - A test that verifies SessionStore basic operations (get_or_create, append, load_history).
  - Mark integration tests (that require running servers) with @pytest.mark.integration so they can be skipped in CI.

  ---
  Cross-Cutting Code Quality Requirements

  - Type annotations: All function signatures must have full type hints. Use list[X] not List[X] (Python 3.11+).
  - Config centralization: No hardcoded ports, URLs, timeouts, or model names outside config/settings.py. Import from
  settings.
  - Error handling: CLI wrappers raise CLIError. Server catches all handler errors and records them in Run.error.
  Orchestrator catches and surfaces errors in WorkflowResult.status.
  - Async throughout: All I/O-bound operations must be async. No subprocess.run - use asyncio.create_subprocess_exec.
  - Logging: Use logging.getLogger(__name__) in every module. Format: %(asctime)s %(name)s %(levelname)s %(message)s.
  - No external dependencies beyond: aiohttp, pyyaml, pytest (for tests). Standard library otherwise.
  - __init__.py: Every package directory gets an __init__.py (can be empty).
