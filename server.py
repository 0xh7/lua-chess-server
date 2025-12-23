from datetime import datetime
import json
import secrets
import time
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
    bans = admin_state["bans"]
    rec = bans.get(ip)
    if not rec:
        return False
    until = rec.get("until", 0)
    if until and time.time() > until:
        bans.pop(ip, None)
        return False
    return True

def _is_locked(room_id: str) -> bool:
    locks = admin_state["room_locks"]
    until = locks.get(room_id)
    if not until:
        return False
    if time.time() > until:
        locks.pop(room_id, None)
        return False
    return True

def _room_entries(room: dict):
    return room.get("players", []) + room.get("viewers", [])

def _token_role_map(room: dict):
    return {e.get("token"): e.get("role") for e in _room_entries(room) if e.get("token")}

async def _send_json(ws: WebSocket, payload: dict):
    await ws.send_text(json.dumps(payload, ensure_ascii=False))

@app.websocket("/play")
@app.websocket("/play/{room_id}")
async def play(ws: WebSocket, room_id: str = "default", role: str = Query(None), token: str = Query(None)):
    ip = _client_ip(ws)
    ua = ws.headers.get("user-agent", "unknown")

    await ws.accept()

    if _is_locked(room_id):
        await _send_json(ws, {"type": "error", "error": "Room closed"})
        await ws.close(code=1008)
        return

    if _is_banned(ip):
        await _send_json(ws, {"type": "error", "error": "Banned"})
        await ws.close(code=1008)
        return

    role = (role or "viewer").lower()
    if role not in ("host", "client", "viewer"):
        role = "viewer"

    if not token:
        token = secrets.token_hex(16)

    room = rooms.setdefault(room_id, {"players": [], "viewers": []})
    connected_at = datetime.utcnow().isoformat() + "Z"

    entry = {"ws": ws, "token": token, "role": role, "ip": ip, "ua": ua, "connected_at": connected_at}

    if role in ("host", "client"):
        if len(room["players"]) >= 2:
            entry["role"] = "viewer"
            room["viewers"].append(entry)
            await _send_json(ws, {"type": "hello", "room": room_id, "role": "viewer", "token": token})
        else:
            room["players"].append(entry)
            await _send_json(ws, {"type": "hello", "room": room_id, "role": role, "token": token})
    else:
        entry["role"] = "viewer"
        room["viewers"].append(entry)
        await _send_json(ws, {"type": "hello", "room": room_id, "role": "viewer", "token": token})

    try:
        while True:
            if _is_locked(room_id):
                await _send_json(ws, {"type": "error", "error": "Room closed"})
                await ws.close(code=1008)
                return

            if _is_banned(ip):
                await _send_json(ws, {"type": "error", "error": "Banned"})
                await ws.close(code=1008)
                return

            raw = await ws.receive_text()
            if not raw:
                continue

            if len(raw) > 10000:
                await _send_json(ws, {"type": "error", "error": "Message too large"})
                continue

            try:
                payload = json.loads(raw)
                if not isinstance(payload, dict):
                    payload = {"type": "raw", "raw": raw}
            except Exception:
                payload = {"type": "raw", "raw": raw}

            msg_type = (payload.get("type") or "").lower()
            role_map = _token_role_map(room)
            sender_role = role_map.get(token, entry.get("role"))

            if msg_type == "move":
                if sender_role not in ("host", "client"):
                    await _send_json(ws, {"type": "error", "error": "Not authorized to move"})
                    continue
                uci = payload.get("uci") or payload.get("move")
                if not uci:
                    await _send_json(ws, {"type": "error", "error": "Missing uci"})
                    continue
                out = {"type": "move", "uci": str(uci), "from_token": token, "from_role": sender_role}
            elif msg_type == "chat":
                msg = payload.get("message")
                if msg is None:
                    msg = payload.get("chat")
                if msg is None:
                    msg = payload.get("text")
                msg = "" if msg is None else str(msg)
                msg = msg.strip()
                if not msg:
                    continue
                if len(msg) > 800:
                    await _send_json(ws, {"type": "error", "error": "Message too long"})
                    continue
                out = {"type": "chat", "message": msg, "from_token": token, "from_role": sender_role}
            else:
                out = {"type": "raw", "raw": raw, "from_token": token, "from_role": sender_role}

            targets = [e["ws"] for e in _room_entries(room) if e.get("ws") is not ws]
            for t in targets:
                try:
                    await _send_json(t, out)
                except Exception:
                    pass

    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        room["players"] = [e for e in room["players"] if e.get("ws") is not ws]
        room["viewers"] = [e for e in room["viewers"] if e.get("ws") is not ws]
        if not room["players"] and not room["viewers"]:
            rooms.pop(room_id, None)

admin_commands.init_admin_routes(app, rooms, admin_state)
