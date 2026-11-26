// Runs static/widget.js in a tiny fake browser. Used by tests/test_widget.py (skipped when node is not installed).
const fs = require("fs");
const assert = require("assert");
const code = fs.readFileSync(__dirname + "/../static/widget.js", "utf8");

class El {
  constructor(tag) { this.tag = tag; this.children = []; this.style = {}; this.className = ""; this.value = ""; this._text = ""; this.scrollLeft = 0; this.listeners = {}; this._cls = new Set(); this.attrs = {};
    this.classList = { toggle: c => this._cls.has(c) ? this._cls.delete(c) : this._cls.add(c), contains: c => this._cls.has(c) }; }
  set textContent(v) { this._text = v; if (v === "") { this.children = []; this.scrollLeft = 0; } }   // like a browser: clearing resets scrolling
  addEventListener(t, f) { this.listeners[t] = f; }
  get textContent() { return this._text; }
  appendChild(c) { this.children.push(c); return c; }
  getAttribute(k) { return this.attrs[k] || null; }
  focus() {}
}
function run({ publicResp, chatResp }) {
  const script = new El("script"); script.attrs = { "data-institute": "demo" }; script.src = "http://localhost:8000/widget.js";
  const body = new El("body"), head = new El("head"), posts = [], urls = [];
  const document = { currentScript: script, head, body, createElement: t => new El(t) };
  const fetchStub = (url, opts) => {
    urls.push(url);
    if (url.includes("/api/public/")) return publicResp();
    posts.push(JSON.parse(opts.body)); return chatResp();
  };
  const ok = d => Promise.resolve({ ok: true, json: () => Promise.resolve(d) });
  const store = {}; const localStorage = { getItem: k => store[k] || null, setItem: (k, v) => { store[k] = v; } };
  new Function("document", "fetch", "localStorage", "URL", "Math", "Date", "encodeURIComponent", "JSON", code)(document, fetchStub, localStorage, URL, Math, Date, encodeURIComponent, JSON);
  const by = id => body.children.map(c => c).find(c => c.id === id) || body.children.find(c => c.id === "cb-box").children.find(c => c.id === id);
  return { by, body, head, posts, urls, ok, wait: () => new Promise(r => setTimeout(r, 25)) };
}
const ok = d => Promise.resolve({ ok: true, json: () => Promise.resolve(d) });
const status = n => Promise.resolve({ ok: false, status: n });
const SUGG = ["Tell me about the institute", "Which courses do you offer?", "When do new batches start?", "How does the scholarship test work?", "How can I apply for admission?", "Tell me about the faculty"];

