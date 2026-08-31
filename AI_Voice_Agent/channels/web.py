"""Web channel — a local browser chat with the agent.

Serves a small chat UI on http://<host>:<port>/ so you can talk to the agent
from a browser — no phone, no external accounts. Useful to test the brain and
the lead-capture flow before connecting WhatsApp/Teams/etc.

Endpoints:
    GET  /                  -> the chat page
    POST /api/message       -> {"text": "..."} -> {"reply": "...", "lead": {...}}
    GET  /api/status        -> {"task": "...", "providers": {...}}
    GET  /healthz           -> {"ok": true}
"""

from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .base import Channel

log = logging.getLogger("channels.web")

_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI Voice Agent — Web Chat</title>
<style>
  :root{color-scheme:dark}
  body{font-family:Segoe UI,system-ui,sans-serif;background:#1e2430;color:#e6edf3;margin:0}
  .wrap{max-width:760px;margin:0 auto;padding:20px}
  h1{font-size:22px}
  .lead{background:#262e3d;border-radius:10px;padding:12px 16px;margin:14px 0;font-size:14px}
  .lead b{color:#58a6ff}
  .ch{margin-top:14px}
  .row{display:flex;gap:8px}
  .msg{margin:8px 0;padding:10px 14px;border-radius:12px;max-width:78%;white-space:pre-wrap}
  .p{background:#2ea043;align-self:flex-end;margin-left:auto}
  .a{background:#30363d}
  .who{font-size:11px;opacity:.6;margin-bottom:2px}
  #chat{display:flex;flex-direction:column;min-height:50vh}
  input{flex:1;padding:12px;border-radius:10px;border:1px solid #30363d;background:#0f1420;color:#fff}
  button{padding:12px 20px;border-radius:10px;border:0;background:#2ea043;color:#fff;cursor:pointer}
  button:disabled{opacity:.5}
  .status{color:#3fb950;font-size:13px}
</style></head><body>
<div class="wrap">
  <h1>AI Voice Agent — Web Chat</h1>
  <div class="status" id="status">Starting…</div>
  <div class="lead" id="lead">Lead: Name: — | Contact: — | Interest: —</div>
  <div id="chat"></div>
  <div class="row">
    <input id="inp" placeholder="Type a message… (or press Enter)" autofocus>
    <button id="btn">Send</button>
  </div>
</div>
<script>
const chat=document.getElementById('chat'),inp=document.getElementById('inp'),
      btn=document.getElementById('btn'),status=document.getElementById('status'),
      lead=document.getElementById('lead');
function add(who,txt){const m=document.createElement('div');m.className='msg '+who;
  m.innerHTML='<div class="who">'+(who==='p'?'You':'Agent')+'</div>'+escape(txt);
  chat.appendChild(m);chat.scrollTop=chat.scrollHeight;}
function escape(s){return s.replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}
async function send(){
  const t=inp.value.trim();if(!t)return;
  add('p',t);inp.value='';btn.disabled=true;status.textContent='Agent is thinking…';
  try{
    const r=await fetch('/api/message',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({text:t})});
    const d=await r.json();
    add('a',d.reply||'(no reply)');status.textContent='● Online';
    if(d.lead){const l=d.lead;
      lead.textContent='Lead: Name: '+(l.name||'—')+' | Contact: '+(l.phone||l.email||'—')+
        ' | Interest: '+(l.interest||'—')+
        (l.captured?'   🎯 LEAD CAPTURED':'');
    }
    if(d.lead_changes&&d.lead_changes.length)for(const c of d.lead_changes)add('a','[lead] '+c);
  }catch(e){add('a','Error: '+e);status.textContent='× offline';}
  finally{btn.disabled=false;inp.focus();}
}
btn.onclick=send;inp.onkeydown=e=>{if(e.key==='Enter')send()};
fetch('/api/status').then(r=>r.json()).then(d=>{
  status.textContent='● Online | task: '+d.task;
}).catch(()=>status.textContent='× offline');
</script></body></html>"""


class WebChannel(Channel):
    name = "web"

    def __init__(self, broker, cfg: dict | None = None, mock: bool = False):
        super().__init__(broker)
        self.cfg = cfg or {}
        self.host = self.cfg.get("host", "0.0.0.0")
        self.port = int(self.cfg.get("port", 8770))
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        from .web import _make_handler  # local import to avoid name clash
        self._server = ThreadingHTTPServer((self.host, self.port),
                                           _make_handler(self))
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        daemon=True)
        self._thread.start()
        self.running = True
        log.info("Web channel listening on http://%s:%s", self.host, self.port)

    def stop(self) -> None:
        self.running = False
        if self._server:
            self._server.shutdown()
            self._server.server_close()

    def _api_message(self, body: dict) -> dict:
        text = (body.get("text") or "").strip()
        if not text:
            return {"reply": "Please type something.", "lead": {}}
        # single "default" session for the browser
        msg = self.handle_text("web-default", text)
        return {
            "reply": msg.reply,
            "lead": msg.lead,
            "lead_changes": msg.lead_changes,
        }

    def _api_status(self) -> dict:
        ctrl = self._sessions.get("web-default")
        task = ctrl.task.name if ctrl else "? "
        return {"task": task, "online": True}


def _make_handler(channel: WebChannel):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, content_type: str, body: bytes):
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/api/status":
                self._send(200, "application/json",
                           json.dumps(channel._api_status()).encode())
            elif self.path == "/healthz":
                self._send(200, "application/json", b'{"ok":true}')
            else:
                self._send(200, "text/html; charset=utf-8", _HTML.encode())

        def do_POST(self):
            if self.path == "/api/message":
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    body = json.loads(self.rfile.read(length) or b"{}")
                    result = channel._api_message(body)
                    self._send(200, "application/json", json.dumps(result).encode())
                except Exception as e:  # pragma: no cover
                    log.exception("web message error")
                    self._send(500, "application/json",
                               json.dumps({"reply": f"Error: {e}"}).encode())
            else:
                self._send(404, "application/json", b'{"error":"not found"}')

        def log_message(self, *a):  # quiet
            pass
    return Handler
