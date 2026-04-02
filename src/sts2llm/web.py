from __future__ import annotations

import json
import threading
import traceback
from dataclasses import dataclass
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from .agent import SYSTEM_PROMPT, SessionAgent, ToolEvent
from .logging_utils import SessionLogger

INDEX_HTML = """<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>STS2LLM Console</title>
    <style>
      :root {
        --bg: #f3ecdf;
        --bg-strong: #fbf7ee;
        --panel: rgba(255, 252, 246, 0.9);
        --panel-strong: rgba(255, 250, 241, 0.98);
        --line: rgba(79, 56, 38, 0.18);
        --text: #2c2018;
        --muted: #6d5948;
        --accent: #b54f2d;
        --accent-soft: #eed7ca;
        --ok: #355f45;
        --busy: #9a5d10;
        --err: #8e2d2d;
        --shadow: 0 16px 48px rgba(76, 53, 38, 0.14);
      }

      * {
        box-sizing: border-box;
      }

      body {
        margin: 0;
        min-height: 100vh;
        font-family: "IBM Plex Sans", "Avenir Next", "Segoe UI", sans-serif;
        color: var(--text);
        background:
          radial-gradient(circle at top left, rgba(219, 148, 88, 0.28), transparent 28rem),
          radial-gradient(circle at bottom right, rgba(136, 87, 43, 0.18), transparent 24rem),
          linear-gradient(180deg, #f7f1e5 0%, #efe3d0 48%, #ead9c1 100%);
      }

      .shell {
        display: grid;
        grid-template-columns: minmax(20rem, 27rem) minmax(0, 1fr);
        gap: 1rem;
        padding: 1rem;
      }

      .panel {
        background: var(--panel);
        border: 1px solid var(--line);
        border-radius: 1.2rem;
        box-shadow: var(--shadow);
        backdrop-filter: blur(10px);
      }

      .sidebar {
        display: flex;
        flex-direction: column;
        gap: 1rem;
        padding: 1rem;
        position: sticky;
        top: 1rem;
        max-height: calc(100vh - 2rem);
        overflow: auto;
      }

      .timeline {
        padding: 1rem;
        min-height: calc(100vh - 2rem);
      }

      .workspace {
        display: grid;
        grid-template-columns: minmax(0, 1.1fr) minmax(24rem, 0.9fr);
        gap: 1rem;
        min-height: calc(100vh - 2rem);
      }

      .hero {
        display: flex;
        justify-content: space-between;
        gap: 1rem;
        align-items: flex-start;
      }

      h1, h2, h3, p {
        margin: 0;
      }

      h1 {
        font-size: 1.35rem;
        letter-spacing: 0.02em;
      }

      .meta {
        display: flex;
        flex-wrap: wrap;
        gap: 0.5rem;
        margin-top: 0.75rem;
      }

      .badge {
        display: inline-flex;
        align-items: center;
        gap: 0.35rem;
        padding: 0.35rem 0.7rem;
        border-radius: 999px;
        font-size: 0.82rem;
        border: 1px solid var(--line);
        background: rgba(255, 255, 255, 0.58);
      }

      .badge[data-status="idle"] {
        color: var(--ok);
        background: rgba(53, 95, 69, 0.1);
      }

      .badge[data-status="running"] {
        color: var(--busy);
        background: rgba(154, 93, 16, 0.12);
      }

      .badge[data-status="error"] {
        color: var(--err);
        background: rgba(142, 45, 45, 0.1);
      }

      .controls {
        display: flex;
        gap: 0.6rem;
      }

      button {
        appearance: none;
        border: none;
        border-radius: 0.9rem;
        padding: 0.75rem 1rem;
        font: inherit;
        cursor: pointer;
        color: #fff9f0;
        background: linear-gradient(135deg, #b54f2d, #8d3619);
        box-shadow: 0 10px 24px rgba(143, 54, 25, 0.2);
      }

      button.secondary {
        color: var(--text);
        background: linear-gradient(135deg, #f5e8d1, #e7d1b6);
        box-shadow: none;
      }

      button:disabled {
        cursor: not-allowed;
        opacity: 0.65;
      }

      textarea,
      pre {
        width: 100%;
        margin: 0;
        border-radius: 1rem;
        border: 1px solid rgba(94, 67, 47, 0.16);
        background: var(--panel-strong);
        color: var(--text);
        font-family: "IBM Plex Mono", "SFMono-Regular", "Menlo", monospace;
        font-size: 0.9rem;
        line-height: 1.5;
      }

      textarea {
        min-height: 8.5rem;
        padding: 0.9rem 1rem;
        resize: vertical;
      }

      pre {
        padding: 0.9rem 1rem;
        overflow: auto;
        white-space: pre-wrap;
        word-break: break-word;
      }

      details {
        border: 1px solid var(--line);
        border-radius: 1rem;
        background: rgba(255, 248, 236, 0.75);
        padding: 0.85rem 0.9rem;
      }

      summary {
        cursor: pointer;
        font-weight: 600;
      }

      .stack {
        display: flex;
        flex-direction: column;
        gap: 0.85rem;
      }

      .timeline-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 1rem;
        margin-bottom: 1rem;
      }

      .event-list {
        display: flex;
        flex-direction: column;
        gap: 0.8rem;
      }

      .event {
        padding: 0.95rem 1rem;
        border-radius: 1rem;
        border: 1px solid var(--line);
        background: rgba(255, 250, 244, 0.92);
      }

      .event-head {
        display: flex;
        justify-content: space-between;
        gap: 0.8rem;
        margin-bottom: 0.65rem;
        align-items: center;
      }

      .event-type {
        font-size: 0.8rem;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: var(--muted);
      }

      .event-title {
        font-weight: 600;
      }

      .hint {
        color: var(--muted);
        font-size: 0.92rem;
      }

      .error {
        color: var(--err);
      }

      .message-body {
        font-family: "IBM Plex Sans", "Avenir Next", "Segoe UI", sans-serif;
        white-space: pre-wrap;
      }

      .tool-grid {
        display: grid;
        grid-template-columns: 1fr;
        gap: 0.5rem;
      }

      .tool-label {
        font-size: 0.78rem;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: var(--muted);
      }

      @media (max-width: 960px) {
        .shell {
          grid-template-columns: 1fr;
        }

        .sidebar {
          position: static;
          max-height: none;
        }

        .timeline {
          min-height: auto;
        }

        .workspace {
          grid-template-columns: 1fr;
          min-height: auto;
        }
      }
    </style>
  </head>
  <body>
    <main class="shell">
      <aside class="panel sidebar">
        <section class="hero">
          <div>
            <h1>STS2LLM Console</h1>
            <p class="hint">查看 system prompt，提交 user prompt，并跟踪每一次工具调用。</p>
          </div>
          <div class="controls">
            <button id="reset-btn" class="secondary" type="button">Reset</button>
          </div>
        </section>

        <section class="stack">
          <div>
            <h2>会话状态</h2>
            <div class="meta">
              <span class="badge" id="status-badge" data-status="idle">idle</span>
              <span class="badge" id="model-badge">model</span>
              <span class="badge" id="rounds-badge">rounds</span>
            </div>
          </div>

          <div>
            <h2>日志文件</h2>
            <p class="hint" id="log-path">-</p>
          </div>

          <details open>
            <summary>Agent System Prompt</summary>
            <pre id="system-prompt"></pre>
          </details>

          <div class="stack">
            <div>
              <h2>User Prompt</h2>
              <p class="hint">会话上下文会保留，直到点击 Reset。</p>
            </div>
            <textarea id="prompt-input" placeholder="例如：读取当前状态，并只帮我完成这个回合。"></textarea>
            <button id="send-btn" type="button">Send Prompt</button>
            <p class="hint" id="composer-hint">Ctrl/Cmd + Enter 也可以提交。</p>
          </div>
        </section>
      </aside>

      <section class="workspace">
        <section class="panel timeline">
          <div class="timeline-header">
            <div>
              <h2>会话窗口</h2>
              <p class="hint">这里只显示 user / assistant message。</p>
            </div>
            <p class="hint" id="message-counter">0 messages</p>
          </div>
          <div id="message-list" class="event-list"></div>
        </section>

        <section class="panel timeline">
          <div class="timeline-header">
            <div>
              <h2>工具监视窗</h2>
              <p class="hint">单独显示 tool call 和 tool output。</p>
            </div>
            <p class="hint" id="tool-counter">0 tool events</p>
          </div>
          <div id="tool-list" class="event-list"></div>
        </section>
      </section>
    </main>

    <script>
      const state = {
        cursor: 0,
        status: "idle",
        polling: false,
        eventCount: 0,
      };

      const dom = {
        statusBadge: document.getElementById("status-badge"),
        modelBadge: document.getElementById("model-badge"),
        roundsBadge: document.getElementById("rounds-badge"),
        logPath: document.getElementById("log-path"),
        systemPrompt: document.getElementById("system-prompt"),
        promptInput: document.getElementById("prompt-input"),
        sendBtn: document.getElementById("send-btn"),
        resetBtn: document.getElementById("reset-btn"),
        messageList: document.getElementById("message-list"),
        toolList: document.getElementById("tool-list"),
        messageCounter: document.getElementById("message-counter"),
        toolCounter: document.getElementById("tool-counter"),
        composerHint: document.getElementById("composer-hint"),
      };

      function setStatus(status) {
        state.status = status;
        dom.statusBadge.dataset.status = status;
        dom.statusBadge.textContent = status;
        const busy = status === "running";
        dom.sendBtn.disabled = busy;
        dom.resetBtn.disabled = busy;
        dom.composerHint.textContent = busy
          ? "Agent 正在运行，本轮结束前不能提交新 prompt。"
          : "Ctrl/Cmd + Enter 也可以提交。";
      }

      function prettyJson(value) {
        if (typeof value === "string") {
          try {
            return JSON.stringify(JSON.parse(value), null, 2);
          } catch {
            return value;
          }
        }
        return JSON.stringify(value, null, 2);
      }

      function buildCard(titleText, typeText, tsText) {
        const card = document.createElement("article");
        card.className = "event";
        const head = document.createElement("div");
        head.className = "event-head";
        const titleWrap = document.createElement("div");
        const type = document.createElement("div");
        type.className = "event-type";
        type.textContent = typeText;
        const title = document.createElement("div");
        title.className = "event-title";
        title.textContent = titleText;
        titleWrap.append(type, title);
        const ts = document.createElement("div");
        ts.className = "hint";
        ts.textContent = tsText;
        head.append(titleWrap, ts);
        card.appendChild(head);
        return card;
      }

      function renderMessageEvent(event) {
        const bodyText = buildMessageBody(event);
        if (!bodyText) {
          return;
        }

        const title = event.event === "assistant_text" ? "Assistant" : event.event === "user_prompt" ? "User" : "Error";
        const card = buildCard(title, "message", event.ts);
        const body = document.createElement("pre");
        body.className = "message-body";
        body.textContent = bodyText;
        if (event.event === "error") {
          body.classList.add("error");
        }
        card.appendChild(body);
        dom.messageList.appendChild(card);
        card.scrollIntoView({ block: "end" });
      }

      function renderToolEvent(event) {
        const title = event.payload.name || (event.event === "tool_call" ? "Tool Call" : "Tool Output");
        const card = buildCard(title, event.event, event.ts);
        const grid = document.createElement("div");
        grid.className = "tool-grid";

        if (event.event === "tool_call") {
          grid.appendChild(buildLabeledBlock("Args", prettyJson(event.payload.args || {})));
        } else if (event.event === "tool_output") {
          if (event.payload.args) {
            grid.appendChild(buildLabeledBlock("Args", prettyJson(event.payload.args)));
          }
          grid.appendChild(buildLabeledBlock("Output", prettyJson(event.payload.output || "")));
        }

        card.appendChild(grid);
        dom.toolList.appendChild(card);
        card.scrollIntoView({ block: "end" });
      }

      function buildLabeledBlock(label, text) {
        const wrap = document.createElement("div");
        const heading = document.createElement("div");
        heading.className = "tool-label";
        heading.textContent = label;
        const body = document.createElement("pre");
        body.textContent = text;
        wrap.append(heading, body);
        return wrap;
      }

      function buildMessageBody(event) {
        if (event.event === "user_prompt") {
          return event.payload.text || "";
        }
        if (event.event === "assistant_text") {
          return typeof event.payload === "string" ? event.payload : "";
        }
        if (event.event === "error") {
          return event.payload.message || prettyJson(event.payload);
        }
        return "";
      }

      function applyState(data) {
        state.cursor = data.cursor;
        setStatus(data.status);
        dom.modelBadge.textContent = data.model;
        dom.roundsBadge.textContent = "max_rounds=" + data.max_rounds;
        dom.logPath.textContent = data.log_path;
        if (!dom.systemPrompt.textContent) {
          dom.systemPrompt.textContent = data.system_prompt;
        }

        for (const event of data.events) {
          if (event.event === "user_prompt" || event.event === "assistant_text" || event.event === "error") {
            renderMessageEvent(event);
            state.eventCount += 1;
          }
          if (event.event === "tool_call" || event.event === "tool_output") {
            renderToolEvent(event);
          }
        }
        dom.messageCounter.textContent = state.eventCount + " messages";
        dom.toolCounter.textContent =
          (dom.toolList.childElementCount || 0) + " tool events";
      }

      async function poll() {
        if (state.polling) {
          return;
        }
        state.polling = true;
        try {
          const res = await fetch("/api/state?after=" + state.cursor, { cache: "no-store" });
          if (!res.ok) {
            throw new Error("poll failed: " + res.status);
          }
          const data = await res.json();
          applyState(data);
        } catch (error) {
          console.error(error);
        } finally {
          state.polling = false;
        }
      }

      async function sendPrompt() {
        const prompt = dom.promptInput.value.trim();
        if (!prompt || state.status === "running") {
          return;
        }
        const res = await fetch("/api/turn", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ prompt }),
        });
        if (res.status === 409) {
          setStatus("running");
          return;
        }
        if (!res.ok) {
          const detail = await res.text();
          alert(detail || "提交失败");
          return;
        }
        dom.promptInput.value = "";
        await poll();
      }

      async function resetSession() {
        if (state.status === "running") {
          return;
        }
        const res = await fetch("/api/reset", { method: "POST" });
        if (!res.ok) {
          const detail = await res.text();
          alert(detail || "reset 失败");
          return;
        }
        const data = await res.json();
        state.cursor = 0;
        state.eventCount = 0;
        dom.messageList.innerHTML = "";
        dom.toolList.innerHTML = "";
        dom.systemPrompt.textContent = "";
        applyState(data);
      }

      dom.sendBtn.addEventListener("click", sendPrompt);
      dom.resetBtn.addEventListener("click", resetSession);
      dom.promptInput.addEventListener("keydown", (event) => {
        if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
          event.preventDefault();
          sendPrompt();
        }
      });

      poll();
      window.setInterval(poll, 1000);
    </script>
  </body>
</html>
"""


