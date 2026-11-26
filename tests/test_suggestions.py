"""Offline tests: suggested questions are generated only from sections that really have facts. Run: python -m tests.test_suggestions"""
from app import registry, suggestions

K = """# comment line
## About
Demo Academy, JEE and NEET coaching.
Phone: +91 90000 00000. Location: Main Road, Sample Nagar, Patna.

## Courses
- JEE Main and Advanced.
- NEET.

## Fees
Fees are NOT provided here. Counsellor must confirm.

## Scholarship test
A scholarship test is held every Sunday at the main branch for Class 10, 11 and 12 passed students.

## Policies
- Refund: NOT provided here.
- Do not mention results.

## Hostel and food
Hostel available for outstation students with meals included in the fee for both boys and girls.

## Never discuss
Fee negotiation, other institutes.

## Demo behaviour
Say this is a demo.
"""
q = suggestions.suggest(K)
assert q[0] == "Tell me about the institute" and "Where is the institute located?" in q and "How can I contact the institute?" in q
assert "Which courses do you offer?" in q and "How does the scholarship test work?" in q and "What facilities do you offer?" in q
assert "What are the course fees?" not in q, q            # fees say 'NOT provided': the bot could not answer it
assert "What is the refund policy?" not in q, q           # the policy has no refund fact
assert not any("discuss" in x.lower() or "demo" in x.lower() for x in q), q  # bot-instruction sections are never suggested

assert suggestions.suggest("## Policies\n- Refund: full refund within 7 days of joining if the student leaves.\n") == ["What is the refund policy?"]
assert len(suggestions.suggest(K, limit=3)) == 3
assert suggestions.suggest(K, custom=["Fees kitni hai?", "  ", "Batch kab shuru hota hai?"]) == ["Fees kitni hai?", "Batch kab shuru hota hai?"]  # owner override
assert suggestions.suggest("") == [] and suggestions.suggest("no headings here at all") == []
assert suggestions.suggest("## Results\nStudents from the last batch secured top ranks in board examinations this year.") == ["Tell me about results"]

inst = registry.load_all(registry.ROOT)                   # the institutes shipped in this project
assert "What are the course fees?" in suggestions.suggest(inst["demo"]["knowledge"])
for iid in [i for i in inst if i != "demo"]:
    qs = suggestions.suggest(inst[iid]["knowledge"])
    assert qs and "What are the course fees?" not in qs and "What is the refund policy?" not in qs, (iid, qs)
print("suggestion tests passed")
