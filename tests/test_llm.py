"""Offline tests for the Groq/Anthropic adapters using fake HTTP/SDK objects. Run: python -m tests.test_llm"""
import json, logging, os
from types import SimpleNamespace as NS

from app import llm

logging.disable(logging.CRITICAL)
llm.time.sleep = lambda s: None  # don't actually wait during retry tests
TOOLS = [{"name": "save_lead", "description": "d", "parameters": {"type": "object", "properties": {}}}]


class Resp:
    def __init__(self, status, data=None, headers=None):
        self.status_code, self._d, self.headers = status, data or {}, headers or {}
        self.text = json.dumps(self._d)
    def json(self): return self._d


class FakeHTTP:
    def __init__(self, *resps): self.resps, self.sent = list(resps), []
    def post(self, url, json=None, headers=None):
        self.sent.append({"url": url, "json": json, "headers": headers})
        return self.resps.pop(0)


def ok(message): return Resp(200, {"choices": [{"message": message, "finish_reason": "stop"}]})


# 1. Request shape: system first, function-style tools, auth header, reasoning effort for gpt-oss
http = FakeHTTP(ok({"role": "assistant", "content": "Hello!"}))
g = llm.GroqLLM(model="openai/gpt-oss-120b", api_key="k1", http=http)
turn = g.complete("SYS", [{"role": "user", "content": "hi"}], TOOLS)
sent = http.sent[0]
assert turn.text == "Hello!" and not turn.tool_calls
assert sent["url"].endswith("/openai/v1/chat/completions") and sent["headers"] == {"Authorization": "Bearer k1"}
assert sent["json"]["messages"][0] == {"role": "system", "content": "SYS"}
assert sent["json"]["tools"][0] == {"type": "function", "function": TOOLS[0]} and sent["json"]["reasoning_effort"] == "low"

# 1b. allow_tools=False sends no tools (final-answer call)
http = FakeHTTP(ok({"role": "assistant", "content": "done"}))
llm.GroqLLM(model="openai/gpt-oss-20b", api_key="k", http=http).complete("S", [], TOOLS, allow_tools=False)
assert "tools" not in http.sent[0]["json"] and "tool_choice" not in http.sent[0]["json"]

# 2. Non-gpt-oss model: no reasoning_effort sent
http = FakeHTTP(ok({"role": "assistant", "content": "x"}))
llm.GroqLLM(model="qwen/qwen3.6-27b", api_key="k", http=http).complete("S", [], TOOLS)
assert "reasoning_effort" not in http.sent[0]["json"]

# 3. Tool call parsing + continuing the conversation in OpenAI format
tc = {"id": "call_1", "type": "function", "function": {"name": "save_lead", "arguments": '{"name":"Ravi","phone":"999"}'}}
http = FakeHTTP(ok({"role": "assistant", "content": None, "reasoning": "secret", "tool_calls": [tc]}))
g = llm.GroqLLM(model="m", api_key="k", http=http)
turn = g.complete("S", [], TOOLS)
assert turn.tool_calls[0].name == "save_lead" and turn.tool_calls[0].args == {"name": "Ravi", "phone": "999"}
msgs = [{"role": "user", "content": "hi"}]
g.extend(msgs, turn, [(turn.tool_calls[0], "Lead saved")])
assert msgs[1] == {"role": "assistant", "content": None, "tool_calls": [tc]}  # extra fields like 'reasoning' stripped
assert msgs[2] == {"role": "tool", "tool_call_id": "call_1", "content": "Lead saved"}

# 4. Malformed tool arguments don't crash; <think> blocks never reach the user
bad = {"id": "c2", "type": "function", "function": {"name": "save_lead", "arguments": "{oops"}}
t = llm.GroqLLM(model="m", api_key="k", http=FakeHTTP(ok({"role": "assistant", "content": "<think>hmm</think>Hi!", "tool_calls": [bad]}))).complete("S", [], TOOLS)
assert t.tool_calls[0].args == {} and t.text == "Hi!"

# 5. Rate limit (429) then success
http = FakeHTTP(Resp(429, {"error": "slow down"}, {"retry-after": "1"}), ok({"role": "assistant", "content": "ok"}))
assert llm.GroqLLM(model="m", api_key="k", http=http).complete("S", [], TOOLS).text == "ok" and len(http.sent) == 2

# 6. A tool call Groq rejects with no usable attempt: resample once with tools; then plain text with a clear instruction
BAD = Resp(400, {"error": {"code": "tool_use_failed", "message": "Failed to call a function"}})
http = FakeHTTP(BAD, ok({"role": "assistant", "content": "second try worked"}))
t = llm.GroqLLM(model="m", api_key="k", http=http).complete("S", [], TOOLS)
assert t.text == "second try worked" and "tools" in http.sent[1]["json"]            # same request, sampled again
http = FakeHTTP(BAD, BAD, ok({"role": "assistant", "content": "plain answer"}))
t = llm.GroqLLM(model="m", api_key="k", http=http).complete("S", [], TOOLS)
last = http.sent[2]["json"]
assert t.text == "plain answer" and "tools" not in last and "TOOLS ARE UNAVAILABLE" in last["messages"][0]["content"]
try:
    llm.GroqLLM(model="m", api_key="k", http=FakeHTTP(BAD, BAD, BAD)).complete("S", [], TOOLS); raise AssertionError("should raise")