@dataclass(slots=True)
class EventRecord:
    seq: int
    ts: str
    event: str
    payload: Any


class WebSession:
    def __init__(self, *, agent: SessionAgent, model: str, max_rounds: int, log_dir: str) -> None:
        self._agent = agent
        self._model = model
        self._max_rounds = max_rounds
        self._log_dir = log_dir
        self._logger = SessionLogger(log_dir)
        self._events: list[EventRecord] = []
        self._next_seq = 0
        self._status = "idle"
        self._condition = threading.Condition()
        with self._condition:
            self._append_event_locked(
                "session_start",
                {
                    "mode": "web",
                    "model": model,
                    "max_rounds": max_rounds,
                },
            )

    def snapshot(self, after: int = 0) -> dict[str, Any]:
        with self._condition:
            events = [event for event in self._events if event.seq > after]
            return {
                "status": self._status,
                "cursor": self._next_seq,
                "events": [
                    {
                        "seq": event.seq,
                        "ts": event.ts,
                        "event": event.event,
                        "payload": event.payload,
                    }
                    for event in events
                ],
                "system_prompt": SYSTEM_PROMPT,
                "model": self._model,
                "max_rounds": self._max_rounds,
                "log_path": str(self._logger.path),
            }

    def reset(self) -> dict[str, Any]:
        with self._condition:
            if self._status == "running":
                raise RuntimeError("Agent is still running.")
            self._agent.reset()
            self._logger = SessionLogger(self._log_dir)
            self._events = []
            self._next_seq = 0
            self._status = "idle"
            self._append_event_locked(
                "session_start",
                {
                    "mode": "web",
                    "model": self._model,
                    "max_rounds": self._max_rounds,
                },
            )
            return self.snapshot()

    def start_turn(self, prompt: str) -> None:
        with self._condition:
            if self._status == "running":
                raise RuntimeError("Agent is already running.")
            self._status = "running"
            self._append_event_locked("user_prompt", {"text": prompt})

        thread = threading.Thread(target=self._run_turn, args=(prompt,), daemon=True)
        thread.start()

    def _run_turn(self, prompt: str) -> None:
        try:
            turn = self._agent.run_turn(prompt, event_handler=self._handle_agent_event)
            self._append_event(
                "turn_complete",
                {
                    "response_id": turn.response_id,
                    "final_text": turn.final_text,
                },
            )
            self._set_status("idle")
        except Exception as exc:
            self._append_event(
                "error",
                {
                    "type": type(exc).__name__,
                    "message": str(exc),
                    "traceback": traceback.format_exc(),
                },
            )
            self._set_status("error")

    def _handle_agent_event(self, event_type: str, payload: Any) -> None:
        if event_type == "tool_output" and isinstance(payload, ToolEvent):
            payload = {
                "name": payload.name,
                "args": payload.args,
                "output": payload.output,
            }
        self._append_event(event_type, payload)

    def _set_status(self, status: str) -> None:
        with self._condition:
            self._status = status
            self._condition.notify_all()

    def _append_event(self, event_type: str, payload: Any) -> None:
        with self._condition:
            self._append_event_locked(event_type, payload)

    def _append_event_locked(self, event_type: str, payload: Any) -> None:
        self._next_seq += 1
        record = EventRecord(
            seq=self._next_seq,
            ts=datetime.now().isoformat(timespec="seconds"),
            event=event_type,
            payload=payload,
        )
        self._events.append(record)
        self._logger.write(event_type, payload)
        self._condition.notify_all()


