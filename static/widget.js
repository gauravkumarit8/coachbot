/* CoachBot website widget. Embed with:
   <script src="https://YOUR-SERVER/widget.js" data-institute="demo" data-title="Chat with us" data-color="#1a56db" async></script> */
(function () {
  var s = document.currentScript;
  var inst = s.getAttribute("data-institute");
  var color = s.getAttribute("data-color") || "#1a56db";
  var title = s.getAttribute("data-title") || "Chat with us";
  var greet = s.getAttribute("data-greeting") || "Hi! Ask me about courses, fees or batches.";
  var api = new URL(s.src).origin;

  var sid;
  try {
    sid = localStorage.getItem("cb_sid");
    if (!sid) { sid = "w" + Math.random().toString(36).slice(2) + Date.now().toString(36); localStorage.setItem("cb_sid", sid); }
  } catch (e) { sid = "w" + Math.random().toString(36).slice(2); }

  var css = document.createElement("style");
  css.textContent =
    "#cb-btn{position:fixed;right:20px;bottom:20px;width:56px;height:56px;border-radius:50%;border:0;background:" + color + ";color:#fff;font-size:26px;cursor:pointer;box-shadow:0 4px 14px rgba(0,0,0,.25);z-index:99999}" +
    "#cb-box{position:fixed;right:20px;bottom:88px;width:340px;max-width:calc(100vw - 40px);height:460px;max-height:calc(100vh - 110px);background:#fff;color:#111;border-radius:14px;box-shadow:0 8px 30px rgba(0,0,0,.25);display:none;flex-direction:column;overflow:hidden;font:14px/1.4 system-ui,sans-serif;z-index:99999}" +
    "#cb-box.open{display:flex}" +
    "#cb-head{background:" + color + ";color:#fff;padding:12px 14px;font-weight:600}" +
    "#cb-msgs{flex:1;min-height:0;overflow-y:auto;padding:12px;background:#f5f6f8}" +
    ".cb-m{max-width:82%;padding:8px 11px;border-radius:12px;margin:6px 0;white-space:pre-wrap;word-wrap:break-word}" +
    ".cb-b{background:#fff;border:1px solid #e3e5e8}.cb-u{background:" + color + ";color:#fff;margin-left:auto}" +
    "#cb-chips{display:none;flex-wrap:nowrap;gap:6px;padding:8px 12px;background:#f5f6f8;border-top:1px solid #e3e5e8;overflow-x:auto;overflow-y:hidden;-webkit-overflow-scrolling:touch;scrollbar-width:thin}" +
    ".cb-chip{border:1px solid " + color + ";background:#fff;color:" + color + ";border-radius:14px;padding:4px 10px;font:inherit;font-size:13px;cursor:pointer;flex:0 0 auto;white-space:nowrap}" +
    "#cb-row{display:flex;border-top:1px solid #e3e5e8}#cb-in{flex:1;border:0;padding:12px;font:inherit;outline:0}" +
    "#cb-send{border:0;background:none;color:" + color + ";font-weight:600;padding:0 14px;cursor:pointer}" +
    ".cb-act{background:" + color + ";color:#fff}" +
    "#cb-note{padding:4px 12px;font-size:11px;color:#6b7280;background:#fff;border-top:1px solid #e3e5e8}#cb-note a{color:inherit}";
  document.head.appendChild(css);

  function el(tag, props, parent) {
    var e = document.createElement(tag);
    for (var k in props) e[k] = props[k];
    if (parent) parent.appendChild(e);
    return e;
  }
  var btn = el("button", { id: "cb-btn", textContent: "\uD83D\uDCAC", title: title }, document.body);
  var box = el("div", { id: "cb-box" }, document.body);
  el("div", { id: "cb-head", textContent: title }, box);
  var msgs = el("div", { id: "cb-msgs" }, box);
  var chips = el("div", { id: "cb-chips" }, box);
  var row = el("div", { id: "cb-row" }, box);
  var input = el("input", { id: "cb-in", placeholder: "Type your question...", maxLength: 1000 }, row);
  var send = el("button", { id: "cb-send", textContent: "Send" }, row);
  var note = el("div", { id: "cb-note", textContent: "AI assistant. Chats may be saved to help the institute reply. " }, box);
  el("a", { href: api + "/privacy", target: "_blank", rel: "noopener", textContent: "Privacy" }, note);

  function add(text, who) {
    var m = el("div", { className: "cb-m " + (who === "u" ? "cb-u" : "cb-b"), textContent: text }, msgs);
    msgs.scrollTop = msgs.scrollHeight;
    return m;
  }
  add(greet, "b");

  var busy = false;
  function ask(text) {
    if (!text || busy) return;
    busy = true;
    actions = []; renderChips();                           // old Yes / No / Skip buttons disappear once the visitor moves on
    add(text, "u");
    var wait = add("...", "b");
    fetch(api + "/chat/" + encodeURIComponent(inst), {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sid, message: text })
    })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (d) { wait.textContent = d.reply; actions = d.actions || []; renderChips(); })
      .catch(function (e) {
        var code = String(e && e.message);
        wait.textContent = code === "404" ? "This chat assistant is not available. Please contact the institute directly." :
                           code === "429" ? "You are sending messages quickly. Please wait a moment and try again." :
                           "Sorry, something went wrong. Please try again in a moment.";
      })
      .then(function () { busy = false; msgs.scrollTop = msgs.scrollHeight; });
  }
  function submit() {
    var text = input.value.trim();
    if (!text || busy) return;
    input.value = "";
    ask(text);
  }

  // Suggested questions: the server builds them from the institute's own details, so each one can be answered.
  var suggestions = [], actions = [];
  function renderChips() {
    var keep = chips.scrollLeft || 0;                      // rebuilding the row resets its scrolling: put it back
    chips.textContent = "";
    if (actions.length) {                                  // the bot's own question (callback offer / skip) replaces the suggestions
      actions.forEach(function (a) {
        var b = el("button", { className: "cb-chip cb-act", textContent: a.label, type: "button" }, chips);
        b.onclick = function () { if (!busy) { actions = []; renderChips(); ask(a.text); } };
      });
      chips.style.display = "flex"; chips.scrollLeft = 0;
      return;
    }
    suggestions.forEach(function (q) {                     // all of them: the row scrolls sideways
      var b = el("button", { className: "cb-chip", textContent: q, type: "button" }, chips);
      b.onclick = function () {
        if (busy) return;
        suggestions = suggestions.filter(function (x) { return x !== q; });
        renderChips();
        ask(q);
      };
    });
    chips.style.display = suggestions.length ? "flex" : "none";
    chips.scrollLeft = keep;
  }
  if (chips.addEventListener) {                            // on a desktop mouse, the wheel scrolls the row sideways
    chips.addEventListener("wheel", function (e) {
      if (e.deltaY && !e.deltaX) { chips.scrollLeft += e.deltaY; e.preventDefault(); }
    }, { passive: false });
  }
  fetch(api + "/api/public/" + encodeURIComponent(inst))
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (d) { if (d && d.suggestions && d.suggestions.length) { suggestions = d.suggestions.slice(); renderChips(); } })
    .catch(function () { /* no suggestions is fine: the chat still works */ });

  send.onclick = submit;
  input.onkeydown = function (e) { if (e.key === "Enter") submit(); };
  btn.onclick = function () { box.classList.toggle("open"); if (box.classList.contains("open")) input.focus(); };
})();
