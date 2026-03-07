import json
import os
import hashlib
import secrets
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict
from enum import Enum
import logging
import shutil
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class AudioPreset(Enum):
    NARROWBAND = "narrowband"
    WIDEBAND = "wideband"
    HD_VOICE = "hd_voice"
    CD_QUALITY = "cd_quality"
    CUSTOM = "custom"

AUDIO_PRESETS = {
    AudioPreset.NARROWBAND: {
        "name": "窄带语音",
        "description": "适合对讲机窄带通信 (2.5kHz)",
        "sample_rate": 8000,
        "channels": 1,
        "bitrate_kbps": 128,
        "latency_ms": 20
    },
    AudioPreset.WIDEBAND: {
        "name": "宽带语音",
        "description": "高质量语音通信",
        "sample_rate": 16000,
        "channels": 1,
        "bitrate_kbps": 256,
        "latency_ms": 16
    },
    AudioPreset.HD_VOICE: {
        "name": "高清语音",
        "description": "专业级语音质量",
        "sample_rate": 24000,
        "channels": 1,
        "bitrate_kbps": 384,
        "latency_ms": 14
    },
    AudioPreset.CD_QUALITY: {
        "name": "CD音质",
        "description": "CD质量音频 (44.1kHz)",
        "sample_rate": 44100,
        "channels": 1,
        "bitrate_kbps": 706,
        "latency_ms": 12
    }
}

@dataclass
class ClientConfig:
    client_id: str
    client_type: int
    client_name: str
    passkey: str
    can_tx: bool = True
    can_aprs: bool = False

@dataclass  
class AudioConfig:
    input_device: str = "plughw:1,0"
    output_device: str = "plughw:1,0"
    sample_rate: int = 8000
    channels: int = 1
    chunk_size: int = 1024
    preset: str = "narrowband"

@dataclass
class SerialConfig:
    port: str = "/dev/ttyUSB0"
    baudrate: int = 115200
    auto_detect: bool = True

@dataclass
class APRSConfig:
    enabled: bool = False
    my_callsign: str = ""
    my_ssid: int = 0
    my_lat: float = 0.0
    my_lon: float = 0.0
    comment: str = "KT8900Copilot"
    digipeater: str = "WIDE1-1,WIDE2-1"
    beacon_interval: int = 600

@dataclass
class DirewolfConfig:
    enabled: bool = False
    config_file: str = "/tmp/direwolf.conf"
    audio_input_device: str = "plughw:1,0"
    audio_output_device: str = "plughw:1,0"
    baud: int = 1200

@dataclass
class WebSocketConfig:
    host: str = "0.0.0.0"
    port: int = 8765

