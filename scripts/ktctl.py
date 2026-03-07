#!/usr/bin/env python3
import argparse
import sys
import os
import json
import subprocess
import signal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.config_manager import ConfigManager, AudioPreset, AUDIO_PRESETS

CONFIG_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'server', 'config.json')

class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    END = '\033[0m'
    BOLD = '\033[1m'

def print_header(text):
    print(f"\n{Colors.HEADER}{Colors.BOLD}{'='*50}{Colors.END}")
    print(f"{Colors.HEADER}{Colors.BOLD}{text.center(50)}{Colors.END}")
    print(f"{Colors.HEADER}{Colors.BOLD}{'='*50}{Colors.END}\n")

def print_success(text):
    print(f"{Colors.GREEN}✓ {text}{Colors.END}")

def print_error(text):
    print(f"{Colors.RED}✗ {text}{Colors.END}")

def print_info(text):
    print(f"{Colors.CYAN}ℹ {text}{Colors.END}")

def print_warning(text):
    print(f"{Colors.YELLOW}⚠ {text}{Colors.END}")

def cmd_status(args):
    print_header("KT8900 Copilot 状态")
    
    manager = ConfigManager(CONFIG_FILE)
    config = manager.get_config()
    audio_info = manager.get_current_audio_info()
    
    print(f"{Colors.BOLD}音频配置:{Colors.END}")
    print(f"  采样率: {audio_info['sample_rate']} Hz")
    print(f"  声道数: {audio_info['channels']}")
    print(f"  比特率: {audio_info['bitrate_kbps']} kbps")
    print(f"  预设: {audio_info.get('preset', 'custom')}")
    
    print(f"\n{Colors.BOLD}网络配置:{Colors.END}")
    ws = config.get('websocket', {})
    print(f"  WebSocket: {ws.get('host', '0.0.0.0')}:{ws.get('port', 8765)}")
    
    print(f"\n{Colors.BOLD}串口配置:{Colors.END}")
    serial = config.get('serial', {})
    print(f"  端口: {serial.get('port', '/dev/ttyUSB0')}")
    print(f"  波特率: {serial.get('baudrate', 115200)}")
    print(f"  自动检测: {'是' if serial.get('auto_detect', True) else '否'}")
    
    print(f"\n{Colors.BOLD}APRS 配置:{Colors.END}")
    aprs = config.get('aprs', {})
    print(f"  状态: {'启用' if aprs.get('enabled', False) else '禁用'}")
    if aprs.get('enabled'):
        callsign = aprs.get('my_callsign', '')
        ssid = aprs.get('my_ssid', 0)
        print(f"  呼号: {callsign}-{ssid}" if ssid else f"  呼号: {callsign}")
    
    print(f"\n{Colors.BOLD}客户端数量:{Colors.END} {len(config.get('clients', []))}")
    
    print(f"\n{Colors.BOLD}调试模式:{Colors.END} {'启用' if config.get('debug', False) else '禁用'}")

def cmd_audio_list(args):
    print_header("音频预设列表")
    
    print(f"{'预设名称':<15} {'采样率':<12} {'比特率':<12} {'描述'}")
    print("-" * 60)
    
    for preset, config in AUDIO_PRESETS.items():
        print(f"{config['name']:<15} {config['sample_rate']}Hz{'':<5} {config['bitrate_kbps']}kbps{'':<4} {config['description']}")
    
    print(f"\n使用方法: ktctl.py audio set <preset>")
    print(f"例如: ktctl.py audio set wideband")

def cmd_audio_set(args):
    manager = ConfigManager(CONFIG_FILE)
    
    try:
        preset = AudioPreset(args.preset.lower())
        if manager.set_audio_preset(preset):
            preset_config = AUDIO_PRESETS[preset]
            print_success(f"音频预设已设置为: {preset_config['name']}")
            print_info(f"采样率: {preset_config['sample_rate']} Hz")
            print_info(f"比特率: {preset_config['bitrate_kbps']} kbps")
            print_warning("重启服务使配置生效")
        else:
            print_error("设置音频预设失败")
    except ValueError:
        print_error(f"未知的预设: {args.preset}")
        print_info("可用预设: narrowband, wideband, hd_voice, cd_quality")

