import socketio
import json
import uvicorn
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from config import settings
import cv2
import numpy as np
import asyncio
import time
from pynput import mouse, keyboard
import screeninfo
from typing import Dict
 
# FastAPI app setup
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
 
# Socket.IO setup with ping configuration
sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins="*",
    ping_timeout=60,  # Wait 60s for pong response
    ping_interval=25,  # Send ping every 25s
    logger=True,
    engineio_logger=True
)
socket_app = socketio.ASGIApp(sio, other_asgi_app=app)
 
# MongoDB setup
MONGO_URI = settings.mongo_uri
DB_NAME = "EbantisV3"
COLLECTION_NAME = "Client_uuid"
client = AsyncIOMotorClient(MONGO_URI)
db = client[DB_NAME]
collection = db[COLLECTION_NAME]
 
# Globals
clients = set()
frame_queues: Dict[str, asyncio.Queue] = {}
latest_frames: Dict[str, np.ndarray] = {}
uuid_sid_map: Dict[str, str] = {}
active_sessions: Dict[str, bool] = {}  # Track intentional sessions
last_heartbeat: Dict[str, float] = {}  # Track last heartbeat time
 
# Get screen size
def get_client_screen_size():
    monitors = screeninfo.get_monitors()
    return sum([monitor.width for monitor in monitors]), max([monitor.height for monitor in monitors])
 
CLIENT_SCREEN_WIDTH, CLIENT_SCREEN_HEIGHT = get_client_screen_size()
DEBOUNCE_DELAY = 0.02
last_mouse_time = time.time()
last_key_time = time.time()
 
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
 
# Input synchronization
def send_input_sync(event_data):
    asyncio.run_coroutine_threadsafe(send_input(event_data), loop)
 
async def send_input(event_data):
    for sid in clients:
        await sio.emit('input_event', event_data, to=sid)
 
# Mouse and keyboard listeners
def on_move(x, y):
    global last_mouse_time
    if time.time() - last_mouse_time > DEBOUNCE_DELAY:
        send_input_sync({
            "type": "mouse_move",
            "x": round(x / CLIENT_SCREEN_WIDTH, 5),
            "y": round(y / CLIENT_SCREEN_HEIGHT, 5)
        })
        last_mouse_time = time.time()
 
def on_click(x, y, button, pressed):
    button_name = button.name if hasattr(button, 'name') else str(button)
    send_input_sync({
        "type": "mouse_click",
        "x": x / CLIENT_SCREEN_WIDTH,
        "y": y / CLIENT_SCREEN_HEIGHT,
        "button": button_name,
        "pressed": pressed
    })
 
def on_press(key):
    global last_key_time
    if time.time() - last_key_time > DEBOUNCE_DELAY:
        try:
            key_str = str(key).replace("'", "")
            send_input_sync({"type": "keyboard", "key": key_str, "pressed": True})
        except AttributeError:
            pass
        last_key_time = time.time()
 
def on_release(key):
    key_str = str(key).replace("'", "")
    send_input_sync({"type": "keyboard", "key": key_str, "pressed": False})
 
# Start input listeners
mouse_listener = mouse.Listener(on_move=on_move, on_click=on_click)
keyboard_listener = keyboard.Listener(on_press=on_press, on_release=on_release)
mouse_listener.start()
keyboard_listener.start()
 
# Socket.IO events
@sio.event
def connect(sid, environ, auth):
    print(f"[CONNECT] Client connected: {sid}")
    clients.add(sid)
   
    query = environ.get("QUERY_STRING", "")
    from urllib.parse import parse_qs
    uuid = parse_qs(query).get("uuid", [None])[0]
   
    if uuid:
        uuid_sid_map[uuid] = sid
        last_heartbeat[uuid] = time.time()
        print(f"[CONNECT] Registered UUID {uuid} with SID {sid}")
        print(f"[CONNECT] UUID map: {uuid_sid_map}")
   
    print(f"[CONNECT] Total connected clients: {len(clients)}")
 
@sio.event
async def disconnect(sid):
    print(f"[DISCONNECT] Client disconnected: {sid}")
    clients.discard(sid)
   
    # Find the UUID for this SID
    uuid_to_remove = None
    for uuid, mapped_sid in list(uuid_sid_map.items()):
        if mapped_sid == sid:
            uuid_to_remove = uuid
            break
   
    if not uuid_to_remove:
        print(f"[DISCONNECT] No UUID found for SID {sid}")
        return
   
    # Check if this was an intentional disconnect (stop_client was called)
    is_intentional = active_sessions.get(str(uuid_to_remove)) == False
   
    if is_intentional:
        print(f"[DISCONNECT] Expected disconnect for UUID {uuid_to_remove} (stop_client called)")
        status = "Stopped"
    else:
        print(f"[DISCONNECT] ⚠️ UNEXPECTED disconnect for UUID {uuid_to_remove}")
        status = "Disconnected"
   
    # Update database
    try:
        await collection.update_one(
            {"uuid": uuid_to_remove},
            {"$set": {"Status": status, "connection": False}}
        )
        print(f"[DISCONNECT] Updated DB: UUID {uuid_to_remove} set to {status}")
    except Exception as e:
        print(f"[DISCONNECT] Error updating DB for UUID {uuid_to_remove}: {e}")
   
    # Clean up server resources
    uuid_sid_map.pop(uuid_to_remove, None)
    active_sessions.pop(str(uuid_to_remove), None)
    last_heartbeat.pop(uuid_to_remove, None)
    latest_frames.pop(str(uuid_to_remove), None)
    frame_queues.pop(str(uuid_to_remove), None)
   
    print(f"[DISCONNECT] Cleaned up resources for UUID {uuid_to_remove}")
 
