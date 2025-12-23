# admin_commands.py
import os
import time
import json
import secrets as _secrets
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse, HTMLResponse
from dotenv import load_dotenv

load_dotenv()

def _read_secret_file(path: str) -> str | None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            v = f.read().strip()
            return v or None
    except Exception:
        return None

ADMIN_KEY = os.getenv("ADMIN_KEY") or _read_secret_file("/etc/secrets/ADMIN_KEY") or _read_secret_file("./ADMIN_KEY")
if not ADMIN_KEY:
    raise RuntimeError("ADMIN_KEY is not set")

def _require_admin(request: Request):
    key = request.headers.get("x-admin-key", "")
    if not key or not _secrets.compare_digest(key, ADMIN_KEY):
        raise HTTPException(status_code=403, detail="Forbidden")

def init_admin_routes(app, rooms, admin_state):
    bans = admin_state.setdefault("bans", {})
    room_locks = admin_state.setdefault("room_locks", {})

    def _ban_is_active(ip: str) -> bool:
        rec = bans.get(ip)
        if not rec:
            return False
        until = rec.get("until", 0)
        if until and time.time() > until:
            bans.pop(ip, None)
            return False
        return True

    def _find_ip_by_token(token: str) -> str | None:
        for r in rooms.values():
            for e in r.get("players", []) + r.get("viewers", []):
                if e.get("token") == token:
                    return e.get("ip")
        return None

    async def _kick_ip(ip: str) -> int:
        kicked = 0
        empty_rooms = []
        for rid, r in rooms.items():
            remaining_players = []
            remaining_viewers = []
            for e in r.get("players", []):
                if e.get("ip") == ip:
                    ws = e.get("ws")
                    if ws:
                        try:
                            await ws.close(code=1008)
                        except Exception:
                            pass
                    kicked += 1
                else:
                    remaining_players.append(e)
            for e in r.get("viewers", []):
                if e.get("ip") == ip:
                    ws = e.get("ws")
                    if ws:
                        try:
                            await ws.close(code=1008)
                        except Exception:
                            pass
                    kicked += 1
                else:
                    remaining_viewers.append(e)
            r["players"] = remaining_players
            r["viewers"] = remaining_viewers
            if not r["players"] and not r["viewers"]:
                empty_rooms.append(rid)
        for rid in empty_rooms:
            rooms.pop(rid, None)
        return kicked

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
input{padding:10px;margin:6px;border-radius:8px;border:1px solid #334155;background:#0b1220;color:#e5e7eb;width:360px;max-width:95%}
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
  <button onclick="banIp()">Ban IP</button>
  <button onclick="unbanIp()">Unban IP</button>
  <button onclick="bans()">Bans</button>
</div>

<div class="small">Use ADMIN_KEY from env/Render secrets.</div>

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
  await showResp(await fetch("/admin/rooms", {headers: hdr()}));
}

async function details(){
  await showResp(await fetch("/admin/details", {headers: hdr()}));
}

async function bans(){
  await showResp(await fetch("/admin/bans", {headers: hdr()}));
}

async function broadcast(){
  const msg = prompt("Message:");
  if(!msg) return;
  await showResp(await fetch("/admin/broadcast", {
    method: "POST",
    headers: hdr(),
    body: JSON.stringify({message: msg})
  }));
}

async function closeRoom(){
  const room = prompt("Room ID:");
  if(!room) return;
  const secs = prompt("Lock seconds (default 300):");
  const lock_seconds = secs ? parseInt(secs,10) : 300;
  await showResp(await fetch("/admin/close", {
    method: "POST",
    headers: hdr(),
    body: JSON.stringify({room: room, lock_seconds})
  }));
}

async function banIp(){
  const ip = prompt("IP (or leave empty to ban by token):");
  let payload = {};
  if(ip){
    payload.ip = ip.trim();
  }else{
    const token = prompt("Token:");
    if(!token) return;
    payload.token = token.trim();
  }
  const secs = prompt("Ban seconds (0 = permanent):");
  payload.seconds = secs ? parseInt(secs,10) : 0;
  await showResp(await fetch("/admin/ban", {
    method: "POST",
    headers: hdr(),
    body: JSON.stringify(payload)
  }));
}

