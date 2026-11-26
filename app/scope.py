"""Keeps the bot on topic. Cheap word rules first; a tiny AI yes/no check only for unclear messages.
The refusal itself is fixed text written here, so it can never turn into an answer (no '2 + 4 = 6')."""
import logging
import re

from . import leadflow, suggestions

log = logging.getLogger("coachbot")

_GREETING = {"hi", "hii", "hello", "hey", "namaste", "namaskar", "thanks", "thank", "thankyou", "you", "ok", "okay", "yes", "no",
             "haan", "han", "nahi", "theek", "thik", "accha", "achha", "bye", "please", "pls", "sir", "madam", "good", "morning",
             "evening", "afternoon", "night", "sure", "great", "nice", "cool", "got", "it", "welcome", "sorry"}
_LEXICON = {"fee", "fees", "course", "courses", "batch", "batches", "timing", "timings", "class", "classes", "admission", "admissions",
            "scholarship", "test", "tests", "hostel", "faculty", "teacher", "teachers", "demo", "syllabus", "jee", "neet", "foundation",
            "olympiad", "board", "boards", "institute", "coaching", "address", "location", "phone", "contact", "whatsapp", "email",
            "refund", "registration", "register", "study", "material", "result", "results", "seat", "seats", "branch", "branches",
            "online", "offline", "doubt", "exam", "price", "cost", "kitni", "kitna", "kitne", "form", "apply", "enroll", "join",
            "call", "installment", "installments", "discount", "counsellor", "counselor", "cuet", "dropper", "app", "number", "available"}

CLASSIFIER = """You are a strict message router for the chatbot of "{name}", a coaching institute.
Answer YES if the user's message is something a parent or student could reasonably ask this institute or its chatbot: courses, fees, batches, timings, admission, scholarships, tests, results, teachers, facilities, hostel, location, contact details, how the chatbot works, a greeting, thanks, or a short follow-up to the previous chatbot message. A question counts even if the institute might not know the answer (for example parking or food).
Answer NO for anything else: maths problems, weather, news, politics, sports, coding, general knowledge, entertainment, or other companies, even if harmless.
Reply with exactly one word: YES or NO."""

_REFUSAL = {
    "english": ("I can only help with questions about {name}.", " For example: {qs}"),
    "hinglish": ("Main sirf {name} se jude sawaalon mein madad kar sakta hoon.", " Jaise: {qs}"),
    "devanagari": ("\u092e\u0948\u0902 \u0915\u0947\u0935\u0932 {name} \u0938\u0947 \u091c\u0941\u0921\u093c\u0947 \u0938\u0935\u093e\u0932\u094b\u0902 \u092e\u0947\u0902 \u092e\u0926\u0926 \u0915\u0930 \u0938\u0915\u0924\u093e \u0939\u0942\u0901\u0964",
                   " \u091c\u0948\u0938\u0947: {qs}"),
}


def _tokens(text: str) -> list:
    return re.findall(r"[a-z0-9]+", text.lower())


def fast_ok(inst: dict, text: str) -> bool:
    """True when the message is obviously about the institute (or a greeting): no AI check needed."""
    words = set(_tokens(text))
    if not words:
        return False
    if words <= _GREETING or words & _LEXICON:
        return True
    return bool(words & {w for w in _tokens(inst["config"]["name"]) if len(w) >= 4})


_PHONE_ONLY = re.compile(r"^[^\w+]*\+?[\d][\d\s().-]{5,}[^\w]*$")
_ASKED_DETAILS = re.compile(r"\b(name|naam|phone|number|mobile|contact|city|class|exam|time|slot|when|kab)\b", re.I)


def is_detail_reply(text: str, last_bot: str) -> bool:
    """True for the answer to 'what is your name / number?': a phone number on its own, or (right after the bot asked for
    details) a very short plain-letters reply such as a name. These are never off-topic and must not reach the AI check,
    which may say NO to a bare number or name and silently block a callback request."""
    t = text.strip()
    if _PHONE_ONLY.match(t) and 7 <= len(re.sub(r"\D", "", t)) <= 15:
        return True
    asked = "?" in (last_bot or "")[-200:] and bool(_ASKED_DETAILS.search((last_bot or "")[-200:]))
    return asked and len(t) <= 30 and len(t.split()) <= 4 and bool(re.fullmatch(r"[^\W\d_]+(?:[ .'-][^\W\d_]+)*", t))


def on_topic(inst: dict, text: str, last_bot: str, llm) -> bool:
    if fast_ok(inst, text) or is_detail_reply(text, last_bot) or leadflow.is_chip(text):
        return True
    user = f"Previous chatbot message: {(last_bot or '(none)')[:300]}\nUser message: {text[:300]}"
    try:
        turn = llm.complete(CLASSIFIER.format(name=inst["config"]["name"]), [{"role": "user", "content": user}], [],
                            max_tokens=64, allow_tools=False)
    except Exception as exc:  # if the check itself fails, let the normal reply path handle the message
        log.warning("scope check skipped: %s", exc)
        return True
    verdict = (turn.text or "").strip().upper()
    log.info("scope check %r -> %s", text[:60], verdict[:12] or "(empty)")
    return not verdict.startswith("NO")


def refusal(inst: dict, lang: str) -> str:
    head, tail = _REFUSAL[lang]
    text = head.format(name=inst["config"]["name"])
    qs = suggestions.suggest(inst["knowledge"], 3, inst["config"].get("suggested_questions"))
    return text + (tail.format(qs=" / ".join(qs)) if qs else "")
