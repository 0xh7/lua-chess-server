from fastapi import FastAPI, WebSocket
import chess

app = FastAPI()
rooms = {}

@app.websocket("/play/{room_id}")
async def play(websocket: WebSocket, room_id: str):
    await websocket.accept()
    if room_id not in rooms:
        rooms[room_id] = {"players": []}
    rooms[room_id]["players"].append(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            for p in rooms[room_id]["players"]:
                if p != websocket:
                    await p.send_text(data)
    except:
        rooms[room_id]["players"].remove(websocket)
