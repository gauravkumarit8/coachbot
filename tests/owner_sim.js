// Runs the script inside static/owner.html in a tiny fake browser. Used by tests/test_owner_page.py.
const fs = require("fs");
const assert = require("assert");
const html = fs.readFileSync(__dirname + "/../static/owner.html", "utf8");
const code = /<script>([\s\S]*)<\/script>/.exec(html)[1];
assert.ok(!/innerHTML/.test(code), "owner page must never build HTML from data (XSS)");

class El {
  constructor(tag) { this.tag = tag; this.children = []; this.className = ""; this.value = ""; this.hidden = false; this.disabled = false; this.href = ""; this._text = ""; this.clicked = false; }
  set textContent(v) { this._text = v; if (v === "") this.children = []; }
  get textContent() { return this._text; }
  appendChild(c) { this.children.push(c); return c; }
  click() { this.clicked = true; }
}
const json = (status, data) => ({ ok: status < 400, status, json: () => Promise.resolve(data), text: () => Promise.resolve(typeof data === "string" ? data : JSON.stringify(data)) });
const wait = () => new Promise(r => setTimeout(r, 25));

function page({ routes, storedKey = null }) {
  const els = {};
  for (const m of html.matchAll(/<[^>]*\bid="([^"]+)"[^>]*>/g)) { els[m[1]] = new El("x"); els[m[1]].hidden = /\shidden(\s|>|=)/.test(m[0]); }
  const store = storedKey ? { "ownerkey:demo": storedKey } : {}, calls = [];
  const fetchStub = (url, o) => { calls.push({ url, method: o.method, key: o.headers["X-Owner-Key"], body: o.body }); return Promise.resolve(routes(url, o)); };
  const made = [];
  const document = { getElementById: i => els[i], createElement: t => { const e = new El(t); made.push(e); return e; },
    createTextNode: t => { const e = new El("#text"); e._text = t; return e; } };
  const sessionStorage = { getItem: k => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = v; }, removeItem: k => { delete store[k]; } };
  new Function("document", "location", "fetch", "sessionStorage", "window", "confirm", "encodeURIComponent", "decodeURIComponent", code)(
    document, { pathname: "/owner/demo" }, fetchStub, sessionStorage, { addEventListener() {} }, () => true, encodeURIComponent, decodeURIComponent);
  return { els, calls, store, made };
}
const LEADS = [{ when: "20 Nov 2026, 10:00 AM", name: "<img src=x onerror=alert(1)>", phone: "+91 99900 01111", exam_or_class: "JEE", interest: "", city: "Patna", channel: "website" },
               { when: "20 Nov 2026, 09:00 AM", name: "Mona", phone: "javascript:alert(1)", exam_or_class: "", interest: "NEET", city: "", channel: "whatsapp" }];
const UNANS = [{ question: "Is there parking?", count: 3, last: "x" }, { question: "Hostel food?", count: 1, last: "y" }];
const good = (extra = {}) => (url, o) => {
  const path = url.replace("/api/owner/demo/", "");
  if (extra[path + ":" + o.method]) return extra[path + ":" + o.method](o);
  if (path === "knowledge" && o.method === "GET") return json(200, { name: "Demo Academy", text: "abc details", max_chars: 12000 });
  if (path === "leads") return json(200, LEADS);
  if (path === "unanswered") return json(200, UNANS);
  return json(200, { ok: true, chars: 11 });
};

