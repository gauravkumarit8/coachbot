"""LLM providers. brain.py only talks to this interface, so the model can be swapped from .env:
  LLM_PROVIDER=groq (default) | anthropic      LLM_MODEL=<model id>

Interface:  complete(system, msgs, tools) -> Turn      extend(msgs, turn, results) -> None
`msgs` is the running conversation in the provider's own format. `tools` use a neutral shape:
{"name", "description", "parameters": <JSON schema>}."""
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field

log = logging.getLogger("coachbot")

# Groq retired llama-3.3-70b-versatile and llama-3.1-8b-instant (Aug 2026). Check
# https://console.groq.com/docs/models for the current list before changing the default.
DEFAULT_MODELS = {"groq": "openai/gpt-oss-120b", "anthropic": "claude-sonnet-5-5"}
_THINK = re.compile(r"<think>.*?</think>", re.S)


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict


@dataclass
class Turn:
    text: str
    tool_calls: list = field(default_factory=list)
    raw: object = None  # provider-specific assistant message, needed to continue after tool calls


def provider_name() -> str:
    return os.getenv("LLM_PROVIDER", "groq").strip().lower()


def info() -> dict:
    p = provider_name()
    model = os.getenv("LLM_MODEL") or (os.getenv("ANTHROPIC_MODEL") if p == "anthropic" else None)
    return {"provider": p, "model": model or DEFAULT_MODELS.get(p, "?")}


_instances: dict = {}


def get_llm():
    """One shared instance per provider+model, so the HTTP connection is reused (a new TLS handshake
    on every message is a big part of 'slow')."""
    p = provider_name()
    if p not in ("groq", "anthropic"):
        raise ValueError(f"Unknown LLM_PROVIDER '{p}'. Use 'groq' or 'anthropic'.")
    key = (p, info()["model"])
    if key not in _instances:
        _instances[key] = GroqLLM() if p == "groq" else AnthropicLLM()
    return _instances[key]


