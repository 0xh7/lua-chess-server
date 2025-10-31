from fastapi import FastAPI, WebSocket, Query
from fastapi.middleware.cors import CORSMiddleware
import sys

sys.path.append("/etc/secrets")
try:
    import admin_commands
except:
    pass

app = FastAPI()
rooms = {}

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.websocket("/play")
@app.websocket("/play/{room_id}")
async def play(ws: WebSocket, room_id: str = "default", role: str = Query(None)):
    await ws.accept()
    role = (role or "viewer").lower()
    room = rooms.setdefault(room_id, {"players": [], "viewers": []})
    if role in ("host", "client") and len(room["players"]) >= 2:
        role = "viewer"
    (room["players"] if role in ("host", "client") else room["viewers"]).append(ws)
    try:
        while True:
            data = await ws.receive_text()
            for p in room["players"] + room["viewers"]:
                if p != ws:
                    await p.send_text(data)
    except:
        pass
    finally:
        if ws in room["players"]:
            room["players"].remove(ws)
        elif ws in room["viewers"]:
            room["viewers"].remove(ws)
        if not room["players"] and not room["viewers"]:
            del rooms[room_id]


