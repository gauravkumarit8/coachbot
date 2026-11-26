# CoachBot: AI enquiry assistant for coaching institutes

One "brain" (`app/brain.py`) answers students/parents on **WhatsApp, Instagram, Facebook and a website widget**,
using only the institute's own info. It captures leads, alerts the owner, and hands over to a human when unsure.

## Run locally (VS Code, 5 minutes)
Needs Python 3.10+. In the project folder:
```bash
python -m venv .venv
.venv\Scripts\Activate.ps1
# Windows PowerShell:  .venv\Scripts\Activate.ps1      macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt
# copy .env.example to .env, then add GROQ_API_KEY (console.groq.com/keys) and ADMIN_TOKEN
python -m tests.test_brain && python -m tests.test_channels   # offline tests, no key needed
uvicorn app.main:app --reload                                  # or press F5 in VS Code
```
Open http://localhost:8000/demo and chat with the sample institute. Leads:
`curl -H "X-Admin-Token: $ADMIN_TOKEN" localhost:8000/admin/leads/demo`

## Choosing the AI model
Default is Groq with `openai/gpt-oss-120b` (set `LLM_PROVIDER` / `LLM_MODEL` in `.env`). Check https://console.groq.com/docs/models
for current model IDs: Groq retires models regularly (the old Llama 3.x defaults were shut down in Aug 2026).
`GET /health` shows which provider and model are active. Open models follow "answer only from the provided info" less
reliably than frontier models, so before every pilot run `python -m tests.live_smoke` and read the answers.
To switch back to Claude: `pip install anthropic`, set `LLM_PROVIDER=anthropic` and `ANTHROPIC_API_KEY`.

## Owners edit their own details (no restarts)
Each institute can update its fees/batches on a phone-friendly page: `https://YOUR-URL/owner/<institute_id>`.
1. In `institutes/<id>/config.json` add `"owner_key_env": "VECTOR_OWNER_KEY"` and put `VECTOR_OWNER_KEY=<long random phrase, 12+ chars>` in `.env`.
   Without a key the page refuses everyone (fails closed). Give each owner only their own key.
2. The owner opens the page, enters the key, edits the text, presses Save. The bot uses the new text within seconds.
3. Every save keeps the old version in `institutes/<id>/history/` (last 20). "Undo last save" restores it.
4. Hand edits to `knowledge.md` / `config.json` are picked up automatically too. A broken edit (e.g. invalid JSON) never
   takes the bot down: the last good copy keeps serving and the error is logged.
Limit: 12,000 characters per institute (every message sends it to the model). Use HTTPS in production, the key travels in a header.

## Handoffs: when does the bot stay silent?
When the bot hands a chat to staff, the owner gets an alert. What happens next is set per channel:
- **Website:** the bot keeps answering other questions (visitors have no staff inbox to reply in).
- **WhatsApp / Instagram / Facebook:** the bot stays silent for 120 minutes so staff can reply without the bot interrupting, then resumes.
Override with `"handoff_minutes": 30` in an institute's `config.json` (`0` = never silent). `POST /admin/resume` ends a lock early.

## Lead follow-up, weekly summary, data retention
- **Follow-up status.** On the owner page each lead has a status list (New, Called, Demo booked, Joined, Not interested) and a short note; both save as soon as they are changed. The page shows how many parents are still waiting for a call. The CSV has Status and Note columns, and `python -m app.report` shows how many leads were followed up and how many joined. Older databases are upgraded automatically.
- **Weekly summary.** Every Monday after 9 am Indian time each institute with alerts (Telegram or email) gets: chats (and how many started outside office hours), leads, demo requests, leads still waiting for a call, joins, the questions the assistant could not answer, and what to do this week. Owners can also read it on their page. Preview or send by hand: `python -m app.weekly <id> [--send]`. Switch off per institute with `"weekly_summary": false`; change office hours with `"office_hours": [9, 19]`.
- **Automatic data retention.** Once a day, chat messages older than 180 days and leads not updated for 365 days are deleted (also old webhook ids, handoffs, answered-question notes and home-page enquiries). Change with `RETENTION_DAYS` and `LEAD_RETENTION_DAYS` in `.env`, or per institute with `"retention_days"` and `"lead_retention_days"` in config.json; 0 keeps forever. Preview: `python -m app.retention` (deletes only with `--yes`). The privacy page states the real numbers.
- **Delete on request.** `python -m app.forget <institute_id> <phone-or-chat-id>` shows what it would delete for one person (their leads, chats, chats that mention their number); add `--yes` to delete. Back up `coachbot.db` first.
- All scheduled jobs run in an hourly background check inside the server and note in the database that they ran, so restarts never repeat them. Turn off with `COACHBOT_BACKGROUND_JOBS=0`.

## Callback offers (optional lead capture)
The bot never makes help depend on personal details. When a visitor shows clear interest (admission, demo, seat, join...) or has asked a few real questions, the answer is followed by ONE polite offer of a callback with two website buttons, **Yes, call me back** and **No thanks**. When the bot asks for a name or number, a **Skip** button is shown. A "no" or "skip" is final for that chat and is answered with fixed text (no AI call). On WhatsApp, Instagram and Facebook the same choice is written as text (YES / NO / SKIP). The offers come from `app/leadflow.py` (code, not AI), are available in English, Hinglish and Hindi, and can be switched off per institute with `"lead_offers": false`.

