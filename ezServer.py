import socket
import threading
import sys
from pathlib import Path
import shutil
import time
from datetime import datetime
import json
import queue
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Dict, Set, Union
from Timer import tm
import random
import re #using re to filter message
from EloSystem import EloSystem
# 设置控制台输出为 UTF-8 编码
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

class ResponseTimeout(Exception):
    """Raised when wait_for_response() times out waiting for data."""


class UnexpectedResponse(Exception):
    """Raised when a received response source differs from what was expected."""


@dataclass
class PendingWaiter:
    expected_src: Set[str]
    event: threading.Event = field(default_factory=threading.Event)
    messages: deque = field(default_factory=deque)
    timeout_at: float = 0.0
    consume: bool = True

    def matches(self, src: str) -> bool:
        return src in self.expected_src

    def add_message(self, msg: dict) -> None:
        self.messages.append(msg)
        self.event.set()


_waiter_tls = threading.local()

count_num = 0

class EzServer:
    def __init__(self, host='127.0.0.1', port=23232):
        self.host = host
        self.port = port
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.connected = False
        self._pending_waiters: Dict[str, PendingWaiter] = {}
        self._general_queue: queue.Queue = queue.Queue()
        self._waiter_lock = threading.Lock()
        self._state_complete = threading.Event()
        
        # Online players
        self.online_players = []

        # Response filters
        self._quiet_unmatched_srcs = {}
        self._auto_process_srcs = {"OnChatMsg"}

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
                        try:
                            # Route decoded JSON messages to registered waiters/queues
                            msg_dict = json.loads(line)
                            self._route_message(msg_dict)
                        except json.JSONDecodeError:
                            print(f'Warning: failed to parse JSON message: {line}')
                            # Preserve raw messages for legacy consumers/debugging
                            self._general_queue.put(line)

                        if not hasattr(self, '_last_cleanup'):
                            self._last_cleanup = time.time()
                            self._msg_count = 0
                        self._msg_count += 1
                        if self._msg_count >= 100 or (time.time() - self._last_cleanup) > 10:
                            self._cleanup_expired_waiters()
                            self._msg_count = 0
                            self._last_cleanup = time.time()
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

    def _route_message(self, msg_dict: dict) -> None:
        """Route incoming messages to waiting handlers or general queue"""
        src = msg_dict.get('src')
        
        if not src:
            self._general_queue.put(msg_dict)
            return
        
        # Match message with pending waiters
        waiters_to_remove = []
        matched = False
        
        with self._waiter_lock:
            for waiter_id, waiter in self._pending_waiters.items():
                if waiter.matches(src):
                    waiter.add_message(msg_dict)
                    matched = True
                    if waiter.consume:
                        waiters_to_remove.append(waiter_id)
        
        # Remove consumed waiters (outside lock for better performance)
        if waiters_to_remove:
            with self._waiter_lock:
                for waiter_id in waiters_to_remove:
                    self._pending_waiters.pop(waiter_id, None)
        
        # Log and handle based on match status
        msg_preview_len = 50 if matched else 200
        match_status = "Matched" if matched else "Unmatched"
        print(f'[INFO] {match_status} message: src="{src}", type={msg_dict.get("type")}, '
            f'msg: {str(msg_dict.get("msg"))[:msg_preview_len]}...')
        
        # Only queue unmatched messages, trying auto-processing first
        if not matched:
            if src in self._auto_process_srcs:
                auto_processed = self._auto_process_message(msg_dict)
                if auto_processed:
                    return  # Don't queue if successfully auto-processed
            
            self._general_queue.put(msg_dict)

    def _cleanup_expired_waiters(self) -> None:
        '''Remove waiters that exceeded their timeout. Called periodically to prevent memory leaks.'''
        with self._waiter_lock:
            current_time = time.time()
            expired = [wid for wid, waiter in self._pending_waiters.items() if current_time > waiter.timeout_at]
            for waiter_id in expired:
                print(f'[WARN] 等待器 {waiter_id} 已超时, 自动清理')
                self._pending_waiters.pop(waiter_id, None)


    def wait_for_response(self, expected_src: Union[str, list], timeout: float = 5.0, consume: bool = True) -> list:    
        """Wait for specific response type(s) from VTOL server. Raises ResponseTimeout on timeout."""
        expected_set: Set[str]
        if isinstance(expected_src, str):
            expected_set = {expected_src}
        else:
            expected_set = set(expected_src)

        if not expected_set:
            raise ValueError('expected_src cannot be empty')

        waiter_id = None
        waiter: Union[PendingWaiter, None] = None
        timeout_at = time.time() + timeout

        with self._waiter_lock:
            # Reuse waiter reserved by send_and_wait (if present) so we do not miss fast responses
            override_id = getattr(_waiter_tls, 'waiter_id', None)
            if override_id is not None:
                setattr(_waiter_tls, 'waiter_id', None)
            if override_id:
                waiter = self._pending_waiters.get(override_id)
                if waiter:
                    waiter.expected_src = expected_set
                    waiter.consume = consume
                    waiter.timeout_at = timeout_at
                    waiter_id = override_id

            if waiter is None:
                waiter_id = f"waiter_{time.time()}_{id(self)}"
                waiter = PendingWaiter(
                    expected_src=expected_set,
                    timeout_at=timeout_at,
                    consume=consume,
                )
                self._pending_waiters[waiter_id] = waiter

        try:
            if not self.connected:
                raise ConnectionError('服务器已断开连接, 无法等待响应')
            event_signaled = waiter.event.wait(timeout)
            if not self.connected:
                raise ConnectionError('服务器已断开连接, 等待过程中断开')
            if event_signaled and waiter.messages:
                messages = list(waiter.messages)
                waiter.messages.clear()
                return messages
            raise ResponseTimeout(f"No response for {expected_set} after {timeout}s")
        finally:
            with self._waiter_lock:
                self._pending_waiters.pop(waiter_id, None)


    def send_and_wait(self, command: str, expected_src: Union[str, list], timeout: float = 5.0) -> list:
        """Send command and wait for response (atomic operation). Prevents race conditions."""
        expected_set: Set[str]
        if isinstance(expected_src, str):
            expected_set = {expected_src}
        else:
            expected_set = set(expected_src)
        if not expected_set:
            raise ValueError('expected_src cannot be empty')

        waiter_id = f"waiter_{time.time()}_{id(self)}"
        waiter = PendingWaiter(
            expected_src=expected_set,
            timeout_at=time.time() + timeout,
            consume=True,
        )

        with self._waiter_lock:
            # Register waiter under this thread so wait_for_response picks it up before routing completes
            self._pending_waiters[waiter_id] = waiter
            setattr(_waiter_tls, 'waiter_id', waiter_id)
            self.send_message(command)

        try:
            return self.wait_for_response(expected_src, timeout)
        finally:
            with self._waiter_lock:
                if getattr(_waiter_tls, 'waiter_id', None) == waiter_id:
                    setattr(_waiter_tls, 'waiter_id', None)
                self._pending_waiters.pop(waiter_id, None)

    def wait_lobby_period(self, seconds: int, on_complete: Callable) -> None:
        '''Start non-blocking lobby timer. Callback fires after duration.'''
        timer_name = f'lobby_{time.time()}_{id(self)}'
        tm.start_timer(timer_name, seconds * 1000, on_complete, single_shot=True)

    def wait_match_duration(self, seconds: int, on_complete: Callable) -> None:
        '''Start non-blocking match timer. Callback fires after duration.'''
        timer_name = f'match_{time.time()}_{id(self)}'
        tm.start_timer(timer_name, seconds * 1000, on_complete, single_shot=True)

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
        # Wake any waiters to avoid deadlocks on disconnect
        with self._waiter_lock:
            if self._pending_waiters:
                print(f'Warning: clearing {len(self._pending_waiters)} pending waiters due to disconnect')
                for waiter in self._pending_waiters.values():
                    waiter.event.set()
                self._pending_waiters.clear()
        self.connected = False
        if self.server:
            self.server.close()
        print('Server stopped')
    
    def _auto_process_message(self, msg_dict: dict) -> bool:
        """Auto-process message if it matches the auto_process_srcs"""
        src = msg_dict.get("src")
        
        # Only process OnChatMsg events
        if src != "OnChatMsg":
            return False
        
        # Extract message content
        msg_content = msg_dict.get("msg")
        if not isinstance(msg_content, dict):
            return False
        
        # Log if auto-processing is enabled
        if src in self._auto_process_srcs:
            print(f'[INFO] Auto-processing message: src="{src}", type={msg_dict.get("type")}, msg: {str(msg_content)[:200]}...')
        
        # Extract player info
        id_dict = msg_content.get("id", {})
        steam_id = id_dict.get("Value")
        msg = msg_content.get("msg", "")
        
        # Regular expressions for event matching
        re_connected = r'^\$log_(.+?) has connected\.$'
        re_disconnected = r'^\$log_(.+?) has disconnected\.$'
        re_kill_event = r'^\$log_([\w ]+?) killed ([A-Za-z0-9/\-]+) \(([^()]+)\) with ([A-Za-z0-9\-]+)\.$'
        
        # Handle connection event
        if m := re.match(re_connected, msg):
            return self._handle_player_connected(m.group(1), steam_id)
        
        # Handle disconnection event
        elif m := re.match(re_disconnected, msg):
            return self._handle_player_disconnected(m.group(1), steam_id)
        
        # Handle kill event
        elif m := re.match(re_kill_event, msg):
            return self._handle_kill_event(
                m.group(1),  # killer name
                m.group(2),  # aircraft
                m.group(3),  # faction
                m.group(4)   # weapon
            )
        
        return False

    def _handle_player_connected(self, playername: str, steam_id: str) -> bool:
        """Handle player connection event"""
        # Check if player already online (by steam_id, not name)
        if any(p["steam_id"] == steam_id for p in self.online_players):
            print(f'[ERROR] Player {playername} (ID: {steam_id}) already connected')
            return False
        
        # Add player
        player_dict = {
            "playername": playername,
            "steam_id": steam_id,
            "in_game_elo": 2000
        }
        self.online_players.append(player_dict)
        
        print(f'[Event] Connected: {playername}')
        self._print_online_players()
        return True

    def _handle_player_disconnected(self, playername: str, steam_id: str) -> bool:
        """Handle player disconnection event"""
        # Find and remove player (safer than modifying during iteration)
        self.online_players = [
            p for p in self.online_players 
            if p["steam_id"] != steam_id
        ]
        
        print(f'[Event] Disconnected: {playername}')
        self._print_online_players()
        return True

    def _handle_kill_event(self, killer_name: str, aircraft: str, faction: str, weapon: str) -> bool:
        """Handle kill event and update ELO"""
        try:
            delta = EloSystem.calculate_elo_change_from_log(
                killer_name, aircraft, faction, weapon
            )
            
            print(f'[Event] Kill Event: {killer_name} killed {aircraft} ({faction}) with {weapon}')
            
            # Update player ELO
            player_found = False
            for player in self.online_players:
                if player["playername"] == killer_name:
                    player["in_game_elo"] += delta
                    player_found = True
                    break
            
            if not player_found:
                print(f'[WARNING] Killer {killer_name} not found in online players')
            
            # Send log to server
            log_msg = f"{killer_name} killed {aircraft} ({faction}) with {weapon} - Elo change: {delta}"
            self.send_message(f"sendlog {log_msg}")
            
            return True
            
        except Exception as e:
            print(f'[ERROR] Error processing kill event: {e}')
            return False

    def _print_online_players(self):
        """Helper to print current online players"""
        print(f"[INFO] Online Players: ")
        for player in self.online_players:
            print(f"  {player['playername']} ({player['steam_id']}) - ELO: {player['in_game_elo']}")

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
    "state6": {"campaign_id":"2860956181", "mapname":"BVR afMtnsHills"},
    "state7": {"campaign_id":"3583755382", "mapname":"Dragon's Valley"},
    "state8": {"campaign_id":"3583755382", "mapname":"Fjord Coast"},
}

