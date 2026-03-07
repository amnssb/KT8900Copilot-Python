import asyncio
import subprocess
import logging
import os
import re
import sys
from typing import Optional, Callable
import tempfile

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class DirewolfIntegration:
    def __init__(self, config: dict):
        self.config = config
        self.config_file = config.get('config_file', '/tmp/direwolf.conf')
        self.audio_input_device = config.get('audio_input_device', 'plughw:1,0')
        self.audio_output_device = config.get('audio_output_device', 'plughw:1,0')
        self.baudrate = config.get('baud', 1200)
        
        self.direwolf_process: Optional[subprocess.Popen] = None
        self.decoder_callback: Optional[Callable[[str], None]] = None
        self.is_running = False
        
        # 检查平台
        self.is_windows = sys.platform.startswith('win')
        
    def _create_config(self):
        config_content = f"""
ADEVICE {self.audio_input_device} {self.audio_output_device}

CHANNEL 0
MYCALL {self.config.get('my_callsign', 'NOSSID')}
MYSSID {self.config.get('my_ssid', 0)}
MODEM 1200

IGSERVER noam.aprs2.net
IGLOGIN {self.config.get('my_callsign', 'NOSSID')} {self.config.get('igpassword', '-1')}
IGFILTER m/10
IGTXLIMIT 30  

"""
        dirname = os.path.dirname(self.config_file)
        if dirname:
            os.makedirs(dirname, exist_ok=True)
        with open(self.config_file, 'w') as f:
            f.write(config_content)
        
        logger.info(f"Direwolf 配置文件已创建: {self.config_file}")
    
    async def start_decoder(self):
        if self.is_running:
            logger.warning("Direwolf 解码器已在运行")
            return
        
        self._create_config()
        
        try:
            self.direwolf_process = subprocess.Popen(
                ['direwolf', '-t', '0', '-r', '48000', '-b', '16', '-c', self.config_file],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1
            )
            
            self.is_running = True
            logger.info("Direwolf 解码器已启动")
            
            asyncio.create_task(self._read_direwolf_output())
            
        except FileNotFoundError:
            logger.error("未找到 direwolf 命令，请确保已安装 direwolf")
        except Exception as e:
            logger.error(f"启动 Direwolf 失败: {e}")
    
    async def _read_direwolf_output(self):
        """异步读取Direwolf输出"""
        if self.is_windows or not hasattr(self.direwolf_process, 'stdout'):
            # Windows平台或无法使用非阻塞IO，使用轮询方式
            while self.is_running and self.direwolf_process:
                try:
                    if self.direwolf_process.stdout:
                        line = self.direwolf_process.stdout.readline()
                        if not line:
                            await asyncio.sleep(0.1)
                            continue
                        
                        if '] .' in line and '>' in line:
                            packet_match = re.search(r'\[(.*?)\].*\[.*?\]\s+(.*)', line)
                            if packet_match:
                                raw_packet = packet_match.group(2).strip()
                                if self.decoder_callback:
                                    self.decoder_callback(raw_packet)
                        
                        elif 'TNC2 format' in line or ']' in line:
                            logger.debug(f"Direwolf 输出: {line.strip()}")
                    
                    await asyncio.sleep(0.1)
                    
                except Exception as e:
                    logger.error(f"读取 Direwolf 输出错误: {e}")
                    await asyncio.sleep(0.1)
        else:
            # Linux平台使用select
            import select
            import fcntl
            
            try:
                stdout_fd = self.direwolf_process.stdout.fileno()
                fl = fcntl.fcntl(stdout_fd, fcntl.F_GETFL)
                fcntl.fcntl(stdout_fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)
                
                while self.is_running and self.direwolf_process:
                    try:
                        readable, _, _ = select.select([stdout_fd], [], [], 0.1)
                        
                        if readable:
                            try:
                                line = self.direwolf_process.stdout.readline()
                            except (IOError, OSError):
                                line = None
                            
                            if not line:
                                await asyncio.sleep(0.01)
                                continue
                            
                            if '] .' in line and '>' in line:
                                packet_match = re.search(r'\[(.*?)\].*\[.*?\]\s+(.*)', line)
                                if packet_match:
                                    raw_packet = packet_match.group(2).strip()
                                    if self.decoder_callback:
                                        self.decoder_callback(raw_packet)
                            
                            elif 'TNC2 format' in line or ']' in line:
                                logger.debug(f"Direwolf 输出: {line.strip()}")
                        else:
                            await asyncio.sleep(0.01)
                    
                    except Exception as e:
                        logger.error(f"读取 Direwolf 输出错误: {e}")
                        await asyncio.sleep(0.1)
            except Exception as e:
                logger.error(f"设置非阻塞模式失败: {e}")
                # 回退到轮询模式
                while self.is_running and self.direwolf_process:
                    try:
                        if self.direwolf_process.stdout:
                            line = self.direwolf_process.stdout.readline()
                            if line and '] .' in line and '>' in line:
                                packet_match = re.search(r'\[(.*?)\].*\[.*?\]\s+(.*)', line)
                                if packet_match:
                                    raw_packet = packet_match.group(2).strip()
                                    if self.decoder_callback:
                                        self.decoder_callback(raw_packet)
                        
                        await asyncio.sleep(0.1)
                    except Exception as e:
                        logger.error(f"读取 Direwolf 输出错误: {e}")
                        await asyncio.sleep(0.1)
    
    async def encode_audio(self, aprs_packet: str) -> Optional[bytes]:
        temp_file = None
        audio_file = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as tf:
                temp_file = tf.name
                tf.write(aprs_packet)
            
            with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix='.wav') as af:
                audio_file = af.name
            
            process = await asyncio.create_subprocess_exec(
                'aprs-encode',
                temp_file,
                '-o', audio_file,
                '-b', str(self.baudrate),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            await process.wait()
            
            if process.returncode == 0:
                with open(audio_file, 'rb') as f:
                    audio_data = f.read()
                return audio_data
            else:
                logger.error(f"APRS 编码失败，返回码: {process.returncode}")
                return None
                
        except FileNotFoundError:
            logger.error("未找到 aprs-encode 命令，尝试使用 Direwolf KISS 模式...")
            return await self._encode_with_kiss(aprs_packet)
        except Exception as e:
            logger.error(f"APRS 编码错误: {e}")
            return None
        finally:
            if temp_file:
                try:
                    os.unlink(temp_file)
                except:
                    pass
            if audio_file:
                try:
                    os.unlink(audio_file)
                except:
                    pass
    
    async def _encode_with_kiss(self, aprs_packet: str) -> Optional[bytes]:
        try:
            kiss_packet = self._make_kiss_frame(aprs_packet.encode('latin-1'))
            
            process = await asyncio.create_subprocess_exec(
                'direwolf',
                '-t', '0',
                '-c', self.config_file,
                '-X',
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate(kiss_packet)
            
            return stdout
            
        except Exception as e:
            logger.error(f"KISS 编码错误: {e}")
            return None
    
    def _make_kiss_frame(self, data: bytes) -> bytes:
        KISS_FEND = 0xC0
        KISS_FESC = 0xDB
        KISS_TFEND = 0xDC
        KISS_TFESC = 0xDD
        
        encoded = bytearray([KISS_FEND])
        encoded.append(0x00)
        
        for byte in data:
            if byte == KISS_FEND:
                encoded.append(KISS_FESC)
                encoded.append(KISS_TFEND)
            elif byte == KISS_FESC:
                encoded.append(KISS_FESC)
                encoded.append(KISS_TFESC)
            else:
                encoded.append(byte)
        
        encoded.append(KISS_FEND)
        return bytes(encoded)
    
    def set_decoder_callback(self, callback: Callable[[str], None]):
        self.decoder_callback = callback
    
    async def stop(self):
        self.is_running = False
        
        if self.direwolf_process:
            try:
                self.direwolf_process.terminate()
                await asyncio.sleep(1)
                if self.direwolf_process.poll() is None:
                    self.direwolf_process.kill()
                logger.info("Direwolf 进程已停止")
            except Exception as e:
                logger.error(f"停止 Direwolf 失败: {e}")