## Company home page, privacy and pilot enquiries
`/` is your company page (edit `site.json`: company name, email, WhatsApp number, public web address, optional `alerts` for Telegram/email). `/privacy` is the privacy page, `/sitemap.xml` and `/robots.txt` are generated. The contact form posts to `/api/contact` (5 per hour per visitor, hidden spam field, consent box). Read enquiries: `curl -H "X-Admin-Token: $ADMIN_TOKEN" localhost:8000/admin/inquiries`. The page embeds the public `demo` institute as the live demo.

## Onboarding and pilot report
`python -m app.onboard <id> "<Name>" --telegram-chat <id> --email <x> --write-env --domain https://YOUR-HOST` sets up a new institute. `python -m app.report <id> [days]` prints the three pilot numbers. Full process: `docs/ONBOARDING.md`. What is still missing for a professional product: `docs/INDUSTRY_READINESS.md`.

## Demo link per prospect (private)
Make a prospect demo with `python -m app.new_demo tribac` (or any institute id). It copies that institute to a folder with a
random id such as `tribac-k4x9m2qa`, marks it `unofficial_demo`, and strips the owner page, alerts and WhatsApp/Meta settings so a
demo can never message anyone. Edit its `knowledge.md`, then send `https://YOUR-URL/demo?institute=tribac-k4x9m2qa`.
- The random part is the only protection. Unofficial demos have **no** `/<id>` shortcut (`/tribac` gives 404), `/health` only shows
  a count, the demo page is `noindex` and `/robots.txt` disallows everything. Never paste a demo link anywhere public.
- Demos of a real institute's public info need `"unofficial_demo": true` (the script sets it): the page shows the "Unofficial demo"
  banner. An unknown id shows "This demo link is not valid".
- Review what prospects typed: `curl -H "X-Admin-Token: $ADMIN_TOKEN" localhost:8000/admin/chats/<id>` and then `/admin/chats/<id>/<ref>`.

## Suggested questions and staying on topic
- The chat widget shows up to 4 clickable question suggestions. They are generated automatically from each institute's
  `knowledge.md`, only from sections that contain real facts (a section that just says "NOT provided" produces no question),
  so every suggestion can be answered. They update when the owner edits their details. To offer your own (for example in Hinglish),
  add `"suggested_questions": ["Fees kitni hai?", "Batch kab shuru hota hai?"]` to the institute's `config.json`.
- The bot only discusses the institute. Obvious institute questions and greetings are passed straight through. Anything unclear
  gets a tiny AI yes/no check first. Off-topic questions (maths, weather, politics...) get a fixed refusal written in our code,
  with example questions, in English, Hinglish or Hindi, so the model can never answer them.

## Owner dashboard: leads and unanswered questions
`/owner/<institute_id>` (owner key, see above) now has three parts:
1. **Details**: edit fees, batches, policies (as before).
2. **Questions your details do not answer yet**: what parents asked that the assistant could not answer, most asked first.
   Add the answers to the details and it starts answering them. "Mark all as done" clears the list. Phone numbers typed inside
   a question are masked. (The assistant marks such replies with a hidden `[[NOINFO]]` tag that is removed before the user sees it.)
3. **Parents who want a callback**: every lead with name, phone (tap to call), class, city and channel.

## Owner page extras: conversations and CSV
- **Recent conversations**: the owner page lists recent chats (phone numbers and session ids shortened to their last 4 characters)
  and opens one to read it. Loaded only when the owner presses the button.
- **Download leads (CSV)**: opens in Excel or Google Sheets. Cells that could run as formulas are defused.
  Developer copy: `curl -H "X-Admin-Token: $ADMIN_TOKEN" localhost:8000/admin/leads/<id>/csv`.
- Times are shown in Indian time (UTC+5:30) and the daily cap resets at midnight IST, whatever zone the server is in.
  Change with `COACHBOT_UTC_OFFSET_MIN` (minutes from UTC).

## Owner alerts without WhatsApp (Telegram, email)
Website-only institutes have no WhatsApp number to alert, so alerts can also go to Telegram (free, instant) and/or email.
Add to the institute's `config.json`: `"alerts": {"telegram_chat_id": "123456789", "email": "owner@example.com"}`.
- **Telegram:** in Telegram open **@BotFather**, send `/newbot`, copy the token into `.env` as `TELEGRAM_BOT_TOKEN`. The owner opens
  your bot, presses Start and sends "hi". Run `python -m app.notify`: it prints their chat id for `config.json`. (A group works too:
  add the bot to the group; its id starts with a minus sign.)
- **Email:** set `SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD` (and optionally `SMTP_PORT`, `SMTP_FROM`) in `.env`. For Gmail use an
  app password, not your normal password.