def cmd_audio_custom(args):
    manager = ConfigManager(CONFIG_FILE)
    
    valid_rates = [8000, 16000, 22050, 24000, 44100, 48000]
    if args.sample_rate not in valid_rates:
        print_error(f"无效的采样率: {args.sample_rate}")
        print_info(f"有效采样率: {', '.join(map(str, valid_rates))}")
        return
    
    if manager.set_custom_audio(args.sample_rate, args.channels, args.chunk_size):
        print_success(f"自定义音频配置已设置")
        print_info(f"采样率: {args.sample_rate} Hz")
        print_info(f"声道数: {args.channels}")
        if args.chunk_size:
            print_info(f"块大小: {args.chunk_size}")
        print_warning("重启服务使配置生效")
    else:
        print_error("设置自定义音频失败")

def cmd_audio_info(args):
    manager = ConfigManager(CONFIG_FILE)
    audio_info = manager.get_current_audio_info()
    
    print_header("音频配置详情")
    print(f"采样率: {audio_info['sample_rate']} Hz")
    print(f"声道数: {audio_info['channels']}")
    print(f"块大小: {audio_info['chunk_size']}")
    print(f"比特率: {audio_info['bitrate_kbps']} kbps")
    print(f"预设: {audio_info.get('preset', 'custom')}")

def cmd_client_list(args):
    manager = ConfigManager(CONFIG_FILE)
    clients = manager.get_clients()
    
    print_header("客户端列表")
    
    type_names = {1: 'ESP32', 2: '用户', 3: '管理员'}
    
    print(f"{'ID':<20} {'名称':<15} {'类型':<10} {'权限'}")
    print("-" * 60)
    
    for client in clients:
        client_type = type_names.get(client['client_type'], str(client['client_type']))
        permissions = []
        if client.get('can_tx', True):
            permissions.append('发射')
        if client.get('can_aprs', False):
            permissions.append('APRS')
        perms_str = ', '.join(permissions) or '无'
        
        print(f"{client['client_id']:<20} {client['client_name']:<15} {client_type:<10} {perms_str}")

def cmd_client_add(args):
    manager = ConfigManager(CONFIG_FILE)
    
    if manager.add_client(
        args.client_id,
        args.type,
        args.name,
        args.passkey,
        args.can_tx,
        args.can_aprs
    ):
        print_success(f"客户端已添加: {args.name}")
        if not args.passkey:
            clients = manager.get_clients()
            for c in clients:
                if c['client_id'] == args.client_id:
                    print_info(f"自动生成的密钥: {c['passkey']}")
                    break
    else:
        print_error(f"添加客户端失败，ID 可能已存在: {args.client_id}")

def cmd_client_remove(args):
    manager = ConfigManager(CONFIG_FILE)
    
    if manager.remove_client(args.client_id):
        print_success(f"客户端已删除: {args.client_id}")
    else:
        print_error(f"客户端不存在: {args.client_id}")

def cmd_config_show(args):
    manager = ConfigManager(CONFIG_FILE)
    config = manager.get_config()
    
    print_header("完整配置")
    print(json.dumps(config, indent=2, ensure_ascii=False))

def cmd_config_backup(args):
    manager = ConfigManager(CONFIG_FILE)
    backup_file = manager._backup_config()
    print_success(f"配置已备份: {backup_file}")

def cmd_config_restore(args):
    manager = ConfigManager(CONFIG_FILE)
    
    if manager.restore_backup(args.backup_file):
        print_success(f"配置已从备份恢复: {args.backup_file}")
    else:
        print_error("恢复备份失败")

def cmd_config_backups(args):
    manager = ConfigManager(CONFIG_FILE)
    backups = manager.list_backups()
    
    print_header("配置备份列表")
    
    if not backups:
        print_info("暂无备份")
        return
    
    print(f"{'文件名':<35} {'大小':<10} {'修改时间'}")
    print("-" * 70)
    
    for backup in backups:
        print(f"{backup['filename']:<35} {backup['size']} bytes  {backup['modified']}")

