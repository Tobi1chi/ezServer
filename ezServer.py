import socket
import threading
import os
import sys
from pathlib import Path
import shutil
import time
from datetime import datetime
import json
import re
import queue
from Timer import tm
import random
# 设置控制台输出为 UTF-8 编码
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

count_num = 0

class EzServer:
    def __init__(self, host='127.0.0.1', port=23232):
        self.host = host
        self.port = port
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.connected = False
        self.received_messages = []
        self.message_lock = threading.Lock()
        self.message_queue = queue.Queue()

    def receive_messages(self):
        buffer = ""
        while self.connected:
            try:
                data = self.server.recv(1024)
                if not data:
                    break
                try:
                    decoded_data = data.decode('utf-8')
                except UnicodeDecodeError:
                    decoded_data = data.decode('utf-8', errors='replace')
                
                buffer += decoded_data
                if buffer and buffer[0] == '\ufeff':
                    buffer = buffer[1:]
                
                while '\n' in buffer:
                    line, buffer = buffer.split('\n', 1)
                    line = line.strip()
                    if line:
                        with self.message_lock:
                            self.received_messages = [line]
                        #print(f"Received: {line}")
            except Exception as e:
                if self.connected:
                    print(f'Receive error: {e}')
                break




    def send_message(self, message):
        if self.connected:
            try:
                self.server.send((message + '\n').encode('utf-8'))
            except Exception as e:
                print(f'Send error: {e}')

    def receive_message(self):
        """拿到最新一条消息，并清空队列"""
        with self.message_lock:
            if not self.received_messages:
                return None
            msg = self.received_messages[-1]   # 取最新的一条
            self.received_messages.clear()     # 清空
            return msg


    def start_server(self):
        try:
            self.server.connect((self.host, self.port))
            self.connected = True
            print(f'Connected to {self.host}:{self.port}')
            threading.Thread(target=self.receive_messages, daemon=True).start()
            return True
        except Exception as e:
            print(f'Connection error: {e}')
            print(f'Failed to connect to {self.host}:{self.port}')
            self.connected = False
            return False
    
    def stop_server(self):
        self.connected = False
        if self.server:
            self.server.close()
        print('Server stopped')
server = EzServer()
S2MS = 1000
MIN2MS = 60 * S2MS
H2MS = 60 * MIN2MS
H2S = 60 * 60

SERVER_NAME = "PvP Server-60min mapcycle"
SERVER_PASSWORD = "2025"
PUBLIC = True
UNIT_ICON = False
BASE_PATH = Path(r"C:\Users\28262\AppData\Roaming\Boundless Dynamics, LLC\VTOLVR\SaveData\Replays")
LOCAL_PATH = Path(__file__).parent
AUTOSAVE_PATH = BASE_PATH / "Autosave1"
DEBUG = False
RAND_MODE = False


FSM_MAPS: dict = {
    "state1": {"campaign_id":"2860956181", "mapname":"BVR Ethi5"},
    "state2": {"campaign_id":"3355613749", "mapname":"MergeLarge"},
    "state3": {"campaign_id":"2860956181", "mapname":"BVR Archipel"},
    "state4": {"campaign_id":"2860956181", "mapname":"BVR Ocixem"},
    "state5": {"campaign_id":"2860956181", "mapname":"BVR Crack"},
    "state6": {"campaign_id":"2860956181", "mapname":"BVR afMtnsHills"}
}

def init_server(state:str):
    server.send_message("sethost name " + SERVER_NAME)
    time.sleep(0.3)
    if PUBLIC:
        server.send_message("sethost password")
    else:
        server.send_message("sethost password " + SERVER_PASSWORD)
    time.sleep(0.3)
    if UNIT_ICON:
        server.send_message("sethost uniticon true")
    else:
        server.send_message("sethost uniticon false")
    time.sleep(0.3)
    server.send_message(f"sethost campaign {FSM_MAPS[state]['campaign_id']}")
    time.sleep(0.3)
    get_message()
    server.send_message(f"sethost mission {FSM_MAPS[state]['mapname']}")
    time.sleep(0.3)
    get_message()
    server.send_message("checkhost")
    time.sleep(0.3)
    get_message()
    time.sleep(0.5)
    server.send_message("config")
    time.sleep(50)
    server.send_message("host")

