"""Offline tests: off-topic gate, fixed refusals, no repeated contact block, shorter history. Run: python -m tests.test_scope"""
import logging, os, tempfile

os.environ["COACHBOT_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
from app import brain, db  # noqa: E402
from app.llm import Turn  # noqa: E402

logging.disable(logging.CRITICAL)
db.init()
INST = brain.load_institutes()["demo"]
INST["config"]["lead_offers"] = False   # these tests are about other behaviour; the callback offers have their own tests (test_leadflow.py)
NAME = INST["config"]["name"]


class Fake:
    """Answers the off-topic check with `router`, and the real reply from scripted answers."""
    def __init__(self, *answers, router="YES"):
        self.answers, self.router, self.router_calls, self.main_calls = list(answers), router, [], []
    def complete(self, system, msgs, tools, max_tokens=600, allow_tools=True):
        if "message router" in system:
            self.router_calls.append(msgs[0]["content"])
            if isinstance(self.router, Exception):
                raise self.router
            return Turn(self.router)
        self.main_calls.append(system)
        return self.answers.pop(0)
    def extend(self, msgs, turn, results):
        pass


def say(t): return Turn(t)


# 1. Obvious on-topic messages and greetings never cost an extra AI call
for i, msg in enumerate(["fees kitni hai?", "hello", "Thanks!", "Is there a hostel?", "scholarship test kab hai", "what is the course fee"]):
    f = Fake(say("ok")); out = brain.run_turn(INST, "website", f"a{i}", msg, None, f)
    assert f.router_calls == [] and len(f.main_calls) == 1 and out["reply"] == "ok", msg

# 1b. Answers to "what is your name / number?" are never refused and never need the AI check
for i, (msg, bot) in enumerate([("9608621088", ""), ("+91 99900 01111", "x"), ("99900-01111", "x"), ("(0612) 2345678", "x"),
                                ("Gaurav", "May I have your name?"), ("Ravi Kumar", "What is your name and phone number?"),
                                ("Patna", "Which city are you in?"), ("Class 11", "Which class is the student in?")]):
    if bot: db.add_message("demo", "website", f"d{i}", "assistant", bot)      # what the bot said just before
    f = Fake(say("ok"), router="NO"); out = brain.run_turn(INST, "website", f"d{i}", msg, None, f)
    assert f.router_calls == [] and out["reply"] == "ok", (msg, out)
# ...but this must not become a hole: arithmetic, long text and a bare name with no question before it still go through the gate
for i, (msg, bot) in enumerate([("2+4", "May I have your name?"), ("1234", "May I have your name?"), ("weather today in patna sir please tell", "May I have your name?"),
                                ("Gaurav", "Fees are Rs 45,000."), ("Gaurav", "May I have your name"), ("Who is the PM of India", "May I have your name?")]):
    db.add_message("demo", "website", f"e{i}", "assistant", bot)
    f = Fake(say("ok"), router="NO"); out = brain.run_turn(INST, "website", f"e{i}", msg, None, f)
    assert f.router_calls and out["reply"].startswith("I can only help"), (msg, out)

# 2. Off-topic: fixed refusal in the user's language, the main model is never asked, suggestions included, stored
cases = [("2+4", "I can only help with questions about " + NAME), ("how is the weather today", "I can only help with"),
         ("who is pm of india", "I can only help with"), ("aaj mausam kaisa hai", "Main sirf " + NAME),
         ("\u092e\u094c\u0938\u092e \u0915\u0948\u0938\u093e \u0939\u0948", "\u092e\u0948\u0902 \u0915\u0947\u0935\u0932")]
for i, (msg, start) in enumerate(cases):
    f = Fake(router="NO"); out = brain.run_turn(INST, "website", f"b{i}", msg, None, f)
    assert out["reply"].startswith(start) and not out["handoff"] and f.main_calls == [] and len(f.router_calls) == 1, (msg, out)
    assert "Which courses do you offer?" in out["reply"] or "Tell me about the institute" in out["reply"], out["reply"]
    assert db.history("demo", "website", f"b{i}")[-1]["text"] == out["reply"]
assert "2 + 4" not in out["reply"]

# 3. Unclear but on-topic messages pass the check; follow-ups are judged WITH the previous bot message
f = Fake(say("We have no parking details."))
out = brain.run_turn(INST, "website", "c1", "do you have parking?", None, f)
assert "Previous chatbot message: (none)" in f.router_calls[0] and out["reply"].startswith("We have")
db.add_message("demo", "website", "c2", "user", "fees?"); db.add_message("demo", "website", "c2", "assistant", "Class 11-12 fee is Rs 45,000.")
f = Fake(say("Same fee.")); brain.run_turn(INST, "website", "c2", "and for 12th?", None, f)
assert "Class 11-12 fee is Rs 45,000." in f.router_calls[0]

# 4. If the check fails or answers oddly, the customer is never blocked (fail open)
for i, router in enumerate([RuntimeError("boom"), "maybe", ""]):
    f = Fake(say("An answer."), router=router)
    assert brain.run_turn(INST, "website", f"d{i}", "do you have parking?", None, f)["reply"] == "An answer."

# 5. A repeated contact block (the exact replies from a real chat) is trimmed, but NOT when the user asks for contact details
FIRST = ("I don't have the fee details here.  \nPlease contact Tribac Blue directly:\n\n- Phone/WhatsApp: +91 8102469653 or +91 9570961582  \n"
         "- Email: tribacpatna@gmail.com  \n- Address: Kanti Factory Main Road, Kankarbagh, Patna \u2013 800020")
SECOND = ("Tribac Blue is a coaching institute in Kankarbagh, Patna offering IIT-JEE, NEET and foundation courses.\n\n"
          "For more specific details (timings, fees, admission steps) you can reach out at:\n\n- Phone/WhatsApp: +91 8102469653 or +91 9570961582  \n"
          "- Email: tribacpatna@gmail.com  \n- Address: Kanti Factory Main Road, Kankarbagh, Patna \u2013 800020")
f = Fake(say(FIRST), say(SECOND), say(SECOND))
first = brain.run_turn(INST, "website", "e1", "what is the course fee", None, f)
assert "8102469653" in first["reply"]                                   # first time: contact details are given
out = brain.run_turn(INST, "website", "e1", "tell me a little about the institute", None, f)
assert "8102469653" not in out["reply"] and "tribacpatna" not in out["reply"] and "reach out" not in out["reply"]
assert out["reply"].startswith("Tribac Blue is a coaching") and out["reply"].endswith("foundation courses.")
out = brain.run_turn(INST, "website", "e1", "what is your phone number?", None, f)
assert "8102469653" in out["reply"]                                     # asked for it: keep

# 6. Edge cases of the trimming
assert brain._dedupe_contact("Short answer.", "earlier text +91 8102469653", "fees?") == "Short answer."
assert brain._dedupe_contact("- Phone: +91 8102469653", "Phone +91 8102469653", "fees?") == "- Phone: +91 8102469653"  # would be empty: keep
assert "9999999999" in brain._dedupe_contact("Info.\n\n- Phone: +91 9999999999", "+91 8102469653", "fees?")             # a new number stays
assert brain._dedupe_contact("Info.\n\n- Phone: +91 8102469653", "", "fees?").endswith("8102469653")                      # nothing sent before

# 7. Long OLD bot replies are shortened in what the model sees; the latest reply is kept whole
hist = [{"role": "user", "text": "a"}, {"role": "assistant", "text": "x" * 800}, {"role": "user", "text": "b"},
        {"role": "assistant", "text": "y" * 800}, {"role": "user", "text": "c"}]
m = brain._messages(hist)
assert len(m[1]["content"]) <= 354 and m[1]["content"].endswith("...") and m[3]["content"] == "y" * 800
print("scope tests passed")