def cmd_aprs_config(args):
    manager = ConfigManager(CONFIG_FILE)
    aprs_config = manager.get_aprs_config()
    
    print_header("APRS 配置")
    print(f"状态: {'启用' if aprs_config.get('enabled', False) else '禁用'}")
    print(f"呼号: {aprs_config.get('my_callsign', '')}")
    print(f"SSID: {aprs_config.get('my_ssid', 0)}")
    print(f"纬度: {aprs_config.get('my_lat', 0.0)}")
    print(f"经度: {aprs_config.get('my_lon', 0.0)}")
    print(f"信标间隔: {aprs_config.get('beacon_interval', 600)} 秒")

def cmd_aprs_set(args):
    manager = ConfigManager(CONFIG_FILE)
    
    updates = {}
    if args.enabled is not None:
        updates['enabled'] = args.enabled
    if args.callsign:
        updates['my_callsign'] = args.callsign
    if args.ssid is not None:
        updates['my_ssid'] = args.ssid
    if args.lat is not None:
        updates['my_lat'] = args.lat
    if args.lon is not None:
        updates['my_lon'] = args.lon
    if args.interval is not None:
        updates['beacon_interval'] = args.interval
    
    if updates and manager.update_aprs_config(updates):
        print_success("APRS 配置已更新")
        for key, value in updates.items():
            print_info(f"  {key}: {value}")
    else:
        print_error("更新 APRS 配置失败")

def cmd_serial_config(args):
    manager = ConfigManager(CONFIG_FILE)
    serial_config = manager.get_serial_config()
    
    print_header("串口配置")
    print(f"端口: {serial_config.get('port', '/dev/ttyUSB0')}")
    print(f"波特率: {serial_config.get('baudrate', 115200)}")
    print(f"自动检测: {'是' if serial_config.get('auto_detect', True) else '否'}")

def cmd_serial_set(args):
    manager = ConfigManager(CONFIG_FILE)
    
    updates = {}
    if args.port:
        updates['port'] = args.port
    if args.baudrate:
        updates['baudrate'] = args.baudrate
    if args.auto_detect is not None:
        updates['auto_detect'] = args.auto_detect
    
    if updates and manager.update_serial_config(updates):
        print_success("串口配置已更新")
        for key, value in updates.items():
            print_info(f"  {key}: {value}")
    else:
        print_error("更新串口配置失败")

def cmd_websocket_config(args):
    manager = ConfigManager(CONFIG_FILE)
    ws_config = manager.get_websocket_config()
    
    print_header("WebSocket 配置")
    print(f"主机: {ws_config.get('host', '0.0.0.0')}")
    print(f"端口: {ws_config.get('port', 8765)}")

def cmd_websocket_set(args):
    manager = ConfigManager(CONFIG_FILE)
    
    updates = {}
    if args.host:
        updates['host'] = args.host
    if args.port:
        updates['port'] = args.port
    
    if updates and manager.update_websocket_config(updates):
        print_success("WebSocket 配置已更新")
        for key, value in updates.items():
            print_info(f"  {key}: {value}")
    else:
        print_error("更新 WebSocket 配置失败")

def cmd_debug(args):
    manager = ConfigManager(CONFIG_FILE)
    
    if args.enable is None:
        status = "启用" if manager.is_debug() else "禁用"
        print_info(f"调试模式: {status}")
    else:
        manager.set_debug(args.enable)
        status = "启用" if args.enable else "禁用"
        print_success(f"调试模式已{status}")

def cmd_server_start(args):
    print_header("启动 KT8900 Copilot 服务")
    
    server_dir = os.path.dirname(CONFIG_FILE)
    main_script = os.path.join(server_dir, 'main.py')
    
    if not os.path.exists(main_script):
        print_error(f"找不到主服务文件: {main_script}")
        return
    
    try:
        print_info(f"启动服务...")
        subprocess.run([sys.executable, main_script], cwd=server_dir)
    except KeyboardInterrupt:
        print_info("\n服务已停止")

