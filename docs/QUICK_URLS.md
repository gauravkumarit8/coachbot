# Addresses to test on your PC (server running on port 8000)

| What | Address |
|---|---|
| Your company home page | http://localhost:8000/ |
| Privacy page | http://localhost:8000/privacy |
| Search engine files | http://localhost:8000/robots.txt and http://localhost:8000/sitemap.xml |
| Public demo chat | http://localhost:8000/demo?institute=demo |
| An institute's chat page (shortcut) | http://localhost:8000/&lt;id&gt; (not for unofficial demos) |
| Owner page of an institute | http://localhost:8000/owner/&lt;id&gt;  (key = `<ID>_OWNER_KEY` in .env) |
| Health check | http://localhost:8000/health |
| Pilot enquiries from the home page | `curl.exe -H "X-Admin-Token: <ADMIN_TOKEN>" http://localhost:8000/admin/inquiries` |
| Chats of an institute | `curl.exe -H "X-Admin-Token: <ADMIN_TOKEN>" http://localhost:8000/admin/chats/<id>` |
| Leads (JSON / CSV) | `.../admin/leads/<id>` and `.../admin/leads/<id>/csv` |

## Try onboarding end to end
```powershell
python -m app.onboard test-inst "Test Institute" --write-env --domain http://localhost:8000
# stop the server (Ctrl+C) and start it again: .env is only read at start
uvicorn app.main:app --reload
```
Then: open `institutes/test-inst/knowledge.md`, replace a few "NOT provided" lines with real-looking fees and batches, save, and open:
- http://localhost:8000/demo?institute=test-inst  (chat; answers from your new details)
- http://localhost:8000/test-inst  (the shortcut)
- http://localhost:8000/owner/test-inst  (log in with the `TEST_INST_OWNER_KEY` line from `.env`)

Other commands for it: `python -m app.report test-inst 7`, `python -m app.weekly test-inst`, `python -m app.retention`, `python -m app.forget test-inst 9990001111`.

Clean up: stop the server, `Remove-Item -Recurse institutes\test-inst`, delete the `TEST_INST_OWNER_KEY=` line from `.env`.
