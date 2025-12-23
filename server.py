from datetime import datetime
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
import secrets
import admin_commands

app = FastAPI()
rooms = {}
admin_state = {"bans": {}}

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

@app.websocket("/play")
@app.websocket("/play/{room_id}")
async def play(ws: WebSocket, room_id: str = "default", role: str = Query(None), token: str = Query(None)):
    ip = _client_ip(ws)
    ua = ws.headers.get("user-agent", "unknown")
    if ip in admin_state["bans"]:
        await ws.accept()
        await ws.send_json({"error": "Banned"})
        await ws.close(code=1008)
        return
    await ws.accept()
    role = (role or "viewer").lower()

    room = rooms.setdefault(room_id, {"players": [], "viewers": [], "tokens": {}})
    connected_at = datetime.utcnow().isoformat() + "Z"

    if not token:
        token = secrets.token_hex(16)
        room["tokens"][token] = "viewer"
        await ws.send_json({"token": token})
    else:
        room["tokens"][token] = role

    entry = {"ws": ws, "token": token, "role": role, "ip": ip, "ua": ua, "connected_at": connected_at}
    if role in ("host", "client"):
        if len(room["players"]) >= 2:
            await ws.send_json({"error": "Room full"})
            role = "viewer"
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
            data = await ws.receive_text()
            valid_tokens = {entry["token"]: entry["role"] for entry in (room["players"] + room["viewers"])}

            if token not in valid_tokens:
                await ws.send_json({"error": "Invalid token"})
                continue

            sender_role = valid_tokens[token]
            if '"move"' in data and sender_role not in ("host", "client"):
                await ws.send_json({"error": "Not authorized to move"})
                continue

            targets = [entry["ws"] for entry in (room["players"] + room["viewers"]) if entry["ws"] is not ws]
            for p in targets:
                await p.send_text(data)

    except WebSocketDisconnect:
        pass
    finally:
        room["players"] = [e for e in room["players"] if e.get("ws") is not ws]
        room["viewers"] = [e for e in room["viewers"] if e.get("ws") is not ws]
        if not room["players"] and not room["viewers"]:
            rooms.pop(room_id, None)

def _client_ip(ws):
    xf = ws.headers.get("x-forwarded-for")
    if xf:
        return xf.split(",")[0].strip()
    if getattr(ws, "client", None) and getattr(ws.client, "host", None):
        return ws.client.host
    return "unknown"

admin_commands.init_admin_routes(app, rooms, admin_state)