def init_server(state:str):
    server.send_message("sethost name " + SERVER_NAME)
    if PUBLIC:
        server.send_message("sethost password")
    else:
        server.send_message("sethost password " + SERVER_PASSWORD)
    if UNIT_ICON:
        server.send_message("sethost uniticon true")
    else:
        server.send_message("sethost uniticon false")
    server.send_message(f"sethost campaign {FSM_MAPS[state]['campaign_id']}")
    server.send_message(f"sethost mission {FSM_MAPS[state]['mapname']}")
    server.send_message("checkhost")
    try:
        server.send_and_wait("config", "HostConfigCoroutine", timeout=60*3)
    except ResponseTimeout as e:
        print(f'[ERROR] config 命令超时: {e}')
        raise
    try:
        time.sleep(1) #看来是必须加这个延迟了，不然会偶发性有bug
        server.send_and_wait("host", "LobbyReady", timeout=60*3)
    except ResponseTimeout as e:
        print(f'[ERROR] host 命令超时: {e}')
        raise

def restart_server(state:str):
    server.send_message(f"sethost campaign {FSM_MAPS[state]['campaign_id']}")
    server.send_message(f"sethost mission {FSM_MAPS[state]['mapname']}")
    time.sleep(1) #看来是必须加这个延迟了，不然会偶发性有bug
    server.send_and_wait("restart", "LobbyReady", timeout=60*3)