(async () => {
  // 1. wrong key: message shown, editor stays hidden
  let p = page({ routes: () => json(403, { detail: "x" }) });
  p.els.key.value = "bad"; p.els.open.onclick(); await wait();
  assert.strictEqual(p.els.loginmsg.textContent, "That key does not match."); assert.strictEqual(p.els.editor.hidden, true);

  // 2. right key: details, questions and leads all load; data is shown as text, never as HTML
  p = page({ routes: good() });
  p.els.key.value = "  secret-key  "; p.els.open.onclick(); await wait();
  assert.strictEqual(p.els.editor.hidden, false); assert.strictEqual(p.els.login.hidden, true);
  assert.strictEqual(p.els.name.textContent, "Demo Academy"); assert.strictEqual(p.els.text.value, "abc details");
  assert.deepStrictEqual(p.calls.map(c => c.url.split("/").pop()), ["knowledge", "leads", "unanswered"]);
  assert.ok(p.calls.every(c => c.key === "secret-key"));
  const rows = p.els["leads-body"].children; assert.strictEqual(rows.length, 2);
  assert.strictEqual(rows[0].children[1].textContent, "<img src=x onerror=alert(1)>");               // shown literally
  assert.strictEqual(rows[0].children[2].children[0].href, "tel:+919990001111");                     // phone link: digits only
  assert.ok(/^tel:[0-9+]*$/.test(rows[1].children[2].children[0].href), rows[1].children[2].children[0].href);   // a hostile 'phone' can only ever be a tel: link of digits
  assert.strictEqual(rows[0].children[3].textContent, "JEE"); assert.strictEqual(rows[1].children[3].textContent, "NEET");
  assert.strictEqual(p.els["leads-empty"].hidden, true); assert.strictEqual(p.els.leads.hidden, false);
  assert.deepStrictEqual(p.els["unans-list"].children.map(li => li.textContent), ["3x  Is there parking?", "Hostel food?"]);
  assert.strictEqual(p.els["unans-clear"].hidden, false);

  // 3. nothing yet: friendly empty states
  p = page({ routes: good({ "leads:GET": () => json(200, []), "unanswered:GET": () => json(200, []) }) });
  p.els.key.value = "k"; p.els.open.onclick(); await wait();
  assert.strictEqual(p.els["leads-empty"].hidden, false); assert.strictEqual(p.els.leads.hidden, true);
  assert.strictEqual(p.els["unans-empty"].hidden, false); assert.strictEqual(p.els["unans-clear"].hidden, true);

  // 4. "Mark all as done" posts, then reloads the lists
  p = page({ routes: good(), storedKey: "k" }); await wait();                                      // stored key logs in by itself
  assert.strictEqual(p.els.editor.hidden, false);
  const before = p.calls.length; p.els["unans-clear"].onclick(); await wait();
  assert.deepStrictEqual(p.calls.slice(before).map(c => c.method + " " + c.url.split("/api/owner/demo/")[1]), ["POST unanswered/clear", "GET leads", "GET unanswered"]);

  // 5. save and undo still work
  p.els.text.value = "new details"; p.els.save.onclick(); await wait();
  const put = p.calls.find(c => c.method === "PUT"); assert.deepStrictEqual(JSON.parse(put.body), { text: "new details" });
  assert.ok(p.els.msg.textContent.startsWith("Saved"));
  p.els.undo.onclick(); await wait(); assert.ok(p.calls.some(c => c.url.endsWith("/undo") && c.method === "POST"));

  // 6. a refresh failure is reported, not silent
  p = page({ routes: good({ "leads:GET": () => json(500, { detail: "boom" }) }), storedKey: "k" }); await wait();
  assert.ok(p.els.msg.textContent.startsWith("Could not refresh"), p.els.msg.textContent);
  // 7. conversations load only on demand, are shown as text (never HTML), and open one by one
  const CHATS = [{ ref: 7, channel: "website", who: "…ab12", started: "s", last: "20 Nov 2026, 10:00 AM", messages: 4, first_question: "<b>fees?</b>", lead: true }];
  const CHAT = { channel: "website", who: "…ab12", messages: [{ role: "user", text: "<img src=x onerror=alert(1)>", when: "t1" }, { role: "assistant", text: "Rs 45,000", when: "t2" }] };
  p = page({ routes: good({ "chats:GET": () => json(200, CHATS), "chats/7:GET": () => json(200, CHAT) }), storedKey: "k" }); await wait();
  assert.ok(!p.calls.some(c => c.url.includes("/chats")), "conversations must not be fetched until asked for");
  p.els["chats-load"].onclick(); await wait();
  const li = p.els["chats-list"].children; assert.strictEqual(li.length, 1);
  assert.ok(li[0].children[0].textContent.includes("<b>fees?</b>") && li[0].children[0].textContent.includes("left a number"));
  li[0].children[0].onclick(); await wait();
  assert.ok(p.calls.some(c => c.url.endsWith("/chats/7")));
  const bubbles = p.els["chat-body"].children; assert.strictEqual(bubbles.length, 2); assert.strictEqual(p.els["chat-view"].hidden, false);
  assert.strictEqual(bubbles[0].children[1].tag, "#text"); assert.strictEqual(bubbles[0].children[1].textContent, "<img src=x onerror=alert(1)>");   // a text node: shown literally
  assert.ok(bubbles[0].className.includes("user") && bubbles[1].className.includes("assistant"));

  // 8. CSV download sends the key in a header (a plain link cannot) and offers the file
  global.Blob = global.Blob || class {}; const realURL = global.URL;
  let made = null; global.URL = { createObjectURL: b => { made = b; return "blob:x"; }, revokeObjectURL() {} };
  p = page({ routes: good({ "leads.csv:GET": () => json(200, "\ufeffWhen,Name\r\n") }), storedKey: "k" }); await wait();
  p.els.csv.onclick(); await wait();
  const csvCall = p.calls.find(c => c.url.endsWith("/leads.csv")); assert.ok(csvCall && csvCall.key === "k");
  assert.ok(made, "a file object was created"); assert.ok(p.made.some(e => e.tag === "a" && e.clicked && e.download === "leads-demo.csv"));
  global.URL = realURL;
  // 9. Follow-up status: each lead gets a status list and a note that save on change; the "waiting" line follows the statuses
  const L2 = [{ id: 5, when: "w", name: "Ravi", phone: "9990001111", exam_or_class: "JEE", interest: "", city: "Patna", channel: "website", status: "new", note: "" },
              { id: 6, when: "w", name: "Sita", phone: "9990002222", exam_or_class: "", interest: "", city: "", channel: "website", status: "called", note: "rang" }];
  let posts = [];
  p = page({ routes: good({ "leads:GET": () => json(200, L2), "leads/5:POST": o => { posts.push(JSON.parse(o.body)); return json(200, { ok: true }); } }), storedKey: "k" }); await wait();
  const trs = p.els["leads-body"].children; assert.strictEqual(trs.length, 2);
  const cells = trs[0].children; assert.strictEqual(cells.length, 8, "8 columns: when, name, phone, class, city, via, status, note");
  const sel = cells[6].children[0], noteIn = cells[7].children[0];
  assert.deepStrictEqual(sel.children.map(o => o.value), ["new", "called", "demo_booked", "joined", "not_interested"]);
  assert.deepStrictEqual(sel.children.map(o => o.textContent), ["New", "Called", "Demo booked", "Joined", "Not interested"]);
  assert.strictEqual(sel.value, "new"); assert.strictEqual(trs[1].children[6].children[0].value, "called"); assert.strictEqual(trs[1].children[7].children[0].value, "rang");
  assert.strictEqual(p.els["leads-waiting"].hidden, false); assert.strictEqual(p.els["leads-waiting"].textContent, "1 parent is still waiting for your call.");
  sel.value = "joined"; noteIn.value = "Joined JEE batch"; sel.onchange(); await wait();
  assert.deepStrictEqual(posts, [{ status: "joined", note: "Joined JEE batch" }]);
  assert.strictEqual(p.els.msg.textContent, "Saved."); assert.strictEqual(p.els["leads-waiting"].hidden, true, "nobody is waiting any more");
  noteIn.value = "Paid fees"; noteIn.onchange(); await wait(); assert.strictEqual(posts.length, 2);
  p = page({ routes: good({ "leads:GET": () => json(200, L2), "leads/5:POST": () => json(404, { detail: "nope" }) }), storedKey: "k" }); await wait();
  const s2 = p.els["leads-body"].children[0].children[6].children[0]; s2.value = "called"; s2.onchange(); await wait();
  assert.strictEqual(p.els.msg.textContent, "nope"); assert.strictEqual(p.els.msg.className, "bad");

  // 10. Weekly summary shows only when asked, as plain text
  p = page({ routes: good({ "summary:GET": () => json(200, { text: "CoachBot weekly summary: <b>X</b>" }) }), storedKey: "k" }); await wait();
  assert.ok(!p.calls.some(c => c.url.endsWith("/summary")) && p.els["summary-text"].hidden === true);
  p.els["summary-load"].onclick(); await wait();
  assert.strictEqual(p.els["summary-text"].textContent, "CoachBot weekly summary: <b>X</b>"); assert.strictEqual(p.els["summary-text"].hidden, false);
  console.log("owner page simulation passed");
})().catch(e => { console.error(e); process.exit(1); });