def cmd_api_start(args):
    print_header("启动管理 API 服务")
    
    server_dir = os.path.dirname(CONFIG_FILE)
    api_script = os.path.join(server_dir, 'api_server.py')
    
    try:
        host = args.host or '0.0.0.0'
        port = args.port or 8080
        print_info(f"API 服务地址: http://{host}:{port}")
        print_info("API 文档: http://localhost:8080/docs")
        subprocess.run([sys.executable, api_script, '--host', host, '--port', str(port)], cwd=server_dir)
    except KeyboardInterrupt:
        print_info("\nAPI 服务已停止")

def main():
    parser = argparse.ArgumentParser(
        description='KT8900 Copilot 管理工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  ktctl.py status                    # 查看系统状态
  ktctl.py audio set wideband        # 设置音频预设
  ktctl.py audio custom -r 16000     # 自定义音频采样率
  ktctl.py client list               # 列出所有客户端
  ktctl.py client add esp01 -n "ESP32" -t 1   # 添加客户端
  ktctl.py server start              # 启动主服务
  ktctl.py api start                 # 启动管理 API
"""
    )
    
    subparsers = parser.add_subparsers(dest='command', help='命令')
    
    status_parser = subparsers.add_parser('status', help='查看系统状态')
    status_parser.set_defaults(func=cmd_status)
    
    audio_parser = subparsers.add_parser('audio', help='音频配置管理')
    audio_sub = audio_parser.add_subparsers(dest='audio_command')
    
    audio_list = audio_sub.add_parser('list', help='列出音频预设')
    audio_list.set_defaults(func=cmd_audio_list)
    
    audio_set = audio_sub.add_parser('set', help='设置音频预设')
    audio_set.add_argument('preset', help='预设名称 (narrowband/wideband/hd_voice/cd_quality)')
    audio_set.set_defaults(func=cmd_audio_set)
    
    audio_custom = audio_sub.add_parser('custom', help='自定义音频配置')
    audio_custom.add_argument('-r', '--sample-rate', type=int, required=True, help='采样率')
    audio_custom.add_argument('-c', '--channels', type=int, default=1, help='声道数')
    audio_custom.add_argument('--chunk-size', type=int, help='块大小')
    audio_custom.set_defaults(func=cmd_audio_custom)
    
    audio_info = audio_sub.add_parser('info', help='显示当前音频配置')
    audio_info.set_defaults(func=cmd_audio_info)
    
    client_parser = subparsers.add_parser('client', help='客户端管理')
    client_sub = client_parser.add_subparsers(dest='client_command')
    
    client_list = client_sub.add_parser('list', help='列出客户端')
    client_list.set_defaults(func=cmd_client_list)
    
    client_add = client_sub.add_parser('add', help='添加客户端')
    client_add.add_argument('client_id', help='客户端 ID')
    client_add.add_argument('-n', '--name', required=True, help='客户端名称')
    client_add.add_argument('-t', '--type', type=int, default=2, help='类型 (1=ESP32, 2=用户, 3=管理员)')
    client_add.add_argument('-p', '--passkey', help='密钥（不指定则自动生成）')
    client_add.add_argument('--no-tx', action='store_false', dest='can_tx', help='禁止发射')
    client_add.add_argument('--can-aprs', action='store_true', help='允许 APRS')
    client_add.set_defaults(func=cmd_client_add, can_tx=True, can_aprs=False)
    
    client_remove = client_sub.add_parser('remove', help='删除客户端')
    client_remove.add_argument('client_id', help='客户端 ID')
    client_remove.set_defaults(func=cmd_client_remove)
    
    config_parser = subparsers.add_parser('config', help='配置管理')
    config_sub = config_parser.add_subparsers(dest='config_command')
    
    config_show = config_sub.add_parser('show', help='显示完整配置')
    config_show.set_defaults(func=cmd_config_show)
    
    config_backup = config_sub.add_parser('backup', help='备份配置')
    config_backup.set_defaults(func=cmd_config_backup)
    
    config_restore = config_sub.add_parser('restore', help='恢复配置')
    config_restore.add_argument('backup_file', help='备份文件路径')
    config_restore.set_defaults(func=cmd_config_restore)
    
    config_backups = config_sub.add_parser('backups', help='列出备份')
    config_backups.set_defaults(func=cmd_config_backups)
    
    aprs_parser = subparsers.add_parser('aprs', help='APRS 配置')
    aprs_sub = aprs_parser.add_subparsers(dest='aprs_command')
    
    aprs_config = aprs_sub.add_parser('show', help='显示 APRS 配置')
    aprs_config.set_defaults(func=cmd_aprs_config)
    
    aprs_set = aprs_sub.add_parser('set', help='设置 APRS 配置')
    aprs_set.add_argument('--enable', action='store_true', dest='enabled', help='启用 APRS')
    aprs_set.add_argument('--disable', action='store_false', dest='enabled', help='禁用 APRS')
    aprs_set.add_argument('--callsign', help='呼号')
    aprs_set.add_argument('--ssid', type=int, help='SSID')
    aprs_set.add_argument('--lat', type=float, help='纬度')
    aprs_set.add_argument('--lon', type=float, help='经度')
    aprs_set.add_argument('--interval', type=int, help='信标间隔（秒）')
    aprs_set.set_defaults(func=cmd_aprs_set, enabled=None)
    
    serial_parser = subparsers.add_parser('serial', help='串口配置')
    serial_sub = serial_parser.add_subparsers(dest='serial_command')
    
    serial_config = serial_sub.add_parser('show', help='显示串口配置')
    serial_config.set_defaults(func=cmd_serial_config)
    
    serial_set = serial_sub.add_parser('set', help='设置串口配置')
    serial_set.add_argument('--port', help='串口设备')
    serial_set.add_argument('--baudrate', type=int, help='波特率')
    serial_set.add_argument('--auto-detect', action='store_true', dest='auto_detect', help='自动检测')
    serial_set.add_argument('--no-auto-detect', action='store_false', dest='auto_detect', help='禁用自动检测')
    serial_set.set_defaults(func=cmd_serial_set, auto_detect=None)
    
    ws_parser = subparsers.add_parser('websocket', help='WebSocket 配置')
    ws_sub = ws_parser.add_subparsers(dest='websocket_command')
    
    ws_config = ws_sub.add_parser('show', help='显示 WebSocket 配置')
    ws_config.set_defaults(func=cmd_websocket_config)
    
    ws_set = ws_sub.add_parser('set', help='设置 WebSocket 配置')
    ws_set.add_argument('--host', help='监听主机')
    ws_set.add_argument('--port', type=int, help='监听端口')
    ws_set.set_defaults(func=cmd_websocket_set)
    
    debug_parser = subparsers.add_parser('debug', help='调试模式')
    debug_parser.add_argument('--enable', action='store_true', dest='enable', help='启用')
    debug_parser.add_argument('--disable', action='store_false', dest='enable', help='禁用')
    debug_parser.set_defaults(func=cmd_debug, enable=None)
    
    server_parser = subparsers.add_parser('server', help='服务管理')
    server_sub = server_parser.add_subparsers(dest='server_command')
    
    server_start = server_sub.add_parser('start', help='启动主服务')
    server_start.set_defaults(func=cmd_server_start)
    
    api_parser = subparsers.add_parser('api', help='管理 API 服务')
    api_sub = api_parser.add_subparsers(dest='api_command')
    
    api_start = api_sub.add_parser('start', help='启动管理 API')
    api_start.add_argument('--host', default='0.0.0.0', help='监听主机')
    api_start.add_argument('--port', type=int, default=8080, help='监听端口')
    api_start.set_defaults(func=cmd_api_start)
    
    args = parser.parse_args()
    
    if hasattr(args, 'func'):
        args.func(args)
    else:
        parser.print_help()

if __name__ == '__main__':
    main()
