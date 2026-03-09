import asyncio
import websockets
import json
import logging
import hashlib
import secrets
from typing import Dict, Set, Optional
from dataclasses import dataclass
from urllib.parse import parse_qs
from audio_manager import AudioManager
from serial_controller import SerialController
from direwolf_integration import DirewolfIntegration
from aprs_engine import APRSEngine
from auth_token import verify_ws_token

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 客户端类型
CLIENT_TYPE_ESP32 = 1
CLIENT_TYPE_USER = 2
CLIENT_TYPE_ADMIN = 3

# 消息命令
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
CMD_IMG_UPLOAD = 0x17
CMD_IMG_UPLOAD_STOP = 0x18
CMD_IMG_DOWNLOAD = 0x19
CMD_IMG_GET = 0x1A
CMD_SET_CONF = 0x1B
CMD_RESET = 0x1C
CMD_FROM = 0x1D
CMD_ONLINE = 0x1E
CMD_OFFLINE = 0x1F
CMD_PCM = 0x51
CMD_IMG = 0x61

@dataclass
class Client:
    client_id: str
    client_type: int
    client_name: str
    passkey: str
    activated: bool = False
    can_tx: bool = True  # 语音权限
    can_aprs: bool = False  # APRS权限
    chan_to_ws: Optional[asyncio.Queue] = None
    chan_from_ws: Optional[asyncio.Queue] = None
    verify_random: Optional[bytes] = None  # 验证随机数
    
