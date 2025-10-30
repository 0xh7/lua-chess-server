from fastapi import FastAPI, WebSocket

app = FastAPI()
players = []

@app.websocket("/play")
async def play(websocket: WebSocket):
    await websocket.accept()
    players.append(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            for p in players:
                if p != websocket:
                    await p.send_text(data)
    except:
        players.remove(websocket)
