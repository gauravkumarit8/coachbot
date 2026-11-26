"""Suggested questions for the chat widget, generated from an institute's knowledge.md.
Each suggestion comes from a section that really contains facts, so the bot can answer it. Sections that only
say 'NOT provided' are skipped. Nothing here calls an AI model: it is instant, free and cannot invent anything."""
import re

_SKIP_HEADING = re.compile(r"never|behaviou?r|rules|instruction", re.I)
_NOT_FACT = re.compile(r"NOT provided|must confirm|counsellor will confirm", re.I)
_RULE_LINE = re.compile(r"^(do not|don't|never|anything|if you|if asked|always)\b", re.I)
_PHONE = re.compile(r"\+?\d[\d\s-]{8,}\d")
_PLACE = re.compile(r"address|location|located|road|nagar", re.I)

# (regex on the section heading, rank, question). Lower rank is shown first.
_RULES = [
    (r"about", 0, "Tell me about the institute"),
    (r"course|program", 1, "Which courses do you offer?"),
    (r"batch", 2, "When do new batches start?"),
    (r"scholarship", 3, "How does the scholarship test work?"),
    (r"fee", 4, "What are the course fees?"),
    (r"admission", 5, "How can I apply for admission?"),
    (r"student", 6, "What do students get with the course?"),
    (r"facilit|hostel", 7, "What facilities do you offer?"),
    (r"faculty|teacher", 8, "Tell me about the faculty"),
    (r"contact|social", 9, "How can I contact the institute?"),
    (r"polic|refund", 10, "What is the refund policy?"),
]


def _sections(text: str) -> list:
    parts = re.split(r"^##\s+(.+?)\s*$", text, flags=re.M)
    return list(zip(parts[1::2], parts[2::2]))


def _facts(body: str) -> list:
    out = []
    for line in body.splitlines():
        line = line.strip().lstrip("-*\u2022 ").strip()
        if not line or line.startswith("#") or _RULE_LINE.match(line) or _NOT_FACT.search(line):
            continue
        out.append(line)
    return out


def _has_facts(body: str) -> bool:
    return sum(len(line) for line in _facts(body)) >= 12  # short bullets such as 'JEE Main and Advanced.' count


def suggest(knowledge: str, limit: int = 6, custom=None) -> list:
    """Questions a visitor could ask whose answers are in `knowledge`. `custom` (from config.json
    "suggested_questions") overrides the automatic list, for example to offer Hinglish questions."""
    if custom:
        return [str(q).strip() for q in custom if str(q).strip()][:limit]
    found: dict = {}
    for heading, body in _sections(knowledge):
        if _SKIP_HEADING.search(heading) or not _has_facts(body):
            continue
        for pattern, rank, question in _RULES:
            if re.search(pattern, heading, re.I):
                if rank == 10 and not _has_facts("\n".join(l for l in body.splitlines() if "refund" in l.lower())):
                    break  # a policies section without an actual refund fact: do not suggest it
                found.setdefault(question, rank)
                break
        else:
            found.setdefault(f"Tell me about {heading.split('(')[0].strip().lower()}", 11)
        if re.search(r"about", heading, re.I) and _PLACE.search(body):
            found.setdefault("Where is the institute located?", 0.5)
        if _PHONE.search(body) or re.search(r"e-?mail|whatsapp", body, re.I):
            found.setdefault("How can I contact the institute?", 9)
    return [q for q, _ in sorted(found.items(), key=lambda kv: kv[1])][:limit]
