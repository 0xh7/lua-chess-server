
from datetime import datetime
import time
import secrets
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
import admin_commands

app = FastAPI()
rooms = {}
admin_state = {"bans": {}, "room_locks": {}}

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def read_root():
    return {"message": "Chess Server is running securely"}

def _client_ip(ws: WebSocket) -> str:
    xf = ws.headers.get("x-forwarded-for")
    if xf:
        return xf.split(",")[0].strip()
    if getattr(ws, "client", None) and getattr(ws.client, "host", None):
        return ws.client.host
    return "unknown"

def _is_banned(ip: str) -> bool:
    bans = admin_state.setdefault("bans", {})
    rec = bans.get(ip)
    if not rec:
        return False
    until = rec.get("until", 0)
    if until and time.time() > until:
        bans.pop(ip, None)
        return False
    return True

def _is_locked(room_id: str) -> bool:
    locks = admin_state.setdefault("room_locks", {})
    until = locks.get(room_id)
    if not until:
        return False
    if time.time() > until:
        locks.pop(room_id, None)
        return False
    return True

@app.websocket("/play")
@app.websocket("/play/{room_id}")
async def play(ws: WebSocket, room_id: str = "default", role: str = Query(None), token: str = Query(None)):
    ip = _client_ip(ws)
    ua = ws.headers.get("user-agent", "unknown")

    await ws.accept()

    if _is_locked(room_id):
        await ws.send_json({"error": "Room closed"})
        await ws.close(code=1008)
        return

    if _is_banned(ip):
        await ws.send_json({"error": "Banned"})
        await ws.close(code=1008)
        return

    role = (role or "viewer").lower()
    room = rooms.setdefault(room_id, {"players": [], "viewers": []})
    connected_at = datetime.utcnow().isoformat() + "Z"

    if not token:
        token = secrets.token_hex(16)
        await ws.send_json({"token": token})

    entry = {"ws": ws, "token": token, "role": role, "ip": ip, "ua": ua, "connected_at": connected_at}

    if role in ("host", "client"):
        if len(room["players"]) >= 2:
            await ws.send_json({"error": "Room full"})
            entry["role"] = "viewer"
            room["viewers"].append(entry)
            await ws.send_json({"role": "viewer"})
        else:
            room["players"].append(entry)
            await ws.send_json({"role": role})
    else:
        entry["role"] = "viewer"
        room["viewers"].append(entry)
        await ws.send_json({"role": "viewer"})

    try:
        while True:
            if _is_banned(ip):
                await ws.send_json({"error": "Banned"})
                await ws.close(code=1008)
                return

            data = await ws.receive_text()

            valid_tokens = {e["token"]: e["role"] for e in (room["players"] + room["viewers"])}
            if token not in valid_tokens:
                await ws.send_json({"error": "Invalid token"})
                continue

            sender_role = valid_tokens[token]
            if '"move"' in data and sender_role not in ("host", "client"):
                await ws.send_json({"error": "Not authorized to move"})
                continue

            targets = [e["ws"] for e in (room["players"] + room["viewers"]) if e["ws"] is not ws]
            for p in targets:
                try:
                    await p.send_text(data)
                except Exception:
                    pass

    except WebSocketDisconnect:
        pass
    finally:
        room["players"] = [e for e in room["players"] if e.get("ws") is not ws]
        room["viewers"] = [e for e in room["viewers"] if e.get("ws") is not ws]
        if not room["players"] and not room["viewers"]:
            rooms.pop(room_id, None)

admin_commands.init_admin_routes(app, rooms, admin_state)