async function unbanIp(){
  const ip = prompt("IP:");
  if(!ip) return;
  await showResp(await fetch("/admin/unban", {
    method: "POST",
    headers: hdr(),
    body: JSON.stringify({ip: ip.trim()})
  }));
}
</script>
</body>
</html>
"""

    @app.get("/admin/rooms")
    async def list_rooms(request: Request):
        _require_admin(request)
        now = time.time()
        return JSONResponse({
            rid: {
                "players": len(r.get("players", [])),
                "viewers": len(r.get("viewers", [])),
                "locked": bool(room_locks.get(rid, 0) > now)
            }
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
                players.append({
                    "token": p.get("token"),
                    "ip": p.get("ip"),
                    "ua": p.get("ua"),
                    "role": p.get("role"),
                    "connected_at": p.get("connected_at")
                })
            for v in r.get("viewers", []):
                viewers.append({
                    "token": v.get("token"),
                    "ip": v.get("ip"),
                    "ua": v.get("ua"),
                    "role": v.get("role"),
                    "connected_at": v.get("connected_at")
                })
            data[rid] = {"players": players, "viewers": viewers}
        return JSONResponse(data)

    @app.get("/admin/bans")
    async def list_bans(request: Request):
        _require_admin(request)
        now = time.time()
        out = {}
        for ip, rec in list(bans.items()):
            until = rec.get("until", 0)
            if until and now > until:
                bans.pop(ip, None)
                continue
            out[ip] = {"until": until, "seconds_left": int(until - now) if until else 0}
        return JSONResponse(out)

    @app.post("/admin/broadcast")
    async def broadcast(request: Request):
        _require_admin(request)
        body = await request.json()
        msg = (body.get("message") or "").strip()
        if not msg:
            raise HTTPException(status_code=400, detail="No message provided")
        if len(msg) > 500:
            raise HTTPException(status_code=400, detail="Message too long")

        payload = json.dumps({"type": "chat", "message": msg, "from": "admin"})
        sent = 0
        for r in rooms.values():
            for e in r.get("players", []) + r.get("viewers", []):
                ws = e.get("ws")
                if ws:
                    try:
                        await ws.send_text(payload)
                        sent += 1
                    except Exception:
                        pass
        return JSONResponse({"sent": sent})

    @app.post("/admin/close")
    async def close_room(request: Request):
        _require_admin(request)
        body = await request.json()
        rid = body.get("room")
        lock_seconds = int(body.get("lock_seconds") or 300)
        if not rid or rid not in rooms:
            raise HTTPException(status_code=404, detail="Room not found")

        entries = rooms[rid].get("players", []) + rooms[rid].get("viewers", [])
        for e in entries:
            ws = e.get("ws")
            if ws:
                try:
                    await ws.close(code=1001)
                except Exception:
                    pass

        rooms.pop(rid, None)
        if lock_seconds > 0:
            room_locks[rid] = time.time() + lock_seconds

        return JSONResponse({"closed": rid, "locked_seconds": lock_seconds})

    @app.post("/admin/ban")
    async def ban(request: Request):
        _require_admin(request)
        body = await request.json()
        ip = (body.get("ip") or "").strip()
        token = (body.get("token") or "").strip()
        seconds = int(body.get("seconds") or 0)

        if not ip and token:
            ip = _find_ip_by_token(token) or ""
        if not ip:
            raise HTTPException(status_code=400, detail="Provide ip or token")

        until = time.time() + seconds if seconds > 0 else 0
        bans[ip] = {"until": until}

        kicked = await _kick_ip(ip)
        return JSONResponse({"banned": ip, "kicked": kicked, "seconds": seconds})

    @app.post("/admin/unban")
    async def unban(request: Request):
        _require_admin(request)
        body = await request.json()
        ip = (body.get("ip") or "").strip()
        if not ip:
            raise HTTPException(status_code=400, detail="Provide ip")
        bans.pop(ip, None)
        return JSONResponse({"unbanned": ip})
