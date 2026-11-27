# Putting CoachBot on GitHub and on your domain

> The Docker files and steps below have been written carefully but not run end to end (no server was available while writing them). Do the first deploy on a quiet day and check each step.

## Part 1. Push to GitHub safely

**Why be careful:** this project has had `.env` (your API keys) tracked by git, and `institutes/` will hold clients' details. Anything ever committed stays in git history, even after you delete the file. So use a **private** repository and a **clean history**.

### Easiest and safest: start a fresh repository
1. Move the project out of OneDrive (OneDrive and git do not mix well): copy the folder to `C:\dev\coachbot` **without** `.git`, `.venv`, `.env` and `coachbot.db`:
   ```powershell
   mkdir C:\dev
   robocopy "C:\Users\gaura\OneDrive\Desktop\learn\coachbot" C:\dev\coachbot /E /XD .git .venv __pycache__ /XF .env coachbot.db
   cd C:\dev\coachbot
   ```
   (Or unzip `coachbot-updated.zip` there: it is already clean.)
2. Create the repository:
   ```powershell
   git init -b main
   git add .
   git status
   ```
   Read the list. **`.env`, `coachbot.db`, `.venv` and `data` must NOT appear.** Git may print "CRLF will be replaced by LF" warnings: that is normal.
3. Check for secrets before the first commit:
   ```powershell
   git grep -n -I -E "gsk_[A-Za-z0-9]{20,}|sk-ant-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|[0-9]{8,10}:[A-Za-z0-9_-]{30,}" -- .
   ```
   (It looks for Groq keys, Anthropic keys, AWS keys and Telegram bot tokens. It must print nothing; also search for your own phone number and email if you do not want them public.)
4. Commit: `git commit -m "CoachBot first version"`
5. On github.com click **New repository**: name `coachbot`, choose **Private**, do **not** add a README. Then:
   ```powershell
   git remote add origin https://github.com/YOUR-USERNAME/coachbot.git
   git push -u origin main
   ```
   A browser window asks you to sign in (or run `gh auth login` with GitHub CLI).
6. Recreate your environment in the new folder: `python -m venv .venv`, activate it, `pip install -r requirements.txt`, then copy your `.env` over by hand.
7. The tests now run on every push (Actions tab on GitHub).

### If you keep your old repository instead
Run `git log --all --oneline -- .env`. If it prints anything, `.env` was committed at some point and your old history contains keys: **rotate every key** (Groq, Telegram, owner keys) and prefer the fresh start above. If it prints nothing, run `git rm --cached .env coachbot.db` and commit.

### Keep real clients out of GitHub
Commit only the demo and template institutes. Onboard real clients **on the server** and tell git to ignore them there: add a line `institutes/<id>/` to `.git/info/exclude` on the server (this file is local, not committed). Back up `institutes/` with the database (Part 5).

## Part 2. Using the same domain: use a subdomain
You do not need a second domain. Keep the existing app on `yourdomain.com` and run CoachBot on a subdomain such as **`coachbot.yourdomain.com`** (any name works: `app.`, `chat.`, `bot.`). A subdomain is just one more DNS record, and it does not touch the old app.

1. Decide where CoachBot will run (Part 3). Note the server's public IP address (or the host's address if it is a platform like Render or Railway).
2. Open the DNS settings of your domain. This is wherever the domain's nameservers point: your registrar, Cloudflare, or the hosting company of the old app.
3. Add one record. **Do not change the existing records for `@` or `www`.**
   | Type | Name | Value |
   |---|---|---|
   | A | `coachbot` | the new server's IPv4 address |
   | (or) CNAME | `coachbot` | the address your platform gives you (platforms only) |
4. Wait a few minutes (sometimes longer), then check: `nslookup coachbot.yourdomain.com` shows the right address.
5. Your pages will be at `https://coachbot.yourdomain.com/` (company page), `/privacy`, `/demo?institute=demo`, `/owner/<id>`.

Why not `yourdomain.com/coachbot` on the same address? CoachBot uses addresses that start at the root (`/widget.js`, `/api/...`, `/owner/...`). Serving it under a path needs rewriting rules that are easy to get wrong, and every institute's embed line would depend on them. A subdomain is simpler and safer. If you prefer CoachBot on the main domain, move the old app to a subdomain instead.

## Part 3. Where to run it
| Option | Good for | Watch out |
|---|---|---|
| **A. A small Linux server (VPS) with Docker** (recommended) | Full control, one monthly price, database on the server's disk | You maintain it (updates, backups) |
| **B. The server that already runs your other app** | No extra cost | Both apps share ports 80/443: put CoachBot behind the web server that is already there (A2 below) |
| **C. A platform (Render, Railway, Fly...)** | Less server work | CoachBot stores its database and the owners' edits in files: you must attach a **persistent disk**. Free plans that sleep or lose files are not suitable for real clients. **Render step by step: `docs/DEPLOY_RENDER.md`** |

