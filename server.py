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
        token = secrets.token_hex(8)
        await ws.send_json({"token": token})
    else:
        room["tokens"][token] = role
    if role in ("host", "client"):
        if len(room["players"]) >= 2:
            await ws.send_json({"error": "Room full"})
            role = "viewer"
        else:
            room["players"].append(ws)
            await ws.send_json({"role": role})
    else:
        room["viewers"].append(ws)
        await ws.send_json({"role": "viewer"})
    try:
        while True:
            data = await ws.receive_text()
            if '"move"' in data and role == "viewer":
                await ws.send_json({"error": "Viewers cannot move"})
                continue
            for p in room["players"] + room["viewers"]:
                if p != ws:
                    await p.send_text(data)
    except WebSocketDisconnect:
        pass
    finally:
        if ws in room["players"]:
            room["players"].remove(ws)
        elif ws in room["viewers"]:
            room["viewers"].remove(ws)
        if not room["players"] and not room["viewers"]:
            del rooms[room_id]

    import admin_commands


