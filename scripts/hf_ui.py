#!/usr/bin/env python3
"""Local web chat UI for the HF Inference Providers router.

A single-file, zero-dependency app (Python stdlib only). It serves a clean
chat page on localhost and proxies requests to router.huggingface.co, so your
HF token stays server-side and never reaches the browser.

Usage:
    HF_TOKEN=hf_xxx python3 scripts/hf_ui.py
    python3 scripts/hf_ui.py hf_xxx
    python3 scripts/hf_ui.py hf_xxx 8765        # custom port

Then open the printed http://127.0.0.1:<port> (it auto-opens your browser).
Press Ctrl-C in the terminal to stop the server.
"""

import datetime
import json
import os
import sys
import threading
import urllib.error
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROUTER = "https://router.huggingface.co/v1"
TOKEN = ""
_SESSION: dict = {"tokens": 0, "cost": 0.0, "requests": 0, "by_model": {}, "start": ""}

PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>HF Inference Chat</title>
<style>
  :root{
    --bg:#f7f7f8; --panel:#ffffff; --ink:#1f2328; --muted:#6b7280;
    --line:#e5e7eb; --user:#2563eb; --user-ink:#fff; --bot:#f1f3f5;
    --accent:#2563eb; --ok:#16a34a; --bad:#dc2626; --code:#0d1117; --code-ink:#e6edf3;
  }
  @media (prefers-color-scheme: dark){
    :root{ --bg:#0f1115; --panel:#161a20; --ink:#e6e6e6; --muted:#9aa4b2;
      --line:#262c36; --bot:#1c2128; --code:#0b0f14; }
  }
  *{box-sizing:border-box}
  html,body{height:100%;margin:0}
  body{font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
    background:var(--bg);color:var(--ink);display:flex;flex-direction:column}
  header{background:var(--panel);border-bottom:1px solid var(--line);padding:10px 16px;
    display:flex;gap:12px;align-items:center;flex-wrap:wrap;position:sticky;top:0;z-index:5}
  header .title{font-weight:600;font-size:15px;display:flex;align-items:center;gap:8px}
  .dot{width:9px;height:9px;border-radius:50%;background:var(--muted);flex:none}
  .dot.ok{background:var(--ok)} .dot.bad{background:var(--bad)}
  select,input,button,textarea{font:inherit;color:var(--ink)}
  select,input[type=number]{background:var(--bg);border:1px solid var(--line);
    border-radius:8px;padding:6px 8px}
  select{max-width:280px}
  .spacer{flex:1}
  .stat{color:var(--muted);font-size:12.5px;white-space:nowrap}
  button{cursor:pointer;border:1px solid var(--line);background:var(--bg);
    border-radius:8px;padding:6px 10px}
  button.primary{background:var(--accent);color:#fff;border-color:var(--accent)}
  button:disabled{opacity:.5;cursor:default}
  .settings{display:flex;gap:10px;align-items:center;flex-wrap:wrap;
    background:var(--panel);border-bottom:1px solid var(--line);padding:8px 16px;font-size:13px}
  .settings label{color:var(--muted);display:flex;gap:6px;align-items:center}
  .settings input[type=number]{width:90px}
  main{flex:1;overflow-y:auto;padding:20px 16px}
  .wrap{max-width:820px;margin:0 auto;display:flex;flex-direction:column;gap:16px}
  .msg{display:flex;gap:10px;align-items:flex-start}
  .msg .who{font-size:11px;font-weight:600;color:var(--muted);text-transform:uppercase;
    letter-spacing:.04em;flex:none;width:64px;padding-top:8px;text-align:right}
  .bubble{padding:10px 14px;border-radius:12px;max-width:100%;overflow-x:auto}
  .msg.user .bubble{background:var(--user);color:var(--user-ink);border-bottom-right-radius:4px}
  .msg.bot .bubble{background:var(--bot);border-bottom-left-radius:4px}
  .bubble p{margin:0 0 8px} .bubble p:last-child{margin:0}
  .bubble pre{background:var(--code);color:var(--code-ink);padding:12px 14px;
    border-radius:8px;overflow-x:auto;margin:8px 0;position:relative}
  .bubble pre code{font:13px/1.5 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
  .bubble code.inline{background:rgba(127,127,127,.18);padding:1px 5px;border-radius:5px;
    font:13px ui-monospace,Menlo,Consolas,monospace}
  .copy{position:absolute;top:6px;right:6px;font-size:11px;padding:2px 7px;
    background:rgba(255,255,255,.12);color:#cfd6dd;border:1px solid rgba(255,255,255,.18)}
  details.think{margin:8px 0;border:1px dashed var(--line);border-radius:8px;padding:6px 10px}
  details.think summary{cursor:pointer;color:var(--muted);font-size:12.5px}
  details.think .body{margin-top:8px;color:var(--muted);white-space:pre-wrap;font-size:13px}
  .meta{font-size:11.5px;color:var(--muted);margin-top:6px}
  .typing{display:inline-flex;gap:4px}
  .typing span{width:6px;height:6px;border-radius:50%;background:var(--muted);
    animation:b 1s infinite ease-in-out}
  .typing span:nth-child(2){animation-delay:.15s}.typing span:nth-child(3){animation-delay:.3s}
  @keyframes b{0%,80%,100%{opacity:.3;transform:translateY(0)}40%{opacity:1;transform:translateY(-3px)}}
  footer{background:var(--panel);border-top:1px solid var(--line);padding:12px 16px}
  .composer{max-width:820px;margin:0 auto;display:flex;gap:10px;align-items:flex-end}
  textarea{flex:1;resize:none;background:var(--bg);border:1px solid var(--line);
    border-radius:10px;padding:10px 12px;max-height:180px;min-height:44px}
  .hint{max-width:820px;margin:6px auto 0;color:var(--muted);font-size:11.5px;text-align:center}
  .empty{color:var(--muted);text-align:center;margin-top:60px}
  .empty h2{margin:0 0 6px;font-size:18px;color:var(--ink)}
  .usage-panel{background:var(--panel);border-bottom:1px solid var(--line);
    padding:0 16px;max-height:0;overflow:hidden;transition:max-height .25s ease,padding .25s ease}
  .usage-panel.open{max-height:600px;padding:14px 16px}
  .usage-grid{max-width:820px;margin:0 auto;display:grid;
    grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:10px}
  .ucard{background:var(--bg);border:1px solid var(--line);border-radius:10px;padding:10px 12px}
  .ucard .ulabel{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px}
  .ucard .uval{font-size:20px;font-weight:600;line-height:1.1}
  .ucard .usub{color:var(--muted);font-size:11.5px;margin-top:3px}
  .ucard.wide{grid-column:1/-1}
  .utable{width:100%;border-collapse:collapse;margin-top:8px;font-size:12.5px}
  .utable th{color:var(--muted);font-weight:500;text-align:left;padding:3px 8px;border-bottom:1px solid var(--line)}
  .utable td{padding:5px 8px;border-bottom:1px solid var(--line)}
  .usage-foot{max-width:820px;margin:10px auto 0;display:flex;gap:10px;align-items:center;
    color:var(--muted);font-size:11.5px}
</style>
</head>
<body>
<header>
  <div class="title"><span id="dot" class="dot"></span> HF Inference Chat</div>
  <select id="model" title="Model"></select>
  <button id="clear" title="Clear conversation">Clear</button>
  <button id="usageBtn" title="Show/hide live usage stats">Usage</button>
  <div class="spacer"></div>
  <div class="stat" id="totals">0 tokens · $0.00000</div>
</header>
<div class="settings">
  <label>max tokens <input id="maxtok" type="number" min="64" max="32000" step="64" value="2048"></label>
  <label>temperature <input id="temp" type="number" min="0" max="2" step="0.1" value="0.7"></label>
  <label>system <input id="sys" type="text" placeholder="(optional system prompt)" style="width:260px"></label>
</div>
<div class="usage-panel" id="usagePanel">
  <div class="usage-grid" id="usageGrid">
    <div style="color:var(--muted);font-size:13px">Loading…</div>
  </div>
  <div class="usage-foot">
    <span id="usageTime"></span>
    <button id="usageRefresh" style="font-size:11.5px;padding:3px 9px">↻ Refresh</button>
    <span style="margin-left:auto">Usage is session-only · cost estimates from router</span>
  </div>
</div>
<main><div class="wrap" id="chat">
  <div class="empty" id="empty">
    <h2>Start chatting</h2>
    <div>Pick a model above, type below, press Enter. Shift+Enter for a newline.</div>
  </div>
</div></main>
<footer>
  <div class="composer">
    <textarea id="box" placeholder="Message the model…" rows="1"></textarea>
    <button id="send" class="primary">Send</button>
  </div>
  <div class="hint">Token stays on your machine · running on router.huggingface.co</div>
</footer>
<script>
const $=s=>document.querySelector(s);
const chat=$("#chat"), box=$("#box"), send=$("#send"), modelSel=$("#model");
let history=[], totalTok=0, totalCost=0, busy=false;

function setStatus(ok,msg){ const d=$("#dot"); d.className="dot "+(ok?"ok":"bad"); d.title=msg||""; }

function esc(t){return t.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");}
function md(text){
  let h=esc(text); const blocks=[];
  h=h.replace(/```(\w*)\n?([\s\S]*?)```/g,(m,lang,code)=>{
    blocks.push(code.replace(/\n+$/,"")); return "B"+(blocks.length-1)+"";});
  h=h.replace(/`([^`\n]+)`/g,'<code class="inline">$1</code>');
  h=h.replace(/\*\*([^*]+)\*\*/g,"<strong>$1</strong>");
  h=h.replace(/^### (.*)$/gm,"<strong>$1</strong>").replace(/^## (.*)$/gm,"<strong>$1</strong>");
  h=h.split(/\n{2,}/).map(p=>"<p>"+p.replace(/\n/g,"<br>")+"</p>").join("");
  h=h.replace(/B(\d+)/g,(m,i)=>'<pre><button class="copy">copy</button><code>'+blocks[i]+"</code></pre>");
  return h;
}
function bubble(role,html,meta,reasoning){
  $("#empty")?.remove();
  const row=document.createElement("div"); row.className="msg "+(role==="user"?"user":"bot");
  const who=document.createElement("div"); who.className="who"; who.textContent=role==="user"?"you":"model";
  const b=document.createElement("div"); b.className="bubble";
  if(reasoning){ const d=document.createElement("details"); d.className="think";
    d.innerHTML='<summary>reasoning</summary><div class="body">'+esc(reasoning)+"</div>"; b.appendChild(d);}
  const c=document.createElement("div"); c.innerHTML=html; b.appendChild(c);
  if(meta){ const m=document.createElement("div"); m.className="meta"; m.textContent=meta; b.appendChild(m);}
  row.appendChild(who); row.appendChild(b); chat.appendChild(row);
  b.querySelectorAll(".copy").forEach(btn=>btn.onclick=()=>{
    navigator.clipboard.writeText(btn.nextElementSibling.textContent);
    btn.textContent="copied"; setTimeout(()=>btn.textContent="copy",1200);});
  window.scrollTo(0,document.body.scrollHeight);
  document.querySelector("main").scrollTop=document.querySelector("main").scrollHeight;
  return b;
}
async function loadModels(){
  try{
    const r=await fetch("/api/models"); const d=await r.json();
    if(d.error){ setStatus(false,d.error); modelSel.innerHTML='<option>'+d.error+'</option>'; return; }
    modelSel.innerHTML=""; d.models.forEach(m=>{const o=document.createElement("option");o.value=o.textContent=m;modelSel.appendChild(o);});
    const pref=d.models.find(m=>/Kimi-K2.7-Code/i.test(m))||d.models.find(m=>/code/i.test(m));
    if(pref) modelSel.value=pref;
    setStatus(true,d.models.length+" models");
  }catch(e){ setStatus(false,String(e)); modelSel.innerHTML='<option>connection failed</option>'; }
}
async function ask(){
  if(busy) return; const text=box.value.trim(); if(!text) return;
  busy=true; send.disabled=true; box.value=""; box.style.height="auto";
  bubble("user","<p>"+md(text).replace(/^<p>|<\/p>$/g,"")+"</p>");
  history.push({role:"user",content:text});
  const holder=bubble("bot",'<span class="typing"><span></span><span></span><span></span></span>');
  try{
    const r=await fetch("/api/chat",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({model:modelSel.value,messages:fullHistory(),
        max_tokens:+$("#maxtok").value,temperature:+$("#temp").value})});
    const d=await r.json();
    if(d.error){ holder.innerHTML='<p style="color:var(--bad)">'+esc(d.error)+'</p>'; }
    else{
      const content=(d.content||"").trim(), reasoning=(d.reasoning||"").trim();
      const shown=content||"(no final content)";
      holder.innerHTML="";
      if(reasoning && !content){ const dt=document.createElement("details"); dt.className="think"; dt.open=true;
        dt.innerHTML='<summary>reasoning (raise max tokens for a final answer)</summary><div class="body">'+esc(reasoning)+'</div>'; holder.appendChild(dt);}
      else if(reasoning){ const dt=document.createElement("details"); dt.className="think";
        dt.innerHTML='<summary>reasoning</summary><div class="body">'+esc(reasoning)+'</div>'; holder.appendChild(dt);}
      const cdiv=document.createElement("div"); cdiv.innerHTML=md(shown); holder.appendChild(cdiv);
      const u=d.usage||{}; let meta="";
      if(u.total_tokens){ totalTok+=u.total_tokens; totalCost+=(u.estimated_cost||0);
        meta=u.total_tokens+" tokens"+(u.estimated_cost!=null?" · $"+(u.estimated_cost).toFixed(5):"");
        if(d.finish_reason==="length") meta+=" · truncated";
        $("#totals").textContent=totalTok+" tokens · $"+totalCost.toFixed(5);}
      if(meta){const m=document.createElement("div");m.className="meta";m.textContent=meta;holder.appendChild(m);}
      holder.querySelectorAll(".copy").forEach(btn=>btn.onclick=()=>{
        navigator.clipboard.writeText(btn.nextElementSibling.textContent);
        btn.textContent="copied";setTimeout(()=>btn.textContent="copy",1200);});
      history.push({role:"assistant",content:content||reasoning});
    }
  }catch(e){ holder.innerHTML='<p style="color:var(--bad)">'+esc(String(e))+'</p>'; }
  busy=false; send.disabled=false; box.focus();
  document.querySelector("main").scrollTop=document.querySelector("main").scrollHeight;
  if(typeof usageOpen!=="undefined"&&usageOpen) loadUsage();
}
function fullHistory(){
  const sys=$("#sys").value.trim();
  return sys?[{role:"system",content:sys},...history]:history;
}
send.onclick=ask;
box.addEventListener("keydown",e=>{ if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();ask();}});
box.addEventListener("input",()=>{box.style.height="auto";box.style.height=Math.min(box.scrollHeight,180)+"px";});
$("#clear").onclick=()=>{history=[];chat.innerHTML='<div class="empty" id="empty"><h2>Cleared</h2><div>New conversation. Type below to begin.</div></div>';};
// ── Usage panel ──────────────────────────────────────────────────────────
let usageOpen=false, usageTimer=null;
const usagePanel=$("#usagePanel");
function fmtN(n){return Number(n||0).toLocaleString();}
function fmtC(n){return "$"+(+n||0).toFixed(5);}
async function loadUsage(){
  try{
    const r=await fetch("/api/usage"); const d=await r.json();
    let html="";
    const acc=d.account||{};
    if(acc.name){
      const tier=acc.isPro?"Pro ✦":"Free";
      html+=`<div class="ucard"><div class="ulabel">Account</div>
        <div class="uval" style="font-size:14px">${esc(acc.fullname||acc.name)}</div>
        <div class="usub">@${esc(acc.name)} · ${tier} · ${esc(acc.role||"token")}</div></div>`;
    } else if(acc.error){
      html+=`<div class="ucard"><div class="ulabel">Account</div><div class="usub" style="color:var(--bad)">${esc(acc.error)}</div></div>`;
    }
    html+=`<div class="ucard"><div class="ulabel">Requests</div>
      <div class="uval">${fmtN(d.requests)}</div>
      <div class="usub">this session</div></div>`;
    html+=`<div class="ucard"><div class="ulabel">Tokens</div>
      <div class="uval">${fmtN(d.tokens)}</div>
      <div class="usub">total billed</div></div>`;
    html+=`<div class="ucard"><div class="ulabel">Est. Cost</div>
      <div class="uval">${fmtC(d.cost)}</div>
      <div class="usub">USD this session</div></div>`;
    const models=Object.entries(d.by_model||{});
    if(models.length){
      html+=`<div class="ucard wide"><div class="ulabel">By model</div>
        <table class="utable"><thead><tr><th>Model</th><th>Req</th><th>Tokens</th><th>Est. Cost</th></tr></thead><tbody>`;
      models.sort((a,b)=>b[1].tokens-a[1].tokens).forEach(([m,v])=>{
        html+=`<tr><td>${esc(m)}</td><td>${fmtN(v.requests)}</td><td>${fmtN(v.tokens)}</td><td>${fmtC(v.cost)}</td></tr>`;
      });
      html+="</tbody></table></div>";
    }
    if(d.start) html+=`<div class="ucard"><div class="ulabel">Session started</div>
      <div class="uval" style="font-size:13px">${esc(d.start)}</div></div>`;
    $("#usageGrid").innerHTML=html||'<div style="color:var(--muted);font-size:13px">No requests yet.</div>';
    $("#usageTime").textContent="Updated "+new Date().toLocaleTimeString();
  }catch(e){
    $("#usageGrid").innerHTML='<div style="color:var(--bad);font-size:13px">'+esc(String(e))+'</div>';
  }
}
$("#usageBtn").onclick=()=>{
  usageOpen=!usageOpen;
  usagePanel.classList.toggle("open",usageOpen);
  if(usageOpen){
    loadUsage();
    usageTimer=usageTimer||setInterval(loadUsage,60000);
  } else {
    if(usageTimer){clearInterval(usageTimer);usageTimer=null;}
  }
};
$("#usageRefresh").onclick=loadUsage;
// ─────────────────────────────────────────────────────────────────────────
loadModels(); box.focus();
</script>
</body>
</html>
"""


def _router_get_models(timeout: float = 15.0):
    req = urllib.request.Request(f"{ROUTER}/models")
    req.add_header("Authorization", f"Bearer {TOKEN}")
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", "hermes-hf-ui/1.0")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode())
    items = data.get("data", data) if isinstance(data, dict) else data
    ids = [m.get("id", m) if isinstance(m, dict) else m for m in items]
    return sorted(ids)


def _hf_whoami(timeout: float = 10.0) -> dict:
    req = urllib.request.Request("https://huggingface.co/api/whoami-v2")
    req.add_header("Authorization", f"Bearer {TOKEN}")
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", "hermes-hf-ui/1.1")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _router_chat(payload: dict, timeout: float = 180.0):
    body = {
        "model": payload["model"],
        "messages": payload["messages"],
        "max_tokens": int(payload.get("max_tokens", 2048)),
        "temperature": float(payload.get("temperature", 0.7)),
        "stream": False,
    }
    req = urllib.request.Request(f"{ROUTER}/chat/completions",
                                 data=json.dumps(body).encode())
    req.add_header("Authorization", f"Bearer {TOKEN}")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "hermes-hf-ui/1.0")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        out = json.loads(r.read().decode())
    choice = out["choices"][0]
    msg = choice.get("message", {})
    usage = out.get("usage", {})
    tok = int(usage.get("total_tokens") or 0)
    cost = float(usage.get("estimated_cost") or 0)
    model_key = body["model"]
    _SESSION["requests"] += 1
    _SESSION["tokens"] += tok
    _SESSION["cost"] += cost
    if model_key not in _SESSION["by_model"]:
        _SESSION["by_model"][model_key] = {"tokens": 0, "cost": 0.0, "requests": 0}
    _SESSION["by_model"][model_key]["tokens"] += tok
    _SESSION["by_model"][model_key]["cost"] += cost
    _SESSION["by_model"][model_key]["requests"] += 1
    return {
        "content": msg.get("content") or "",
        "reasoning": msg.get("reasoning_content") or msg.get("reasoning") or "",
        "finish_reason": choice.get("finish_reason"),
        "usage": usage,
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def _json(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path == "/" or self.path.startswith("/index"):
            b = PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)
        elif self.path == "/api/models":
            try:
                self._json(200, {"models": _router_get_models()})
            except urllib.error.HTTPError as e:
                self._json(200, {"error": f"HTTP {e.code}: {e.read().decode()[:200]}"})
            except Exception as e:
                self._json(200, {"error": str(e)})
        elif self.path == "/api/usage":
            data: dict = {
                "requests": _SESSION["requests"],
                "tokens": _SESSION["tokens"],
                "cost": _SESSION["cost"],
                "by_model": _SESSION["by_model"],
                "start": _SESSION["start"],
            }
            try:
                me = _hf_whoami()
                tok_info = (me.get("auth", {}) or {}).get("accessToken", {}) or {}
                data["account"] = {
                    "name": me.get("name", ""),
                    "fullname": me.get("fullname", "") or me.get("name", ""),
                    "type": me.get("type", ""),
                    "isPro": bool(me.get("isPro")),
                    "role": tok_info.get("role", ""),
                }
            except urllib.error.HTTPError as e:
                data["account"] = {"error": f"HTTP {e.code}: {e.read().decode()[:120]}"}
            except Exception as e:
                data["account"] = {"error": str(e)[:120]}
            self._json(200, data)
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/api/chat":
            return self._json(404, {"error": "not found"})
        try:
            n = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(n).decode())
            self._json(200, _router_chat(payload))
        except urllib.error.HTTPError as e:
            self._json(200, {"error": f"HTTP {e.code}: {e.read().decode()[:300]}"})
        except Exception as e:
            self._json(200, {"error": str(e)})


def main() -> int:
    global TOKEN
    args = sys.argv[1:]
    if args and args[0].startswith("hf_"):
        TOKEN = args.pop(0).strip()
    else:
        TOKEN = os.environ.get("HF_TOKEN", "").strip()
    port = int(args[0]) if args and args[0].isdigit() else 8765

    if not TOKEN:
        print("FAIL: no token. Set HF_TOKEN or pass it as the first argument.",
              file=sys.stderr)
        return 1

    _SESSION["start"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    url = f"http://127.0.0.1:{port}"
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"HF Inference Chat UI running at {url}")
    print("Token loaded from", "argument" if args else "$HF_TOKEN",
          f"({len(TOKEN)} chars). Bound to localhost only.")
    print("Press Ctrl-C to stop.")
    threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
