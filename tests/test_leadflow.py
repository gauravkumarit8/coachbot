"""Offline tests: optional, skippable callback offers. Run: python -m tests.test_leadflow"""
import logging, os, tempfile

os.environ["COACHBOT_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
from app import brain, db, leadflow as L  # noqa: E402
from app.llm import ToolCall, Turn  # noqa: E402

logging.disable(logging.CRITICAL)
db.init()
INST = brain.load_institutes()["demo"]
NAME = INST["config"]["name"]
OFFER_EN, OFFER_HI = L.OFFER["english"], L.OFFER["hinglish"]


class Fake:
    router = "YES"
    def __init__(self, *turns): self.turns, self.calls = list(turns), []
    def complete(self, system, msgs, tools, max_tokens=600, allow_tools=True):
        if "message router" in system: return Turn(self.router)
        self.calls.append(system); return self.turns.pop(0)
    def extend(self, msgs, turn, results): msgs += [{"role": "assistant", "content": "(tool)"}, {"role": "user", "content": "(result)"}]


def say(t): return Turn(t)
def chat(uid, text, *replies, channel="website", inst=INST):
    f = Fake(*[say(r) for r in replies]); out = brain.run_turn(inst, channel, uid, text, None, f); out["_calls"] = f.calls; return out


# 1. Ordinary first question: answered, NO offer
o = chat("a1", "What are the fees for Class 11?", "Class 11 is Rs 45,000 a year.")
assert o["reply"] == "Class 11 is Rs 45,000 a year." and "actions" not in o

# 2. Clear buying signal: the answer comes first, then ONE polite offer with Yes / No buttons
o = chat("b1", "How do I take admission?", "Fill the form and pay the registration fee.")
assert o["reply"] == "Fill the form and pay the registration fee.\n\n" + OFFER_EN, o
assert [a["label"] for a in o["actions"]] == ["Yes, call me back", "No thanks"]
assert db.history("demo", "website", "b1", 5)[-1]["text"].endswith(OFFER_EN)      # remembered, so it is never repeated

# 3. "No thanks": fixed reply, NO AI call, and never asked again in this chat, even on another buying signal
o = chat("b1", "No thanks")
assert o["_calls"] == [] and o["reply"].startswith("No problem.") and NAME in o["reply"] and "actions" not in o
o = chat("b1", "I want a demo class", "Our free demo class is on Saturdays.")
assert o["reply"] == "Our free demo class is on Saturdays." and "actions" not in o and "call me back" not in o["reply"].lower().replace("write", "")

# 4. "Yes": the AI is told to ask ONLY for a first name (optional), nothing else
o = chat("c1", "Is there a scholarship test?", "Yes, every Sunday.")
assert OFFER_EN in o["reply"]
o = chat("c1", "Yes, call me back", "Great! May I know your name? You can skip if you prefer.")
assert "Ask ONLY for their first name" in o["_calls"][0]
assert [a["label"] for a in o["actions"]] == ["Skip"]                         # asking for a name: always a Skip button
o = chat("c1", "Skip")
assert o["_calls"] == [] and o["reply"].startswith("No problem.")
assert not db.has_lead("demo", "website", "c1")

# 5. Giving details: no more offers once a lead exists
o = chat("d1", "I want to join the JEE batch", "Please share your name and number so we can call you.")
assert "actions" in o and o["actions"][0]["label"] == "Skip" and OFFER_EN not in o["reply"]   # the AI asked itself: no second offer
db.save_lead("demo", "website", "d1", name="Ravi", phone="9990001111")
o = chat("d1", "What are the batch timings?", "Batches run 4 to 7 pm.")
assert o["reply"] == "Batches run 4 to 7 pm." and "actions" not in o

# 6. The AI offered a callback itself: attach the buttons, do not add a second offer
o = chat("e1", "tell me about the courses", "We offer JEE and NEET. Would you like a callback from our counsellor?")
assert o["reply"].count("?") == 1 and [a["label"] for a in o["actions"]] == ["Yes, call me back", "No thanks"]

# 7. Engaged enough: three real questions, then ONE offer (not before, not twice)
r = [chat("f1", "fees kitni hai?", "Rs 45,000.")["reply"]]
assert OFFER_HI not in r[0]
r.append(chat("f1", "batch timing?", "4 to 7 pm.")["reply"]); assert OFFER_HI not in r[1]
o = chat("f1", "teachers kaun hain?", "Experienced faculty.")
assert o["reply"].endswith(OFFER_HI) and o["actions"][0]["label"] == "Haan, call karein"      # Hinglish offer for a Hinglish chat
o = chat("f1", "and the results?", "Good results every year.")
assert "actions" not in o and OFFER_HI not in o["reply"]                                         # ignored once: not repeated right away

# 8. Devanagari chat gets a Devanagari offer and buttons
o = chat("g1", "\u090f\u0921\u092e\u093f\u0936\u0928 \u0915\u0948\u0938\u0947 \u0932\u0947\u0902?", "\u092b\u0949\u0930\u094d\u092e \u092d\u0930\u0947\u0902\u0964")
assert o["reply"].endswith(L.OFFER["devanagari"]) and o["actions"][1]["label"] == L.NO["devanagari"]
o = chat("g1", L.NO["devanagari"])
assert o["_calls"] == [] and o["reply"].startswith("\u0915\u094b\u0908 \u092c\u093e\u0924")

# 9. No offer when the details do not cover the question (the contact options were already given), or off topic
o = chat("h1", "Do you have admission for a hostel with AC?", "[[NOINFO]] I don't have that information. Please call the office.")
assert "actions" not in o and OFFER_EN not in o["reply"]
Fake.router = "NO"
o = chat("h2", "2+4")
Fake.router = "YES"
assert o["reply"].startswith("I can only help") and "actions" not in o

# 10. Chat apps have no buttons: the choice is written as text
o = chat("w1", "How do I take admission?", "Fill the form.", channel="whatsapp")
assert "actions" not in o and o["reply"].endswith(L.TEXT_CHOICE["english"]) and OFFER_EN in o["reply"]
o = chat("w1", "NO", channel="whatsapp")
assert o["_calls"] == [] and o["reply"].startswith("No problem.")
o = chat("w2", "I want a demo", "Please share your number.", channel="whatsapp")
assert o["reply"].endswith(L.TEXT_SKIP["english"])

# 11. Owner can switch it off
off = {**INST, "config": {**INST["config"], "lead_offers": False}}
o = chat("z1", "How do I take admission?", "Fill the form.", inst=off)
assert o["reply"] == "Fill the form." and "actions" not in o

# 12. A plain "no" to some other question is NOT a decline (only right after an offer / request for details)
o = chat("n1", "Is there a hostel?", "Hostel information is not listed.")
o = chat("n1", "no", "Okay.")
assert o["_calls"] != [] and o["reply"] == "Okay."

# 13. Unit checks of the helpers
assert L.interest("admission kab se start") == 2 and L.interest("fees?") == 1 and L.interest("hello") == 0
assert L.is_chip("No thanks") and L.is_chip(L.YES["devanagari"]) and not L.is_chip("2+4")
assert not L.should_offer([{"role": "user", "text": "admission?"}], True, "x")             # lead exists
assert not L.should_offer([{"role": "user", "text": "admission?"}], False, "x", enabled=False)
print("leadflow tests passed")
