import os
import json
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
    key = request.headers.get("x-admin-key", "") or request.headers.get("X-Admin-Key", "")
    if not key or not _secrets.compare_digest(key, ADMIN_KEY):
        raise HTTPException(status_code=403, detail="Forbidden")

def _ws_ip(ws):
    xf = ws.headers.get("x-forwarded-for")
    if xf:
        return xf.split(",")[0].strip()
    if getattr(ws, "client", None) and getattr(ws.client, "host", None):
        return ws.client.host
    return "unknown"

def _now_iso():
    return datetime.utcnow().isoformat() + "Z"

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
  <button onclick="banIp()">Ban IP</button>
  <button onclick="unbanIp()">Unban IP</button>
  <button onclick="bansList()">Bans</button>
</div>

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

async function bansList(){
  const r = await fetch("/admin/bans", {headers: hdr()});
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

async function banIp(){
  const ip = prompt("IP to ban:");
  if(!ip) return;
  const reason = prompt("Reason (optional):") || "";
  const r = await fetch("/admin/ban", {
    method: "POST",
    headers: hdr(),
    body: JSON.stringify({ip: ip, reason: reason})
  });
  await showResp(r);
}

async function unbanIp(){
  const ip = prompt("IP to unban:");
  if(!ip) return;
  const r = await fetch("/admin/unban", {
    method: "POST",
    headers: hdr(),
    body: JSON.stringify({ip: ip})
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
                        "ip": p.get("ip") or _ws_ip(ws),
                        "ua": p.get("ua") or ws.headers.get("user-agent", "unknown"),
                        "role": p.get("role"),
                        "token": p.get("token"),
                        "connected_at": p.get("connected_at") or ""
                    })
            for v in r.get("viewers", []):
                ws = v.get("ws")
                if ws:
                    viewers.append({
                        "ip": v.get("ip") or _ws_ip(ws),
                        "ua": v.get("ua") or ws.headers.get("user-agent", "unknown"),
                        "role": v.get("role"),
                        "token": v.get("token"),
                        "connected_at": v.get("connected_at") or ""
                    })
            data[rid] = {"players": players, "viewers": viewers}
        return JSONResponse(data)

    @app.get("/admin/bans")
    async def list_bans(request: Request):
        _require_admin(request)
        return JSONResponse(bans)

    @app.post("/admin/ban")
    async def ban_ip(request: Request):
        _require_admin(request)
        body = await request.json()
        ip = (body.get("ip") or "").strip()
        reason = (body.get("reason") or "").strip()
        if not ip:
            raise HTTPException(status_code=400, detail="Missing ip")
        bans[ip] = {"reason": reason, "at": _now_iso()}

        closed = 0
        for r in rooms.values():
            for entry in (r.get("players", []) + r.get("viewers", [])):
                eip = entry.get("ip") or (entry.get("ws") and _ws_ip(entry["ws"])) or "unknown"
                if eip == ip:
                    ws = entry.get("ws")
                    if ws:
                        try:
                            await ws.send_text(json.dumps({"type": "system", "message": "Banned"}))
                        except:
                            pass
                        try:
                            await ws.close(code=1008)
                            closed += 1
                        except:
                            pass
        return JSONResponse({"banned": ip, "closed": closed})

    @app.post("/admin/unban")
    async def unban_ip(request: Request):
        _require_admin(request)
        body = await request.json()
        ip = (body.get("ip") or "").strip()
        if not ip:
            raise HTTPException(status_code=400, detail="Missing ip")
        existed = ip in bans
        bans.pop(ip, None)
        return JSONResponse({"unbanned": ip, "existed": existed})

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

        payload = json.dumps({"type": "chat", "chat": f"[ADMIN]: {msg}", "message": f"[ADMIN]: {msg}"})
        sent = 0
        for r in rooms.values():
            for entry in r.get("players", []) + r.get("viewers", []):
                ws = entry.get("ws")
                if ws:
                    try:
                        await ws.send_text(payload)
                        sent += 1
                    except:
                        pass
        return JSONResponse({"sent": sent, "message": msg})
