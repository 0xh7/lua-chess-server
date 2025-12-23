from datetime import datetime
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
import secrets
import admin_commands

app = FastAPI()
rooms = {}
admin_state = {"bans": set()}

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

def _client_ip(ws):
    xf = ws.headers.get("x-forwarded-for")
    if xf:
        return xf.split(",")[0].strip()
    if ws.client and ws.client.host:
        return ws.client.host
    return "unknown"

@app.websocket("/play")
@app.websocket("/play/{room_id}")
async def play(ws: WebSocket, room_id: str = "default", role: str = Query(None), token: str = Query(None)):
    ip = _client_ip(ws)

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

    entry = {
        "ws": ws,
        "token": token,
        "role": role,
        "ip": ip,
        "ua": ws.headers.get("user-agent", "unknown"),
        "connected_at": connected_at
    }

    if role in ("host", "client"):
        if len(room["players"]) >= 2:
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
            valid = {e["token"]: e["role"] for e in room["players"] + room["viewers"]}

            if token not in valid:
                continue

            if '"move"' in data and valid[token] not in ("host", "client"):
                continue

            for e in room["players"] + room["viewers"]:
                if e["ws"] is not ws:
                    await e["ws"].send_text(data)

    except WebSocketDisconnect:
        pass
    finally:
        room["players"] = [e for e in room["players"] if e["ws"] is not ws]
        room["viewers"] = [e for e in room["viewers"] if e["ws"] is not ws]
        if not room["players"] and not room["viewers"]:
            rooms.pop(room_id, None)

admin_commands.init_admin_routes(app, rooms, admin_state)