### A1. Fresh server (nothing else uses ports 80 and 443)
On the server (Ubuntu), over SSH:
```bash
# 1. Install Docker (with the compose plugin): follow https://docs.docker.com/engine/install/ubuntu/
sudo apt install -y git sqlite3
# 2. Firewall
sudo ufw allow OpenSSH && sudo ufw allow 80 && sudo ufw allow 443 && sudo ufw enable
# 3. Get the code (private repo: add the server's key under GitHub > repo > Settings > Deploy keys)
ssh-keygen -t ed25519 -C "coachbot-server"      # then paste ~/.ssh/id_ed25519.pub into Deploy keys (read-only)
git clone git@github.com:YOUR-USERNAME/coachbot.git && cd coachbot
# 4. Folders and settings
mkdir -p data && sudo chown -R 1000:1000 data institutes
cp .env.example .env && nano .env && chmod 600 .env
cp Caddyfile.example Caddyfile && nano Caddyfile      # put coachbot.yourdomain.com in it
# 5. Start (Caddy gets the HTTPS certificate by itself)
docker compose --profile caddy up -d --build
docker compose logs -f coachbot
```
In `.env` fill at least: `GROQ_API_KEY`, `ADMIN_TOKEN` (32+ random characters), `DEMO_OWNER_KEY` (12+ characters), `TELEGRAM_BOT_TOKEN`, and `CORS_ORIGINS`. Generate random values with `openssl rand -base64 24`.

### A2. The server already runs another app (ports 80/443 taken)
Start only CoachBot (`docker compose up -d --build`, no `--profile caddy`). It listens on `127.0.0.1:8000` only. Then add it to the web server you already have.

*nginx:* create `/etc/nginx/sites-available/coachbot`
```nginx
server {
    server_name coachbot.yourdomain.com;
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $remote_addr;    # replaces anything the visitor sent: keeps the limits honest (CoachBot reads it with TRUST_PROXY=xff)
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```
then `sudo ln -s /etc/nginx/sites-available/coachbot /etc/nginx/sites-enabled/ && sudo nginx -t && sudo systemctl reload nginx && sudo certbot --nginx -d coachbot.yourdomain.com`.

*Caddy:* add `coachbot.yourdomain.com { reverse_proxy 127.0.0.1:8000 }` to your existing Caddyfile and reload.

### After it is running (any option)
1. Edit `site.json` on the server: `"domain": "https://coachbot.yourdomain.com"` (no restart needed). Also fill `whatsapp` and `alerts` when you have them.
2. Open `https://coachbot.yourdomain.com/health`: it should say ok.
3. Run the test-case workbook against the live address instead of localhost.
4. Check the visitor address the app sees: `curl.exe -H "X-Admin-Token: <ADMIN_TOKEN>" https://coachbot.yourdomain.com/admin/whoami` must show your real address in `app_uses`, also when you add a fake `X-Forwarded-For: 1.2.3.4` header.
4b. Add a free uptime monitor (for example UptimeRobot) on `/health`.
5. Search engines: add the site in Google Search Console and submit `/sitemap.xml`.
6. The embed line for an institute is now `<script src="https://coachbot.yourdomain.com/widget.js" data-institute="<id>" async></script>`. Add their website to `CORS_ORIGINS` in `.env`, then `docker compose up -d`.

## Part 4. Updating
```bash
cd coachbot && git pull && docker compose up -d --build        # add --profile caddy if you use it
```
Edits owners make on their page are saved in `institutes/` on the server (not in git), so an update never overwrites them.

## Part 5. Backups (do this before the first client)
```bash
mkdir -p ~/backups
crontab -e     # add this one line:
0 3 * * * cd ~/coachbot && sqlite3 data/coachbot.db ".backup '$HOME/backups/coachbot-$(date +\%F).db'" && tar czf $HOME/backups/institutes-$(date +\%F).tgz institutes site.json && find $HOME/backups -mtime +14 -delete
```
Copy `~/backups` somewhere off the server regularly (your provider's snapshots, or a cloud drive with rclone). Restore once on a test machine to prove it works.

## Part 6. Before the first real client
- [ ] Repository is private; no secrets in it; Groq key rotated if it was ever committed
- [ ] `.env` has strong `ADMIN_TOKEN` and owner keys; file permissions 600
- [ ] Only ports 22, 80 and 443 are open; SSH uses keys
- [ ] `CORS_ORIGINS` lists your own address and each client's website
- [ ] Groq paid tier on
- [ ] Backups running and a restore tested
- [ ] `/privacy` and the pilot agreement reviewed by a lawyer
- [ ] If you connect WhatsApp or Meta later: set `META_APP_SECRET` first (without it, webhooks are not signature-checked)
