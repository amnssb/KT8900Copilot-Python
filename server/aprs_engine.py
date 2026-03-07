import asyncio
import logging
from datetime import datetime
from typing import Optional, Callable, Dict, Any

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class APRSPacket:
    def __init__(self, raw: str):
        self.raw = raw
        self.source = ""
        self.destination = ""
        self.path = []
        self.info = ""
        self.timestamp = datetime.now()
        self.parse()
    
    def parse(self):
        try:
            parts = self.raw.split('>')
            if len(parts) >= 2:
                self.source = parts[0].strip()
                rest = parts[1]
                
                if ',' in rest:
                    info_parts = rest.split(',')
                    self.destination = info_parts[0].strip()
                    self.path = [p.strip() for p in info_parts[1:-1]]
                    self.info = info_parts[-1].strip()
                else:
                    self.destination = rest.strip()
                    self.info = ""
                    
        except Exception as e:
            logger.error(f"解析 APRS 数据包失败: {e}")
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'source': self.source,
            'destination': self.destination,
            'path': self.path,
            'info': self.info,
            'timestamp': self.timestamp.isoformat(),
            'raw': self.raw
        }
    
    def is_position(self) -> bool:
        return self.info.startswith('=') or self.info.startswith('!')
    
    def parse_position(self) -> Optional[Dict[str, Any]]:
        if not self.is_position():
            return None
        
        try:
            info = self.info[1:].strip()
            parts = info.split('/')
            
            if len(parts) >= 2:
                time_str = parts[0]
                pos_str = parts[1]
                
                lat = None
                lon = None
                
                if len(pos_str) >= 20:
                    lat_deg = int(pos_str[0:2])
                    lat_min = float(pos_str[2:4] + '.' + pos_str[4:5])
                    lat_dir = pos_str[5]
                    
                    lon_deg = int(pos_str[7:10])
                    lon_min = float(pos_str[10:12] + '.' + pos_str[12:13])
                    lon_dir = pos_str[13]
                    
                    lat = (lat_deg + lat_min / 60) * (1 if lat_dir == 'N' else -1)
                    lon = (lon_deg + lon_min / 60) * (1 if lon_dir == 'E' else -1)
                
                return {
                    'lat': lat,
                    'lon': lon
                }
        except Exception as e:
            logger.error(f"解析位置失败: {e}")
        
        return None
    
    def is_message(self) -> bool:
        return self.info.startswith(':')
    
    def parse_message(self) -> Optional[Dict[str, str]]:
        if not self.is_message():
            return None
        
        try:
            info = self.info[1:].strip()
            
            addressee_end = min(9, len(info))
            addressee = info[:addressee_end].strip()
            message = info[addressee_end:].strip()
            
            return {
                'addressee': addressee,
                'message': message
            }
        except Exception as e:
            logger.error(f"解析消息失败: {e}")
        
        return None

class APRSEngine:
    def __init__(self, config: Dict[str, Any]):
        self.enabled = config.get('enabled', False)
        self.my_callsign = config.get('my_callsign', '')
        self.my_ssid = config.get('my_ssid', 0)
        self.my_lat = config.get('my_lat', 0.0)
        self.my_lon = config.get('my_lon', 0.0)
        self.comment = config.get('comment', '')
        self.digipeater = config.get('digipeater', 'WIDE1-1,WIDE2-1')
        self.beacon_interval = config.get('beacon_interval', 600)
        
        self.decoder_callback: Optional[Callable[[APRSPacket], None]] = None
        self.is_running = False
        self.beacon_task = None
    
    def set_decoder_callback(self, callback: Callable[[APRSPacket], None]):
        self.decoder_callback = callback
    
    def handle_packet(self, raw_packet: str):
        try:
            packet = APRSPacket(raw_packet)
            
            if self.decoder_callback:
                self.decoder_callback(packet)
            
            logger.info(f"APRS 数据包: {packet.source} -> {packet.destination}: {packet.info[:50]}")
            
        except Exception as e:
            logger.error(f"处理 APRS 数据包错误: {e}")
    
    def encode_position(self, lat: float, lon: float, comment: str = "", course: int = 0, speed: int = 0) -> str:
        callsign = self.my_callsign + f"-{self.my_ssid}" if self.my_ssid > 0 else self.my_callsign
        
        lat_dir = 'N' if lat >= 0 else 'S'
        lat = abs(lat)
        lat_deg = int(lat)
        lat_min = (lat - lat_deg) * 60
        lat_min_int = int(lat_min)
        lat_min_dec = int((lat_min - lat_min_int) * 100)
        
        lon_dir = 'E' if lon >= 0 else 'W'
        lon = abs(lon)
        lon_deg = int(lon)
        lon_min = (lon - lon_deg) * 60
        lon_min_int = int(lon_min)
        lon_min_dec = int((lon_min - lon_min_int) * 100)
        
        packet = f"/{course:03d}/{speed:03d}" + f"{lat_deg:02d}{lat_min_int:02d}.{lat_min_dec:01d}{lat_dir}" + f"{lon_deg:03d}{lon_min_int:02d}.{lon_min_dec:01d}{lon_dir}" + comment
        
        return f"{callsign}>APRS,{self.digipeater}:{packet}"
    
    def encode_message(self, destination: str, message: str, ack_num: int = 0) -> str:
        callsign = self.my_callsign + f"-{self.my_ssid}" if self.my_ssid > 0 else self.my_callsign
        dest_padded = destination.ljust(9)
        
        ack = f"{{ {ack_num} }}" if ack_num > 0 else ""
        total_message = f"{dest_padded}:{message}{ack}"
        
        return f"{callsign}>APRS,{self.digipeater}:{total_message}"
    
    async def beacon_position(self):
        if not self.enabled or self.my_lat == 0.0 or self.my_lon == 0.0:
            return
        
        packet = self.encode_position(self.my_lat, self.my_lon, self.comment)
        return packet
    
    async def start_beacon(self, send_callback: Callable[[str], None]):
        await self.stop_beacon()
        self.is_running = True
        self.beacon_task = asyncio.create_task(self._beacon_loop(send_callback))
    
    async def _beacon_loop(self, send_callback: Callable[[str], None]):
        while self.is_running:
            try:
                packet = await self.beacon_position()
                if packet and send_callback:
                    send_callback(packet)
                
                await asyncio.sleep(self.beacon_interval)
                
            except Exception as e:
                logger.error(f"发送 APRS 信标错误: {e}")
                await asyncio.sleep(60)
    
    async def stop_beacon(self):
        self.is_running = False
        if self.beacon_task and not self.beacon_task.done():
            self.beacon_task.cancel()
            try:
                await self.beacon_task
            except asyncio.CancelledError:
                pass