except RuntimeError as e:
    assert "400" in str(e)

# 6b. Salvage: the exact failures from a real console log. Groq's validator rejected the call, but the error
#     contains the model's attempt, so we use it instead of failing the customer's message.
BOTH = TOOLS + [{"name": "handoff_to_human", "description": "d", "parameters": {"type": "object", "properties": {}}}]
def rejected(msg, gen): return Resp(400, {"error": {"message": msg, "type": "invalid_request_error", "code": "tool_use_failed", "failed_generation": gen}})
cases = [
    (rejected("Tool call validation failed: parameters for tool save_lead did not match schema: errors: [missing properties: 'phone']",
              '{"name": "save_lead", "arguments": {"name": "Gairav"}}'), "save_lead", {"name": "Gairav"}),
    (rejected("Tool choice is none, but model called a tool",
              '{"name": "handoff_to_human", "arguments": {"reason":"Need phone number but user says name only"}}'),
     "handoff_to_human", {"reason": "Need phone number but user says name only"}),
    (rejected("Failed to parse tool call arguments as JSON",
              '{"name": "save_lead<|channel|>commentary", "arguments": {"name": "Ravi", "phone": "9990001111"}}'),
     "save_lead", {"name": "Ravi", "phone": "9990001111"}),
]
for resp, name, args in cases:
    http = FakeHTTP(resp)
    t = llm.GroqLLM(model="m", api_key="k", http=http).complete("S", [], BOTH)
    assert len(http.sent) == 1 and t.tool_calls[0].name == name and t.tool_calls[0].args == args, (name, t.tool_calls)
    msgs = []; g = llm.GroqLLM(model="m", api_key="k", http=FakeHTTP()); g.extend(msgs, t, [(t.tool_calls[0], "ok")])
    assert msgs[0]["tool_calls"][0]["function"]["name"] == name and msgs[1]["role"] == "tool"   # conversation can continue
# a call to a tool we do not have is NOT trusted
http = FakeHTTP(rejected("Tool call validation failed", '{"name": "delete_everything", "arguments": {}}'), ok({"role": "assistant", "content": "fine"}))
assert llm.GroqLLM(model="m", api_key="k", http=http).complete("S", [], BOTH).text == "fine" and len(http.sent) == 2

# 7. Hard errors raise (brain turns this into a safe fallback + handoff)
try:
    llm.GroqLLM(model="m", api_key="bad", http=FakeHTTP(Resp(401, {"error": "invalid key"}))).complete("S", [], TOOLS)
    raise AssertionError("should raise")
except RuntimeError as e:
    assert "401" in str(e)

# 7b. Network/DNS failure gives a clear message
class Offline:
    def post(self, *a, **k): raise OSError("getaddrinfo failed")
try:
    llm.GroqLLM(model="m", api_key="k", http=Offline()).complete("S", [], TOOLS); raise AssertionError("should raise")
except RuntimeError as e:
    assert "Cannot reach Groq" in str(e)

# 7c. Warm-up opens the connection; failures are harmless
class WarmHTTP(FakeHTTP):
    def get(self, url, headers=None, timeout=None):
        self.sent.append({"get": url, "headers": headers}); return Resp(200)
wh = WarmHTTP(); llm.GroqLLM(model="m", api_key="k1", http=wh).warm()
assert wh.sent[0]["get"].endswith("/openai/v1/models") and wh.sent[0]["headers"] == {"Authorization": "Bearer k1"}
llm.GroqLLM(model="m", api_key="k", http=Offline()).warm()  # no exception

# 8. Provider selection and defaults
os.environ.pop("LLM_PROVIDER", None); os.environ.pop("LLM_MODEL", None)
assert llm.info() == {"provider": "groq", "model": "openai/gpt-oss-120b"}
os.environ["LLM_PROVIDER"] = "anthropic"
assert llm.info()["provider"] == "anthropic" and isinstance(llm.get_llm(), llm.AnthropicLLM)
assert llm.get_llm() is llm.get_llm()  # shared instance => connection reuse
os.environ["LLM_PROVIDER"] = "nope"
try:
    llm.get_llm(); raise AssertionError("should raise")
except ValueError:
    pass

# 9. Anthropic adapter (fake SDK): neutral tools converted, tool results sent back
class FakeSDK:
    def __init__(self): self.messages, self.kw = self, None
    def create(self, **kw):
        self.kw = kw
        return NS(content=[NS(type="text", text="hi"), NS(type="tool_use", id="a1", name="save_lead", input={"name": "R", "phone": "1"})])
sdk = FakeSDK(); a = llm.AnthropicLLM(model="claude-x", client=sdk)
t = a.complete("S", [], TOOLS)
assert sdk.kw["tools"][0]["input_schema"] == TOOLS[0]["parameters"] and t.tool_calls[0].args == {"name": "R", "phone": "1"}
m = []; a.extend(m, t, [(t.tool_calls[0], "done")])
assert m[1]["content"][0] == {"type": "tool_result", "tool_use_id": "a1", "content": "done"}
sdk2 = FakeSDK(); llm.AnthropicLLM(model="claude-x", client=sdk2).complete("S", [], [])
assert "tools" not in sdk2.kw   # the off-topic check calls with no tools
print("llm tests passed")
