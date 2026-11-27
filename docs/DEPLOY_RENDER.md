# Deploying CoachBot on Render, on a subdomain of your domain

> Written from Render's current documentation. The Docker and Blueprint files are tested only offline (file checks, no real build). Do the first deploy on a quiet day and use the checks below at each step. Render's screens change, so if a button is named differently, trust Render's own docs.

## First decide: Free plan or a paid instance with a disk?
| | Free + a monitor pinging it | Starter (paid) + 1 GB disk |
|---|---|---|
| Stays awake | Yes, if something calls it at least every 15 minutes | Always on |
| Chats, leads, status marks, fees edited on the owner page | **Lost** whenever it restarts, redeploys or spins down (Render may restart it at any time) | Kept on the disk, plus a daily snapshot |
| Shell tab (onboarding, alert test) | **Not available** | Available |
| Hours | 750 free hours a month for the **whole workspace**; one always-on service uses about 720 to 744 | Included |
| Good for | Demos for prospects, testing the pages | A real pilot with real parents and clients |

**Recommendation:** use the Free plan now for demos and testing, and move to Starter + disk before the first real pilot. The code and Docker image are the same; only `render.yaml` changes.

### Free plan: how to do it
1. Create the service with **`render.free.yaml`** (copy it over `render.yaml` before pushing, or create the service by hand: New > Web Service > Docker > Free, with the same environment variables). Skip section 3's "institutes folder" log line, section 7's Shell test and section 8 (no Shell on Free).
2. **Keep the monitor ping going.** Render spins a Free service down after 15 minutes without any request. In UptimeRobot (free) add a monitor: type HTTP(s), URL `https://coachbot.yourdomain.com/health`, interval **5 minutes** (the shortest the free plan allows, and well inside Render's 15 minutes). `/health` is light: it does not call the AI model and answers GET and HEAD. Any other free pinger works the same way.
3. **Count your hours.** The 750 hours are shared by every Free web service in your Render workspace, and if they run out Render suspends all of them until next month. One always-on service fits (about 720 to 744 hours). **If your other app is also a Free service on Render, two always-on services do not fit.**
4. **Treat everything that is not in git as temporary.**
   - Put demo and client institutes in the repository (`python -m app.onboard ...` on your PC, then commit `institutes/<id>/` to your private repo). Add each owner key as an environment variable in the Render dashboard (the name is printed by the command), not in git.
   - Owners must not rely on the owner page for edits (they vanish at the next restart). Make changes in git and push.
   - **Set up alerts first** (`TELEGRAM_BOT_TOKEN` and `telegram_chat_id`). A Telegram message is stored outside Render, so it is your only lasting record of each lead on the Free plan. Download leads (CSV) from an owner page or `/admin/leads/<id>/csv` before you redeploy.
   - The weekly summary and the daily cleanup restart from zero after each restart.
5. After any restart the first visitor waits about a minute while it starts. Your monitor will also email you when it happens.
6. The server log shows a `STORAGE IS NOT PERSISTENT` warning on this setup. That is expected.

### Moving from Free to Starter later
Service > Settings: change the instance type to **Starter**; add a **Disk** (name `coachbot-data`, mount path `/data`, 1 GB); in Environment add `COACHBOT_DB=/data/coachbot.db`, `COACHBOT_INSTITUTES_DIR=/data/institutes`, `COACHBOT_ENV_FILE=/data/extra.env`. Render redeploys, the shipped institutes are copied onto the disk, and from then on the rest of this guide applies in full. (Or switch to the Blueprint in `render.yaml`.) Data from the Free period is not carried over, so export your leads first.

## What you need
- The project in a **private GitHub repository** (`docs/DEPLOY.md`, Part 1).
- A Render account with a payment method. CoachBot keeps its database and the owners' edits in **files**, so it needs a **persistent disk**, and Render only gives disks to **paid** instances (the "Starter" plan and above). The Free plan has no disk and sleeps when idle: your data would be lost on every restart. Check the current prices on render.com/pricing.
- Your domain's DNS settings (wherever the domain's nameservers point). We will add one CNAME record for a subdomain, for example `coachbot.yourdomain.com`. Your existing app and its records are not touched.
- Your Groq API key (a fresh one, never committed).