def end_state(state:str):
    server.send_message("skip")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    try:
        responses = server.send_and_wait("flightlog", "GetFlightLog", timeout=10)
        raw = responses[0]
    except ResponseTimeout:
        print("没有收到 flightlog 响应,重新获取")
        try:
            responses = server.send_and_wait("flightlog", "GetFlightLog", timeout=10)
            raw = responses[0]
        except ResponseTimeout:
            print("没有收到 flightlog 响应")
            raw = {}

    print("flightlog raw:", raw)

    try:
        if isinstance(raw, dict):
            d = raw
        else:
            d = json.loads(raw)
        src = d.get("src")
        if not src or "GetFlightLog" not in src:
            print("flightlog 响应中没有 GetFlightLog 字段:", d)
            try:
                responses = server.send_and_wait("flightlog", "GetFlightLog", timeout=10)
                raw = responses[0]
                print("flightlog raw:", raw)
                if isinstance(raw, dict):
                    d = raw
                else:
                    d = json.loads(raw)
                src = d.get("src")
                if not src or "GetFlightLog" not in src:
                    print("flightlog 响应中没有 GetFlightLog 字段,退出")
                    return
            except ResponseTimeout:
                print("flightlog 响应中没有 GetFlightLog 字段,退出")
                return
    except json.JSONDecodeError as e:
        print("flightlog JSON 解析失败:", e)
        return

    msg = d.get("msg")
    if msg is None:
        print("flightlog 响应中没有 msg 字段:", d)
        return
    print("flightlog msg:")
    for log in msg:
        print(log)
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