Alerts are sent for new/updated leads, handoffs and bot errors. Phone numbers are never written to the server log.
Telegram and SMTP could not be tried from the build environment: send yourself a test alert before relying on them.

Test it: `python -m app.notify test <institute_id>` sends one test alert through that institute's `alerts` settings and prints
`sent` or `FAILED` per channel (the reason is in the log lines above it). Run it once per institute before a pilot.

## Protecting the public chat
- Messages are limited **per visitor address** (default 20/minute) as well as per session id, so rotating session ids does not help.
  Behind a tunnel or reverse proxy (cloudflared, ngrok, nginx) set `TRUST_PROXY=1` in `.env`, otherwise every visitor looks like the
  proxy. Only set it when you really are behind one: the header it trusts can be forged on a direct connection.
- A **daily cap** per institute (default 2000 customer messages; `CHAT_DAILY_CAP` or `"daily_message_cap"` in `config.json`, 0 = none).
  When it is reached visitors are asked to contact the institute directly and the owner gets one alert.
- Limits are kept in memory and reset when the server restarts.

## Keeping the project safe
- `.gitignore` keeps `.env`, `*.db`, `.venv` and patch files out of version control. Start tracking changes: `git init`, `git add -A`,
  `git commit -m "baseline"`. Never share `.env`.
- Do not keep the project inside OneDrive: it syncs the database and `.venv`, which can lock or corrupt `coachbot.db`. Close VS Code,
  copy the folder (including `.env` and `coachbot.db`, not `.venv`) to e.g. `C:\dev\coachbot`, recreate the virtual environment there.
- Run all offline tests with one command: `python -m tests.run_all`.

## Add a real institute
1. Copy `institutes/demo` to `institutes/<id>`.
2. Edit `knowledge.md` (fees, batches, admission, policies, what the bot must NOT discuss). This file is the product.
   Mark anything unknown as "NOT provided; counsellor must confirm" so the bot hands off instead of guessing.
3. Edit `config.json`: owner phone, WhatsApp phone-number ID, Facebook page ID / Instagram account ID.
4. Restart. Website embed:
   `<script src="https://YOUR-SERVER/widget.js" data-institute="<id>" async></script>`

## Connect Meta channels (verify against Meta's current docs)
- Create a Meta app, add **WhatsApp** and **Messenger/Instagram** products.
- Webhooks: `https://YOUR-SERVER/webhook/whatsapp` and `https://YOUR-SERVER/webhook/meta`, verify token = `VERIFY_TOKEN`.
- Put `META_APP_SECRET` in `.env` so forged webhooks are rejected.
- Local testing: expose with a tunnel (ngrok / cloudflared). Production: any small VPS with HTTPS.
- Real client numbers need Meta business verification; Instagram/Messenger access beyond test users needs app review.

## WhatsApp through a BSP (institute owns its number; you don't need your own Meta approvals)
Works with any provider that mirrors Meta's Cloud API format (360dialog does: `POST https://waba-v2.360dialog.io/messages`,
header `D360-API-KEY`). Confirm before paying: (1) your plan includes the messaging API + inbound webhooks, (2) webhook payloads
use Meta's format, (3) each number gets its own API key.

1. The institute signs up with the BSP in its own name and registers its own number (not already on WhatsApp).
2. In `institutes/<id>/config.json` use:
```json
"whatsapp": {
  "provider": "bsp",
  "send_url": "https://waba-v2.360dialog.io/messages",
  "auth_header": "D360-API-KEY",
  "api_key_env": "ACME_WA_KEY",
  "webhook_key_env": "ACME_WEBHOOK_KEY"
}
```
3. Put `ACME_WA_KEY` (the institute's API key from the BSP) and `ACME_WEBHOOK_KEY` (a long random string you invent) in `.env`.
4. Point the BSP's inbound webhook to `https://YOUR-URL/webhook/bsp/<institute_id>?key=<ACME_WEBHOOK_KEY>`.
5. Message the institute's number from your phone; the bot should reply. A different BSP format needs a new branch in
   `channels.py` (`send_whatsapp` / `parse_whatsapp`).

## Before the first pilot
- [ ] Owner alerts: outside WhatsApp's 24-hour window Meta only allows approved **template** messages. Create a
      `new_lead` template and send it from `notify_owner()` in `app/main.py` (currently plain text).
- [x] Per-institute credentials: each institute's `config.json` names the env vars holding its keys (see below).
- [ ] Restrict CORS in `main.py` to each client's website domain.
- [ ] Add a short privacy line to the bot's first reply or website (chats are stored; many users are minors).
      Check India's DPDP Act obligations with someone qualified.
- [ ] Read 20 real chats per day in week 1 and fix `knowledge.md` gaps.

## Not built yet (good next steps)
Voice-note transcription, Google Sheets sync, follow-up messages to quiet leads (needs templates), a staff inbox to
reply to handed-off chats (consider Chatwoot), weekly summary report, per-institute dashboard.

## Honest status
Logic is covered by offline tests with a fake model. The Meta and Anthropic API calls themselves have NOT been run
end to end, so expect small fixes when you first connect real credentials.