(async () => {
  // 1. Chips appear (max 4), clicking one asks that exact question, removes it and shows the next one
  let w = run({ publicResp: () => ok({ suggestions: SUGG }), chatResp: () => ok({ reply: "ANSWER ONE" }) });
  await w.wait();
  let chips = w.by("cb-chips");
  assert.strictEqual(chips.style.display, "flex");
  assert.deepStrictEqual(chips.children.map(c => c.textContent), SUGG);   // ALL suggestions are in the (scrollable) row
  const css = head => head.children[0].textContent;
  assert.ok(css(w.head).includes("flex-wrap:nowrap") && css(w.head).includes("overflow-x:auto") && css(w.head).includes("flex:0 0 auto"), "chip row must scroll sideways");
  chips.scrollLeft = 120;                                        // user has scrolled the row
  chips.children[1].onclick();                                   // click "Which courses do you offer?"
  await w.wait();
  assert.deepStrictEqual(w.posts.map(p => p.message), ["Which courses do you offer?"]);
  assert.ok(w.posts[0].session_id.startsWith("w"));
  chips = w.by("cb-chips");
  assert.deepStrictEqual(chips.children.map(c => c.textContent), [SUGG[0], SUGG[2], SUGG[3], SUGG[4], SUGG[5]]);  // clicked one gone
  assert.strictEqual(chips.scrollLeft, 120, "scroll position must survive the re-render");
  let prevented = false; chips.listeners.wheel({ deltaY: 40, deltaX: 0, preventDefault() { prevented = true; } });
  assert.ok(prevented && chips.scrollLeft === 160, "mouse wheel scrolls the row sideways");
  prevented = false; chips.listeners.wheel({ deltaY: 0, deltaX: 30, preventDefault() { prevented = true; } });
  assert.ok(!prevented && chips.scrollLeft === 160, "a real sideways gesture is left alone");
  const msgs = w.by("cb-msgs").children.map(c => c.textContent);
  assert.deepStrictEqual(msgs.slice(1), ["Which courses do you offer?", "ANSWER ONE"]);
  // typed message with Enter still works
  const input = w.by("cb-row").children.find(c => c.id === "cb-in");
  input.value = "  fees?  "; input.onkeydown({ key: "Enter" }); await w.wait();
  assert.strictEqual(w.posts[1].message, "fees?");

  // 2. No suggestions endpoint (404): no chips, chat still works
  w = run({ publicResp: () => status(404), chatResp: () => ok({ reply: "hi" }) }); await w.wait();
  assert.strictEqual(w.by("cb-chips").style.display === "flex", false);
  const in2 = w.by("cb-row").children.find(c => c.id === "cb-in"); in2.value = "hello"; in2.onkeydown({ key: "Enter" }); await w.wait();
  assert.strictEqual(w.posts.length, 1);

  // 3. Suggestions request fails entirely (network): chat unaffected
  w = run({ publicResp: () => Promise.reject(new Error("offline")), chatResp: () => ok({ reply: "hi" }) }); await w.wait();
  assert.strictEqual(w.by("cb-msgs").children.length, 1);

  // 4. A chip click while a reply is still pending is ignored (no double send)
  let release; w = run({ publicResp: () => ok({ suggestions: SUGG }), chatResp: () => new Promise(r => { release = () => r({ ok: true, json: () => Promise.resolve({ reply: "late" }) }); }) });
  await w.wait(); w.by("cb-chips").children[0].onclick(); w.by("cb-chips").children[0] && w.by("cb-chips").children[0].onclick();
  await w.wait(); assert.strictEqual(w.posts.length, 1); release(); await w.wait();

  // 5. Friendly messages for 404 / 429
  for (const [code, text] of [[404, "not available"], [429, "sending messages quickly"]]) {
    w = run({ publicResp: () => ok({ suggestions: [] }), chatResp: () => status(code) }); await w.wait();
    const i = w.by("cb-row").children.find(c => c.id === "cb-in"); i.value = "x"; i.onkeydown({ key: "Enter" }); await w.wait();
    const last = w.by("cb-msgs").children.slice(-1)[0].textContent; assert.ok(last.includes(text), last);
  }
  // 6. The bot's callback offer shows Yes / No buttons INSTEAD of the suggestions; a button sends its text and the buttons go away
  const ACTS = [{ label: "Yes, call me back", text: "Yes, call me back" }, { label: "No thanks", text: "No thanks" }];
  let n = 0;
  w = run({ publicResp: () => ok({ suggestions: SUGG }), chatResp: () => ok(n++ === 0 ? { reply: "Fill the form.\n\nCall back?", actions: ACTS } : { reply: "No problem." }) }); await w.wait();
  w.by("cb-chips").children[0].onclick(); await w.wait();                 // ask the first suggestion -> reply carries actions
  chips = w.by("cb-chips");
  assert.deepStrictEqual(chips.children.map(c => c.textContent), ["Yes, call me back", "No thanks"]);
  assert.ok(chips.children.every(c => c.className.includes("cb-act")) && chips.style.display === "flex");
  chips.children[1].onclick(); await w.wait();                           // click "No thanks"
  assert.strictEqual(w.posts[1].message, "No thanks");
  assert.ok(w.by("cb-chips").children.map(c => c.textContent).includes(SUGG[1]), "suggestions come back after the buttons are used");
  assert.ok(!w.by("cb-chips").children.some(c => c.className.includes("cb-act")));
  // typing instead of clicking also removes the buttons
  n = 0; w = run({ publicResp: () => ok({ suggestions: [] }), chatResp: () => ok(n++ === 0 ? { reply: "Name?", actions: [{ label: "Skip", text: "Skip" }] } : { reply: "ok" }) }); await w.wait();
  const i6 = w.by("cb-row").children.find(c => c.id === "cb-in"); i6.value = "hi"; i6.onkeydown({ key: "Enter" }); await w.wait();
  assert.deepStrictEqual(w.by("cb-chips").children.map(c => c.textContent), ["Skip"]);
  i6.value = "Ravi"; i6.onkeydown({ key: "Enter" }); await w.wait();
  assert.strictEqual(w.by("cb-chips").children.length, 0, "buttons disappear once the visitor types");
  // 7. Privacy note with a link, shown in the widget
  const noteEl = w.by("cb-note"); assert.ok(noteEl && noteEl.textContent.includes("Chats may be saved") && noteEl.children[0].href.endsWith("/privacy"));
  console.log("widget simulation passed");
})().catch(e => { console.error(e); process.exit(1); });