Good to know about disks: only files under the disk's mount path (`/data`) survive restarts and deploys; the service runs as a **single instance**; and deploys cause a short break (no zero-downtime deploys). Render also takes a snapshot of the disk every 24 hours.

## 1. Prepare the repository
1. In `site.json` set your public address and keep your details:
   ```json
   "domain": "https://coachbot.yourdomain.com"
   ```
2. Check `render.yaml` (in the repo root). Defaults: Docker service named `coachbot`, **Starter** plan, region **Singapore** (closest to India; it cannot be changed later), 1 GB disk at `/data`, health check `/health`. Change the name or plan if you wish.
3. Commit and push:
   ```powershell
   git add -A
   git commit -m "Render settings"
   git push
   ```

## 2. Create the service from the Blueprint
1. In the Render dashboard click **New > Blueprint**, connect GitHub (allow access to the private `coachbot` repository) and choose it.
2. Render reads `render.yaml` and asks for the secret values:
   - `GROQ_API_KEY`: your key.
   - `TELEGRAM_BOT_TOKEN`: your bot token (leave empty for now if you have none).
   - `CORS_ORIGINS`: `https://coachbot.yourdomain.com` (add each client's website later, separated by commas).
3. Click **Apply**. Render builds the image (a few minutes) and starts it.

(No Blueprint? **New > Web Service > Docker**, then add the same environment variables by hand from `render.yaml`, add a disk with mount path `/data`, and set the health check path to `/health`.)

## 3. Check the first deploy
1. Open the service's **Logs**. You should see a line like `institutes folder: /data/institutes  added: demo, mcm-..., tribac-...` (the shipped institutes are copied onto the disk the first time), then uvicorn starting.
2. Open the temporary address Render shows (like `https://coachbot-xxxx.onrender.com`):
   - `/health` says ok.
   - `/` shows your company page, `/demo?institute=demo` answers questions.
3. **Environment** tab: copy the generated `ADMIN_TOKEN` and `DEMO_OWNER_KEY` into a password manager. You need them for the admin commands and the demo owner page.

## 4. Point your subdomain at it
1. Service > **Settings > Custom Domains > Add Custom Domain**: enter `coachbot.yourdomain.com`. Render shows the target, `coachbot-xxxx.onrender.com`.
2. At your DNS provider add:
   | Type | Name | Value |
   |---|---|---|
   | CNAME | `coachbot` | the `...onrender.com` address Render showed |
   - Do not change the records for `@` or `www`.
   - If the name `coachbot` already has an **A or AAAA** record, delete that one (a CNAME cannot share a name).
   - If your DNS is on **Cloudflare**, set this record to **DNS only** (grey cloud), at least until Render has verified it.
3. Wait a few minutes (`nslookup coachbot.yourdomain.com` should show the Render address), then click **Verify** in Render. Render issues the HTTPS certificate by itself, and redirects http to https.
4. Open `https://coachbot.yourdomain.com/health`.

## 5. Check that visitor limits see the right address (important)
CoachBot limits messages per visitor address. Render's proxy adds to the `X-Forwarded-For` header and does not remove what a visitor typed, so the app counts addresses **from the right**. `render.yaml` starts with `TRUST_PROXY=xff` and `PROXY_HOPS=2`; verify it:
```powershell
curl.exe -H "X-Admin-Token: YOUR_ADMIN_TOKEN" https://coachbot.yourdomain.com/admin/whoami
```
Compare `app_uses` with your real public address (search "what is my IP"). Then try forging one:
```powershell
curl.exe -H "X-Forwarded-For: 1.2.3.4" -H "X-Admin-Token: YOUR_ADMIN_TOKEN" https://coachbot.yourdomain.com/admin/whoami
```
`app_uses` must **still be your real address, not 1.2.3.4**. If it is not, look at `x_forwarded_for` in the output: set `PROXY_HOPS` to the position of your real address counted from the right (1 = last), save the environment (Render redeploys), and test again. Do not go live until both checks pass.

## 6. Test the app on the live address
Use `docs/QUICK_URLS.md` with `https://coachbot.yourdomain.com` instead of `localhost:8000`, and the test-case workbooks. At least:
- `/`, `/privacy`, `/robots.txt`, `/sitemap.xml`
- `/demo?institute=demo`: chat, a callback with Yes/No buttons, a lead
- `/owner/demo` with `DEMO_OWNER_KEY`: leads, status, summary
- Restart the service from the dashboard and confirm the lead is still there (this proves the disk works)

## 7. Alerts
1. Fill `site.json` `alerts` (`{"telegram_chat_id": "..."}`) to get home-page enquiries on Telegram, and each institute's own `alerts` in its config.
2. In the service's **Shell** tab (paid instances): `python -m app.notify test demo` should say `telegram: sent`.

## 8. Onboarding a client on Render
Real clients live on the disk and never in git. In the **Shell** tab:
```bash
echo $COACHBOT_INSTITUTES_DIR $COACHBOT_ENV_FILE        # must print /data/institutes /data/extra.env
python -m app.onboard mcm-patna "MCM Patna" --telegram-chat 123456789 --email owner@example.com --write-env --domain https://coachbot.yourdomain.com
cat /data/extra.env                                      # the new owner key (give it to the owner privately)
```
Then **Manual Deploy > Restart service** so the new key is loaded. The owner (or you) opens `https://coachbot.yourdomain.com/owner/mcm-patna` and pastes the real fees and batches into the editor. Add the client's website to `CORS_ORIGINS` (Environment tab) so the chat widget works on it. The rest of the process is in `docs/ONBOARDING.md`.

## 9. Updates, backups, monitoring
- **Update:** `git push`. Render rebuilds and redeploys (there is a short break). Institutes on the disk, including owners' edits, are kept. A change you make to a *shipped demo's* files in git does not overwrite the disk copy (edit it on its owner page instead).
- **Backups:** Render snapshots the disk daily. As well, once a week download a copy: enable SSH in Render, then
  ```bash
  # in the Shell tab, make a consistent copy of the database:
  python -c "import sqlite3; s=sqlite3.connect('/data/coachbot.db'); d=sqlite3.connect('/data/backup.db'); s.backup(d)"
  ```
  and copy `/data/backup.db`, `/data/institutes` and `/data/extra.env` to your PC with `scp -s coachbot@ssh.singapore.render.com:/data/backup.db .` (see Render's disk docs for the exact SSH setup).
- **Monitoring:** add a free uptime monitor on `https://coachbot.yourdomain.com/health`.
- **Search engines:** add the site in Google Search Console and submit `/sitemap.xml`.

## Troubleshooting
| Symptom | Likely cause |
|---|---|
| Build fails | Read the build log. Check that `Dockerfile` and `docker-entrypoint.sh` are in the repo and the script has Linux line endings (`.gitattributes` handles it). |
| Deploy "unhealthy" | The health check needs `/health` to answer. Read the runtime logs: a missing or wrong `GROQ_API_KEY` does not stop the app but chat replies fail with 401. |
| `Permission denied` on `/data` | The entrypoint should fix ownership at start. Check the log shows the app starting through it; confirm the disk mount path is exactly `/data`. |
| Data lost after restart | The disk is missing or mounted somewhere else; or the service is on the Free plan. |
| Domain stays unverified | Wrong CNAME target, a leftover A/AAAA record on the same name, Cloudflare proxy (orange cloud) on, or DNS not yet propagated. |
| Chat works on your site but not on a client's | Their website is not in `CORS_ORIGINS`. |
| Everyone shares one limit / limits never trigger | Redo section 5. |