def _test():
    print("Test")
    try:
        responses = server.send_and_wait("checkhost", ["CheckHost", "HostConfig"], timeout=5)
        dict_received_message = responses[0]
    except ResponseTimeout:
        print("checkhost timeout")
        return
    print(dict_received_message.get("msg", "No msg field"))

def _state1():
    global count_num
    print("State 1\n")
    print(f"count_num: {count_num}\n")
    duration = 1 * H2S
    time_prepare = 60 #time for read briefing
    if count_num == 0:
        init_server("state1")
        count_num += 1
    else:
        restart_server("state1")
        count_num += 1
    def on_lobby_complete():
        server.send_message("start")

        def on_match_complete():
            end_state("state1")
            server._state_complete.set()

        server.wait_match_duration(duration, on_match_complete)

    server.wait_lobby_period(time_prepare, on_lobby_complete)

def _state2():
    global count_num
    duration = 1 * H2S
    time_prepare = 60 #time for read briefing
    print("State 2\n")
    print(f"count_num: {count_num}\n")
    if count_num == 0:
        init_server("state2")
        count_num += 1
    else:
        restart_server("state2")
        count_num += 1
    def on_lobby_complete():
        server.send_message("start")

        def on_match_complete():
            end_state("state2")
            server._state_complete.set()

        server.wait_match_duration(duration, on_match_complete)

    server.wait_lobby_period(time_prepare, on_lobby_complete)

