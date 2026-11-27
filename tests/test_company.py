"""Offline tests: company home page, privacy page, sitemap/robots and the pilot contact form.
Run: python -m tests.test_company"""
import json, logging, os, re, tempfile, types
from pathlib import Path

from tests import fastapi_stub
fastapi_stub.install()
os.environ.update(COACHBOT_DB=os.path.join(tempfile.mkdtemp(), "t.db"), ADMIN_TOKEN="admin-token-123456", LLM_PROVIDER="anthropic")
for k in ("TRUST_PROXY",):
    os.environ.pop(k, None)

from app import company, db, main, notify  # noqa: E402
from fastapi import HTTPException  # noqa: E402

logging.disable(logging.CRITICAL)
db.init()
REAL_LOAD = company.load
SETTINGS = {**REAL_LOAD(), "company_name": "Acme <Tech>", "product_name": "CoachBot", "email": "hello@acme.in", "whatsapp": "+91 99999-00001", "instagram": "@acme.coach",
            "domain": "https://acme.in/", "alerts": {"telegram_chat_id": "42"}}
company.load = lambda: dict(SETTINGS, domain=SETTINGS["domain"].rstrip("/"), whatsapp=re.sub(r"\D", "", SETTINGS["whatsapp"]), instagram=company.instagram_handle(SETTINGS["instagram"]))


class Req:
    def __init__(self, host="1.1.1.1"): self.headers, self.client = {}, types.SimpleNamespace(host=host)
def code_of(fn, *a, **k):
    try:
        fn(*a, **k)
    except HTTPException as e:
        return e.status_code, e.detail
    return 200, None
def form(**kw):
    base = dict(name="Ravi Kumar", institute="ABC Classes", city="Kankarbagh", phone="9999900001", email="", message="Interested", consent=True, website="")
    return main.ContactIn(**{**base, **kw})


# ---- pages ----
home = main.root().body
assert "<h1>" in home and "{{" not in home and "Acme &lt;Tech&gt;" in home and "Acme <Tech>" not in re.sub(r"<script.*?</script>", "", home, flags=re.S)   # filled in and HTML-escaped
assert "https://wa.me/919999900001" in home and "mailto:hello@acme.in" in home and 'rel="canonical" href="https://acme.in/"' in home
assert 'href="https://www.instagram.com/acme.coach/"' in home and "Instagram @acme.coach" in home                   # handle cleaned from "@acme.coach"
assert json.loads(re.search(r'ld\+json">(.*?)</script>', home, re.S).group(1))["@graph"][0]["sameAs"] == ["https://www.instagram.com/acme.coach/"]
assert 'application/ld+json' in home and json.loads(re.search(r'ld\+json">(.*?)</script>', home, re.S).group(1))["@graph"][0]["name"] == "Acme <Tech>"
assert 'data-institute="demo"' in home and "/api/contact" in home and "/privacy" in home                          # live demo + form + privacy link
assert "Free 14-day pilot" in home and 'name="viewport"' in home and "description" in home
for promise in ("WhatsApp, Instagram and Facebook messages",):
    assert promise in home and home.index("Coming soon") < home.index(promise)                                    # never promised as live
priv = main.privacy().body
assert "Instagram @acme.coach" in priv and "deleted automatically after 180 days" in priv and "after 365 days" in priv   # the real retention defaults
assert "{{" not in priv and "hello@acme.in" in priv and "Skip" in priv and "under 18" in priv and "delete" in priv.lower()
# nothing configured: the page still works and leaves contact details out
company.load = lambda: dict(company.DEFAULTS)
bare = main.root().body
assert "wa.me" not in bare and "mailto:" not in bare and "canonical" not in bare and "Use the form on the home page" in bare
assert "the contact form on our home page" in main.privacy().body
# a missing or broken site.json never breaks the page
real_root = company.ROOT
company.ROOT = Path(tempfile.mkdtemp()); company.load = REAL_LOAD
assert company.load()["company_name"] == "CoachBot"
(company.ROOT / "site.json").write_text("{ broken"); assert company.load()["company_name"] == "CoachBot"
(company.ROOT / "site.json").write_text(json.dumps({"_help": "x", "company_name": "Zed", "whatsapp": "+91 99999 00000", "domain": "https://z.in/"}))
cfg = company.load(); assert cfg["company_name"] == "Zed" and cfg["whatsapp"] == "919999900000" and cfg["domain"] == "https://z.in" and "_help" not in cfg
company.ROOT = real_root
shipped = json.loads((real_root / "site.json").read_text())                                                          # the shipped file is valid JSON
assert shipped["company_name"] == "CoachBot" and shipped["email"] == "helpchatbot304@gmail.com" and company.instagram_handle(shipped["instagram"]) == "helpchatbot305"
company.load = lambda: dict(SETTINGS, domain="https://acme.in", whatsapp="919999900001")

