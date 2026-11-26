"""Smart, OPTIONAL contact requests.

The bot never makes help depend on personal details. But a parent who asks about admission, a demo class or a seat is a
real prospect, so when the chat shows that kind of interest the bot adds ONE short, polite offer of a callback, with two
buttons: "Yes, call me back" and "No thanks". Saying no (or "Skip" when asked for a name or number) is final for that chat.

Decisions are made here in code from the words used and the chat so far (small AI models are unreliable at timing
this, and the code costs no extra AI call). Owners can switch it off with "lead_offers": false in config.json."""
import re

# ---- fixed texts (code, not AI): English, Hinglish (English letters), Hindi (Devanagari) ----
OFFER = {
    "english": "Would you like our counsellor to call you back about this? Only if you want to, there is no obligation.",
    "hinglish": "Kya aap chahenge ki hamare counsellor aapko is baare mein call karein? Sirf agar aap chahein, koi zaroori nahi.",
    "devanagari": "\u0915\u094d\u092f\u093e \u0906\u092a \u091a\u093e\u0939\u0947\u0902\u0917\u0947 \u0915\u093f \u0939\u092e\u093e\u0930\u0947 \u0915\u093e\u0909\u0902\u0938\u0932\u0930 \u0907\u0938 \u092c\u093e\u0930\u0947 \u092e\u0947\u0902 \u0906\u092a\u0915\u094b \u0915\u0949\u0932 \u0915\u0930\u0947\u0902? \u0915\u0947\u0935\u0932 \u092f\u0926\u093f \u0906\u092a \u091a\u093e\u0939\u0947\u0902, \u0915\u094b\u0908 \u092c\u093e\u0927\u094d\u092f\u0924\u093e \u0928\u0939\u0940\u0902\u0964",
}
YES = {"english": "Yes, call me back", "hinglish": "Haan, call karein", "devanagari": "\u0939\u093e\u0901, \u0915\u0949\u0932 \u0915\u0930\u0947\u0902"}
NO = {"english": "No thanks", "hinglish": "Nahi, abhi nahi", "devanagari": "\u0928\u0939\u0940\u0902, \u0927\u0928\u094d\u092f\u0935\u093e\u0926"}
SKIP = {"english": "Skip", "hinglish": "Skip karein", "devanagari": "\u091b\u094b\u0921\u093c\u0947\u0902"}
AFTER_SKIP = {
    "english": 'No problem. Ask me anything else about {name}. If you change your mind, just write "call me back".',
    "hinglish": 'Koi baat nahi. {name} ke baare mein aur kuch bhi poochhiye. Mann badle toh bas "call me back" likh dijiye.',
    "devanagari": "\u0915\u094b\u0908 \u092c\u093e\u0924 \u0928\u0939\u0940\u0902\u0964 {name} \u0915\u0947 \u092c\u093e\u0930\u0947 \u092e\u0947\u0902 \u0915\u0941\u091b \u092d\u0940 \u092a\u0942\u091b\u093f\u090f\u0964 \u092e\u0928 \u092c\u0926\u0932\u0947 \u0924\u094b \u092c\u0938 \"call me back\" \u0932\u093f\u0916 \u0926\u0940\u091c\u093f\u090f\u0964",
}
# Chat apps (WhatsApp, Instagram, Facebook) have no buttons here, so the choice is written as text.
TEXT_CHOICE = {"english": "(Reply YES for a call back, or NO to skip.)", "hinglish": "(Call ke liye YES likhiye, ya NO likhkar skip karein.)",
               "devanagari": "(\u0915\u0949\u0932 \u0915\u0947 \u0932\u093f\u090f YES \u0932\u093f\u0916\u0947\u0902, \u092f\u093e NO \u0932\u093f\u0916\u0915\u0930 \u091b\u094b\u0921\u093c\u0947\u0902\u0964)"}
TEXT_SKIP = {"english": "(You can reply SKIP if you would rather not share.)", "hinglish": "(Agar nahi dena chahte toh SKIP likh dijiye.)",
             "devanagari": "(\u0905\u0917\u0930 \u0928\u0939\u0940\u0902 \u0926\u0947\u0928\u093e \u091a\u093e\u0939\u0924\u0947 \u0924\u094b SKIP \u0932\u093f\u0916 \u0926\u0940\u091c\u093f\u090f\u0964)"}

_CHIP_TEXTS = {re.sub(r"\W+", " ", t.lower()).strip() for d in (YES, NO, SKIP) for t in d.values()}
_SKIP_WORDS = re.compile(r"^\W*(no|nope|nahi|nahin|skip|skip karein|not now|no thanks?|no thank you|maybe later|later|abhi nahi|nahi chahiye|"
                         r"rehne do|dont want|don.t want|not interested|\u0928\u0939\u0940\u0902|\u0928\u0939\u0940\u0902 \u0927\u0928\u094d\u092f\u0935\u093e\u0926|"
                         r"\u091b\u094b\u0921\u093c\u0947\u0902|\u0930\u0939\u0928\u0947 \u0926\u0940\u091c\u093f\u090f|\u091c\u093c\u0930\u0942\u0930\u0924 \u0928\u0939\u0940\u0902)\W*$", re.I)
_YES_WORDS = re.compile(r"^\W*(yes|yeah|yep|ok|okay|sure|haan|han|ha|ji|ji haan|please|yes please|call me|call me back|call karein|"
                        r"\u0939\u093e\u0901|\u0939\u093e\u0902|\u091c\u0940)\b", re.I)

