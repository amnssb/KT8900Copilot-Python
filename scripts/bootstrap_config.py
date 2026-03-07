#!/usr/bin/env python3
import argparse
import json
import os
import secrets
import string
from pathlib import Path


def random_passkey(length: int = 20) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def build_config(
    radio_name: str,
    admin_client_id: str,
    admin_display_name: str,
    admin_passkey: str,
) -> dict:
    return {
        "websocket": {
            "host": "0.0.0.0",
            "port": 8765,
        },
        "radio": {
            "name": radio_name,
        },
        "audio": {
            "input_device": "plughw:1,0",
            "output_device": "plughw:1,0",
            "sample_rate": 16000,
            "channels": 1,
            "chunk_size": 160,
            "buffer_count": 2,
            "period_size": 80,
            "preset": "wideband",
        },
        "serial": {
            "port": "/dev/ttyUSB0",
            "baudrate": 115200,
            "auto_detect": True,
        },
        "clients": [
            {
                "client_id": "esp32_c3_001",
                "client_type": 1,
                "client_name": f"{radio_name} Gateway",
                "passkey": random_passkey(),
                "can_tx": True,
                "can_aprs": False,
            },
            {
                "client_id": admin_client_id,
                "client_type": 3,
                "client_name": admin_display_name,
                "passkey": admin_passkey,
                "can_tx": True,
                "can_aprs": True,
            },
        ],
        "aprs": {
            "enabled": False,
            "my_callsign": "YOURCALL",
            "my_ssid": 0,
            "my_lat": 0.0,
            "my_lon": 0.0,
            "comment": "KT8900Copilot",
            "digipeater": "WIDE1-1,WIDE2-1",
            "beacon_interval": 600,
        },
        "direwolf": {
            "enabled": False,
            "config_file": "/tmp/direwolf.conf",
            "audio_input_device": "plughw:1,0",
            "audio_output_device": "plughw:1,0",
            "baud": 1200,
        },
        "api": {
            "host": "0.0.0.0",
            "port": 8080,
        },
        "debug": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap KT8900 config.json")
    parser.add_argument("--output", required=True, help="Output config path")
    parser.add_argument("--radio-name", required=True, help="Radio station display name")
    parser.add_argument("--admin-id", required=True, help="Default admin client_id")
    parser.add_argument("--admin-name", required=True, help="Default admin display name")
    parser.add_argument("--admin-passkey", required=True, help="Default admin passkey")
    parser.add_argument("--force", action="store_true", help="Overwrite existing config")
    args = parser.parse_args()

    out_path = Path(args.output)
    if out_path.exists() and not args.force:
        print(f"[bootstrap] Skip existing config: {out_path}")
        return 0

    out_path.parent.mkdir(parents=True, exist_ok=True)
    config = build_config(
        radio_name=args.radio_name,
        admin_client_id=args.admin_id,
        admin_display_name=args.admin_name,
        admin_passkey=args.admin_passkey,
    )

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    print(f"[bootstrap] Wrote config: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
