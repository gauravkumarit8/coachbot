"""Your company's public pages: home page (/), privacy page (/privacy), sitemap and the contact form.
Settings live in site.json (company name, email, WhatsApp number, public web address); empty values are left out."""
import html
import json
import re
from datetime import date
from pathlib import Path

from . import retention

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
DEFAULTS = {"company_name": "CoachBot", "product_name": "CoachBot", "city": "Patna, Bihar", "domain": "", "email": "",
            "whatsapp": "", "instagram": "", "demo_institute": "demo", "alerts": {}}


def load() -> dict:
    cfg = dict(DEFAULTS)
    try:
        cfg.update({k: v for k, v in json.loads((ROOT / "site.json").read_text(encoding="utf-8")).items() if not k.startswith("_")})
    except (OSError, ValueError):
        pass  # missing or broken file: use the defaults, never break the page
    cfg["domain"] = str(cfg.get("domain") or "").strip().rstrip("/")
    cfg["whatsapp"] = re.sub(r"\D", "", str(cfg.get("whatsapp") or ""))
    cfg["instagram"] = instagram_handle(cfg.get("instagram"))
    return cfg


def instagram_handle(value) -> str:
    """'helpchatbot305', '@helpchatbot305' or a full instagram.com link all give 'helpchatbot305'. Anything odd gives ''."""
    v = str(value or "").strip()
    m = re.search(r"instagram\.com/([A-Za-z0-9._]+)", v)
    v = (m.group(1) if m else v).lstrip("@").strip("/ ")
    return v if re.fullmatch(r"[A-Za-z0-9._]{1,30}", v) else ""


def _e(v) -> str:
    return html.escape(str(v or ""), quote=True)


def _jsonld(cfg: dict) -> str:
    data = {"@context": "https://schema.org", "@graph": [
        {"@type": "Organization", "name": cfg["company_name"], "url": cfg["domain"] or None, "email": cfg["email"] or None,
         "address": {"@type": "PostalAddress", "addressLocality": cfg["city"]},
         "sameAs": [f"https://www.instagram.com/{cfg['instagram']}/"] if cfg["instagram"] else None},
        {"@type": "SoftwareApplication", "name": cfg["product_name"], "applicationCategory": "BusinessApplication",
         "operatingSystem": "Web", "description": "AI enquiry assistant for coaching institutes: answers parents from the institute's own details, "
         "captures optional callback requests and alerts the owner."}]}
    for item in data["@graph"]:
        for k in [k for k, v in item.items() if v is None]:
            del item[k]
    return json.dumps(data, ensure_ascii=False).replace("</", "<\\/")


def render(template: str, cfg: dict | None = None) -> str:
    """Fill {{tokens}} in static/<template>. Everything is HTML-escaped."""
    cfg = cfg or load()
    path = "/privacy" if template == "privacy.html" else "/"
    contacts = []
    if cfg["whatsapp"]:
        contacts.append(f'<a href="https://wa.me/{_e(cfg["whatsapp"])}" rel="noopener">WhatsApp us</a>')
    if cfg["email"]:
        contacts.append(f'<a href="mailto:{_e(cfg["email"])}">{_e(cfg["email"])}</a>')
    if cfg["instagram"]:
        contacts.append(f'<a href="https://www.instagram.com/{_e(cfg["instagram"])}/" rel="noopener">Instagram @{_e(cfg["instagram"])}</a>')
    values = {
        "company": _e(cfg["company_name"]), "product": _e(cfg["product_name"]), "city": _e(cfg["city"]),
        "demo_institute": _e(cfg["demo_institute"]), "year": str(date.today().year), "updated": date.today().strftime("%d %B %Y"),
        "canonical": f'<link rel="canonical" href="{_e(cfg["domain"] + path)}">' if cfg["domain"] else "",
        "og_url": f'<meta property="og:url" content="{_e(cfg["domain"] + path)}">' if cfg["domain"] else "",
        "contact_links": " &middot; ".join(contacts) or "Use the form on the home page.",
        "email_or_form": _e(cfg["email"]) if cfg["email"] else "the contact form on our home page",
        "jsonld": _jsonld(cfg),
        "retention_text": _retention_text(),
    }
    out = (STATIC / template).read_text(encoding="utf-8")
    for k, v in values.items():
        out = out.replace("{{" + k + "}}", v)
    return out


def _retention_text() -> str:
    msg, lead = retention.settings({})
    if not msg and not lead:
        return "Chats and leads are kept until the institute or you ask for them to be deleted."
    parts = []
    if msg:
        parts.append(f"Chat messages are deleted automatically after {msg} days")
    if lead:
        parts.append(f"details you shared for a callback are deleted automatically after {lead} days" if msg else
                     f"Details you shared for a callback are deleted automatically after {lead} days")
    return (", and ".join(parts) + ", unless the institute has agreed a different period with us. You can also ask for earlier deletion (see below).")


def sitemap(base: str, cfg: dict | None = None) -> str:
    cfg = cfg or load()
    base = cfg["domain"] or base.rstrip("/")
    urls = "".join(f"<url><loc>{_e(base + p)}</loc></url>" for p in ("/", "/privacy"))
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>\n'


def robots(cfg: dict | None = None) -> str:
    """Search engines may index the home and privacy pages only. Demos, owner pages, admin and the APIs stay out."""
    cfg = cfg or load()
    lines = ["User-agent: *", "Allow: /$", "Allow: /privacy", "Disallow: /demo", "Disallow: /owner/", "Disallow: /admin/",
             "Disallow: /api/", "Disallow: /chat/", "Disallow: /webhook/"]
    if cfg["domain"]:
        lines.append(f"Sitemap: {cfg['domain']}/sitemap.xml")
    return "\n".join(lines) + "\n"


_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def clean_contact(body) -> tuple[dict | None, str | None]:
    """Validate the home-page contact form. Returns (fields, None) or (None, message for the visitor)."""
    f = {"name": body.name.strip()[:100], "institute": body.institute.strip()[:120], "city": body.city.strip()[:80],
         "phone": body.phone.strip()[:30], "email": body.email.strip()[:120], "message": body.message.strip()[:1000]}
    digits = re.sub(r"\D", "", f["phone"])
    if len(f["name"]) < 2:
        return None, "Please enter your name."
    if not (10 <= len(digits) <= 15) and not _EMAIL.match(f["email"]):
        return None, "Please enter a phone or WhatsApp number (10 digits), or an email address, so we can reach you."
    if f["phone"] and not 10 <= len(digits) <= 15:
        return None, "That phone number does not look right. Please check it."
    if not body.consent:
        return None, "Please tick the box to agree that we may contact you."
    return f, None