class ConfigManager:
    DEFAULT_CONFIG_FILE = "config.json"
    BACKUP_DIR = "config_backups"
    
    def __init__(self, config_file: Optional[str] = None):
        self.config_file = config_file or self.DEFAULT_CONFIG_FILE
        self.config: Dict[str, Any] = {}
        self._load_config()
    
    def _load_config(self):
        if os.path.exists(self.config_file):
            with open(self.config_file, 'r', encoding='utf-8') as f:
                self.config = json.load(f)
            logger.info(f"配置已加载: {self.config_file}")
        else:
            logger.warning(f"配置文件不存在，使用默认配置")
            self.config = self._get_default_config()
            self._save_config()
    
    def _get_default_config(self) -> Dict[str, Any]:
        return {
            "websocket": {"host": "0.0.0.0", "port": 8765},
            "audio": {
                "input_device": "plughw:1,0",
                "output_device": "plughw:1,0", 
                "sample_rate": 8000,
                "channels": 1,
                "chunk_size": 1024,
                "preset": "narrowband"
            },
            "serial": {
                "port": "/dev/ttyUSB0",
                "baudrate": 115200,
                "auto_detect": True
            },
            "clients": [
                {
                    "client_id": "admin",
                    "client_type": 3,
                    "client_name": "Admin User",
                    "passkey": self._generate_passkey(),
                    "can_tx": True,
                    "can_aprs": True
                }
            ],
            "aprs": {
                "enabled": False,
                "my_callsign": "",
                "my_ssid": 0,
                "my_lat": 0.0,
                "my_lon": 0.0,
                "comment": "KT8900Copilot",
                "digipeater": "WIDE1-1,WIDE2-1",
                "beacon_interval": 600
            },
            "direwolf": {
                "enabled": False,
                "config_file": "/tmp/direwolf.conf",
                "audio_input_device": "plughw:1,0",
                "audio_output_device": "plughw:1,0",
                "baud": 1200
            },
            "debug": False
        }
    
    def _generate_passkey(self) -> str:
        return secrets.token_hex(16)
    
    def _save_config(self):
        with open(self.config_file, 'w', encoding='utf-8') as f:
            json.dump(self.config, f, indent=2, ensure_ascii=False)
        logger.info(f"配置已保存: {self.config_file}")
    
    def _backup_config(self):
        if not os.path.exists(self.BACKUP_DIR):
            os.makedirs(self.BACKUP_DIR)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = os.path.join(self.BACKUP_DIR, f"config_{timestamp}.json")
        shutil.copy2(self.config_file, backup_file)
        logger.info(f"配置已备份: {backup_file}")
        return backup_file
    
    def get_config(self) -> Dict[str, Any]:
        return self.config.copy()
    
    def update_config(self, updates: Dict[str, Any]) -> bool:
        try:
            self._backup_config()
            self._deep_update(self.config, updates)
            self._save_config()
            return True
        except Exception as e:
            logger.error(f"更新配置失败: {e}")
            return False
    
    def _deep_update(self, target: dict, source: dict):
        for key, value in source.items():
            if key in target and isinstance(target[key], dict) and isinstance(value, dict):
                self._deep_update(target[key], value)
            else:
                target[key] = value
    
    def get_audio_config(self) -> Dict[str, Any]:
        return self.config.get("audio", {})
    
    def set_audio_preset(self, preset: AudioPreset) -> bool:
        if preset not in AUDIO_PRESETS:
            logger.error(f"未知的音频预设: {preset}")
            return False
        
        preset_config = AUDIO_PRESETS[preset]
        self.config["audio"]["sample_rate"] = preset_config["sample_rate"]
        self.config["audio"]["preset"] = preset.value
        
        self._save_config()
        logger.info(f"音频预设已更新: {preset_config['name']}")
        return True
    
    def set_custom_audio(self, sample_rate: int, channels: int = 1, chunk_size: Optional[int] = None) -> bool:
        valid_rates = [8000, 16000, 22050, 24000, 44100, 48000]
        if sample_rate not in valid_rates:
            logger.error(f"无效的采样率: {sample_rate}")
            return False
        
        self.config["audio"]["sample_rate"] = sample_rate
        self.config["audio"]["channels"] = channels
        self.config["audio"]["preset"] = "custom"
        if chunk_size:
            self.config["audio"]["chunk_size"] = chunk_size
        
        self._save_config()
        logger.info(f"自定义音频配置已更新: {sample_rate}Hz, {channels}ch")
        return True
    
    def get_audio_presets(self) -> Dict[str, Dict[str, Any]]:
        result = {}
        for preset, config in AUDIO_PRESETS.items():
            result[preset.value] = config
        return result
    
    def get_current_audio_info(self) -> Dict[str, Any]:
        audio_config = self.get_audio_config()
        sample_rate = audio_config.get("sample_rate", 8000)
        channels = audio_config.get("channels", 1)
        
        bitrate = sample_rate * 16 * channels
        
        matched_preset = None
        for preset, config in AUDIO_PRESETS.items():
            if config["sample_rate"] == sample_rate:
                matched_preset = preset.value
                break
        
        return {
            "sample_rate": sample_rate,
            "channels": channels,
            "chunk_size": audio_config.get("chunk_size", 1024),
            "bitrate_kbps": bitrate // 1000,
            "preset": audio_config.get("preset", "custom"),
            "matched_preset": matched_preset
        }
    
    def get_clients(self) -> List[Dict[str, Any]]:
        return self.config.get("clients", [])
    
    def add_client(self, client_id: str, client_type: int, client_name: str,
                   passkey: Optional[str] = None, can_tx: bool = True, can_aprs: bool = False) -> bool:
        clients = self.get_clients()
        
        for client in clients:
            if client["client_id"] == client_id:
                logger.error(f"客户端已存在: {client_id}")
                return False
        
        new_client = {
            "client_id": client_id,
            "client_type": client_type,
            "client_name": client_name,
            "passkey": passkey or self._generate_passkey(),
            "can_tx": can_tx,
            "can_aprs": can_aprs
        }
        
        clients.append(new_client)
        self.config["clients"] = clients
        self._save_config()
        logger.info(f"客户端已添加: {client_name}")
        return True
    
    def remove_client(self, client_id: str) -> bool:
        clients = self.get_clients()
        
        for i, client in enumerate(clients):
            if client["client_id"] == client_id:
                del clients[i]
                self.config["clients"] = clients
                self._save_config()
                logger.info(f"客户端已删除: {client_id}")
                return True
        
        logger.error(f"客户端不存在: {client_id}")
        return False
    
    def update_client(self, client_id: str, updates: Dict[str, Any]) -> bool:
        clients = self.get_clients()
        
        for client in clients:
            if client["client_id"] == client_id:
                client.update(updates)
                self.config["clients"] = clients
                self._save_config()
                logger.info(f"客户端已更新: {client_id}")
                return True
        
        logger.error(f"客户端不存在: {client_id}")
        return False
    
    def get_aprs_config(self) -> Dict[str, Any]:
        return self.config.get("aprs", {})
    
    def update_aprs_config(self, updates: Dict[str, Any]) -> bool:
        if "aprs" not in self.config:
            self.config["aprs"] = {}
        self.config["aprs"].update(updates)
        self._save_config()
        return True
    
    def get_serial_config(self) -> Dict[str, Any]:
        return self.config.get("serial", {})
    
    def update_serial_config(self, updates: Dict[str, Any]) -> bool:
        if "serial" not in self.config:
            self.config["serial"] = {}
        self.config["serial"].update(updates)
        self._save_config()
        return True
    
    def get_websocket_config(self) -> Dict[str, Any]:
        return self.config.get("websocket", {})
    
    def update_websocket_config(self, updates: Dict[str, Any]) -> bool:
        if "websocket" not in self.config:
            self.config["websocket"] = {}
        self.config["websocket"].update(updates)
        self._save_config()
        return True
    
    def is_debug(self) -> bool:
        return self.config.get("debug", False)
    
    def set_debug(self, enabled: bool):
        self.config["debug"] = enabled
        self._save_config()
    
    def restore_backup(self, backup_file: str) -> bool:
        try:
            if os.path.exists(backup_file):
                self._backup_config()
                with open(backup_file, 'r', encoding='utf-8') as f:
                    self.config = json.load(f)
                self._save_config()
                logger.info(f"配置已从备份恢复: {backup_file}")
                return True
            else:
                logger.error(f"备份文件不存在: {backup_file}")
                return False
        except Exception as e:
            logger.error(f"恢复备份失败: {e}")
            return False
    
    def list_backups(self) -> List[Dict[str, Any]]:
        backups = []
        if os.path.exists(self.BACKUP_DIR):
            for f in sorted(os.listdir(self.BACKUP_DIR), reverse=True):
                if f.startswith("config_") and f.endswith(".json"):
                    filepath = os.path.join(self.BACKUP_DIR, f)
                    stat = os.stat(filepath)
                    backups.append({
                        "file": filepath,
                        "filename": f,
                        "size": stat.st_size,
                        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat()
                    })
        return backups

config_manager = ConfigManager()
