
import os
import secrets as _secrets
from datetime import datetime
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse, HTMLResponse
from dotenv import load_dotenv

load_dotenv()

ADMIN_KEY = os.getenv("ADMIN_KEY")
if not ADMIN_KEY:
    raise RuntimeError("ADMIN_KEY is not set")

def _require_admin(request: Request):
    key = request.headers.get("x-admin-key", "")
    if not key or not _secrets.compare_digest(key, ADMIN_KEY):
        raise HTTPException(status_code=403, detail="Forbidden")

def _ws_ip(ws):
    xf = ws.headers.get("x-forwarded-for")
    if xf:
        return xf.split(",")[0].strip()
    if getattr(ws, "client", None) and getattr(ws.client, "host", None):
        return ws.client.host
    return "unknown"

def _ws_port(ws):
    if getattr(ws, "client", None) and getattr(ws.client, "port", None):
        return ws.client.port
    return None

def _now_iso():
    return datetime.utcnow().isoformat() + "Z"

def _entry_ip(entry):
    ip = entry.get("ip")
    if ip:
        return ip
    ws = entry.get("ws")
    return _ws_ip(ws) if ws else "unknown"

def _entry_ua(entry):
    ua = entry.get("ua")
    if ua:
        return ua
    ws = entry.get("ws")
    if ws:
        return ws.headers.get("user-agent", "unknown")
    return "unknown"

def _entry_details(entry, kind):
    ws = entry.get("ws")
    return {
        "token": entry.get("token"),
        "role": entry.get("role"),
        "kind": kind,
        "ip": _entry_ip(entry),
        "port": _ws_port(ws) if ws else None,
        "ua": _entry_ua(entry),
        "connected_at": entry.get("connected_at") or "",
    }

def init_admin_routes(app, rooms, admin_state):
    bans = admin_state.setdefault("bans", {})

    @app.get("/admin", response_class=HTMLResponse)
    async def admin_panel():
        return """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Chess Admin</title>
<style>
body{background:#0f172a;color:#e5e7eb;font-family:Arial;padding:20px}
button{padding:10px 12px;margin:6px;background:#2563eb;color:white;border:none;border-radius:8px;cursor:pointer}
button:hover{opacity:.92}
input{padding:10px;margin:6px;border-radius:8px;border:1px solid #334155;background:#0b1220;color:#e5e7eb;width:340px;max-width:95%}
pre{background:#020617;padding:12px;border-radius:10px;white-space:pre-wrap;word-break:break-word;border:1px solid #1e293b}
.row{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
.small{opacity:.8;font-size:13px;margin-top:6px}
</style>
</head>
<body>
<h2>🛠 Chess Admin Panel</h2>

<div class="row">
  <input id="key" type="password" placeholder="ADMIN KEY">
  <button onclick="rooms()">Rooms</button>
  <button onclick="details()">Details</button>
  <button onclick="broadcast()">Broadcast</button>
  <button onclick="closeRoom()">Close Room</button>
</div>

<div class="small">lol   .env/Secret Files.</div>

<pre id="out"></pre>

<script>
const out = document.getElementById("out");

function hdr(){
  return {
    "X-Admin-Key": document.getElementById("key").value,
    "Content-Type": "application/json"
  };
}

async function showResp(r){
  const text = await r.text();
  try{
    const j = JSON.parse(text);
    out.textContent = JSON.stringify(j, null, 2);
  }catch{
    out.textContent = text || ("HTTP " + r.status);
  }
}

async function rooms(){
  const r = await fetch("/admin/rooms", {headers: hdr()});
  await showResp(r);
}

async function details(){
  const r = await fetch("/admin/details", {headers: hdr()});
  await showResp(r);
}

async function broadcast(){
  const msg = prompt("Message:");
  if(!msg) return;
  const r = await fetch("/admin/broadcast", {
    method: "POST",
    headers: hdr(),
    body: JSON.stringify({message: msg})
  });
  await showResp(r);
}

async function closeRoom(){
  const room = prompt("Room ID:");
  if(!room) return;
  const r = await fetch("/admin/close", {
    method: "POST",
    headers: hdr(),
    body: JSON.stringify({room: room})
  });
  await showResp(r);
}
</script>
</body>
</html>
"""

    @app.get("/admin/rooms")
    async def list_rooms(request: Request):
        _require_admin(request)
        return JSONResponse({
            rid: {"players": len(r.get("players", [])), "viewers": len(r.get("viewers", []))}
            for rid, r in rooms.items()
        })

    @app.get("/admin/details")
    async def room_details(request: Request):
        _require_admin(request)
        data = {}
        for rid, r in rooms.items():
            players = []
            viewers = []
            for p in r.get("players", []):
                ws = p.get("ws")
                if ws:
                    players.append({
                        "ip": _ws_ip(ws),
                        "port": _ws_port(ws),
                        "ua": ws.headers.get("user-agent", "unknown"),
                        "role": p.get("role")
                    })
                else:
                    players.append({"unknown": True})
            for v in r.get("viewers", []):
                ws = v.get("ws")
                if ws:
                    viewers.append({
                        "ip": _ws_ip(ws),
                        "port": _ws_port(ws),
                        "ua": ws.headers.get("user-agent", "unknown"),
                        "role": v.get("role")
                    })
                else:
                    viewers.append({"unknown": True})
            data[rid] = {"players": players, "viewers": viewers}
        return JSONResponse(data)

    @app.post("/admin/close")
    async def close_room(request: Request):
        _require_admin(request)
        body = await request.json()
        rid = body.get("room")
        if not rid or rid not in rooms:
            raise HTTPException(status_code=404, detail="Room not found")
        entries = rooms[rid].get("players", []) + rooms[rid].get("viewers", [])
        for entry in entries:
            ws = entry.get("ws")
            if ws:
                try:
                    await ws.close()
                except:
                    pass
        rooms.pop(rid, None)
        return JSONResponse({"closed": rid})

    @app.post("/admin/broadcast")
    async def broadcast(request: Request):
        _require_admin(request)
        body = await request.json()
        msg = (body.get("message") or "").strip()
        if not msg:
            raise HTTPException(status_code=400, detail="No message provided")
        if len(msg) > 500:
            raise HTTPException(status_code=400, detail="Message too long")
        sent = 0
        for r in rooms.values():
            for entry in r.get("players", []) + r.get("viewers", []):
                ws = entry.get("ws")
                if ws:
                    try:
                        await ws.send_text(f"[ADMIN]: {msg}")
                        sent += 1
                    except:
                        pass
        return JSONResponse({"message": msg, "sent": sent})