class _AppServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], app: WebSession) -> None:
        self.app = app
        super().__init__(server_address, _RequestHandler)


class _RequestHandler(BaseHTTPRequestHandler):
    server: _AppServer

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._write_html(INDEX_HTML)
            return

        if parsed.path == "/api/state":
            query = parse_qs(parsed.query)
            after = int(query.get("after", ["0"])[0] or "0")
            self._write_json(HTTPStatus.OK, self.server.app.snapshot(after=after))
            return

        self._write_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/turn":
            body = self._read_json_body()
            prompt = str(body.get("prompt", "")).strip()
            if not prompt:
                self._write_json(HTTPStatus.BAD_REQUEST, {"error": "Prompt is required."})
                return
            try:
                self.server.app.start_turn(prompt)
            except RuntimeError as exc:
                self._write_json(HTTPStatus.CONFLICT, {"error": str(exc)})
                return
            self._write_json(HTTPStatus.ACCEPTED, self.server.app.snapshot())
            return

        if parsed.path == "/api/reset":
            try:
                snapshot = self.server.app.reset()
            except RuntimeError as exc:
                self._write_json(HTTPStatus.CONFLICT, {"error": str(exc)})
                return
            self._write_json(HTTPStatus.OK, snapshot)
            return

        self._write_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})

    def log_message(self, format: str, *args: object) -> None:
        return

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def _write_html(self, body: str) -> None:
        encoded = body.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _write_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def serve_web_ui(*, agent: SessionAgent, model: str, max_rounds: int, log_dir: str, host: str, port: int) -> None:
    app = WebSession(agent=agent, model=model, max_rounds=max_rounds, log_dir=log_dir)
    server = _AppServer((host, port), app)
    print(f"STS2LLM web UI listening on http://{host}:{port}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping web UI.")
    finally:
        server.server_close()