@sio.on('heartbeat')
async def handle_heartbeat(sid, data):
    """Handle heartbeat from client to keep connection alive"""
    uuid = data.get("uuid")
    if uuid:
        last_heartbeat[uuid] = time.time()
        await sio.emit('heartbeat_ack', {"timestamp": time.time()}, to=sid)
 
@sio.on('register_uuid')
async def register_uuid(sid, data):
    uuid = data.get("uuid")
    print(f"[REGISTER] Received UUID registration: {uuid}")
 
@sio.on("frame")
async def receive_frame(sid, data):
    uuid = str(data.get("uuid"))
    frame_data = data.get("frame")
   
    if not uuid or not frame_data:
        print("[FRAME] Missing frame or UUID from client")
        return
   
    # Update last heartbeat time when receiving frames
    last_heartbeat[uuid] = time.time()
   
    if uuid not in frame_queues:
        frame_queues[uuid] = asyncio.Queue(maxsize=10)
   
    if frame_queues[uuid].full():
        # Drop oldest frame instead of newest
        try:
            await frame_queues[uuid].get()
        except:
            pass
   
    try:
        await frame_queues[uuid].put((uuid, frame_data))
    except Exception as e:
        print(f"[FRAME] Error queuing frame for UUID {uuid}: {e}")
 
# Frame processor
async def process_frames():
    print("[PROCESSOR] Frame processing loop started")
    while True:
        for uuid, queue in list(frame_queues.items()):
            if not queue.empty():
                try:
                    _, data = await queue.get()
                    np_frame = np.frombuffer(data, dtype=np.uint8)
                    frame_image = cv2.imdecode(np_frame, cv2.IMREAD_COLOR)
                   
                    if frame_image is not None:
                        latest_frames[uuid] = frame_image
                        # Only log occasionally to reduce spam
                        if int(time.time()) % 5 == 0:
                            print(f"[PROCESSOR] Stored frame for UUID: {uuid}")
                    else:
                        print(f"[PROCESSOR] Failed to decode frame for UUID: {uuid}")
                except Exception as e:
                    print(f"[PROCESSOR] Error decoding frame for UUID {uuid}: {e}")
       
        await asyncio.sleep(0.01)
 
# Connection health monitor
async def monitor_connections():
    """Monitor connection health and detect stale connections"""
    print("[MONITOR] Connection health monitor started")
    while True:
        await asyncio.sleep(30)  # Check every 30 seconds
       
        current_time = time.time()
        for uuid, last_beat in list(last_heartbeat.items()):
            time_since_heartbeat = current_time - last_beat
           
            # Warn if no heartbeat for 45 seconds
            if time_since_heartbeat > 45:
                print(f"[MONITOR] ⚠️ No heartbeat from UUID {uuid} for {time_since_heartbeat:.1f}s")
           
            # Consider connection dead after 90 seconds
            if time_since_heartbeat > 90:
                print(f"[MONITOR] ⚠️ UUID {uuid} appears dead, cleaning up")
                sid = uuid_sid_map.get(uuid)
                if sid:
                    await sio.disconnect(sid)
 
@app.on_event("startup")
async def startup_event():
    print("[STARTUP] Starting background tasks...")
    asyncio.create_task(process_frames())
    asyncio.create_task(monitor_connections())
    print("[STARTUP] All background tasks started")
 
@app.websocket("/ws/stream/{uuid}")
async def websocket_stream(websocket: WebSocket, uuid: str):
    await websocket.accept()
    print(f"[WEBSOCKET] Connected for UUID: {uuid}")
   
    try:
        while True:
            # Send frame to frontend
            frame = latest_frames.get(uuid)
            if frame is not None:
                _, encoded_image = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                await websocket.send_bytes(encoded_image.tobytes())
           
            # Receive and forward input event
            try:
                msg = await asyncio.wait_for(websocket.receive_text(), timeout=0.01)
                try:
                    input_data = json.loads(msg)
                    if input_data.get("type") in ["mouse_move", "mouse_click", "keyboard"]:
                        sid = uuid_sid_map.get(uuid)
                        if sid:
                            await sio.emit("input_event", input_data, to=sid)
                        else:
                            print(f"[WEBSOCKET] No SID found for UUID {uuid}")
                except json.JSONDecodeError:
                    print("[WEBSOCKET] Invalid JSON input from WebSocket")
            except asyncio.TimeoutError:
                pass
           
            await asyncio.sleep(0.03)
           
    except WebSocketDisconnect:
        print(f"[WEBSOCKET] Disconnected for UUID: {uuid}")
    except Exception as e:
        print(f"[WEBSOCKET] Error for UUID {uuid}: {e}")
 
