import asyncio
import subprocess
import threading
import queue
from typing import Optional, Callable
import logging
import tempfile
import os
import sys

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class AudioManager:
    """使用ALSA原生工具的音频管理器"""
    def __init__(self, 
                 input_device: Optional[str] = None,
                 output_device: Optional[str] = None,
                 sample_rate: int = 8000,
                 channels: int = 1,
                 chunk_size: int = 1024):
        self.input_device = input_device
        self.output_device = output_device
        self.sample_rate = sample_rate
        self.channels = channels
        self.chunk_size = chunk_size
        
        self.is_running = False
        self.loop = None
        
        self.audio_callback: Optional[Callable[[bytes], None]] = None
        self.playback_queue = asyncio.Queue()
        
        self.arecord_process: Optional[subprocess.Popen] = None
        self.aplay_process: Optional[subprocess.Popen] = None
        
        # 使用线程来处理阻塞的音频I/O
        self.input_thread: Optional[threading.Thread] = None
        self.output_thread: Optional[threading.Thread] = None
        self.output_buffer_queue = queue.Queue()
        
        # 检查平台
        self.is_windows = sys.platform.startswith('win')
        
        self.list_devices()
    
    def list_devices(self):
        """列出可用的音频设备"""
        logger.info("可用音频设备:")
        
        if self.is_windows:
            logger.info("  Windows平台，使用WASAPI/DirectSound")
            return
        
        try:
            result = subprocess.run(['arecord', '-l'], capture_output=True, text=True)
            if result.returncode == 0:
                logger.info("录制设备:")
                for line in result.stdout.split('\n')[:10]:
                    if line.strip():
                        logger.info(f"  {line}")
        except FileNotFoundError:
            logger.warning("arecord 命令未找到")
        
        try:
            result = subprocess.run(['aplay', '-l'], capture_output=True, text=True)
            if result.returncode == 0:
                logger.info("播放设备:")
                for line in result.stdout.split('\n')[:10]:
                    if line.strip():
                        logger.info(f"  {line}")
        except FileNotFoundError:
            logger.warning("aplay 命令未找到")
    
    async def start_input(self):
        """启动音频输入（录音）"""
        if self.is_windows:
            logger.warning("Windows平台不支持ALSA，请使用sounddevice或其他方案")
            return
            
        try:
            device_arg = f"-D {self.input_device}" if self.input_device else "-D plughw:1,0"
            
            cmd = [
                'arecord',
                '-f', 'S16_LE',
                '-r', str(self.sample_rate),
                '-c', str(self.channels),
                device_arg,
                '-t', 'raw',
                '-'
            ]
            
            self.arecord_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=self.chunk_size * 2
            )
            
            logger.info(f"音频输入已启动: {self.input_device or '默认设备'} @ {self.sample_rate}Hz")
            
            # 在线程中读取音频数据
            self.input_thread = threading.Thread(target=self._input_loop, daemon=True)
            self.input_thread.start()
            
        except FileNotFoundError:
            logger.error("arecord 命令未找到，请安装alsa-utils")
        except Exception as e:
            logger.error(f"启动音频输入失败: {e}")
    
    def _input_loop(self):
        """在线程中读取音频输入"""
        if not self.arecord_process:
            return
            
        chunk_bytes = self.chunk_size * self.channels * 2  # 16-bit = 2 bytes
        
        while self.is_running and self.arecord_process and self.arecord_process.poll() is None:
            try:
                data = self.arecord_process.stdout.read(chunk_bytes)
                
                if len(data) == chunk_bytes and self.audio_callback:
                    # 使用call_soon_threadsafe在事件循环中调用回调
                    if self.loop and self.loop.is_running():
                        try:
                            self.loop.call_soon_threadsafe(
                                lambda d=data: asyncio.create_task(self._dispatch_audio(d))
                            )
                        except RuntimeError:
                            # 事件循环不在运行
                            pass
                    else:
                        self.audio_callback(data)
                        
            except Exception as e:
                logger.error(f"读取音频输入错误: {e}")
                import time
                time.sleep(0.01)
    
    async def _dispatch_audio(self, data: bytes):
        """在事件循环中分发音频数据"""
        if self.audio_callback:
            self.audio_callback(data)
    
    async def start_output(self):
        """启动音频输出（播放）"""
        if self.is_windows:
            logger.warning("Windows平台不支持ALSA，请使用sounddevice或其他方案")
            return
            
        try:
            device_arg = f"-D {self.output_device}" if self.output_device else "-D plughw:1,0"
            
            cmd = [
                'aplay',
                '-f', 'S16_LE',
                '-r', str(self.sample_rate),
                '-c', str(self.channels),
                device_arg,
                '-t', 'raw',
                '-'
            ]
            
            self.aplay_process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=self.chunk_size * 2
            )
            
            logger.info(f"音频输出已启动: {self.output_device or '默认设备'} @ {self.sample_rate}Hz")
            
            # 在线程中写入音频数据
            self.output_thread = threading.Thread(target=self._output_loop, daemon=True)
            self.output_thread.start()
            
            # 启动异步播放任务
            asyncio.create_task(self._playback_dispatcher())
            
        except FileNotFoundError:
            logger.error("aplay 命令未找到，请安装alsa-utils")
        except Exception as e:
            logger.error(f"启动音频输出失败: {e}")
    
    def _output_loop(self):
        """在线程中写入音频输出"""
        if not self.aplay_process:
            return
            
        chunk_bytes = self.chunk_size * self.channels * 2
        silence = b'\x00' * chunk_bytes
        
        while self.is_running and self.aplay_process and self.aplay_process.poll() is None:
            try:
                # 非阻塞获取数据
                try:
                    data = self.output_buffer_queue.get(timeout=0.001)
                except queue.Empty:
                    # 播放静音
                    data = silence
                
                if self.aplay_process and self.aplay_process.stdin:
                    self.aplay_process.stdin.write(data)
                    self.aplay_process.stdin.flush()
                    
            except Exception as e:
                logger.error(f"写入音频输出错误: {e}")
                import time
                time.sleep(0.01)
    
    async def _playback_dispatcher(self):
        """将异步播放队列数据分发到线程安全队列"""
        while self.is_running:
            try:
                # 从asyncio队列获取数据
                data = await asyncio.wait_for(self.playback_queue.get(), timeout=0.1)
                # 放入线程安全队列
                self.output_buffer_queue.put(data)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"播放调度错误: {e}")
    
    async def play_audio(self, audio_bytes: bytes):
        """播放音频数据"""
        try:
            chunk_bytes = self.chunk_size * self.channels * 2
            
            # 将音频数据分块放入队列
            for i in range(0, len(audio_bytes), chunk_bytes):
                chunk = audio_bytes[i:i + chunk_bytes]
                
                # 填充最后一个块
                if len(chunk) < chunk_bytes:
                    chunk = chunk + b'\x00' * (chunk_bytes - len(chunk))
                
                await self.playback_queue.put(chunk)
                
        except Exception as e:
            logger.error(f"播放音频失败: {e}")
    
    async def play_wav_file(self, file_path: str):
        """播放WAV文件"""
        try:
            # 使用aplay播放WAV文件
            device_arg = f"-D {self.output_device}" if self.output_device else "-D plughw:1,0"
            
            cmd = ['aplay', device_arg, file_path]
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            await process.wait()
            
            if process.returncode == 0:
                logger.info(f"播放 WAV 文件完成: {file_path}")
            else:
                logger.error(f"播放 WAV 文件失败，返回码: {process.returncode}")
                
        except Exception as e:
            logger.error(f"播放 WAV 文件失败: {e}")
    
    def set_audio_callback(self, callback: Callable[[bytes], None]):
        self.audio_callback = callback
    
    async def start(self, input_enabled: bool = True, output_enabled: bool = True):
        """启动音频管理器"""
        self.is_running = True
        try:
            self.loop = asyncio.get_running_loop()
        except RuntimeError:
            self.loop = None
        
        if input_enabled:
            await self.start_input()
        
        if output_enabled:
            await self.start_output()
    
    async def stop(self):
        """停止音频管理器"""
        self.is_running = False
        
        # 停止输入
        if self.arecord_process:
            try:
                self.arecord_process.terminate()
                self.arecord_process.wait(timeout=2)
                logger.info("音频输入已停止")
            except:
                try:
                    self.arecord_process.kill()
                except:
                    pass
            self.arecord_process = None
        
        # 停止输出
        if self.aplay_process:
            try:
                if self.aplay_process.stdin:
                    self.aplay_process.stdin.close()
                self.aplay_process.terminate()
                self.aplay_process.wait(timeout=2)
                logger.info("音频输出已停止")
            except:
                try:
                    self.aplay_process.kill()
                except:
                    pass
            self.aplay_process = None
        
        # 等待线程结束
        if self.input_thread and self.input_thread.is_alive():
            self.input_thread.join(timeout=2)
        
        if self.output_thread and self.output_thread.is_alive():
            self.output_thread.join(timeout=2)