#
# websocket_manager.py
#
import json
from typing import Dict, List
from fastapi import WebSocket, WebSocketDisconnect

class ConnectionManager:
    """Manages active WebSocket connections."""
    def __init__(self):
        # Stores active connections by a "channel" or "room" ID
        # e.g., "provider-doctor@example.com" or "insurer-queue"
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, channel: str, websocket: WebSocket):
        """Accept and store a new connection."""
        await websocket.accept()
        if channel not in self.active_connections:
            self.active_connections[channel] = []
        self.active_connections[channel].append(websocket)
        print(f"Connection added to channel: {channel}")

    def disconnect(self, channel: str, websocket: WebSocket):
        """Remove a connection."""
        if channel in self.active_connections:
            try:
                self.active_connections[channel].remove(websocket)
                print(f"Connection removed from channel: {channel}")
            except ValueError:
                pass # Already removed

    async def broadcast(self, channel: str, data: dict):
        """Send a JSON message to all clients in a specific channel."""
        if channel in self.active_connections:
            print(f"Broadcasting to channel: {channel}")
            
            # Convert data to JSON string for sending
            # Use default=str to handle Decimals, datetimes, etc.
            message = json.dumps(data, default=str) 
            
            # Send to all clients in the list
            # We iterate over a copy in case disconnect() modifies the list
            for connection in self.active_connections[channel][:]:
                try:
                    await connection.send_text(message)
                except Exception as e:
                    print(f"Error sending to a websocket: {e}")
                    # This connection is dead, remove it
                    self.disconnect(channel, connection)
                    pass

# Create a single, global instance to be imported by main.py
manager = ConnectionManager()