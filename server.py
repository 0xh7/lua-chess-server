# server.py
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
import secrets

app = FastAPI()
rooms = {}

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def read_root():
    return {"message": "Lua Chess Server is running securely"}

@app.websocket("/play")
@app.websocket("/play/{room_id}")
async def play(ws: WebSocket, room_id: str = "default", role: str = Query(None), token: str = Query(None)):
    await ws.accept()
    role = (role or "viewer").lower()
    room = rooms.setdefault(room_id, {"players": [], "viewers": [], "tokens": {}})
    if not token:
        token = secrets.token_hex(16)
        room["tokens"][token] = "viewer"
        await ws.send_json({"token": token})
    else:
        room["tokens"][token] = role
    if role in ("host", "client"):
        if len(room["players"]) >= 2:
            await ws.send_json({"error": "Room full"})
            role = "viewer"
        else:
            room["players"].append({"ws": ws, "token": token, "role": role})
            await ws.send_json({"role": role})
    else:
        room["viewers"].append({"ws": ws, "token": token, "role": "viewer"})
        await ws.send_json({"role": "viewer"})
    try:
        while True:
            data = await ws.receive_text()
            valid_tokens = {entry["token"]: entry["role"] for entry in room["players"] + room["viewers"]}
            if token not in valid_tokens:
                await ws.send_json({"error": "Invalid token"})
                continue
            sender_role = valid_tokens[token]
            if '"move"' in data and sender_role not in ("host", "client"):
                await ws.send_json({"error": "Not authorized to move"})
                continue
            targets = [entry["ws"] for entry in room["players"] + room["viewers"] if entry["ws"] is not ws]
            for p in targets:
                await p.send_text(data)
    except WebSocketDisconnect:
        pass
    finally:
        room_players_ws = [entry["ws"] for entry in room["players"]]
        room_viewers_ws = [entry["ws"] for entry in room["viewers"]]
        if ws in room_players_ws:
            idx = room_players_ws.index(ws)
            room["players"].pop(idx)
        elif ws in room_viewers_ws:
            idx = room_viewers_ws.index(ws)
            room["viewers"].pop(idx)
        if not room["players"] and not room["viewers"]:
            del rooms[room_id]

@app.on_event("startup")
async def startup():
    import admin_commands
    admin_commands.register_admin(app, rooms)