@app.post("/request_client/")
async def request_client(data: dict):
    requested_uuid = data.get("uuid")
    key = data.get("key")
   
    print(f"[REQUEST] Received request for UUID: {requested_uuid}")
   
    if not requested_uuid:
        raise HTTPException(status_code=400, detail="UUID is required")
   
    client_info = await collection.find_one({"uuid": requested_uuid}, {"_id": 0})
   
    if not client_info:
        raise HTTPException(status_code=404, detail="Client not found in database")
   
    local_ip = client_info.get("LocalIP")
    if not local_ip:
        raise HTTPException(status_code=404, detail="Local IP not found")
   
    print(f"[REQUEST] Found IP: {local_ip}")
   
    sid = uuid_sid_map.get(str(requested_uuid))
   
    if not sid:
        print(f"[REQUEST] ⚠️ No active SID found for UUID {requested_uuid}")
        raise HTTPException(status_code=404, detail="Client not connected")
   
    # Mark this as an active, intentional session
    active_sessions[str(requested_uuid)] = True
   
    # Update database (this will trigger MongoDB Change Stream on client side)
    await collection.update_one(
        {"uuid": requested_uuid},
        {"$set": {"Status": "Running", "connection": True}}
    )
   
    # BETTER APPROACH: Push notification via Socket.IO (client listens via on_start_client)
    # This allows client to start without polling MongoDB
    print(f"[REQUEST] Emitting 'start_client' push notification to SID: {sid}")
    await sio.emit("start_client", {
        "uuid": requested_uuid,
        "key": key
    }, to=sid)
    
    # ALSO emit legacy client_info for backward compatibility
    print(f"[REQUEST] Emitting client_info to SID: {sid}")
    await sio.emit("client_info", {
        "local_ip": local_ip,
        "uuid": requested_uuid,
        "key": key
    }, to=sid)
   
    print(f"[REQUEST] Successfully started session for UUID {requested_uuid}")
    return {"local_ip": local_ip, "status": "started"}
 
 
 
 
 
 
 
 
@app.post("/start_monitor/")
async def start_monitor(data: dict):
   
    requested_uuid = data.get("uuid")
   
    print(f"[START_MONITOR] Received request for UUID: {requested_uuid}")
   
    if not requested_uuid:
        raise HTTPException(status_code=400, detail="UUID is required")
   
    # Check if client is connected via Socket.IO
    sid = uuid_sid_map.get(str(requested_uuid))
   
    if not sid:
        print(f"[START_MONITOR] ⚠️ No active SID found for UUID {requested_uuid}")
        raise HTTPException(status_code=404, detail="Client not connected")
   
    # Mark this as an active session
    active_sessions[str(requested_uuid)] = True
   
    # OPTION 1: Push notification via Socket.IO (BEST - No MongoDB polling needed)
    # This is more efficient than waiting for client to poll MongoDB
    print(f"[START_MONITOR] Emitting 'check_live_status_start' to SID: {sid}")
    await sio.emit("check_live_status_start", {
        "uuid": requested_uuid,
        "message": "Start checking live connection status"
    }, to=sid)
   
    print(f"[START_MONITOR] Successfully triggered monitoring for UUID {requested_uuid}")
    return {
        "status": "success",
        "message": "Client notified to start monitoring",
        "uuid": requested_uuid
    }
 
 
 
 
 
 
@app.post("/stop_client/")
async def stop_client(data: dict):
    requested_uuid = data.get("uuid")
   
    print(f"[STOP] Received stop request for UUID: {requested_uuid}")
   
    if not requested_uuid:
        raise HTTPException(status_code=400, detail="UUID is required")
   
    sid = uuid_sid_map.get(str(requested_uuid))
   
    if not sid:
        print(f"[STOP] Client {requested_uuid} not connected, updating DB only")
        await collection.update_one(
            {"uuid": requested_uuid},
            {"$set": {"Status": "Stopped", "connection": False}}
        )
        active_sessions.pop(str(requested_uuid), None)
        return {"status": "Client was not connected, DB updated"}
   
    # Mark this session as intentionally stopped
    active_sessions[str(requested_uuid)] = False
   
    print(f"[STOP] Marked session {requested_uuid} for intentional disconnect")
    print(f"[STOP] Sending disconnect signal to SID {sid}")
   
    # Send disconnect signal to client
    await sio.emit("disconnect_client_info", {"reason": "stop_requested"}, to=sid)
   
    # Update database (disconnect handler will also update, but do it now too)
    await collection.update_one(
        {"uuid": requested_uuid},
        {"$set": {"Status": "Stopped", "connection": False}}
    )
   
    print(f"[STOP] Stop signal sent for UUID {requested_uuid}")
    return {"status": "Disconnect signal sent"}
 
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "connected_clients": len(clients),
        "active_sessions": len(active_sessions),
        "tracked_uuids": len(uuid_sid_map)
    }
 
def start_server():
    uvicorn.run(
        "centralized_server:socket_app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
 
if __name__ == "__main__":
    start_server()