import machine
import utime
import sys

class KT8900Controller:
    def __init__(self):
        # GPIO 配置 - 根据你的接线修改
        self.PTT_PIN = 3
        self.COR_PIN = 10
        
        # PTT 引脚
        self.ptt = machine.Pin(self.PTT_PIN, machine.Pin.OUT)
        self.ptt.value(1)
        
        # COR 引脚
        self.cor = machine.Pin(self.COR_PIN, machine.Pin.IN, machine.Pin.PULL_UP)
        self.last_cor_state = self.cor.value()
        
        # 心跳
        self.heartbeat_interval = 5000
        self.last_heartbeat = utime.ticks_ms()
        self.heartbeat_count = 0
        
        # 命令缓冲
        self.command_buffer = ""
        
        # 状态 LED
        try:
            self.led = machine.Pin(8, machine.Pin.OUT)
            self.led.value(0)
        except:
            self.led = None
        
        print("KT8900 Controller OK")
        print(f"PTT=GPIO{self.PTT_PIN}, COR=GPIO{self.COR_PIN}")
    
    def handle_command(self, cmd):
        cmd = cmd.strip().upper()
        
        if cmd == "PTT_ON":
            self.ptt.value(0)
            print("PTT ON")
            
        elif cmd == "PTT_OFF":
            self.ptt.value(1)
            print("PTT OFF")
            
        elif cmd == "STATUS":
            print(f"COR={self.last_cor_state}, PTT={self.ptt.value()}")
            
        elif cmd == "PING":
            print("PONG")
    
    def check_cor(self):
        current = self.cor.value()
        if current != self.last_cor_state:
            self.last_cor_state = current
            status = 1 if current == 0 else 0
            print(f"COR:{status}")
    
    def run(self):
        print("Running...")
        
        # USB 串口默认已启用，直接用 sys.stdin
        while True:
            self.check_cor()
            
            # 检查虚拟串口
            if sys.stdin:
                try:
                    data = sys.stdin.read(1)
                    if data:
                        self.command_buffer += data
                        if '\n' in self.command_buffer:
                            line, self.command_buffer = self.command_buffer.split('\n', 1)
                            if line.strip():
                                self.handle_command(line)
                except:
                    pass
            
            # 心跳
            if utime.ticks_diff(utime.ticks_ms(), self.last_heartbeat) >= self.heartbeat_interval:
                self.heartbeat_count += 1
                print(f"HB:{self.heartbeat_count}")
                self.last_heartbeat = utime.ticks_ms()
            
            utime.sleep_ms(10)

controller = KT8900Controller()
controller.run()