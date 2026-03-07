import asyncio
import numpy as np
import sounddevice as sd
import threading
import time
from typing import Optional, Callable
import logging
from collections import deque

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class OptimizedAudioManager:
    """
    高性能低延迟音频管理器
    
    优化点：
    1. 使用 sounddevice 直接访问声卡，避免子进程开销
    2. 使用环形缓冲区减少内存分配
    3. 双缓冲策略避免卡顿
    4. 独立的音频线程，避免 Python GIL 影响
    """
    
    def __init__(self,
                 input_device: Optional[int] = None,
                 output_device: Optional[int] = None,
                 sample_rate: int = 16000,
                 channels: int = 1,
                 chunk_size: int = 160,
                 latency: str = 'low'):
        self.sample_rate = sample_rate
        self.channels = channels
        self.chunk_size = chunk_size
        self.latency_mode = latency
        
        self.input_device = input_device
        self.output_device = output_device
        
        self.audio_callback: Optional[Callable[[bytes], None]] = None
        
        self.playback_buffer = deque(maxlen=100)
        self.buffer_lock = threading.Lock()
        
        self.stats = {
            'input_frames': 0,
            'output_frames': 0,
            'dropped_frames': 0,
            'buffer_underruns': 0,
        }
        
        self.input_stream = None
        self.output_stream = None
        self.is_running = False
        
        self._prewarm_buffer()
        
        logger.info(f"音频管理器初始化: {sample_rate}Hz, {channels}ch, chunk={chunk_size}")
        
    def _prewarm_buffer(self):
        silence = np.zeros(self.chunk_size, dtype=np.int16)
        for _ in range(5):
            self.playback_buffer.append(silence.tobytes())
    
    def _input_callback(self, indata: np.ndarray, frames: int, time_info: dict, status: sd.CallbackFlags):
        if status and status.input_overflow:
            self.stats['dropped_frames'] += 1
        
        if self.audio_callback:
            audio_bytes = indata.astype(np.int16).tobytes()
            self.stats['input_frames'] += 1
            
            try:
                loop = asyncio.get_running_loop()
                loop.call_soon_threadsafe(
                    lambda: asyncio.create_task(self._dispatch_audio(audio_bytes))
                )
            except RuntimeError:
                self.audio_callback(audio_bytes)
    
    async def _dispatch_audio(self, data: bytes):
        if self.audio_callback:
            self.audio_callback(data)
    
    def _output_callback(self, outdata: np.ndarray, frames: int, time_info: dict, status: sd.CallbackFlags):
        if status and status.output_underflow:
            self.stats['buffer_underruns'] += 1
        
        with self.buffer_lock:
            if len(self.playback_buffer) > 0:
                data = self.playback_buffer.popleft()
                expected_bytes = frames * self.channels * 2
                if len(data) >= expected_bytes:
                    outdata[:] = np.frombuffer(data[:expected_bytes], dtype=np.int16).reshape(-1, self.channels)
                else:
                    outdata.fill(0)
            else:
                outdata.fill(0)
                self.stats['buffer_underruns'] += 1
        
        self.stats['output_frames'] += 1
    
    async def start(self, input_enabled: bool = True, output_enabled: bool = True):
        self.is_running = True
        
        try:
            if input_enabled:
                self.input_stream = sd.InputStream(
                    device=self.input_device,
                    samplerate=self.sample_rate,
                    channels=self.channels,
                    dtype=np.int16,
                    blocksize=self.chunk_size,
                    latency=self.latency_mode,
                    callback=self._input_callback
                )
                self.input_stream.start()
                logger.info(f"音频输入已启动 (延迟: {self.latency_mode})")
            
            if output_enabled:
                self.output_stream = sd.OutputStream(
                    device=self.output_device,
                    samplerate=self.sample_rate,
                    channels=self.channels,
                    dtype=np.int16,
                    blocksize=self.chunk_size,
                    latency=self.latency_mode,
                    callback=self._output_callback
                )
                self.output_stream.start()
                logger.info(f"音频输出已启动 (延迟: {self.latency_mode})")
            
            asyncio.create_task(self._stats_reporter())
            
        except Exception as e:
            logger.error(f"启动音频流失败: {e}")
            raise
    
    async def play_audio(self, audio_bytes: bytes):
        if not self.is_running or not self.output_stream:
            return
        
        try:
            with self.buffer_lock:
                chunk_bytes = self.chunk_size * self.channels * 2
                
                for i in range(0, len(audio_bytes), chunk_bytes):
                    chunk = audio_bytes[i:i + chunk_bytes]
                    
                    if len(chunk) < chunk_bytes:
                        chunk = chunk + b'\x00' * (chunk_bytes - len(chunk))
                    
                    self.playback_buffer.append(chunk)
                    
        except Exception as e:
            logger.error(f"播放音频错误: {e}")
    
    async def stop(self):
        self.is_running = False
        
        if self.input_stream:
            self.input_stream.stop()
            self.input_stream.close()
            self.input_stream = None
            logger.info("音频输入已停止")
        
        if self.output_stream:
            self.output_stream.stop()
            self.output_stream.close()
            self.output_stream = None
            logger.info("音频输出已停止")
    
    def set_audio_callback(self, callback: Callable[[bytes], None]):
        self.audio_callback = callback
    
    def get_stats(self) -> dict:
        return {
            'input_frames': self.stats['input_frames'],
            'output_frames': self.stats['output_frames'],
            'dropped_frames': self.stats['dropped_frames'],
            'buffer_underruns': self.stats['buffer_underruns'],
            'buffer_depth': len(self.playback_buffer),
            'estimated_latency_ms': (self.chunk_size / self.sample_rate) * 1000
        }
    
    async def _stats_reporter(self):
        while self.is_running:
            await asyncio.sleep(30)
            stats = self.get_stats()
            logger.info(f"音频统计: 输入={stats['input_frames']}, 输出={stats['output_frames']}, "
                       f"欠载={stats['buffer_underruns']}, 缓冲区深度={stats['buffer_depth']}")
    
    @staticmethod
    def list_devices():
        print("\n可用音频设备:")
        print(sd.query_devices())
        
    def get_latency_ms(self) -> float:
        return (self.chunk_size / self.sample_rate) * 1000


class ZeroCopyAudioManager(OptimizedAudioManager):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._memory_pool = [bytearray(self.chunk_size * self.channels * 2) for _ in range(20)]
        self._pool_index = 0
        
    def _get_buffer(self) -> bytearray:
        buf = self._memory_pool[self._pool_index]
        self._pool_index = (self._pool_index + 1) % len(self._memory_pool)
        return buf
    
    async def play_audio(self, audio_bytes: bytes):
        if not self.is_running or not self.output_stream:
            return
        
        try:
            with self.buffer_lock:
                chunk_bytes = self.chunk_size * self.channels * 2
                
                for i in range(0, len(audio_bytes), chunk_bytes):
                    chunk = audio_bytes[i:i + chunk_bytes]
                    
                    buf = self._get_buffer()
                    buf[:len(chunk)] = chunk
                    
                    if len(chunk) < chunk_bytes:
                        buf[len(chunk):chunk_bytes] = b'\x00' * (chunk_bytes - len(chunk))
                    
                    self.playback_buffer.append(bytes(buf[:chunk_bytes]))
                    
        except Exception as e:
            logger.error(f"播放音频错误: {e}")


AudioManager = OptimizedAudioManager
