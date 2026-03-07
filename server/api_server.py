import asyncio
from typing import Optional, Dict, Any
from datetime import datetime
import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

from config_manager import AudioPreset, config_manager
from auth_token import create_ws_token, get_token_secret, DEFAULT_INSECURE_SECRET

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="KT8900 Copilot API",
    description="业余电台远程控制系统管理API",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

server_instance: Any = None
server_task = None

class AudioPresetRequest(BaseModel):
    preset: str

class CustomAudioRequest(BaseModel):
    sample_rate: int
    channels: int = 1
    chunk_size: Optional[int] = None

class ClientCreateRequest(BaseModel):
    client_id: str
    client_type: int
    client_name: str
    passkey: Optional[str] = None
    can_tx: bool = True
    can_aprs: bool = False

class ClientUpdateRequest(BaseModel):
    client_name: Optional[str] = None
    passkey: Optional[str] = None
    can_tx: Optional[bool] = None
    can_aprs: Optional[bool] = None

class APRSConfigRequest(BaseModel):
    enabled: Optional[bool] = None
    my_callsign: Optional[str] = None
    my_ssid: Optional[int] = None
    my_lat: Optional[float] = None
    my_lon: Optional[float] = None
    comment: Optional[str] = None
    digipeater: Optional[str] = None
    beacon_interval: Optional[int] = None

class SerialConfigRequest(BaseModel):
    port: Optional[str] = None
    baudrate: Optional[int] = None
    auto_detect: Optional[bool] = None

class WebSocketConfigRequest(BaseModel):
    host: Optional[str] = None
    port: Optional[int] = None


class WsTokenRequest(BaseModel):
    client_id: str
    passkey: str

@app.get("/")
async def root():
    return {"message": "KT8900 Copilot API", "version": "1.0.0"}

@app.get("/api/status")
async def get_status():
    return {
        "status": "running" if server_instance else "stopped",
        "timestamp": datetime.now().isoformat(),
        "audio": config_manager.get_current_audio_info(),
        "websocket": config_manager.get_websocket_config(),
        "ws_token_enabled": True,
        "ws_token_secret_ok": get_token_secret() != DEFAULT_INSECURE_SECRET,
    }


@app.post("/api/auth/ws-token")
async def issue_ws_token(request: WsTokenRequest):
    clients = config_manager.get_clients()
    target = None
    for c in clients:
        if c.get("client_id") == request.client_id:
            target = c
            break

    if not target or target.get("passkey") != request.passkey:
        raise HTTPException(status_code=401, detail="client_id 或 passkey 错误")

    token = create_ws_token(
        {
            "client_id": target["client_id"],
            "client_name": target.get("client_name", target["client_id"]),
            "client_type": target.get("client_type", 2),
            "can_tx": bool(target.get("can_tx", True)),
            "can_aprs": bool(target.get("can_aprs", False)),
            "token_type": "ws",
        },
        ttl_seconds=120,
    )

    return {
        "status": "success",
        "token": token,
        "expires_in": 120,
    }

@app.get("/api/config")
async def get_config():
    return config_manager.get_config()

@app.put("/api/config")
async def update_config(updates: Dict[str, Any]):
    if config_manager.update_config(updates):
        return {"status": "success", "message": "配置已更新，重启服务生效"}
    raise HTTPException(status_code=400, detail="更新配置失败")

@app.get("/api/audio/info")
async def get_audio_info():
    return config_manager.get_current_audio_info()

@app.get("/api/audio/presets")
async def get_audio_presets():
    return config_manager.get_audio_presets()

@app.post("/api/audio/preset")
async def set_audio_preset(request: AudioPresetRequest):
    try:
        preset = AudioPreset(request.preset)
        if config_manager.set_audio_preset(preset):
            return {"status": "success", "message": f"音频预设已更新为: {preset.value}"}
        raise HTTPException(status_code=400, detail="设置预设失败")
    except ValueError:
        raise HTTPException(status_code=400, detail=f"未知的预设: {request.preset}")

@app.post("/api/audio/custom")
async def set_custom_audio(request: CustomAudioRequest):
    if config_manager.set_custom_audio(request.sample_rate, request.channels, request.chunk_size):
        return {"status": "success", "message": f"自定义音频配置已更新: {request.sample_rate}Hz"}
    raise HTTPException(status_code=400, detail="设置自定义音频失败")

