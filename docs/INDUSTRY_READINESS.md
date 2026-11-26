# What is left before this is a professional, sellable product

Honest status as of this patch. **Done** = built and covered by offline tests; **Partly** = exists but not proven live or incomplete; **Not done** = still to do. Everything marked live is unproven until you test it (see the test-case workbook).

## A. Must do before a pilot with real parents
| # | Item | Status | What to do |
|---|---|---|---|
| 1 | Always-on hosting with HTTPS | Not done | A small cloud server (or Railway/Render/Fly) with your own domain. Your PC and a tunnel are fine for demos, not for a pilot. |
| 2 | Backups | Not done | Copy `coachbot.db` and `institutes/` daily to another place. Test a restore once. |
| 3 | Secrets | Partly | Keep `.env` out of git and zips (`git rm --cached .env`). Rotate any key that was ever shared. Set `ADMIN_TOKEN` and owner keys (12+ characters). |
| 4 | Webhook security fails open | Not done | `verify_signature` accepts everything when `META_APP_SECRET` is empty. Set the secret before connecting any real channel. |
| 5 | CORS is open to every website | Not done | Restrict to your clients' domains before the pilot. |
| 6 | Groq paid tier | Not done | The free tier (about 8,000 tokens a minute) allows about 4 messages a minute. |
| 7 | Privacy notice and page | Partly | Widget line and `/privacy` page are built. Fill `site.json`, then have a lawyer review the page and the pilot agreement. |
| 8 | Children's data (DPDP) | Not done | India's DPDP Rules were notified on 13 Nov 2025; most obligations apply from about May 2027, including verifiable parental consent for children's data (with some exemptions for educational institutions). Get advice on whether and how it applies to a chatbot vendor serving institutes. |
| 9 | Retention and deletion | Done (offline-tested) | Daily automatic cleanup (chats 180 days, leads 365 days, configurable) and `python -m app.forget` for delete-on-request. Still agree the periods with each institute in the pilot agreement. |
| 10 | Real-model proof | Not done | Run the test-case workbook, especially the `[[NOINFO]]` tag, language, no-fake-lead and handoff cases. |

## B. Needed for a product people pay for
| Item | Status | Notes |
|---|---|---|
| Uptime monitoring and error alerts | Not done | Free: UptimeRobot on `/health`. Also alert yourself when the model fails (the owner alert exists; add one for you). |
| Logs without personal data | Partly | Phone numbers are masked in alert logs; check the access log and add rotation. |
| Quality test set per institute | Partly | 20 to 50 real parent questions with expected answers, rerun after every change (`tests/live_smoke.py` is the start). |
| Owner weekly summary | Done (offline-tested) | Monday summary by Telegram or email, and on the owner page. Telegram/email delivery itself still needs your live test. |
| Lead follow-up status | Done (offline-tested) | Owners mark leads New / Called / Demo booked / Joined / Not interested with a note. The pilot report counts them. |
| Billing and invoices | Not done | Register (Udyam or proprietorship), UPI or Razorpay, GST when it applies. |
| Terms of service and a data processing clause | Not done | The pilot template covers a pilot only. |
| Support routine | Not done | One WhatsApp number for owners, a reply-within-a-day promise. |
| Owner page in Hindi | Not done | Many owners will prefer it. |
| Hindi/Hinglish landing page | Not done | The home page is English. |
| Accessibility basics | Partly | Home page uses labels, headings and contrast; widget needs keyboard and screen-reader checks. |

## C. Messaging channels
| Item | Status | Notes |
|---|---|---|
| WhatsApp | Not done | Needs a BSP or Meta verification (a registered business). WhatsApp bans open-ended general-purpose AI bots from the Business API since 15 Jan 2026, but customer-support bots limited to one business's own questions are allowed. The scope gate already keeps the bot task-specific; confirm with your BSP before signing. |
| Message templates and the 24-hour window | Not done | Needed for owner alerts and follow-ups outside 24 hours. |
| Instagram and Facebook | Not done | Needs Meta app review. |
| Voice notes | Not done | Parents often send them; today the bot asks them to type. |

## D. Scaling (later, not now)
- SQLite is fine for the first 10 to 20 institutes; move to Postgres after that.
- Per-institute usage and cost tracking (tokens), so pricing covers the AI bill.
- Move limits to the proxy (nginx or Cloudflare) and add basic load testing.
- Staging copy of the app for testing changes.
- CI that runs `python -m tests.run_all` on every change.

## E. Built in this and earlier patches
Private demo links, owner chat viewer and CSV export, Indian time, alert test command, skippable callback offers, company home page with a pilot enquiry form, privacy page, sitemap and robots, onboarding script, pilot report, lead follow-up status, weekly owner summary, automatic data retention, delete-on-request.
