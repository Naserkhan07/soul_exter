#!/usr/bin/env python3
"""Live browser preview of the AI Voice Agent (offline mock brain).

This is a DEMO/preview so you can see the agent working without the Qwen GPU
server. It runs the agent with the offline 'mock' provider — no Kaggle, no keys.
When you type a message it replies from the real Maqsusi task knowledge and
captures a lead, exactly like the live version will.

Usage:
    python web_preview.py            # serves on 0.0.0.0:8770
    python web_preview.py --port 8770

Open the shown URL in your browser. It is NOT the real deployment — the real
GUI is `python run.py` (a desktop window), and the real brain is Qwen on your
Kaggle GPU.
"""

from __future__ import annotations

import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from config import load_config
from main import build_controller, ROOT

PAGE = """<!doctype html>
<html><head><meta charset="utf-8">
<title>AI Voice Agent — preview</title>
<style>
 body{font-family:'Segoe UI',Arial,sans-serif;background:#0f1420;color:#e6edf3;
      display:flex;justify-content:center;padding:24px;}
 .box{max-width:760px;width:100%;}
 h1{color:#ffffff;} .sub{color:#9fb3c8;font-size:13px;}
 .chat{background:#1e2430;border-radius:12px;padding:14px;height:420px;overflow-y:auto;margin:14px 0;}
 .row{margin:8px 0;} .who{font-weight:bold;}
 .agent .who{color:#58a6ff;} .person .who{color:#3fb950;}
 .lead{background:#262e3d;border-radius:12px;padding:12px;font-size:14px;}
 .lead b{color:#e3b341;}
 input,button{font-size:15px;padding:10px;border:none;border-radius:8px;}
 input{flex:1;background:#0f1420;color:#fff;margin-right:8px;}
 button{background:#2ea043;color:#fff;cursor:pointer;}
 .inrow{display:flex;}
 .caps{color:#3fb950;font-weight:bold;}
</style></head><body><div class="box">
<h1>🎙️ AI Voice Agent — live preview</h1>
<div class="sub">Offline mock demo of the agent (real brain = Qwen on your Kaggle GPU).
Try: <i>"Hi, I'm Ravi and we need a website"</i> or <i>"नमस्ते, पोलारियन क्या है?"</i></div>
<div class="chat" id="chat"></div>
<div class="lead" id="lead">Goal: capture a lead (name, contact, interest).</div>
<div class="inrow"><input id="inp" placeholder="Type your message…" autofocus>
<button onclick="send()">Send</button></div>
</div>
<script>
const chat=document.getElementById('chat'),lead=document.getElementById('lead');
function add(who,txt){const d=document.createElement('div');d.className='row '+who;
  d.innerHTML='<span class="who">'+(who==='agent'?'Agent':'You')+':</span> '+txt;
  chat.appendChild(d);chat.scrollTop=chat.scrollHeight;}
function refreshLead(l){
  let s='Name: <b>'+(l.name||'—')+'</b> · Contact: <b>'+(l.phone||l.email||'—')+
    '</b> · Interest: <b>'+(l.interest||'—')+'</b> · ';
  if(l.captured){s+='<span class="caps">🎯 LEAD CAPTURED</span>';}
  else{s+='Completeness: '+(l.completeness*100|0)+'%';}
  lead.innerHTML=s;
}
async function send(){
  const inp=document.getElementById('inp');const t=inp.value.trim();if(!t)return;
  inp.value='';add('person',t);
  const r=await fetch('/api/message',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({text:t})}).then(x=>x.json());
  add('agent',r.reply);refreshLead(r.lead);
}
</script></body></html>
"""


CTRL = None


def _build():
    global CTRL
    if CTRL is None:
        cfg = load_config()
        ctrl = build_controller(cfg, mock=True)   # offline mock brain
        ctrl.start_call()
        CTRL = ctrl
    return CTRL


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quieter logs
        pass

    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if urlparse(self.path).path == "/healthz":
            return self._send(200, {"ok": True})
        if urlparse(self.path).path == "/api/status":
            return self._send(200, {"task": "my_business", "online": True, "mock": True})
        # fall back to the chat page
        body = PAGE.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if urlparse(self.path).path != "/api/message":
            return self._send(404, {"error": "not found"})
        length = int(self.headers.get("Content-Length", 0))
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
            text = (data.get("text") or "").strip()
        except Exception:
            return self._send(400, {"error": "bad json"})
        if not text:
            return self._send(400, {"error": "empty text"})
        ctrl = _build()
        reply = ctrl.handle_utterance(text)
        return self._send(200, {
            "reply": reply,
            "lead": {
                "name": ctrl.lead.name, "phone": ctrl.lead.phone,
                "email": ctrl.lead.email, "interest": ctrl.lead.interest,
                "captured": ctrl.lead.captured,
                "completeness": ctrl.lead.completeness,
            },
        })


def main():
    ap = argparse.ArgumentParser(description="AI Voice Agent preview server")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8770)
    args = ap.parse_args()
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Preview server listening on http://{args.host}:{args.port}")
    srv.serve_forever()


if __name__ == "__main__":
    main()