def _state3():
    global count_num
    duration = 1 * H2S
    time_prepare = 60 #time for read briefing
    print("State 3\n")
    print(f"count_num: {count_num}\n")
    if count_num == 0:
        init_server("state3")
        count_num += 1
    else:
        restart_server("state3")
        count_num += 1
    def on_lobby_complete():
        server.send_message("start")

        def on_match_complete():
            end_state("state3")
            server._state_complete.set()

        server.wait_match_duration(duration, on_match_complete)

    server.wait_lobby_period(time_prepare, on_lobby_complete)

def _state4():
    global count_num
    duration = 1 * H2S
    time_prepare = 60 #time for read briefing
    print("State 4\n")
    print(f"count_num: {count_num}\n")
    if count_num == 0:
        init_server("state4")
        count_num += 1
    else:
        restart_server("state4")
        count_num += 1
    def on_lobby_complete():
        server.send_message("start")

        def on_match_complete():
            end_state("state4")
            server._state_complete.set()

        server.wait_match_duration(duration, on_match_complete)

    server.wait_lobby_period(time_prepare, on_lobby_complete)

def _state5():
    global count_num
    duration = 1 * H2S
    time_prepare = 60 #time for read briefing
    print("State 5\n")
    print(f"count_num: {count_num}\n")
    if count_num == 0:
        init_server("state5")
        count_num += 1
    else:
        restart_server("state5")
        count_num += 1
    def on_lobby_complete():
        server.send_message("start")

        def on_match_complete():
            end_state("state5")
            server._state_complete.set()

        server.wait_match_duration(duration, on_match_complete)

    server.wait_lobby_period(time_prepare, on_lobby_complete)

def _state6():
    global count_num
    duration = 1 * H2S
    time_prepare = 60 #time for read briefing
    print("State 6\n")
    print(f"count_num: {count_num}\n")
    if count_num == 0:
        init_server("state6")
        count_num += 1
    else:
        restart_server("state6")
        count_num += 1
    def on_lobby_complete():
        server.send_message("start")

        def on_match_complete():
            end_state("state6")
            server._state_complete.set()

        server.wait_match_duration(duration, on_match_complete)

    server.wait_lobby_period(time_prepare, on_lobby_complete)


def _state7():
    global count_num
    duration = 1 * H2S
    time_prepare = 60 #time for read briefing
    print("State 7\n")
    print(f"count_num: {count_num}\n")
    if count_num == 0:
        init_server("state7")
        count_num += 1
    else:
        restart_server("state7")
        count_num += 1
    def on_lobby_complete():
        server.send_message("start")

        def on_match_complete():
            end_state("state7")
            server._state_complete.set()

        server.wait_match_duration(duration, on_match_complete)
    server.wait_lobby_period(time_prepare, on_lobby_complete)

def _state8():
    global count_num
    duration = 1 * H2S
    time_prepare = 60 #time for read briefing
    print("State 8\n")
    print(f"count_num: {count_num}\n")
    if count_num == 0:
        init_server("state8")
        count_num += 1
    else:
        restart_server("state8")
        count_num += 1
    def on_lobby_complete():
        server.send_message("start")

        def on_match_complete():
            end_state("state8")
            server._state_complete.set()

        server.wait_match_duration(duration, on_match_complete)
    server.wait_lobby_period(time_prepare, on_lobby_complete)

def main():
    FSM_Nodes = [_state1, _state2, _state3, _state4, _state5, _state6, _state7, _state8]
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
            server._state_complete.wait()
            server._state_complete.clear()
            continue
    for func in FSM_Nodes[start_index:]:
        func()
        server._state_complete.wait()
        server._state_complete.clear()
    while True:
        for func in FSM_Nodes:
            func()
            server._state_complete.wait()
            server._state_complete.clear()

    
if __name__ == '__main__':
    main()