def _salvage_tool_call(r, known):
    """If Groq rejected a tool call but included the model's attempt ('failed_generation') and it is a call to
    one of OUR tools, return it in OpenAI format. Otherwise None."""
    try:
        gen = r.json()["error"]["failed_generation"]
    except Exception:
        return None
    if not isinstance(gen, str):
        return None
    try:
        obj = json.loads(gen)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", gen, re.S)
        try:
            obj = json.loads(m.group(0)) if m else None
        except json.JSONDecodeError:
            return None
    if isinstance(obj, list):
        obj = obj[0] if obj else None
    if not isinstance(obj, dict):
        return None
    name = re.split(r"[^A-Za-z0-9_]", str(obj.get("name", "")), maxsplit=1)[0]  # cut junk like 'save_lead<|channel|>commentary'
    args = obj.get("arguments", obj.get("parameters", {}))
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            args = {}
    if name not in known or not isinstance(args, dict):
        return None
    return {"id": f"salvaged_{name}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


def _plain_text_only(payload):
    """Last resort after repeated tool failures: no tools, and tell the model so (it still 'wants' to call them)."""
    p = {k: v for k, v in payload.items() if k not in ("tools", "tool_choice")}
    msgs = list(p["messages"])
    msgs[0] = {**msgs[0], "content": msgs[0]["content"] + "\n\nTOOLS ARE UNAVAILABLE for this reply. Do not call any tool. Answer the user in plain text only."}
    p["messages"] = msgs
    return p


class GroqLLM:
    """Groq's OpenAI-compatible chat API, called with plain httpx (no extra SDK needed)."""
    URL = "https://api.groq.com/openai/v1/chat/completions"

    def __init__(self, model=None, api_key=None, http=None):
        self.model = model or info()["model"]
        self.key = api_key or os.getenv("GROQ_API_KEY", "")
        self._http = http  # injectable for tests
        # gpt-oss models are reasoning models: "low" keeps replies fast and cheap. Override or disable via env.
        default_effort = "low" if self.model.startswith("openai/gpt-oss") else ""
        self.effort = os.getenv("GROQ_REASONING_EFFORT", default_effort)

    def _payload(self, system, msgs, tools, max_tokens):
        p = {"model": self.model, "max_tokens": max_tokens,
             "messages": [{"role": "system", "content": system}] + msgs}
        if tools:
            p["tools"] = [{"type": "function", "function": t} for t in tools]
            p["tool_choice"] = "auto"
        if self.effort:
            p["reasoning_effort"] = self.effort
        return p

    def _client(self):
        if self._http is None:
            import httpx  # lazy so tests and parsing work without the dependency
            self._http = httpx.Client(timeout=30, limits=httpx.Limits(max_keepalive_connections=10, keepalive_expiry=60))
        return self._http

    def warm(self):
        """Open the connection before the first customer message (a cold first call is the slowest)."""
        try:
            self._client().get(self.URL.replace("/chat/completions", "/models"),
                               headers={"Authorization": f"Bearer {self.key}"}, timeout=10)
        except Exception as e:
            log.info("LLM warm-up skipped: %s", type(e).__name__)

    def _send(self, payload, known=frozenset()):
        http = self._client()
        tool_failures = 0
        for attempt in range(6):
            try:
                r = http.post(self.URL, json=payload, headers={"Authorization": f"Bearer {self.key}"})
            except Exception as e:  # DNS failure, timeout, proxy/VPN problem...
                raise RuntimeError(f"Cannot reach Groq ({type(e).__name__}). Check internet, VPN/proxy and DNS.") from e
            if r.status_code == 200:
                return r.json()
            if r.status_code in (429, 500, 502, 503) and attempt < 5:  # rate limit / hiccup: wait, retry
                try:
                    wait = min(float(r.headers.get("retry-after", 2 ** attempt)), 8)
                except (TypeError, ValueError):
                    wait = 2
                log.warning("Groq %s (%s) retrying in %.0fs", r.status_code, r.text[:400].replace("\n", " "), wait)
                time.sleep(wait)
                continue
            if r.status_code == 400 and "tool" in r.text.lower():
                # Open models sometimes emit a call Groq's validator rejects (missing argument, junk in the name).
                # The error carries the model's attempt, so use it: our own code answers it politely.
                call = _salvage_tool_call(r, known)
                if call:
                    log.warning("Groq rejected a tool call; using the model's call from the error: %s", call["function"]["name"])
                    return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [call]}}], "usage": {}}
                tool_failures += 1
                if tool_failures == 1:
                    log.warning("Groq rejected a tool call, trying once more: %s", r.text[:200].replace("\n", " "))
                elif tool_failures == 2:
                    log.warning("Groq rejected a tool call again, answering in plain text: %s", r.text[:200].replace("\n", " "))
                    payload = _plain_text_only(payload)
                else:
                    raise RuntimeError(f"Groq API 400: {r.text[:300]}")
                continue
            raise RuntimeError(f"Groq API {r.status_code}: {r.text[:300]}")
        raise RuntimeError("Groq API: retries exhausted")

    def complete(self, system, msgs, tools, max_tokens=600, allow_tools=True) -> Turn:
        t0 = time.perf_counter()
        data = self._send(self._payload(system, msgs, tools if allow_tools else [], max_tokens), {t["name"] for t in tools})
        u = data.get("usage") or {}
        log.info("LLM %s %.1fs prompt_tokens=%s completion_tokens=%s queue_time=%s", self.model,
                 time.perf_counter() - t0, u.get("prompt_tokens"), u.get("completion_tokens"), u.get("queue_time"))
        m = data["choices"][0]["message"]
        text = _THINK.sub("", m.get("content") or "").strip()  # never show model 'thinking' to parents
        calls = []
        for tc in m.get("tool_calls") or []:
            try:
                args = json.loads(tc["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            calls.append(ToolCall(tc["id"], tc["function"]["name"], args if isinstance(args, dict) else {}))
        raw = {"role": "assistant", "content": m.get("content") or None}
        if m.get("tool_calls"):
            raw["tool_calls"] = m["tool_calls"]
        return Turn(text, calls, raw)

    def extend(self, msgs, turn, results):
        msgs.append(turn.raw)
        for tc, result in results:
            msgs.append({"role": "tool", "tool_call_id": tc.id, "content": result})


class AnthropicLLM:
    """Optional: Claude via the official SDK (pip install anthropic, set ANTHROPIC_API_KEY)."""

    def __init__(self, model=None, client=None):
        self.model = model or info()["model"]
        self._client = client

    def warm(self):
        pass

    def complete(self, system, msgs, tools, max_tokens=600, allow_tools=True) -> Turn:
        # allow_tools is ignored here: Anthropic requires tools to stay defined once tool blocks are in the chat.
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic()
        kw = dict(model=self.model, max_tokens=max_tokens, system=system, messages=msgs)
        if tools:  # the scope check calls with no tools
            kw["tools"] = [{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]} for t in tools]
        resp = self._client.messages.create(**kw)
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        calls = [ToolCall(b.id, b.name, dict(b.input)) for b in resp.content if b.type == "tool_use"]
        return Turn(text, calls, resp.content)

    def extend(self, msgs, turn, results):
        msgs.append({"role": "assistant", "content": turn.raw})
        msgs.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": tc.id, "content": result} for tc, result in results]})