class KTCopilotServer:
    def __init__(self, config_file: str = "config.json"):
        with open(config_file, 'r', encoding='utf-8') as f:
            self.config = json.load(f)
        
        self.ws_host = self.config['websocket']['host']
        self.ws_port = self.config['websocket']['port']
        self.debug = self.config.get('debug', False)
        
        # 客户端管理
        self.clients: Dict[websockets.WebSocketServerProtocol, Client] = {}
        self.client_registry: Dict[str, Client] = {}
        
        self.audio_manager = None
        self.serial_controller = None
        self.direwolf_integration = None
        self.aprs_engine = None
        self.cor_status = False
        self.ptt_active = False
        
        # 加载客户端配置
        self._load_clients()
        
    def _load_clients(self):
        """加载客户端配置"""
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
            logger.info(f"加载客户端: {client.client_name} (类型: {client.client_type}, APRS: {client.can_aprs})")
    
    def _verify_client(self, client_id: str) -> Optional[Client]:
        """验证客户端ID"""
        return self.client_registry.get(client_id)
    
    def _generate_verify_bytes(self) -> bytes:
        """生成16字节随机验证数"""
        return secrets.token_bytes(16)
    
    def _compute_auth_digest(self, data: str) -> bytes:
        """计算认证摘要（SHA-256 前16字节）"""
        return hashlib.sha256(data.encode()).digest()[:16]
    
    async def _handle_verify(self, websocket, client_id: str):
        """处理客户端验证"""
        client = self._verify_client(client_id)
        
        if not client:
            logger.warning(f"验证失败：未知客户端 {client_id}")
            await websocket.send(bytes([CMD_REFUSE]))
            return None
        
        if client.activated:
            logger.warning(f"客户端忙碌：{client_id}")
            await websocket.send(bytes([CMD_BUSY]))
            return None
        
        # 生成验证随机数
        verify_bytes = self._generate_verify_bytes()
        client.verify_random = verify_bytes
        
        # 发送验证请求
        response = bytes([CMD_VERIFY]) + verify_bytes
        await websocket.send(response)
        
        return client
    
    async def _verify_response(self, websocket, client: Client, response: bytes):
        """验证客户端响应"""
        if len(response) != 16:
            logger.warning(f"验证失败：响应长度错误 {len(response)}")
            await websocket.send(bytes([CMD_REFUSE]))
            return False
        
        # 计算期望的认证摘要
        if client.verify_random is None:
            await websocket.send(bytes([CMD_REFUSE]))
            return False
        data = client.client_id + client.verify_random.hex() + client.passkey
        expected = self._compute_auth_digest(data)
        
        if response != expected:
            logger.warning(f"验证失败：摘要不匹配 {client.client_id}")
            await websocket.send(bytes([CMD_REFUSE]))
            return False
        
        # 验证成功
        client.activated = True
        client.chan_to_ws = asyncio.Queue(maxsize=4)
        client.chan_from_ws = asyncio.Queue(maxsize=4)
        
        logger.info(f"客户端验证成功: {client.client_name}")
        await websocket.send(bytes([CMD_ONLINE]))
        
        return True

    async def _verify_token_client(self, websocket, token: str) -> Optional[Client]:
        claims = verify_ws_token(token)
        if not claims or claims.get("token_type") != "ws":
            await websocket.send(bytes([CMD_REFUSE]))
            return None

        client_id = claims.get("client_id")
        if not isinstance(client_id, str):
            await websocket.send(bytes([CMD_REFUSE]))
            return None

        client = self._verify_client(client_id)
        if not client:
            await websocket.send(bytes([CMD_REFUSE]))
            return None

        if client.activated:
            await websocket.send(bytes([CMD_BUSY]))
            return None

        client.activated = True
        client.chan_to_ws = asyncio.Queue(maxsize=4)
        client.chan_from_ws = asyncio.Queue(maxsize=4)
        client.client_name = claims.get("client_name", client.client_name)
        client.client_type = int(claims.get("client_type", client.client_type))
        client.can_tx = bool(claims.get("can_tx", client.can_tx))
        client.can_aprs = bool(claims.get("can_aprs", client.can_aprs))

        await websocket.send(bytes([CMD_ONLINE]))
        logger.info(f"客户端令牌验证成功: {client.client_name}")
        return client
    
    async def broadcast_message(self, message: dict, exclude_client: Client = None):
        """广播消息给所有已验证客户端"""
        if self.clients:
            message_str = json.dumps(message)
            for ws, client in self.clients.items():
                if client != exclude_client:
                    try:
                        await ws.send(message_str)
                    except:
                        pass
    
    async def broadcast_binary(self, data: bytes, exclude_client: Client = None):
        """广播二进制数据"""
        for ws, client in self.clients.items():
            if client != exclude_client and client.can_tx:
                try:
                    await ws.send(data)
                except:
                    pass
    
    async def broadcast_audio(self, audio_bytes: bytes):
        """广播音频数据"""
        # 添加PCM命令头
        data = bytes([CMD_PCM]) + audio_bytes
        await self.broadcast_binary(data)
    
    def handle_audio_input(self, audio_bytes: bytes):
        asyncio.create_task(self.broadcast_audio(audio_bytes))
    
    def handle_cor_status(self, status: bool):
        if status != self.cor_status:
            self.cor_status = status
            logger.info(f"COR 状态变化: {status}")
            
            # 广播COR状态
            cmd = CMD_RX if status else CMD_RX_STOP
            asyncio.create_task(self.broadcast_binary(bytes([cmd])))
            
            asyncio.create_task(self.broadcast_message({
                'type': 'cor_status',
                'active': status
            }))
    
    def handle_aprs_packet(self, raw_packet: str):
        if self.aprs_engine:
            self.aprs_engine.handle_packet(raw_packet)
        
        asyncio.create_task(self.broadcast_message({
            'type': 'aprs_packet',
            'raw': raw_packet
        }))
        
        logger.info(f"APRS 数据包: {raw_packet[:100]}")
    
    async def handle_client_message(self, websocket, client: Client, message):
        try:
            # JSON 格式的控制消息
            if isinstance(message, str) and message.startswith('{'):
                data = json.loads(message)
                message_type = data.get('type')
                
                if message_type == 'ptt_press':
                    if not self.ptt_active and client.can_tx:
                        self.ptt_active = True
                        await self.broadcast_binary(bytes([CMD_PTT_ON]))
                        await self.broadcast_message({
                            'type': 'ptt_status',
                            'active': True,
                            'from': client.client_name,
                            'from_id': client.client_id,
                            'from_type': client.client_type
                        })
                        if self.serial_controller:
                            await self.serial_controller.send_ptt_on()
                
                elif message_type == 'ptt_release':
                    if self.ptt_active:
                        self.ptt_active = False
                        await self.broadcast_binary(bytes([CMD_PTT_OFF]))
                        await self.broadcast_message({
                            'type': 'ptt_status',
                            'active': False,
                            'from': None,
                            'from_id': None,
                            'from_type': None
                        })
                        if self.serial_controller:
                            await self.serial_controller.send_ptt_off()
                
                elif message_type == 'get_status':
                    await websocket.send(json.dumps({
                        'type': 'status',
                        'cor_active': self.cor_status,
                        'ptt_active': self.ptt_active,
                        'user_type': client.client_type,
                        'can_aprs': client.can_aprs
                    }))
                
                elif message_type == 'aprs_beacon':
                    if not client.can_aprs:
                        await websocket.send(json.dumps({
                            'type': 'aprs_response',
                            'status': 'error',
                            'message': '无APRS权限'
                        }))
                        logger.warning(f"用户 {client.client_name} 尝试发送APRS但无权限")
                        return
                    
                    logger.info(f"APRS 信标请求 from {client.client_name}")
                    await self.broadcast_message({
                        'type': 'aprs_response',
                        'status': 'queued'
                    })
                    
                    if self.aprs_engine:
                        packet = await self.aprs_engine.beacon_position()
                        if packet:
                            logger.info(f"发送 APRS 信标: {packet}")
                            await self.broadcast_message({
                                'type': 'aprs_response',
                                'status': 'sent',
                                'packet': packet
                            })

            # 二进制音频数据
            elif isinstance(message, bytes):
                if self.ptt_active and client.can_tx:
                    await self.audio_manager.play_audio(message)

        except json.JSONDecodeError:
            if self.ptt_active and client.can_tx:
                await self.audio_manager.play_audio(message)
        except Exception as e:
            logger.error(f"处理客户端消息错误: {e}")
    
    async def client_handler(self, websocket, path):
        client_addr = websocket.remote_address
        logger.info(f"客户端连接: {client_addr}")
        
        client = None
        verify_stage = 0  # 0: 等待ID, 1: 等待响应, 2: 已验证

        params = parse_qs(path.split("?", 1)[1] if "?" in path else "")
        token_values = params.get("token", [])
        if token_values:
            token_client = await self._verify_token_client(websocket, token_values[0])
            if token_client:
                client = token_client
                self.clients[websocket] = client
                verify_stage = 2
                logger.info(f"客户端已验证(令牌): {client.client_name}")
            else:
                return
        
        try:
            async for message in websocket:
                if verify_stage == 0:
                    # 第一步：接收客户端ID
                    if isinstance(message, bytes):
                        client_id = message.decode('utf-8', errors='ignore')
                        client = await self._handle_verify(websocket, client_id)
                        if client:
                            verify_stage = 1
                    else:
                        logger.warning(f"验证失败：无效的消息类型")
                        await websocket.send(bytes([CMD_REFUSE]))
                        break
                        
                elif verify_stage == 1:
                    # 第二步：验证响应
                    if isinstance(message, bytes):
                        if await self._verify_response(websocket, client, message):
                            self.clients[websocket] = client
                            verify_stage = 2
                            logger.info(f"客户端已验证: {client.client_name}")
                    else:
                        logger.warning(f"验证失败：无效的响应格式")
                        await websocket.send(bytes([CMD_REFUSE]))
                        break
                
                elif verify_stage == 2:
                    # 已验证，处理正常消息
                    await self.handle_client_message(websocket, client, message)
                    
        except websockets.exceptions.ConnectionClosed:
            logger.info(f"客户端断开: {client_addr}")
        finally:
            if client:
                client.activated = False
            self.clients.pop(websocket, None)
    
    async def start(self):
        logger.info("=" * 50)
        logger.info("KT8900 Copilot 服务器启动")
        logger.info(f"已加载 {len(self.client_registry)} 个客户端")
        logger.info("=" * 50)
        
        # 初始化音频管理器
        self.audio_manager = AudioManager(
            input_device=self.config['audio']['input_device'],
            output_device=self.config['audio']['output_device'],
            sample_rate=self.config['audio']['sample_rate'],
            channels=self.config['audio']['channels'],
            chunk_size=self.config['audio']['chunk_size']
        )
        self.audio_manager.set_audio_callback(self.handle_audio_input)
        await self.audio_manager.start(input_enabled=True, output_enabled=True)
        
        # 初始化串口控制器
        port = "auto" if self.config['serial']['auto_detect'] else self.config['serial']['port']
        self.serial_controller = SerialController(
            port=port,
            baudrate=self.config['serial']['baudrate']
        )
        self.serial_controller.set_cor_callback(self.handle_cor_status)
        await self.serial_controller.start()
        
        # 初始化APRS引擎
        if self.config.get('aprs'):
            self.aprs_engine = APRSEngine(self.config['aprs'])
            logger.info("APRS 引擎已初始化")
        
        # 初始化Direwolf集成（可选）
        if self.config.get('direwolf', {}).get('enabled', False):
            self.direwolf_integration = DirewolfIntegration(self.config.get('direwolf', {}))
            self.direwolf_integration.set_decoder_callback(self.handle_aprs_packet)
            await self.direwolf_integration.start_decoder()
        
        # 启动WebSocket服务器
        ssl_context = None
        ssl_conf = self.config.get('ssl', {})
        if ssl_conf.get('enabled') and ssl_conf.get('cert_file') and ssl_conf.get('key_file'):
            import ssl
            import os
            cert_file = ssl_conf['cert_file']
            key_file = ssl_conf['key_file']
            if os.path.exists(cert_file) and os.path.exists(key_file):
                ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                ssl_context.load_cert_chain(certfile=cert_file, keyfile=key_file)
                logger.info(f"WSS (SSL/TLS) 已启用, 证书: {cert_file}")
            else:
                logger.error("SSL/TLS 证书文件不存在，将回退到普通 WS 模式！")

        protocol = "wss://" if ssl_context else "ws://"
        logger.info(f"WebSocket 服务器启动: {protocol}{self.ws_host}:{self.ws_port}")
        
        async with websockets.serve(
            self.client_handler,
            self.ws_host,
            self.ws_port,
            ssl=ssl_context,
            ping_interval=20,
            ping_timeout=20
        ):
            logger.info("服务器准备就绪！")
            logger.info("等待客户端连接...")
            
            try:
                await asyncio.Future()
            except KeyboardInterrupt:
                logger.info("收到停止信号，正在关闭服务器...")
            finally:
                await self.stop()
    
    async def stop(self):
        logger.info("正在关闭服务器...")
        
        # 关闭所有客户端连接
        for websocket in list(self.clients.keys()):
            await websocket.close()
        
        if self.serial_controller:
            await self.serial_controller.stop()
        
        if self.audio_manager:
            await self.audio_manager.stop()
        
        if self.direwolf_integration:
            await self.direwolf_integration.stop()
        
        logger.info("服务器已关闭")

def main():
    server = KTCopilotServer()
    try:
        asyncio.run(server.start())
    except KeyboardInterrupt:
        logger.info("用户中断")

if __name__ == "__main__":
    main()
