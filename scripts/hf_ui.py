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
import subprocess
import sys
import threading
import urllib.error
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROUTER = "https://router.huggingface.co/v1"
TOKEN = ""
_SESSION: dict = {"tokens": 0, "cost": 0.0, "requests": 0, "by_model": {}, "start": ""}
_AGENT: dict = {"cancel": False}
_PENDING: dict = {}  # approval_id -> {"event": threading.Event, "decision": str|None}

PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>HF · Claude Code Terminal</title>
<style>
  :root{
    --bg:#0F0D15; --panel:#1A1625; --surface:#242033; --code:#181325;
    --text:#F4F0EB; --muted:#A49FB0; --placeholder:#6A617D;
    --accent:#B18CFF; --accent-strong:#7C3AED;
    --success:#6BCB77; --warning:#FFD93D; --error:#FF6B6B;
    --border:#322B45; --border-focus:#5B4E75; --radius:6px;
    --font-mono:"JetBrains Mono","Fira Code","SF Mono",ui-monospace,Menlo,Consolas,monospace;
  }
  *{box-sizing:border-box}
  html,body{height:100%;margin:0}
  body{font:14px/1.55 var(--font-mono);background:var(--bg);color:var(--text);
    display:flex;flex-direction:column;overflow:hidden}
  /* ── Header ─────────────────────────────────────────────── */
  .app-header{height:40px;flex:none;background:var(--panel);
    border-bottom:1px solid var(--border);display:flex;align-items:center;
    justify-content:space-between;padding:0 16px;user-select:none}
  .brand{display:flex;align-items:center;gap:8px;font-weight:600;font-size:13px}
  .brand .logo{color:var(--accent)}
  .brand .hk{color:var(--muted);font-weight:400;font-size:11px;margin-left:6px}
  .status{display:flex;align-items:center;gap:10px;color:var(--muted);font-size:11px}
  .dot{width:8px;height:8px;border-radius:50%;background:var(--muted);flex:none}
  .dot.ok{background:var(--success)} .dot.bad{background:var(--error)}
  .totals{color:var(--muted);white-space:nowrap}
  /* ── Body ───────────────────────────────────────────────── */
  .app-body{flex:1;display:flex;overflow:hidden}
  .sidebar{width:248px;flex:none;background:var(--panel);
    border-right:1px solid var(--border);overflow-y:auto;
    transition:margin-left .2s ease;display:flex;flex-direction:column;gap:2px}
  .sidebar.collapsed{margin-left:-248px}
  .sb-sec{padding:12px 14px;border-bottom:1px solid var(--border)}
  .sb-label{color:var(--muted);font-size:11px;text-transform:uppercase;
    letter-spacing:.06em;margin-bottom:8px;display:flex;align-items:center;
    justify-content:space-between}
  .sb-sec label{display:block;color:var(--muted);font-size:11px;margin:8px 0 0}
  select,input,textarea,button{font:inherit;color:var(--text)}
  select,input[type=number],.sb-sec textarea{width:100%;background:var(--bg);
    border:1px solid var(--border);border-radius:var(--radius);padding:7px 9px;
    margin-top:4px;outline:none;font-size:13px}
  .sb-sec textarea{resize:vertical;min-height:42px}
  select:focus,input:focus,textarea:focus{border-color:var(--border-focus);
    box-shadow:0 0 0 2px rgba(177,140,255,.18)}
  button{cursor:pointer;background:var(--surface);border:1px solid var(--border);
    border-radius:var(--radius);padding:7px 11px;color:var(--text)}
  button:hover{border-color:var(--border-focus)}
  button.mini{padding:1px 7px;font-size:12px;background:transparent;border:none;color:var(--muted)}
  button.mini:hover{color:var(--accent)}
  button.ghost{width:100%;color:var(--muted)}
  button.ghost:hover{color:var(--text)}
  button:disabled{opacity:.5;cursor:default}
  button:focus-visible,input:focus-visible,select:focus-visible,textarea:focus-visible{
    outline:2px solid var(--accent);outline-offset:1px}
  /* ── Usage cards ────────────────────────────────────────── */
  .usage-grid{display:grid;grid-template-columns:1fr 1fr;gap:6px}
  .ucard{background:var(--bg);border:1px solid var(--border);border-radius:var(--radius);
    padding:7px 9px}
  .ucard.wide{grid-column:1/-1}
  .ucard .ulabel{color:var(--muted);font-size:9.5px;text-transform:uppercase;
    letter-spacing:.05em;margin-bottom:2px}
  .ucard .uval{font-size:15px;font-weight:600;line-height:1.15;word-break:break-all}
  .ucard .usub{color:var(--muted);font-size:10px;margin-top:1px}
  .utable{width:100%;border-collapse:collapse;font-size:10.5px;margin-top:4px}
  .utable th{color:var(--muted);font-weight:500;text-align:left;padding:2px 4px;border-bottom:1px solid var(--border)}
  .utable td{padding:3px 4px;border-bottom:1px solid var(--border);word-break:break-all}
  .muted{color:var(--muted)} .small{font-size:10px}
  /* ── Terminal area ──────────────────────────────────────── */
  .terminal{flex:1;overflow-y:auto;padding:18px 16px}
  .wrap{max-width:880px;margin:0 auto;display:flex;flex-direction:column;gap:14px}
  .msg{display:flex;flex-direction:column;gap:3px;max-width:88%;width:fit-content}
  .msg.user{align-self:flex-end;align-items:flex-end}
  .msg.bot{align-self:flex-start}
  .meta{color:var(--muted);font-size:10.5px}
  .bubble{padding:9px 13px;border-radius:var(--radius);max-width:100%;overflow-x:auto}
  .msg.user .bubble{background:var(--surface);border:1px solid var(--border)}
  .msg.bot .bubble{background:transparent;border:1px solid transparent;padding-left:0}
  .bubble p{margin:0 0 8px} .bubble p:last-child{margin:0}
  .bubble pre{background:var(--code);border:1px solid var(--border);color:var(--text);
    padding:12px 14px;border-radius:var(--radius);overflow-x:auto;margin:8px 0;position:relative}
  .bubble pre code{font:12.5px/1.5 var(--font-mono)}
  .bubble code.inline{background:var(--surface);padding:1px 5px;border-radius:4px;
    color:var(--accent);font:12.5px var(--font-mono)}
  .copy{position:absolute;top:6px;right:6px;font-size:10.5px;padding:2px 7px;
    background:var(--surface);color:var(--muted);border:1px solid var(--border)}
  .copy:hover{color:var(--accent)}
  details.think{margin:8px 0;border:1px dashed var(--border);border-radius:var(--radius);padding:6px 10px}
  details.think summary{cursor:pointer;color:var(--muted);font-size:12px}
  details.think .body{margin-top:8px;color:var(--muted);white-space:pre-wrap;font-size:12.5px}
  .msgmeta{font-size:10.5px;color:var(--muted);margin-top:5px}
  .typing{display:inline-flex;gap:4px;padding:4px 0}
  .typing span{width:6px;height:6px;border-radius:50%;background:var(--accent);
    animation:b 1s infinite ease-in-out}
  .typing span:nth-child(2){animation-delay:.15s}.typing span:nth-child(3){animation-delay:.3s}
  @keyframes b{0%,80%,100%{opacity:.3;transform:translateY(0)}40%{opacity:1;transform:translateY(-3px)}}
  .empty{color:var(--muted);text-align:center;margin-top:64px}
  .empty h2{margin:0 0 6px;font-size:16px;color:var(--text);font-weight:600}
  .empty code{background:var(--surface);color:var(--accent);padding:2px 6px;border-radius:4px}
  /* ── Input bar ──────────────────────────────────────────── */
  .inputbar{flex:none;background:var(--panel);border-top:1px solid var(--border);
    padding:10px 16px;display:flex;gap:10px;align-items:flex-start}
  .inputbar .composer{max-width:880px;margin:0 auto;display:flex;gap:10px;
    align-items:flex-start;width:100%}
  .prompt{color:var(--accent);font-weight:700;padding-top:9px;user-select:none}
  #box{flex:1;resize:none;background:var(--bg);border:1px solid var(--border);
    border-radius:var(--radius);padding:9px 12px;max-height:180px;min-height:38px;
    outline:none;font-size:14px}
  #box::placeholder{color:var(--placeholder)}
  #box:focus{border-color:var(--border-focus);box-shadow:0 0 0 2px rgba(177,140,255,.18)}
  .send{background:var(--accent);color:var(--bg);border:none;font-weight:600;
    padding:9px 16px}
  .send:hover{background:var(--accent-strong);color:var(--text)}
  .stop{background:var(--error);color:#1a0f12;border:none;font-weight:600;padding:9px 16px}
  .sb-sec label.row{flex-direction:row;align-items:center;gap:8px;cursor:pointer}
  .sb-sec label.row input{width:auto;margin:0}
  /* agent trace */
  .agent{display:flex;flex-direction:column;gap:8px}
  .astep{color:var(--accent);font-size:11px;text-transform:uppercase;letter-spacing:.05em;
    border-top:1px solid var(--border);padding-top:8px;margin-top:2px}
  .athink{font-size:13.5px}
  .atool{background:var(--code);border:1px solid var(--border);border-radius:var(--radius);
    overflow:hidden}
  .atool-h{padding:6px 10px;color:var(--accent);font-size:12px;font-weight:600;
    border-bottom:1px solid var(--border)}
  .atool-cmd{margin:0;padding:9px 11px;background:transparent;border:none}
  .atool-cmd code{font:12.5px/1.5 var(--font-mono);color:var(--text)}
  details.aresult{border:1px solid var(--border);border-radius:var(--radius);
    padding:6px 10px;background:var(--bg)}
  details.aresult summary{cursor:pointer;color:var(--muted);font-size:11.5px}
  details.aresult pre{margin:8px 0 0;background:var(--code);border:1px solid var(--border);
    border-radius:var(--radius);padding:10px;overflow-x:auto;max-height:320px}
  details.aresult pre code{font:12px/1.5 var(--font-mono);white-space:pre-wrap;word-break:break-word}
  .afinal{border-left:3px solid var(--success);padding:6px 0 6px 12px;margin-top:4px}
  .aerr{color:var(--error);font-size:13px;padding:6px 0}
  .approve{display:flex;gap:8px;align-items:center;padding:8px 10px;
    border-top:1px solid var(--border);background:var(--surface)}
  .approve button{padding:5px 12px;font-size:12px;font-weight:600}
  .approve button.ok{background:var(--success);color:#0b160d;border:none}
  .approve button.no{background:var(--error);color:#1a0f12;border:none}
  .approve .amsg{font-size:12px;color:var(--warning)}
  .approve .amsg.ok{color:var(--success)} .approve .amsg.no{color:var(--error)}
  ::-webkit-scrollbar{width:9px;height:9px}
  ::-webkit-scrollbar-track{background:transparent}
  ::-webkit-scrollbar-thumb{background:var(--border);border-radius:4px}
  ::-webkit-scrollbar-thumb:hover{background:var(--border-focus)}
</style>
</head>
<body>
<header class="app-header">
  <div class="brand"><span class="logo">◆</span> HF Inference
    <span class="hk">Ctrl+B sidebar · Ctrl+L clear</span></div>
  <div class="status">
    <span id="dot" class="dot"></span><span id="status-text">connecting…</span>
    <span class="totals" id="totals">0 tokens · $0.00000</span>
  </div>
</header>
<div class="app-body">
  <aside id="sidebar" class="sidebar">
    <div class="sb-sec">
      <div class="sb-label">Model</div>
      <select id="model" title="Model"></select>
    </div>
    <div class="sb-sec">
      <div class="sb-label">Settings</div>
      <label>max tokens
        <input id="maxtok" type="number" min="64" max="128000" step="64" value="20000"></label>
      <label>temperature
        <input id="temp" type="number" min="0" max="2" step="0.1" value="0.7"></label>
      <label>system prompt
        <textarea id="sys" rows="2" placeholder="(optional)"></textarea></label>
    </div>
    <div class="sb-sec">
      <div class="sb-label">Agent mode</div>
      <label class="row"><input type="checkbox" id="agent"> autonomous (uses tools)</label>
      <label class="row"><input type="checkbox" id="approve"> ask before each command</label>
      <label>working dir
        <input id="workdir" type="text" value="~/hermes-agent" spellcheck="false"></label>
      <label>max steps
        <input id="maxsteps" type="number" min="1" max="50" value="12"></label>
      <div class="muted small" style="margin-top:6px">Runs bash / edits files on this
        machine until the goal is done. Approval gates bash &amp; file writes.</div>
    </div>
    <div class="sb-sec">
      <div class="sb-label">Live usage <button id="usageRefresh" class="mini" title="Refresh">↻</button></div>
      <div id="usageGrid" class="usage-grid"><div class="muted small">— send a message —</div></div>
      <div class="muted small" id="usageTime" style="margin-top:6px"></div>
    </div>
    <div class="sb-sec" style="border-bottom:none">
      <button id="clear" class="ghost">Clear conversation</button>
    </div>
  </aside>
  <main id="terminal" class="terminal" aria-live="polite" aria-atomic="false">
    <div class="wrap" id="chat">
      <div class="empty" id="empty">
        <h2>◆ HF Inference Terminal</h2>
        <div>Pick a model, type below, press <code>Enter</code>. <code>Shift+Enter</code> for a newline.</div>
      </div>
    </div>
  </main>
</div>
<footer class="inputbar">
  <div class="composer">
    <span class="prompt" aria-hidden="true">❯</span>
    <textarea id="box" placeholder="Message the model…" rows="1"
      autocomplete="off" spellcheck="false" aria-label="Message input"></textarea>
    <button id="send" class="send">Send</button>
    <button id="stop" class="stop" style="display:none">Stop</button>
  </div>
</footer>
<script>
const $=s=>document.querySelector(s);
const chat=$("#chat"), box=$("#box"), send=$("#send"), modelSel=$("#model");
const term=$("#terminal"), sidebar=$("#sidebar");
let history=[], totalTok=0, totalCost=0, busy=false;

function setStatus(ok,msg){ const d=$("#dot"); d.className="dot "+(ok?"ok":"bad");
  $("#status-text").textContent=msg||(ok?"ready":"error"); }
function scrollDown(){ term.scrollTop=term.scrollHeight; }

function esc(t){return t.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");}
function md(text){
  let h=esc(text); const blocks=[];
  h=h.replace(/```(\w*)\n?([\s\S]*?)```/g,(m,lang,code)=>{
    blocks.push(code.replace(/\n+$/,"")); return ""+(blocks.length-1)+"";});
  h=h.replace(/`([^`\n]+)`/g,'<code class="inline">$1</code>');
  h=h.replace(/\*\*([^*]+)\*\*/g,"<strong>$1</strong>");
  h=h.replace(/^### (.*)$/gm,"<strong>$1</strong>").replace(/^## (.*)$/gm,"<strong>$1</strong>");
  h=h.split(/\n{2,}/).map(p=>"<p>"+p.replace(/\n/g,"<br>")+"</p>").join("");
  h=h.replace(/(\d+)/g,(m,i)=>'<pre><button class="copy">copy</button><code>'+blocks[i]+"</code></pre>");
  return h;
}
function wireCopy(el){ el.querySelectorAll(".copy").forEach(btn=>btn.onclick=()=>{
  navigator.clipboard.writeText(btn.nextElementSibling.textContent);
  btn.textContent="copied"; setTimeout(()=>btn.textContent="copy",1200);}); }
function bubble(role,html,reasoning){
  $("#empty")?.remove();
  const row=document.createElement("div"); row.className="msg "+(role==="user"?"user":"bot");
  const meta=document.createElement("div"); meta.className="meta";
  meta.textContent=(role==="user"?"you":"assistant")+" · "+
    new Date().toLocaleTimeString([], {hour:"2-digit",minute:"2-digit"});
  const b=document.createElement("div"); b.className="bubble";
  if(reasoning){ const d=document.createElement("details"); d.className="think";
    d.innerHTML='<summary>reasoning</summary><div class="body">'+esc(reasoning)+"</div>"; b.appendChild(d);}
  const c=document.createElement("div"); c.innerHTML=html; b.appendChild(c);
  row.appendChild(meta); row.appendChild(b); chat.appendChild(row);
  wireCopy(b); scrollDown(); return b;
}
async function loadModels(){
  try{
    const r=await fetch("/api/models"); const d=await r.json();
    if(d.error){ setStatus(false,d.error); modelSel.innerHTML='<option>'+esc(d.error)+'</option>'; return; }
    modelSel.innerHTML=""; d.models.forEach(m=>{const o=document.createElement("option");o.value=o.textContent=m;modelSel.appendChild(o);});
    const pref=d.models.find(m=>/Kimi-K2.7-Code/i.test(m))||d.models.find(m=>/code/i.test(m));
    if(pref) modelSel.value=pref;
    setStatus(true,d.models.length+" models");
  }catch(e){ setStatus(false,String(e)); modelSel.innerHTML='<option>connection failed</option>'; }
}
async function ask(){
  if(busy) return; const text=box.value.trim(); if(!text) return;
  busy=true; send.disabled=true; box.value=""; box.style.height="auto";
  bubble("user",md(text));
  history.push({role:"user",content:text});
  const holder=bubble("bot",'<span class="typing"><span></span><span></span><span></span></span>');
  try{
    const r=await fetch("/api/chat",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({model:modelSel.value,messages:fullHistory(),
        max_tokens:+$("#maxtok").value,temperature:+$("#temp").value})});
    const d=await r.json();
    if(d.error){ holder.innerHTML='<p style="color:var(--error)">'+esc(d.error)+'</p>'; }
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
      if(meta){const m=document.createElement("div");m.className="msgmeta";m.textContent=meta;holder.appendChild(m);}
      wireCopy(holder);
      history.push({role:"assistant",content:content||reasoning});
    }
  }catch(e){ holder.innerHTML='<p style="color:var(--error)">'+esc(String(e))+'</p>'; }
  busy=false; send.disabled=false; box.focus(); scrollDown();
  loadUsage();
}
function fullHistory(){
  const sys=$("#sys").value.trim();
  return sys?[{role:"system",content:sys},...history]:history;
}
// ── Live usage (sidebar) ─────────────────────────────────────────────────
function fmtN(n){return Number(n||0).toLocaleString();}
function fmtC(n){return "$"+(+n||0).toFixed(5);}
async function loadUsage(){
  try{
    const r=await fetch("/api/usage"); const d=await r.json();
    let html=""; const acc=d.account||{};
    if(acc.name){
      const tier=acc.isPro?"Pro ✦":"Free";
      html+=`<div class="ucard wide"><div class="ulabel">Account</div>
        <div class="uval" style="font-size:12px">${esc(acc.fullname||acc.name)}</div>
        <div class="usub">@${esc(acc.name)} · ${tier} · ${esc(acc.role||"token")}</div></div>`;
    } else if(acc.error){
      html+=`<div class="ucard wide"><div class="ulabel">Account</div><div class="usub" style="color:var(--error)">${esc(acc.error)}</div></div>`;
    }
    html+=`<div class="ucard"><div class="ulabel">Requests</div><div class="uval">${fmtN(d.requests)}</div></div>`;
    html+=`<div class="ucard"><div class="ulabel">Tokens</div><div class="uval">${fmtN(d.tokens)}</div></div>`;
    html+=`<div class="ucard wide"><div class="ulabel">Est. cost (session)</div><div class="uval">${fmtC(d.cost)}</div></div>`;
    const models=Object.entries(d.by_model||{});
    if(models.length){
      html+=`<div class="ucard wide"><div class="ulabel">By model</div>
        <table class="utable"><thead><tr><th>Model</th><th>Req</th><th>Tok</th></tr></thead><tbody>`;
      models.sort((a,b)=>b[1].tokens-a[1].tokens).forEach(([m,v])=>{
        const short=m.split("/").pop();
        html+=`<tr><td title="${esc(m)}">${esc(short)}</td><td>${fmtN(v.requests)}</td><td>${fmtN(v.tokens)}</td></tr>`;
      });
      html+="</tbody></table></div>";
    }
    $("#usageGrid").innerHTML=html;
    $("#usageTime").textContent="updated "+new Date().toLocaleTimeString();
  }catch(e){ $("#usageGrid").innerHTML='<div class="small" style="color:var(--error)">'+esc(String(e))+'</div>'; }
}
function clearChat(){ history=[]; totalTok=0; totalCost=0;
  $("#totals").textContent="0 tokens · $0.00000";
  chat.innerHTML='<div class="empty" id="empty"><h2>◆ Cleared</h2><div>New conversation. Type below to begin.</div></div>'; }
// ── Agent mode ─────────────────────────────────────────────────────────────
let agentCtrl=null;
function resolveApproval(id,decision,ap){
  ap.innerHTML='<span class="amsg">'+decision+'…</span>';
  fetch("/api/agent/approve",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({id,decision})}).catch(()=>{});
}
function handleAgentEvent(ev,root,cards){
  if(ev.type==="step"){
    const d=document.createElement("div"); d.className="astep";
    d.textContent="step "+ev.n+" / "+ev.max; root.appendChild(d);
  } else if(ev.type==="assistant" && (ev.content||ev.reasoning)){
    const d=document.createElement("div"); d.className="athink";
    if(ev.reasoning){ const dt=document.createElement("details"); dt.className="think";
      dt.innerHTML='<summary>reasoning</summary><div class="body">'+esc(ev.reasoning)+'</div>'; d.appendChild(dt);}
    if(ev.content){ const c=document.createElement("div"); c.innerHTML=md(ev.content); d.appendChild(c);}
    root.appendChild(d); wireCopy(d);
  } else if(ev.type==="tool_call"){
    const arg = ev.name==="bash" ? (ev.args.command||"")
              : ev.name==="write_file" ? (ev.args.path||"")+"\n"+(ev.args.content||"")
              : (ev.args.path!=null ? ev.args.path : JSON.stringify(ev.args));
    const d=document.createElement("div"); d.className="atool";
    d.innerHTML='<div class="atool-h">▸ '+esc(ev.name)+'</div>'+
      '<pre class="atool-cmd"><code>'+esc(arg)+'</code></pre>';
    if(ev.needs_approval){ const ap=document.createElement("div"); ap.className="approve";
      ap.innerHTML='<span class="amsg">waiting for approval…</span>'; d.appendChild(ap); }
    root.appendChild(d); if(cards) cards[ev.id]=d;
  } else if(ev.type==="approval_request"){
    const d=cards&&cards[ev.id]; if(!d) return; const ap=d.querySelector(".approve"); if(!ap) return;
    ap.innerHTML='<button class="ok">Approve</button><button class="no">Deny</button>';
    ap.querySelector(".ok").onclick=()=>resolveApproval(ev.id,"approve",ap);
    ap.querySelector(".no").onclick=()=>resolveApproval(ev.id,"deny",ap);
  } else if(ev.type==="approval_resolved"){
    const d=cards&&cards[ev.id]; if(!d) return; const ap=d.querySelector(".approve"); if(!ap) return;
    const k=ev.decision==="approve"?"ok":"no";
    ap.innerHTML='<span class="amsg '+k+'">'+esc(ev.decision||"")+'</span>';
  } else if(ev.type==="tool_result"){
    const d=document.createElement("details"); d.className="aresult";
    d.innerHTML='<summary>output</summary><pre><code>'+esc(ev.output||"")+'</code></pre>';
    root.appendChild(d);
  } else if(ev.type==="final"){
    const d=document.createElement("div"); d.className="afinal";
    d.innerHTML=md(ev.content||"(done)"); root.appendChild(d); wireCopy(d);
  } else if(ev.type==="error"){
    const d=document.createElement("div"); d.className="aerr"; d.textContent=ev.message; root.appendChild(d);
  }
  scrollDown();
}
async function runAgent(){
  if(busy) return; const goal=box.value.trim(); if(!goal) return;
  busy=true; send.disabled=true; box.value=""; box.style.height="auto";
  $("#stop").style.display="";
  bubble("user",md(goal));
  history.push({role:"user",content:goal});
  const panel=bubble("bot",'<div class="agent"></div>');
  const root=panel.querySelector(".agent");
  const cards={};
  agentCtrl=new AbortController();
  let finalText="";
  try{
    const r=await fetch("/api/agent",{method:"POST",
      headers:{"Content-Type":"application/json"}, signal:agentCtrl.signal,
      body:JSON.stringify({model:modelSel.value, goal, history,
        workdir:$("#workdir").value, max_steps:+$("#maxsteps").value,
        approve_each:$("#approve").checked,
        max_tokens:+$("#maxtok").value, temperature:+$("#temp").value})});
    const reader=r.body.getReader(); const dec=new TextDecoder(); let buf="";
    while(true){
      const {value,done}=await reader.read(); if(done) break;
      buf+=dec.decode(value,{stream:true}); let nl;
      while((nl=buf.indexOf("\n"))>=0){
        const line=buf.slice(0,nl).trim(); buf=buf.slice(nl+1);
        if(!line) continue;
        let ev; try{ ev=JSON.parse(line); }catch(_){ continue; }
        handleAgentEvent(ev,root,cards);
        if(ev.type==="final") finalText=ev.content||"";
      }
    }
  }catch(e){ if(e.name!=="AbortError"){
    root.insertAdjacentHTML("beforeend",'<div class="aerr">'+esc(String(e))+'</div>'); } }
  if(finalText) history.push({role:"assistant",content:finalText});
  busy=false; send.disabled=false; $("#stop").style.display="none"; agentCtrl=null;
  box.focus(); scrollDown(); loadUsage();
}
function submit(){ if($("#agent").checked) runAgent(); else ask(); }
// ── Events ───────────────────────────────────────────────────────────────
send.onclick=submit;
$("#stop").onclick=()=>{ if(agentCtrl) agentCtrl.abort();
  fetch("/api/agent/stop",{method:"POST"}).catch(()=>{}); };
box.addEventListener("keydown",e=>{ if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();submit();}});
box.addEventListener("input",()=>{box.style.height="auto";box.style.height=Math.min(box.scrollHeight,180)+"px";});
$("#agent").addEventListener("change",e=>{
  box.placeholder=e.target.checked?"Give the agent a goal — it'll work on its own…":"Message the model…";
});
$("#clear").onclick=clearChat;
$("#usageRefresh").onclick=loadUsage;
document.addEventListener("keydown",e=>{
  if(e.ctrlKey && e.key.toLowerCase()==="b"){ e.preventDefault(); sidebar.classList.toggle("collapsed"); }
  if(e.ctrlKey && e.key.toLowerCase()==="l"){ e.preventDefault(); clearChat(); box.focus(); }
});
loadModels(); loadUsage(); box.focus();
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
        "max_tokens": int(payload.get("max_tokens", 20000)),
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


# ── Agent mode ────────────────────────────────────────────────────────────
AGENT_TOOLS = [
    {"type": "function", "function": {
        "name": "bash",
        "description": "Run a bash command in the working directory and return "
                       "combined stdout/stderr. Use for builds, tests, git, "
                       "searching, installing, anything a shell can do.",
        "parameters": {"type": "object", "properties": {
            "command": {"type": "string", "description": "Shell command to run."}},
            "required": ["command"]}}},
    {"type": "function", "function": {
        "name": "read_file",
        "description": "Read a UTF-8 text file and return its contents.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "write_file",
        "description": "Create or overwrite a text file with the given content.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"]}}},
    {"type": "function", "function": {
        "name": "list_dir",
        "description": "List the entries in a directory.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}}, "required": ["path"]}}},
]

AGENT_SYSTEM = (
    "You are an autonomous coding agent running directly on the user's machine, "
    "similar to Claude Code. You have these tools: bash, read_file, write_file, "
    "list_dir. Your working directory is {workdir}.\n\n"
    "Work the goal end to end on your own: break it into steps and EXECUTE them "
    "with the tools. Do not ask the user for confirmation or for more input — "
    "keep going until the goal is fully accomplished. Inspect before you change "
    "(read files, list dirs, run commands), make the change, then verify it "
    "(run the build/tests). Prefer paths relative to the working directory. Be "
    "careful with destructive commands. When the goal is complete, stop calling "
    "tools and reply with a short summary of what you did and how you verified it."
)


def _trunc(s: str, n: int = 6000) -> str:
    return s if len(s) <= n else s[:n] + f"\n…[truncated {len(s) - n} chars]"


def _agent_workdir(wd) -> str:
    wd = os.path.expanduser((wd or "~").strip())
    return wd if os.path.isdir(wd) else os.path.expanduser("~")


def _resolve(path: str, workdir: str) -> str:
    path = os.path.expanduser(path)
    return path if os.path.isabs(path) else os.path.join(workdir, path)


def _exec_tool(name: str, args: dict, workdir: str) -> str:
    try:
        if name == "bash":
            cmd = args.get("command", "")
            p = subprocess.run(cmd, shell=True, cwd=workdir, capture_output=True,
                               text=True, timeout=120)
            out = ((p.stdout or "") + (p.stderr or "")).strip()
            return _trunc(out or f"(exit {p.returncode}, no output)")
        if name == "read_file":
            with open(_resolve(args["path"], workdir), encoding="utf-8",
                      errors="replace") as f:
                return _trunc(f.read())
        if name == "write_file":
            path = _resolve(args["path"], workdir)
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            content = args.get("content", "")
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return f"wrote {len(content)} bytes to {path}"
        if name == "list_dir":
            return _trunc("\n".join(sorted(os.listdir(_resolve(args.get("path", "."), workdir)))))
        return f"unknown tool: {name}"
    except subprocess.TimeoutExpired:
        return "error: command timed out (120s)"
    except Exception as e:
        return f"error: {e}"


def _router_chat_agent(model, messages, max_tokens, temperature, timeout=180.0):
    body = {"model": model, "messages": messages, "max_tokens": int(max_tokens),
            "temperature": float(temperature), "tools": AGENT_TOOLS,
            "tool_choice": "auto", "stream": False}
    req = urllib.request.Request(f"{ROUTER}/chat/completions",
                                 data=json.dumps(body).encode())
    req.add_header("Authorization", f"Bearer {TOKEN}")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "hermes-hf-ui/agent")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        out = json.loads(r.read().decode())
    choice = out["choices"][0]
    usage = out.get("usage", {})
    tok = int(usage.get("total_tokens") or 0)
    cost = float(usage.get("estimated_cost") or 0)
    _SESSION["requests"] += 1
    _SESSION["tokens"] += tok
    _SESSION["cost"] += cost
    bm = _SESSION["by_model"].setdefault(model, {"tokens": 0, "cost": 0.0, "requests": 0})
    bm["tokens"] += tok
    bm["cost"] += cost
    bm["requests"] += 1
    return choice.get("message", {}) or {}, usage


APPROVAL_TOOLS = ("bash", "write_file")  # mutating actions that need an OK


def run_agent(model, messages, workdir, max_steps, max_tokens, temperature,
              approve_each=False):
    """Generator yielding NDJSON-able event dicts as the agent works."""
    _AGENT["cancel"] = False
    for step in range(1, max_steps + 1):
        if _AGENT["cancel"]:
            yield {"type": "final", "content": "(stopped by user)"}
            return
        yield {"type": "step", "n": step, "max": max_steps}
        try:
            msg, usage = _router_chat_agent(model, messages, max_tokens, temperature)
        except urllib.error.HTTPError as e:
            yield {"type": "error", "message": f"HTTP {e.code}: {e.read().decode()[:300]}"}
            return
        except Exception as e:
            yield {"type": "error", "message": str(e)}
            return

        content = (msg.get("content") or "").strip()
        reasoning = (msg.get("reasoning_content") or msg.get("reasoning") or "").strip()
        tool_calls = msg.get("tool_calls") or []
        if content or reasoning:
            yield {"type": "assistant", "content": content, "reasoning": reasoning}

        if tool_calls:
            messages.append({"role": "assistant", "content": msg.get("content") or "",
                             "tool_calls": tool_calls})
        else:
            messages.append({"role": "assistant", "content": msg.get("content") or ""})
            yield {"type": "final", "content": content or reasoning or "(no output)",
                   "usage": usage}
            return

        for tc in tool_calls:
            fn = tc.get("function", {}) or {}
            name = fn.get("name", "")
            raw = fn.get("arguments") or "{}"
            try:
                a = json.loads(raw) if isinstance(raw, str) else (raw or {})
            except Exception:
                a = {"_raw": raw}
            tcid = tc.get("id") or f"s{step}-{name}"
            need_ok = approve_each and name in APPROVAL_TOOLS and not _AGENT["cancel"]
            yield {"type": "tool_call", "name": name, "args": a, "id": tcid,
                   "needs_approval": need_ok}

            if _AGENT["cancel"]:
                result = "(stopped by user)"
            elif need_ok:
                ev = threading.Event()
                _PENDING[tcid] = {"event": ev, "decision": None}
                yield {"type": "approval_request", "id": tcid}
                ok = ev.wait(600)  # wait up to 10 min for the human
                decision = (_PENDING.pop(tcid, {}) or {}).get("decision") if ok else "timeout"
                yield {"type": "approval_resolved", "id": tcid,
                       "decision": decision or "deny"}
                if _AGENT["cancel"]:
                    result = "(stopped by user)"
                elif decision == "approve":
                    result = _exec_tool(name, a, workdir)
                else:
                    result = ("(denied by user — do NOT retry this exact action; "
                              "take a different approach or finish and report).")
            else:
                result = _exec_tool(name, a, workdir)

            yield {"type": "tool_result", "name": name, "output": result, "id": tcid}
            messages.append({"role": "tool", "tool_call_id": tc.get("id"),
                             "name": name, "content": result})
    yield {"type": "final", "content": "(reached max steps without finishing — "
           "raise max steps or refine the goal)"}


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
        if self.path == "/api/agent/stop":
            _AGENT["cancel"] = True
            return self._json(200, {"ok": True})
        if self.path == "/api/agent/approve":
            try:
                n = int(self.headers.get("Content-Length", 0))
                p = json.loads(self.rfile.read(n).decode())
            except Exception as e:
                return self._json(400, {"error": str(e)})
            rec = _PENDING.get(p.get("id"))
            if rec:
                rec["decision"] = p.get("decision", "deny")
                rec["event"].set()
            return self._json(200, {"ok": bool(rec)})
        if self.path == "/api/agent":
            return self._agent()
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

    def _agent(self):
        try:
            n = int(self.headers.get("Content-Length", 0))
            p = json.loads(self.rfile.read(n).decode())
        except Exception as e:
            return self._json(400, {"error": str(e)})
        model = p.get("model", "")
        goal = (p.get("goal") or "").strip()
        workdir = _agent_workdir(p.get("workdir"))
        max_steps = max(1, min(50, int(p.get("max_steps", 12))))
        max_tokens = int(p.get("max_tokens", 4096))
        temperature = float(p.get("temperature", 0.3))
        approve_each = bool(p.get("approve_each"))
        messages = ([{"role": "system", "content": AGENT_SYSTEM.format(workdir=workdir)}]
                    + list(p.get("history") or [])
                    + [{"role": "user", "content": goal}])
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            for ev in run_agent(model, messages, workdir, max_steps, max_tokens,
                                temperature, approve_each):
                self.wfile.write((json.dumps(ev) + "\n").encode())
                self.wfile.flush()
            self.wfile.write((json.dumps({"type": "done"}) + "\n").encode())
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            _AGENT["cancel"] = True


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