def restart_server(state:str):
    server.send_message(f"sethost campaign {FSM_MAPS[state]['campaign_id']}")
    time.sleep(0.3)
    server.send_message(f"sethost mission {FSM_MAPS[state]['mapname']}")
    time.sleep(0.3)
    server.send_message("restart")


def end_state(state:str):
    server.send_message("skip")
    time.sleep(0.3)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    server.receive_message() #接收并清空队列
    server.send_message("flightlog")
    time.sleep(0.5)
    raw = server.receive_message()
    print("flightlog raw:", raw)

    if not raw:
        print("没有收到 flightlog 响应,重新获取")
        server.receive_message()
        server.send_message("flightlog")
        time.sleep(0.5)
        raw = server.receive_message()

    if not raw:
        print("没有收到 flightlog 响应")
        raw = "{}"

    try:
        d = json.loads(raw)
        src = d.get("src")
        if "GetFlightLog" not in src:
            print("flightlog 响应中没有 GetFlightLog 字段:", d)
            server.send_message("flightlog")
            time.sleep(0.5)
            raw = server.receive_message()
        d = json.loads(raw)
        src = d.get("src")
        if "GetFlightLog" not in src:
            print("flightlog 响应中没有 GetFlightLog 字段,退出")
            return
    except json.JSONDecodeError as e:
        print("flightlog JSON 解析失败:", e)
        return

    msg = d.get("msg")
    if msg is None:
        print("flightlog 响应中没有 msg 字段:", d)
        return

    print("flightlog msg:", msg)
    # 如果 msg 是列表或字典，转换为 JSON 字符串；如果已经是字符串，直接使用
    if isinstance(msg, (list, dict)):
        msg_str = json.dumps(msg, ensure_ascii=False, indent=2)
    else:
        msg_str = str(msg)
    with open(LOCAL_PATH/'Flightlog_Latest.json', "w", encoding='utf-8') as f:
        f.write(msg_str)
    try:
        copy_folder(AUTOSAVE_PATH, LOCAL_PATH/"Replays"/f"{FSM_MAPS[state]['mapname']}_{timestamp}")
        with open(LOCAL_PATH/"Replays"/f"{FSM_MAPS[state]['mapname']}_{timestamp}/flightlog.json", "w", encoding='utf-8') as f:
            f.write(msg_str)
        time.sleep(1)
        zip_folder(LOCAL_PATH/"Replays"/f"{FSM_MAPS[state]['mapname']}_{timestamp}", LOCAL_PATH/"Replays"/f"{FSM_MAPS[state]['mapname']}_{timestamp}.zip")
        delete_folder(LOCAL_PATH/"Replays"/f"{FSM_MAPS[state]['mapname']}_{timestamp}")
        delete_folder(AUTOSAVE_PATH)

    except Exception as e:
        print(f"保存replay失败: {e}")
        print("单独保存flightlog")
        create_folder(LOCAL_PATH/"Replays"/f"{FSM_MAPS[state]['mapname']}_{timestamp}")
        with open(LOCAL_PATH/"Replays"/f"{FSM_MAPS[state]['mapname']}_{timestamp}/flightlog.json", "w", encoding='utf-8') as f:
            f.write(msg_str)
        zip_folder(LOCAL_PATH/"Replays"/f"{FSM_MAPS[state]['mapname']}_{timestamp}", LOCAL_PATH/"Replays"/f"{FSM_MAPS[state]['mapname']}_{timestamp}.zip")
        delete_folder(LOCAL_PATH/"Replays"/f"{FSM_MAPS[state]['mapname']}_{timestamp}")

    time.sleep(60) #1 分钟玩家复盘时间

