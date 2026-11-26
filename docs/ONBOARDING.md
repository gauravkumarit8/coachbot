# Onboarding a new institute

Use this for a **paying or pilot** institute. (Prospect demos built from a public website are different: `python -m app.new_demo`.)

## 0. Is this a good fit?
- The owner (or a counsellor) can reply to you within a day, and decides quickly.
- They have fees, batches and admission steps they can write down. If not, the bot will have nothing to say.
- They have a website you can add one line to. If not, give them their chat link `https://YOUR-HOST/<id>` for their Instagram bio and WhatsApp status (it works for any institute that is not an unofficial demo).
- Skip national chains and tiny home tutors (see the handoff document).

## 1. Agree the pilot (before any setup)
Send `docs/PILOT_AGREEMENT_TEMPLATE.md` (have it reviewed by a lawyer first). It covers: 14 free days, the three numbers the pilot is judged on, who owns the data, that an AI service processes message text, no guarantees, and how either side can stop.

## 2. Collect the details (send this list on WhatsApp)
1. Institute name, area and city, years running.
2. Courses and classes (9 to 12, JEE, NEET, foundation...).
3. Batches: name, class, timing, start date, seats.
4. Fees per course, registration fee, installments (only what is really offered).
5. Admission steps and documents; scholarship test date and rules.
6. Free demo class: yes or no, when.
7. Facilities: doubt classes, weekly tests, material, hostel, online option.
8. Teachers (names and subjects they are happy to share) and results they can prove.
9. Refund and attendance policy.
10. Contact: phone, WhatsApp, email, address, office hours.
11. Who gets the lead alerts: a Telegram account or email (WhatsApp alerts come later).
12. Anything the bot must never say.

Never ask for or store students' personal data at this stage.

## 3. Set it up (10 minutes)
```powershell
python -m app.onboard mcm-patna "MCM Patna" --telegram-chat 123456789 --email owner@example.com --write-env --domain https://YOUR-HOST
```
- Creates `institutes/mcm-patna/` (config + a knowledge template), makes a strong owner key, writes it to `.env`, prints the links.
- Fill `institutes/mcm-patna/knowledge.md` from the answers. Unknown items stay `NOT provided, counsellor must confirm`. Under 12,000 characters.
- Restart the server (the new key is read from `.env` at start).
- Optional `config.json` settings: `lead_offers` (false turns off the callback offers), `handoff_minutes`, `daily_message_cap`, `suggested_questions`, `website_handoff_message`.
- `python -m app.notify test mcm-patna` must say `telegram: sent` (or `email: sent`).

## 4. Test before the owner sees it (30 minutes)
Ask in English, Hinglish and Hindi:
- 10 normal questions: fees, batches, timings, admission, scholarship, demo, hostel, results, teachers, location. Every figure must match the knowledge file.
- 5 questions the details do not cover: it must say so once, give contact options, never invent.
- 2 off-topic: `2+4`, weather. Both refused.
- 1 refund request and 1 angry message: handoff plus an alert on the owner's phone.
- 1 callback: say you want admission, answer Yes, give name and number. The lead must appear on the owner page and the alert must arrive.
- 1 No thanks and 1 Skip: it must stop asking.
Fix the knowledge file for anything wrong, not the code.

## 5. Show the owner (15 minutes, on a call or in person)
1. Open `/owner/<id>`, log in with the key (give the key privately, never in a group).
2. Edit a fee, Save, ask the chat: it changes at once. Press Undo.
3. Show the leads list: the status list and note on each lead (New, Called, Demo booked, Joined, Not interested), Download (CSV), the unanswered questions, "Show this week's summary", and Recent conversations. Ask them to mark every lead after they call it: that is how you both see what the pilot is worth.
4. Explain handoffs: refunds, complaints and fee negotiation need their staff.
5. Tell them: tell us when fees or batches change, or edit it yourself.

## 6. Go live
- Paste before `</body>` on their site: `<script src="https://YOUR-HOST/widget.js" data-institute="<id>" data-title="Chat with us" async></script>`
- Test once on a phone. Check the privacy line appears under the chat box.
- Tell them WhatsApp, Instagram and Facebook are not connected yet.

## 7. During the 14 days
| Day | Do |
|---|---|
| 1 | Read every conversation (admin chats). Fix wrong or missing answers in the knowledge file. |
| 3 | `python -m app.report <id> 3`. Add answers for the unanswered questions. Check the owner is marking leads Called / Joined. |
| 7 | Report again. Look for failed or odd replies. Share the numbers with the owner. |
| 14 | `python -m app.report <id> 14`, then decide with the owner. |

The pilot is judged on three numbers (printed by the report): enquiries answered after hours, leads captured, demo classes requested. The report also shows how many leads the owner followed up and how many joined. The owner gets a weekly summary on Monday (Telegram or email); check it arrives.

## 8. Convert or stop
- Convert: agree the monthly price in writing, then raise `daily_message_cap` if needed and keep reviewing monthly.
- Chats are deleted automatically after 180 days and leads after 365 days (change in config.json with `retention_days` / `lead_retention_days`; 0 keeps forever). Agree this with the owner in the pilot agreement.
- Stop: remove the script line from their website, give them the leads (Download CSV), then delete their data on request:
```powershell
sqlite3 coachbot.db "DELETE FROM messages WHERE institute='<id>'; DELETE FROM leads WHERE institute='<id>'; DELETE FROM handoffs WHERE institute='<id>'; DELETE FROM unanswered WHERE institute='<id>';"
Remove-Item -Recurse institutes/<id>
```
(Take a backup of `coachbot.db` first.)

## 9. Checklist
- [ ] Pilot agreement agreed
- [ ] Details collected and entered; every figure checked by the owner
- [ ] Owner key given privately; owner can log in
- [ ] `python -m app.notify test <id>` works
- [ ] Test pack passed
- [ ] Widget line added and tested on a phone
- [ ] Day 1, 3, 7 and 14 reviews booked