# Instagram handle cleaning: handle, @handle and links all work; odd values are ignored
for raw, want in (("helpchatbot305", "helpchatbot305"), ("@helpchatbot305", "helpchatbot305"), ("https://www.instagram.com/helpchatbot305/", "helpchatbot305"),
                  ("instagram.com/a.b_c?igsh=x", "a.b_c"), ("", ""), (None, ""), ("bad handle!", ""), ("<script>", ""), ("x" * 40, "")):
    assert company.instagram_handle(raw) == want, raw
os.environ["RETENTION_DAYS"], os.environ["LEAD_RETENTION_DAYS"] = "0", "0"
assert "kept until" in company.render("privacy.html"); os.environ.pop("RETENTION_DAYS"); os.environ.pop("LEAD_RETENTION_DAYS")

# ---- robots + sitemap: our pages indexable, everything private not ----
rb = main.robots().body
assert "Allow: /$" in rb and "Allow: /privacy" in rb and "Sitemap: https://acme.in/sitemap.xml" in rb
for private in ("/demo", "/owner/", "/admin/", "/api/", "/chat/", "/webhook/"):
    assert f"Disallow: {private}" in rb, private
sm = main.sitemap(Req())
assert sm.media_type == "application/xml" and "<loc>https://acme.in/</loc>" in sm.body and "<loc>https://acme.in/privacy</loc>" in sm.body

# ---- contact form ----
sent = []
main.channels.run_in_background = lambda fn, *a, **k: sent.append((fn, a))
assert main.contact(form(), Req("2.2.2.2")) == {"ok": True}
row = db.list_inquiries()[0]
assert row["name"] == "Ravi Kumar" and row["institute"] == "ABC Classes" and row["phone"] == "9999900001" and row["message"] == "Interested"
assert sent and sent[0][0] is notify.send_alerts and sent[0][1][0] == {"telegram_chat_id": "42"} and "Ravi Kumar" in sent[0][1][1] and "ABC Classes" in sent[0][1][1]
n = len(db.list_inquiries())
bad = [(dict(name="R"), "name"), (dict(phone="", email=""), "phone or WhatsApp"), (dict(phone="12345", email="a@b.in"), "does not look right"),
       (dict(consent=False), "tick the box"), (dict(phone="abc", email="x"), "phone")]
for i, (kw, text) in enumerate(bad):
    code, detail = code_of(main.contact, form(**kw), Req(f"3.3.3.{i}"))
    assert code == 400 and text in detail, (kw, code, detail)
assert code_of(main.contact, form(phone="", email="owner@abc.in"), Req("4.4.4.4"))[0] == 200                      # email alone is enough
assert len(db.list_inquiries()) == n + 1
assert main.contact(form(website="http://spam"), Req("5.5.5.5")) == {"ok": True} and len(db.list_inquiries()) == n + 1   # honeypot: nothing stored
long = main.contact(form(message="x" * 5000, name="N" * 500), Req("6.6.6.6")); last = db.list_inquiries()[0]
assert len(last["message"]) == 1000 and len(last["name"]) == 100
for i in range(5):
    code_of(main.contact, form(), Req("7.7.7.7"))
assert code_of(main.contact, form(), Req("7.7.7.7"))[0] == 429                                                        # 5 per hour per visitor address
assert code_of(main.contact, form(), Req("8.8.8.8"))[0] == 200                                                        # another visitor is unaffected

# ---- admin list ----
adm = main.admin_inquiries("admin-token-123456")
assert adm[0]["when"] and any(a["name"] == "Ravi Kumar" for a in adm)
assert code_of(main.admin_inquiries, "nope")[0] == 403 and code_of(main.admin_inquiries, None)[0] == 403
print("company page tests passed")
