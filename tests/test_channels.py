"""Offline tests for WhatsApp parsing and provider routing. Run: python -m tests.test_channels"""
import os
import logging
from app import channels

logging.disable(logging.CRITICAL)  # new tests trigger expected warnings

os.environ["DEMO_WA_KEY"] = "secret123"
calls = []
channels._post = lambda url, headers, payload: calls.append((url, headers, payload)) or True

# Meta-format inbound payload (used by Meta directly and by Cloud-API-style BSPs)
payload = {"entry": [{"changes": [{"value": {
    "metadata": {"phone_number_id": "111"},
    "messages": [{"id": "wamid.A", "from": "919900000000", "type": "text", "text": {"body": "fees?"}}]}},
    {"value": {"metadata": {"phone_number_id": "111"}, "statuses": [{"status": "delivered"}]}}]}]}
parsed = channels.parse_whatsapp(payload)
assert parsed == [("111", payload["entry"][0]["changes"][0]["value"]["messages"][0])]  # statuses ignored

# Direct Meta send
channels.send_whatsapp(channels.wa_settings({"whatsapp": {"phone_number_id": "111", "api_key_env": "DEMO_WA_KEY"}}), "91999", "hi")
url, headers, body = calls[-1]
assert url.endswith("/111/messages") and headers == {"Authorization": "Bearer secret123"}
assert body["to"] == "91999" and body["text"]["body"] == "hi"

# BSP send, API-key header style (360dialog-like)
bsp = {"whatsapp": {"provider": "bsp", "send_url": "https://waba-v2.360dialog.io/messages",
                    "auth_header": "D360-API-KEY", "api_key_env": "DEMO_WA_KEY"}}
channels.send_whatsapp(channels.wa_settings(bsp), "91999", "hello")
url, headers, body = calls[-1]
assert url == "https://waba-v2.360dialog.io/messages" and headers == {"D360-API-KEY": "secret123"}

# BSP send, bearer style
bsp["whatsapp"]["auth_header"] = "Authorization"
channels.send_whatsapp(channels.wa_settings(bsp), "91999", "hello")
assert calls[-1][1] == {"Authorization": "Bearer secret123"}

# Empty/whitespace key: nothing is sent (this used to crash with an illegal-header error); padded keys are trimmed
n = len(calls)
os.environ["EMPTY_KEY"] = "   "
assert channels.send_whatsapp(channels.wa_settings({"whatsapp": {"phone_number_id": "1", "api_key_env": "EMPTY_KEY"}}), "9", "x") is False
os.environ.pop("NO_SUCH_ENV", None)
assert channels.send_whatsapp(channels.wa_settings({"whatsapp": {"phone_number_id": "1", "api_key_env": "NO_SUCH_ENV"}}), "9", "x") is False
assert channels.send_meta("1", "x", "NO_SUCH_ENV") is False
assert len(calls) == n  # nothing was sent
os.environ["PADDED_KEY"] = "  tok123 \n"
channels.send_whatsapp(channels.wa_settings({"whatsapp": {"phone_number_id": "1", "api_key_env": "PADDED_KEY"}}), "9", "x")
assert calls[-1][1] == {"Authorization": "Bearer tok123"}

# Missing config defaults to Meta provider
assert channels.wa_settings({})["provider"] == "meta"
# Background helper runs the job off-thread and survives errors
import threading, time
done = []
t = channels.run_in_background(lambda: (time.sleep(0.05), done.append(threading.current_thread().name)))
assert not done and t.daemon  # returned immediately, job still running
t.join(); assert done and done[0] != threading.main_thread().name
import logging; logging.disable(logging.CRITICAL)
channels.run_in_background(lambda: 1 / 0).join()  # error is logged, not raised
print("channel tests passed")
