import asyncio
import websockets
import json
import logging
import hashlib
import secrets
import time
import uvloop
from typing import Dict, Set, Optional
from dataclasses import dataclass
from optimized_audio_manager import OptimizedAudioManager, ZeroCopyAudioManager
from serial_controller import SerialController
from aprs_engine import APRSEngine

asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CLIENT_TYPE_ESP32 = 1
CLIENT_TYPE_USER = 2
CLIENT_TYPE_ADMIN = 3

CMD_SKIP = 0x00
CMD_VERIFY = 0x01
CMD_REFUSE = 0x02
CMD_BUSY = 0x03
CMD_RX = 0x11
CMD_RX_STOP = 0x12
CMD_TX = 0x13
CMD_TX_STOP = 0x14
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

class PerformanceStats:
    def __init__(self):
        self.ws_messages_in = 0
        self.ws_messages_out = 0
        self.audio_chunks_in = 0
        self.audio_chunks_out = 0
        self.bytes_in = 0
        self.bytes_out = 0
        self.start_time = time.time()
        self._last_report = time.time()
    
    def record_in(self, bytes_count: int, is_audio: bool = False):
        self.ws_messages_in += 1
        self.bytes_in += bytes_count
        if is_audio:
            self.audio_chunks_in += 1
    
    def record_out(self, bytes_count: int, is_audio: bool = False):
        self.ws_messages_out += 1
        self.bytes_out += bytes_count
        if is_audio:
            self.audio_chunks_out += 1
    
    def get_report(self) -> dict:
        elapsed = time.time() - self.start_time
        return {
            'uptime_s': round(elapsed, 1),
            'messages_in': self.ws_messages_in,
            'messages_out': self.ws_messages_out,
            'bytes_in_mb': round(self.bytes_in / 1024 / 1024, 2),
            'bytes_out_mb': round(self.bytes_out / 1024 / 1024, 2),
            'audio_chunks_in': self.audio_chunks_in,
            'audio_chunks_out': self.audio_chunks_out,
            'throughput_in_kbps': round(self.bytes_in * 8 / 1024 / elapsed, 1) if elapsed > 0 else 0,
            'throughput_out_kbps': round(self.bytes_out * 8 / 1024 / elapsed, 1) if elapsed > 0 else 0,
        }