# ---- what the bot's own reply is doing ----
_ASKS_DETAILS = re.compile(r"(your|apka|aapka|\u0906\u092a\u0915\u093e)\s+(full\s+|good\s+|first\s+)?(name|naam|phone|number|mobile|contact|\u0928\u093e\u092e|\u0928\u0902\u092c\u0930)|"
                           r"(share|give|send|drop|provide|bataiye|batayen|dijiye)[^.?!\n]{0,30}(name|number|phone|naam)|"
                           r"(name|number|phone)[^.?!\n]{0,20}\?", re.I)
_OFFERS_CALL = re.compile(r"call\s*(you\s*)?back|callback|call you|counsell?or[^.?!\n]{0,40}(call|contact|reach)|"
                          r"(call|contact)[^.?!\n]{0,20}karein|\u0915\u0949\u0932 \u0915\u0930\u0947\u0902", re.I)

# ---- how interested does the visitor sound? ----
STRONG = re.compile(r"\b(admission|admissions|admit|enrol|enroll|enrolment|join|joining|register|registration|demo|trial|seat|seats|"
                    r"book|visit|callback|call me|call back|apply|form|interested|scholarship|shuru|start date|batch start|"
                    r"kab (se|tak)|dakhila|daakhila)\b|\u090f\u0921\u092e\u093f\u0936\u0928|\u092a\u094d\u0930\u0935\u0947\u0936|\u0926\u093e\u0916\u093f\u0932\u093e|\u0921\u0947\u092e\u094b|\u0930\u091c\u093f\u0938\u094d\u091f\u094d\u0930\u0947\u0936\u0928", re.I)
MILD = re.compile(r"\b(fee|fees|price|cost|kitni|kitna|batch|batches|timing|timings|course|courses|class|classes|syllabus|faculty|teacher|"
                  r"teachers|result|results|jee|neet|foundation|olympiad|board|boards)\b", re.I)


def norm(text: str) -> str:
    return re.sub(r"\W+", " ", (text or "").lower()).strip()


def is_chip(text: str) -> bool:
    """The exact words of our Yes / No / Skip buttons (they must pass the off-topic gate in every language)."""
    return norm(text) in _CHIP_TEXTS


def is_skip(text: str) -> bool:
    return bool(_SKIP_WORDS.match((text or "").strip()))


def is_yes(text: str) -> bool:
    return bool(_YES_WORDS.match((text or "").strip()))


def asks_details(reply: str) -> bool:
    return bool(_ASKS_DETAILS.search(reply or ""))


def offers_call(reply: str) -> bool:
    return bool(_OFFERS_CALL.search(reply or ""))


def _is_offer_text(text: str) -> bool:
    return any(o in (text or "") for o in OFFER.values())


def asked_for_contact(bot_text: str) -> bool:
    """True if this bot message was a callback offer or asked for a name / number."""
    return _is_offer_text(bot_text) or asks_details(bot_text) or offers_call(bot_text)


def declined(hist: list) -> bool:
    """Did the visitor say no / skip right after an offer or a request for details? Then never ask again in this chat."""
    for i, h in enumerate(hist):
        if h["role"] == "user" and (is_skip(h["text"]) or norm(h["text"]) in {norm(t) for t in list(NO.values()) + list(SKIP.values())}):
            prev = next((x for x in reversed(hist[:i]) if x["role"] == "assistant"), None)
            if prev and asked_for_contact(prev["text"]):
                return True
    return False


def skipped_now(hist: list) -> bool:
    """The latest visitor message is a 'no / skip' answer to the bot's offer or request for details."""
    if not hist or hist[-1]["role"] != "user":
        return False
    return declined(hist[-2:]) if len(hist) >= 2 else False


def interest(text: str) -> int:
    """2 = clear buying signal (admission, demo, seat...), 1 = ordinary enquiry (fees, batches), 0 = nothing."""
    return 2 if STRONG.search(text or "") else 1 if MILD.search(text or "") else 0


def should_offer(hist: list, has_lead: bool, reply: str, enabled: bool = True) -> bool:
    """hist = whole chat so far INCLUDING the visitor's latest message (not yet the new reply)."""
    if not enabled or has_lead or declined(hist):
        return False
    if asks_details(reply) or offers_call(reply):          # the model already asked: do not ask twice
        return False
    users = [h["text"] for h in hist if h["role"] == "user"]
    if not users or is_skip(users[-1]) or is_yes(users[-1]):
        return False
    offers_made = sum(1 for h in hist if h["role"] == "assistant" and _is_offer_text(h["text"]))
    if offers_made >= 2:
        return False
    if offers_made == 1:                                    # ignored once: only again on a clear signal, a few messages later
        last_offer = max(i for i, h in enumerate(hist) if h["role"] == "assistant" and _is_offer_text(h["text"]))
        after = sum(1 for h in hist[last_offer + 1:] if h["role"] == "user")
        return interest(users[-1]) == 2 and after >= 4
    if interest(users[-1]) == 2:
        return True
    return len(users) >= 3 and sum(1 for u in users if interest(u) >= 1) >= 2   # a few real questions: engaged enough


def yes_hint(last_bot: str, user_text: str):
    """Extra instruction for the AI when the visitor just said yes to our offer: ask only for a first name, optional."""
    if _is_offer_text(last_bot) and (is_yes(user_text) or norm(user_text) in {norm(t) for t in YES.values()}):
        return ("\n\nThe visitor just agreed to a callback. Ask ONLY for their first name now, in one short line, and say they can skip "
                "(for example: 'Great! May I know your name? You can skip if you prefer.'). Do not ask anything else and do not call save_lead yet.")
    return ""


def actions_for(lang: str, kind: str) -> list:
    """Buttons for the website widget. kind: 'offer' (Yes / No) or 'details' (Skip)."""
    if kind == "offer":
        return [{"label": YES[lang], "text": YES[lang]}, {"label": NO[lang], "text": NO[lang]}]
    return [{"label": SKIP[lang], "text": SKIP[lang]}]
