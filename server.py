from fastapi import FastAPI, WebSocket

app = FastAPI()
rooms = {}

@app.websocket("/play/{room_id}")
async def play(websocket: WebSocket, room_id: str):
    await websocket.accept()
    if room_id not in rooms:
        rooms[room_id] = []
    rooms[room_id].append(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            for p in rooms[room_id]:
                if p != websocket:
                    await p.send_text(data)
    except:
        rooms[room_id].remove(websocket)
        if not rooms[room_id]:
            del rooms[room_id]