def zip_folder(folder: Path, out_zip: Path):
    shutil.make_archive(str(out_zip), "zip", str(folder.parent), folder.name)

def copy_folder(src: Path, dst: Path):
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)

def rename_folder(folder: Path, new_name: str) -> Path:
    new_path = folder.with_name(new_name)
    folder.rename(new_path)
    return new_path

def delete_folder(folder: Path):
    if folder.exists() and folder.is_dir():
        shutil.rmtree(folder)

def create_folder(folder: Path):
    if not folder.exists():
        folder.mkdir(parents=True)

def get_message():
    msg = server.receive_message()
    if msg is None:
        return None
    print(msg)

def _test():
    print("Test")
    server.send_message("checkhost")
    time.sleep(0.2)
    dict_received_message = json.loads(server.receive_message())
    print(dict_received_message["msg"])

def _state1():
    global count_num
    print("State 1\n")
    print(f"count_num: {count_num}\n")
    if count_num == 0:
        init_server("state1")
        count_num += 1
    else:
        restart_server("state1")
        count_num += 1
    time.sleep(60) # 1 minute
    server.send_message("start")
    time.sleep(1*H2S) # 1 hour
    end_state("state1")

def _state2():
    global count_num
    print("State 2\n")
    print(f"count_num: {count_num}\n")
    if count_num == 0:
        init_server("state2")
        count_num += 1
    else:
        restart_server("state2")
        count_num += 1
    time.sleep(60) # 1 minute
    server.send_message("start")
    time.sleep(1*H2S) # 1 hour
    end_state("state2")

def _state3():
    global count_num
    print("State 3\n")
    print(f"count_num: {count_num}\n")
    if count_num == 0:
        init_server("state3")
        count_num += 1
    else:
        restart_server("state3")
        count_num += 1
    time.sleep(60) # 1 minute
    server.send_message("start")
    time.sleep(1*H2S) # 1 hour
    end_state("state3")

def _state4():
    global count_num
    print("State 4\n")
    print(f"count_num: {count_num}\n")
    if count_num == 0:
        init_server("state4")
        count_num += 1
    else:
        restart_server("state4")
        count_num += 1
    time.sleep(60) # 1 minute
    server.send_message("start")
    time.sleep(1*H2S) # 1 hour
    end_state("state4")

def _state5():
    global count_num
    print("State 5\n")
    print(f"count_num: {count_num}\n")
    if count_num == 0:
        init_server("state5")
        count_num += 1
    else:
        restart_server("state5")
        count_num += 1
    time.sleep(60) # 1 minute
    server.send_message("start")
    time.sleep(1*H2S) # 1 hour
    end_state("state5")

def _state6():
    global count_num
    print("State 6\n")
    print(f"count_num: {count_num}\n")
    if count_num == 0:
        init_server("state6")
        count_num += 1
    else:
        restart_server("state6")
        count_num += 1
    time.sleep(60) # 1 minute
    server.send_message("start")
    time.sleep(1*H2S) # 1 hour
    end_state("state6")

def main():
    FSM_Nodes = [_state1, _state2, _state3, _state4, _state5, _state6]
    if not server.start_server():
        print("无法连接到服务器，程序退出")
        return
    _test()
    while DEBUG:
        time.sleep(1)
    
    print("--------------------------------")
    print("已加载的FSM状态:")
    for k, v in FSM_MAPS.items():
        print(k, "=>", v["mapname"])
    print("--------------------------------")
    start_index = input("请输入起始状态(从0开始): ")
    start_index = int(start_index)
    if RAND_MODE:
        while True:
            random.choice(FSM_Nodes)()
            continue
    for func in FSM_Nodes[start_index:]:
        func()
    while True:
        for func in FSM_Nodes:
            func()

    
if __name__ == '__main__':
    main()


