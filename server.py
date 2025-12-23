from datetime import datetime
import asyncio
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

async def _safe_close(ws: WebSocket, code: int = 1008):
    try:
        await ws.close(code=code)
    except Exception:
        pass

def _room_entry_remove(room_id: str, ws: WebSocket):
    room = rooms.get(room_id)
    if not room:
        return
    room["players"] = [e for e in room.get("players", []) if e.get("ws") is not ws]
    room["viewers"] = [e for e in room.get("viewers", []) if e.get("ws") is not ws]
    if not room["players"] and not room["viewers"]:
        rooms.pop(room_id, None)

@app.websocket("/play")
@app.websocket("/play/{room_id}")
async def play(
    ws: WebSocket,
    room_id: str = "default",
    role: str = Query(None),
    token: str = Query(None),
):
    ip = _client_ip(ws)
    ua = ws.headers.get("user-agent", "unknown")

    await ws.accept()

    if _is_locked(room_id):
        await ws.send_text(json.dumps({"type": "system", "event": "room_closed"}, ensure_ascii=False))
        await _safe_close(ws, 1008)
        return

    if _is_banned(ip):
        await ws.send_text(json.dumps({"type": "system", "event": "banned"}, ensure_ascii=False))
        await _safe_close(ws, 1008)
        return

    role = (role or "viewer").lower()
    if role not in ("host", "client", "viewer"):
        role = "viewer"

    room = rooms.setdefault(room_id, {"players": [], "viewers": []})
    connected_at = datetime.utcnow().isoformat() + "Z"

    if not token:
        token = secrets.token_hex(16)

    entry = {
        "ws": ws,
        "token": token,
        "role": role,
        "ip": ip,
        "ua": ua,
        "connected_at": connected_at,
    }

    if role in ("host", "client"):
        if len(room["players"]) >= 2:
            entry["role"] = "viewer"
            room["viewers"].append(entry)
            role = "viewer"
        else:
            room["players"].append(entry)
    else:
        entry["role"] = "viewer"
        room["viewers"].append(entry)
        role = "viewer"

    await ws.send_text(json.dumps({"type": "hello", "room": room_id, "role": role, "token": token}, ensure_ascii=False))

    async def guard():
        while True:
            await asyncio.sleep(0.7)
            if _is_locked(room_id):
                try:
                    await ws.send_text(json.dumps({"type": "system", "event": "room_closed"}, ensure_ascii=False))
                except Exception:
                    pass
                await _safe_close(ws, 1008)
                break
            if _is_banned(ip):
                try:
                    await ws.send_text(json.dumps({"type": "system", "event": "banned"}, ensure_ascii=False))
                except Exception:
                    pass
                await _safe_close(ws, 1008)
                break

    guard_task = asyncio.create_task(guard())

    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except Exception:
                continue

            mtype = (msg.get("type") or "").lower()

            if mtype == "move":
                if role not in ("host", "client"):
                    await ws.send_text(json.dumps({"type": "error", "error": "not_allowed"}, ensure_ascii=False))
                    continue
                uci = msg.get("uci") or msg.get("move")
                if not uci:
                    continue
                out = {"type": "move", "uci": str(uci), "from": role}

            elif mtype == "chat":
                text = msg.get("message") or msg.get("chat") or msg.get("text")
                if text is None:
                    continue
                text = str(text).strip()
                if not text:
                    continue
                if len(text) > 500:
                    text = text[:500]
                out = {"type": "chat", "message": text, "from": role}

            else:
                continue

            payload = json.dumps(out, ensure_ascii=False)
            targets = (room.get("players", []) + room.get("viewers", []))
            for e in targets:
                tws = e.get("ws")
                if not tws or tws is ws:
                    continue
                try:
                    await tws.send_text(payload)
                except Exception:
                    pass

    except WebSocketDisconnect:
        pass
    finally:
        guard_task.cancel()
        _room_entry_remove(room_id, ws)

admin_commands.init_admin_routes(app, rooms, admin_state)

