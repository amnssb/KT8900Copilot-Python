import asyncio
import serial
import serial.tools.list_ports
from typing import Optional, Callable
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class SerialController:
    def __init__(self, port: str = "/dev/ttyUSB0", baudrate: int = 115200):
        self.port = port
        self.baudrate = baudrate
        self.serial_conn: Optional[serial.Serial] = None
        self.cor_status_callback: Optional[Callable[[bool], None]] = None
        self.is_running = False
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.last_cor_status = False
        
    def find_esp32_port(self) -> Optional[str]:
        ports = serial.tools.list_ports.comports()
        for port in ports:
            if "CP2102" in port.description or "ESP32" in port.description or "USB" in port.description:
                logger.info(f"找到 ESP32 端口: {port.device}")
                return port.device
        logger.warning("未找到 ESP32 串口")
        return None
    
    async def connect(self) -> bool:
        if self.port == "auto":
            self.port = self.find_esp32_port()
            if not self.port:
                return False
        
        try:
            self.serial_conn = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=0.1,
                write_timeout=1.0,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE
            )
            logger.info(f"成功连接到串口: {self.port} @ {self.baudrate} baud")
            
            self.loop = asyncio.get_running_loop()
            self.loop.create_task(self._read_loop())
            return True
        except serial.SerialException as e:
            logger.error(f"串口连接失败: {e}")
            return False
    
    async def _read_loop(self):
        buffer = ""
        while self.is_running and self.serial_conn and self.serial_conn.is_open:
            try:
                if self.serial_conn.in_waiting > 0:
                    data = self.serial_conn.readline().decode('utf-8', errors='ignore').strip()
                    if data:
                        logger.debug(f"串口接收: {data}")
                        
                        if data.startswith("COR_STATUS:"):
                            status = data.split(":")[1]
                            cor_active = status == "1"
                            if self.cor_status_callback:
                                if self.loop and hasattr(self.loop, 'call_soon_threadsafe'):
                                    try:
                                        self.loop.call_soon_threadsafe(
                                            self.cor_status_callback, cor_active
                                        )
                                    except RuntimeError:
                                        # 事件循环不在运行
                                        self.cor_status_callback(cor_active)
                                else:
                                    # 事件循环不可用，直接调用
                                    self.cor_status_callback(cor_active)
                        
                        elif data.startswith("PTT ON"):
                            logger.info("ESP32: PTT 激活")
                        
                        elif data.startswith("PTT OFF"):
                            logger.info("ESP32: PTT 释放")
                        
                        else:
                            logger.debug(f"串口数据: {data}")
                
                await asyncio.sleep(0.01)
                
            except Exception as e:
                logger.error(f"读取串口错误: {e}")
                await asyncio.sleep(0.1)
    
    async def send_ptt_on(self):
        if self.serial_conn and self.serial_conn.is_open:
            try:
                self.serial_conn.write(b"PTT_ON\r\n")
                self.serial_conn.flush()
                logger.debug("发送 PTT_ON 指令")
            except Exception as e:
                logger.error(f"发送 PTT_ON 失败: {e}")
    
    async def send_ptt_off(self):
        if self.serial_conn and self.serial_conn.is_open:
            try:
                self.serial_conn.write(b"PTT_OFF\r\n")
                self.serial_conn.flush()
                logger.debug("发送 PTT_OFF 指令")
            except Exception as e:
                logger.error(f"发送 PTT_OFF 失败: {e}")
    
    def set_cor_callback(self, callback: Callable[[bool], None]):
        self.cor_status_callback = callback
    
    async def start(self):
        self.is_running = True
        await self.connect()
    
    async def stop(self):
        self.is_running = False
        if self.serial_conn and self.serial_conn.is_open:
            self.serial_conn.close()
            logger.info("串口连接已关闭")
    
    def get_cor_status(self) -> bool:
        return self.last_cor_status
    
    def set_cor_status(self, status: bool):
        self.last_cor_status = status