@app.get("/api/clients")
async def get_clients():
    return config_manager.get_clients()

@app.post("/api/clients")
async def add_client(request: ClientCreateRequest):
    if config_manager.add_client(
        request.client_id,
        request.client_type,
        request.client_name,
        request.passkey,
        request.can_tx,
        request.can_aprs
    ):
        return {"status": "success", "message": f"客户端已添加: {request.client_name}"}
    raise HTTPException(status_code=400, detail="添加客户端失败，ID可能已存在")

@app.delete("/api/clients/{client_id}")
async def remove_client(client_id: str):
    if config_manager.remove_client(client_id):
        return {"status": "success", "message": f"客户端已删除: {client_id}"}
    raise HTTPException(status_code=404, detail="客户端不存在")

@app.put("/api/clients/{client_id}")
async def update_client(client_id: str, request: ClientUpdateRequest):
    updates = request.dict(exclude_unset=True)
    if config_manager.update_client(client_id, updates):
        return {"status": "success", "message": f"客户端已更新: {client_id}"}
    raise HTTPException(status_code=404, detail="客户端不存在")

@app.get("/api/aprs")
async def get_aprs_config():
    return config_manager.get_aprs_config()

@app.put("/api/aprs")
async def update_aprs_config(request: APRSConfigRequest):
    updates = request.dict(exclude_unset=True)
    if config_manager.update_aprs_config(updates):
        return {"status": "success", "message": "APRS配置已更新"}
    raise HTTPException(status_code=400, detail="更新APRS配置失败")

@app.get("/api/serial")
async def get_serial_config():
    return config_manager.get_serial_config()

@app.put("/api/serial")
async def update_serial_config(request: SerialConfigRequest):
    updates = request.dict(exclude_unset=True)
    if config_manager.update_serial_config(updates):
        return {"status": "success", "message": "串口配置已更新"}
    raise HTTPException(status_code=400, detail="更新串口配置失败")

@app.get("/api/websocket")
async def get_websocket_config():
    return config_manager.get_websocket_config()

@app.put("/api/websocket")
async def update_websocket_config(request: WebSocketConfigRequest):
    updates = request.dict(exclude_unset=True)
    if config_manager.update_websocket_config(updates):
        return {"status": "success", "message": "WebSocket配置已更新"}
    raise HTTPException(status_code=400, detail="更新WebSocket配置失败")

@app.get("/api/backups")
async def list_backups():
    return config_manager.list_backups()

@app.post("/api/backups/restore")
async def restore_backup(backup_file: str):
    if config_manager.restore_backup(backup_file):
        return {"status": "success", "message": f"配置已从备份恢复: {backup_file}"}
    raise HTTPException(status_code=400, detail="恢复备份失败")

@app.post("/api/backup")
async def create_backup():
    backup_file = config_manager._backup_config()
    return {"status": "success", "message": f"配置已备份: {backup_file}"}

@app.get("/api/debug")
async def get_debug():
    return {"debug": config_manager.is_debug()}

@app.post("/api/debug")
async def set_debug(enabled: bool):
    config_manager.set_debug(enabled)
    return {"status": "success", "message": f"调试模式: {'启用' if enabled else '禁用'}"}

@app.post("/api/server/restart")
async def restart_server():
    global server_instance, server_task
    
    if server_instance and hasattr(server_instance, "stop"):
        await server_instance.stop()
        server_instance = None
    
    await asyncio.sleep(1)
    
    return {"status": "success", "message": "服务器重启中..."}

@app.on_event("startup")
async def startup_event():
    logger.info("KT8900 Copilot API 服务器启动")

@app.on_event("shutdown")
async def shutdown_event():
    global server_instance
    if server_instance and hasattr(server_instance, "stop"):
        await server_instance.stop()
    logger.info("KT8900 Copilot API 服务器关闭")

def run_api_server(host: str = "0.0.0.0", port: int = 8080):
    uvicorn.run(app, host=host, port=port, log_level="info")

if __name__ == "__main__":
    run_api_server()
