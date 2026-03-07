import asyncio
import websockets
import json
import logging
import hashlib
import secrets
import time
import os
from typing import Dict, Optional
from dataclasses import dataclass
from http import HTTPStatus
from urllib.parse import parse_qs

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CLIENT_TYPE_ESP32 = 1
CLIENT_TYPE_USER = 2
CLIENT_TYPE_ADMIN = 3

CMD_VERIFY = 0x01
CMD_REFUSE = 0x02
CMD_BUSY = 0x03
CMD_RX = 0x11
CMD_RX_STOP = 0x12
CMD_PTT_ON = 0x15
CMD_PTT_OFF = 0x16
CMD_PCM = 0x51
CMD_ONLINE = 0x1D

@dataclass
class Client:
    client_id: str
    client_type: int
    client_name: str
    passkey: str
    activated: bool = False
    can_tx: bool = True
    can_aprs: bool = False
    verify_random: Optional[bytes] = None

class IntegratedServer:
    def __init__(self, config_file: str = "config.json"):
        with open(config_file, 'r', encoding='utf-8') as f:
            self.config = json.load(f)
        
        self.ws_host = self.config['websocket']['host']
        self.ws_port = self.config['websocket']['port']
        self.api_port = self.config.get('api', {}).get('port', 8080)
        
        self.clients: Dict[websockets.WebSocketServerProtocol, Client] = {}
        self.client_registry: Dict[str, Client] = {}
        
        self.cor_status = False
        self.ptt_active = False
        
        self.config_file = config_file
        self._load_clients()
    
    def _load_clients(self):
        for client_conf in self.config.get('clients', []):
            client = Client(
                client_id=client_conf['client_id'],
                client_type=client_conf.get('client_type', CLIENT_TYPE_USER),
                client_name=client_conf.get('client_name', client_conf['client_id']),
                passkey=client_conf['passkey'],
                can_tx=client_conf.get('can_tx', True),
                can_aprs=client_conf.get('can_aprs', False)
            )
            self.client_registry[client.client_id] = client
    
    def _save_config(self):
        with open(self.config_file, 'w', encoding='utf-8') as f:
            json.dump(self.config, f, indent=2, ensure_ascii=False)
    
    def _generate_verify_bytes(self) -> bytes:
        return secrets.token_bytes(16)
    
    def _compute_md5(self, data: str) -> bytes:
        return hashlib.md5(data.encode()).digest()
    
    async def broadcast_binary(self, data: bytes):
        for ws, client in self.clients.items():
            try:
                await ws.send(data)
            except:
                pass
    
    async def broadcast_message(self, message: dict):
        message_str = json.dumps(message)
        for ws in self.clients.keys():
            try:
                await ws.send(message_str)
            except:
                pass
    
    async def handle_ws_client(self, websocket, path):
        client = None
        verify_stage = 0
        
        try:
            async for message in websocket:
                if verify_stage == 0:
                    if isinstance(message, bytes):
                        client_id = message.decode('utf-8', errors='ignore')
                        client = self.client_registry.get(client_id)
                        
                        if not client:
                            await websocket.send(bytes([CMD_REFUSE]))
                            break
                        if client.activated:
                            await websocket.send(bytes([CMD_BUSY]))
                            break
                        
                        verify_bytes = self._generate_verify_bytes()
                        client.verify_random = verify_bytes
                        await websocket.send(bytes([CMD_VERIFY]) + verify_bytes)
                        verify_stage = 1
                        
                elif verify_stage == 1:
                    if isinstance(message, bytes) and len(message) == 16:
                        data = client.client_id + client.verify_random.hex() + client.passkey
                        expected = self._compute_md5(data)
                        
                        if message == expected:
                            client.activated = True
                            self.clients[websocket] = client
                            await websocket.send(bytes([CMD_ONLINE]))
                            verify_stage = 2
                        else:
                            await websocket.send(bytes([CMD_REFUSE]))
                            break
                
                elif verify_stage == 2:
                    await self.handle_ws_message(websocket, client, message)
                    
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            if client:
                client.activated = False
            self.clients.pop(websocket, None)
    
    async def handle_ws_message(self, websocket, client: Client, message):
        if isinstance(message, str) and message.startswith('{'):
            data = json.loads(message)
            msg_type = data.get('type')
            
            if msg_type == 'ptt_press' and not self.ptt_active and client.can_tx:
                self.ptt_active = True
                await self.broadcast_binary(bytes([CMD_PTT_ON]))
                await self.broadcast_message({'type': 'ptt_status', 'active': True})
            
            elif msg_type == 'ptt_release' and self.ptt_active:
                self.ptt_active = False
                await self.broadcast_binary(bytes([CMD_PTT_OFF]))
                await self.broadcast_message({'type': 'ptt_status', 'active': False})
    
    async def handle_api_request(self, reader, writer):
        try:
            request_line = await reader.readline()
            if not request_line:
                writer.close()
                return
            
            request = request_line.decode().strip()
            parts = request.split(' ')
            if len(parts) < 2:
                writer.close()
                return
            
            method, path = parts[0], parts[1]
            
            headers = {}
            while True:
                line = await reader.readline()
                if not line or line == b'\r\n':
                    break
                line = line.decode().strip()
                if ':' in line:
                    key, value = line.split(':', 1)
                    headers[key.strip().lower()] = value.strip()
            
            content_length = int(headers.get('content-length', 0))
            body = b''
            if content_length > 0:
                body = await reader.read(content_length)
            
            response = await self._route_api(method, path, body)
            
            writer.write(response)
            await writer.drain()
            writer.close()
            
        except Exception as e:
            logger.error(f"API 请求处理错误: {e}")
            try:
                writer.close()
            except:
                pass
    
    async def _route_api(self, method: str, path: str, body: bytes) -> bytes:
        if path == '/api/status':
            return self._json_response({
                'status': 'running',
                'clients': len(self.clients),
                'cor_status': self.cor_status,
                'ptt_active': self.ptt_active
            })
        
        elif path == '/api/config' and method == 'GET':
            return self._json_response(self.config)
        
        elif path == '/api/config' and method == 'PUT':
            try:
                updates = json.loads(body)
                self.config.update(updates)
                self._save_config()
                return self._json_response({'status': 'ok'})
            except:
                return self._json_response({'error': 'invalid json'}, 400)
        
        elif path == '/api/audio/preset' and method == 'POST':
            try:
                data = json.loads(body)
                preset = data.get('preset', 'wideband')
                presets = {
                    'narrowband': 8000,
                    'wideband': 16000,
                    'hd_voice': 24000,
                    'cd_quality': 44100
                }
                if preset in presets:
                    self.config['audio']['sample_rate'] = presets[preset]
                    self.config['audio']['preset'] = preset
                    self._save_config()
                    return self._json_response({'status': 'ok', 'preset': preset})
                return self._json_response({'error': 'unknown preset'}, 400)
            except:
                return self._json_response({'error': 'invalid request'}, 400)
        
        elif path == '/api/clients' and method == 'GET':
            clients = []
            for c in self.client_registry.values():
                clients.append({
                    'client_id': c.client_id,
                    'client_name': c.client_name,
                    'client_type': c.client_type,
                    'can_tx': c.can_tx,
                    'can_aprs': c.can_aprs,
                    'activated': c.activated
                })
            return self._json_response(clients)
        
        else:
            return self._json_response({'error': 'not found'}, 404)
    
    def _json_response(self, data, status: int = 200) -> bytes:
        status_text = {200: 'OK', 400: 'Bad Request', 404: 'Not Found'}.get(status, 'OK')
        body = json.dumps(data, ensure_ascii=False)
        response = f"HTTP/1.1 {status} {status_text}\r\n"
        response += "Content-Type: application/json; charset=utf-8\r\n"
        response += "Access-Control-Allow-Origin: *\r\n"
        response += f"Content-Length: {len(body.encode())}\r\n"
        response += "\r\n"
        response += body
        return response.encode()
    
    async def start(self):
        logger.info(f"WebSocket 服务: {self.ws_host}:{self.ws_port}")
        logger.info(f"管理 API 服务: 0.0.0.0:{self.api_port}")
        
        ws_server = await websockets.serve(
            self.handle_ws_client,
            self.ws_host,
            self.ws_port,
            ping_interval=20,
            ping_timeout=20
        )
        
        api_server = await asyncio.start_server(
            self.handle_api_request,
            '0.0.0.0',
            self.api_port
        )
        
        logger.info("服务已启动")
        
        await asyncio.Future()

def main():
    server = IntegratedServer()
    try:
        asyncio.run(server.start())
    except KeyboardInterrupt:
        logger.info("服务已停止")

if __name__ == "__main__":
    main()