class OptimizedKTCopilotServer:
    def __init__(self, config_file: str = "config.json"):
        with open(config_file, 'r', encoding='utf-8') as f:
            self.config = json.load(f)
        
        self.ws_host = self.config['websocket']['host']
        self.ws_port = self.config['websocket']['port']
        
        self.clients: Dict[websockets.WebSocketServerProtocol, Client] = {}
        self.client_registry: Dict[str, Client] = {}
        
        audio_config = self.config.get('audio', {})
        self.audio_manager = ZeroCopyAudioManager(
            sample_rate=audio_config.get('sample_rate', 16000),
            channels=audio_config.get('channels', 1),
            chunk_size=audio_config.get('chunk_size', 160),
            latency='low'
        )
        
        self.serial_controller = None
        self.aprs_engine = None
        self.cor_status = False
        self.ptt_active = False
        
        self.stats = PerformanceStats()
        self._load_clients()
        
        self._audio_broadcast_queue = asyncio.Queue(maxsize=100)
        
    def _load_clients(self):
        clients_config = self.config.get('clients', [])
        for client_conf in clients_config:
            client = Client(
                client_id=client_conf['client_id'],
                client_type=client_conf.get('client_type', CLIENT_TYPE_USER),
                client_name=client_conf.get('client_name', client_conf['client_id']),
                passkey=client_conf['passkey'],
                can_tx=client_conf.get('can_tx', True),
                can_aprs=client_conf.get('can_aprs', False)
            )
            self.client_registry[client.client_id] = client
            logger.info(f"加载客户端: {client.client_name}")
    
    def _generate_verify_bytes(self) -> bytes:
        return secrets.token_bytes(16)
    
    def _compute_md5(self, data: str) -> bytes:
        return hashlib.md5(data.encode()).digest()
    
    async def _handle_verify(self, websocket, client_id: str) -> Optional[Client]:
        client = self.client_registry.get(client_id)
        
        if not client:
            await websocket.send(bytes([CMD_REFUSE]))
            return None
        
        if client.activated:
            await websocket.send(bytes([CMD_BUSY]))
            return None
        
        verify_bytes = self._generate_verify_bytes()
        client.verify_random = verify_bytes
        
        response = bytes([CMD_VERIFY]) + verify_bytes
        await websocket.send(response)
        self.stats.record_out(len(response))
        
        return client
    
    async def _verify_response(self, websocket, client: Client, response: bytes) -> bool:
        if len(response) != 16:
            await websocket.send(bytes([CMD_REFUSE]))
            return False
        
        data = client.client_id + client.verify_random.hex() + client.passkey
        expected = self._compute_md5(data)
        
        if response != expected:
            await websocket.send(bytes([CMD_REFUSE]))
            return False
        
        client.activated = True
        logger.info(f"客户端验证成功: {client.client_name}")
        await websocket.send(bytes([CMD_ONLINE]))
        self.stats.record_out(1)
        
        return True
    
    async def _audio_broadcast_loop(self):
        while True:
            try:
                audio_bytes = await self._audio_broadcast_queue.get()
                
                data = bytes([CMD_PCM]) + audio_bytes
                
                tasks = []
                for ws, client in list(self.clients.items()):
                    if client.can_tx:
                        tasks.append(ws.send(data))
                        self.stats.record_out(len(data), is_audio=True)
                
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
                    
            except Exception as e:
                logger.error(f"音频广播错误: {e}")
    
    def handle_audio_input(self, audio_bytes: bytes):
        try:
            self._audio_broadcast_queue.put_nowait(audio_bytes)
            self.stats.record_in(len(audio_bytes), is_audio=True)
        except asyncio.QueueFull:
            pass
    
    def handle_cor_status(self, status: bool):
        if status != self.cor_status:
            self.cor_status = status
            logger.info(f"COR 状态变化: {status}")
            
            cmd = CMD_RX if status else CMD_RX_STOP
            asyncio.create_task(self.broadcast_binary(bytes([cmd])))
    
    async def broadcast_binary(self, data: bytes):
        tasks = []
        for ws, client in self.clients.items():
            if client.can_tx:
                tasks.append(ws.send(data))
                self.stats.record_out(len(data))
        
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
    
    async def broadcast_message(self, message: dict):
        message_str = json.dumps(message)
        tasks = []
        for ws in self.clients.keys():
            tasks.append(ws.send(message_str))
            self.stats.record_out(len(message_str))
        
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
    
    async def handle_client_message(self, websocket, client: Client, message):
        try:
            if isinstance(message, str) and message.startswith('{'):
                data = json.loads(message)
                message_type = data.get('type')
                
                if message_type == 'ptt_press':
                    if not self.ptt_active and client.can_tx:
                        self.ptt_active = True
                        await self.broadcast_binary(bytes([CMD_PTT_ON]))
                        await self.broadcast_message({'type': 'ptt_status', 'active': True})
                        if self.serial_controller:
                            await self.serial_controller.send_ptt_on()
                
                elif message_type == 'ptt_release':
                    if self.ptt_active:
                        self.ptt_active = False
                        await self.broadcast_binary(bytes([CMD_PTT_OFF]))
                        await self.broadcast_message({'type': 'ptt_status', 'active': False})
                        if self.serial_controller:
                            await self.serial_controller.send_ptt_off()
                
                elif message_type == 'get_stats':
                    stats = self.stats.get_report()
                    stats['audio'] = self.audio_manager.get_stats()
                    await websocket.send(json.dumps({'type': 'stats', 'data': stats}))
                
            elif isinstance(message, bytes):
                self.stats.record_in(len(message), is_audio=True)
                if self.ptt_active and client.can_tx:
                    await self.audio_manager.play_audio(message)
                    
        except Exception as e:
            logger.error(f"处理客户端消息错误: {e}")
    
    async def client_handler(self, websocket, path):
        client_addr = websocket.remote_address
        logger.info(f"客户端连接: {client_addr}")
        
        client = None
        verify_stage = 0
        
        try:
            async for message in websocket:
                self.stats.record_in(len(message) if isinstance(message, (bytes, str)) else 0)
                
                if verify_stage == 0:
                    if isinstance(message, bytes):
                        client_id = message.decode('utf-8', errors='ignore')
                        client = await self._handle_verify(websocket, client_id)
                        if client:
                            verify_stage = 1
                    else:
                        await websocket.send(bytes([CMD_REFUSE]))
                        break
                        
                elif verify_stage == 1:
                    if isinstance(message, bytes):
                        if await self._verify_response(websocket, client, message):
                            self.clients[websocket] = client
                            verify_stage = 2
                    else:
                        await websocket.send(bytes([CMD_REFUSE]))
                        break
                
                elif verify_stage == 2:
                    await self.handle_client_message(websocket, client, message)
                    
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            if client:
                client.activated = False
            self.clients.pop(websocket, None)
            logger.info(f"客户端断开: {client_addr}")
    
    async def _stats_reporter(self):
        while True:
            await asyncio.sleep(60)
            report = self.stats.get_report()
            logger.info(f"性能统计: {json.dumps(report)}")
    
    async def start(self):
        logger.info("=" * 50)
        logger.info("KT8900 Copilot 高性能服务器启动")
        logger.info(f"使用 uvloop 事件循环")
        logger.info("=" * 50)
        
        self.audio_manager.set_audio_callback(self.handle_audio_input)
        await self.audio_manager.start(input_enabled=True, output_enabled=True)
        
        asyncio.create_task(self._audio_broadcast_loop())
        asyncio.create_task(self._stats_reporter())
        
        if self.config.get('serial', {}).get('auto_detect', True):
            self.serial_controller = SerialController(port="auto")
            self.serial_controller.set_cor_callback(self.handle_cor_status)
            await self.serial_controller.start()
        
        logger.info(f"WebSocket 服务器启动: {self.ws_host}:{self.ws_port}")
        
        async with websockets.serve(
            self.client_handler,
            self.ws_host,
            self.ws_port,
            ping_interval=20,
            ping_timeout=20,
            max_size=2**20,  # 1MB max message
            compression=None  # 禁用压缩，减少 CPU 开销
        ):
            logger.info("服务器准备就绪！")
            await asyncio.Future()

def main():
    server = OptimizedKTCopilotServer()
    try:
        asyncio.run(server.start())
    except KeyboardInterrupt:
        logger.info("用户中断")

if __name__ == "__main__":
    main()
