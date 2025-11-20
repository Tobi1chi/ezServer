from operator import ge
import sqlite3
import os
from pathlib import Path
from typing import List, Dict, Union
import json
import datetime
import re 
from EloSystem import WEAPON_ELO_MULTIPLIER, AIRCRAFT_ELO_MULTIPLIER
FLIGHTLOG_DB_PATH = Path(__file__).parent /"DataBase"/"flightlogDB.sqlite"
TEST_PATH = Path(__file__).parent /"MergeLarge_20251114_120521"/"flightlog.json"
DB_DIR = Path(__file__).parent /"DataBase"
#DB_PATH = Path(__file__).parent / "game.db"
DB_PATH = FLIGHTLOG_DB_PATH
ELO_TYPE = {
    "BVR": "current_elo_BVR",
    "BFM": "current_elo_BFM",
    "PVE": "current_elo_PVE",
}
class flightlogDB:
    def __init__(self, db_path: Union[Path, str] = DB_PATH):
        self.db_path = db_path
        self.init_db()
        self.global_event_history_template = {
            "event_type": "",
            "datetime": "",
            "killer_id": "",
            "killer_name": "",
            "killer_aircraft": "",
            "victim_id": "",
            "victim_name": "",
            "victim_aircraft": "",
            "weapon": "",
            "elo_delta": 0,
        }
        self.replay_info_template = {
            "file_name": "",
            "map_name": "",
            "played_at": "",
            "meta_blob": "",
            "map_type": "",
        }
        
    def get_conn(self):
        """获取一个启用了外键约束的 SQLite 连接"""
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def init_db(self, db_path: Union[Path, str] = DB_PATH):
        """初始化数据库：创建所有表（如果不存在）"""
        if not DB_DIR.exists():
            DB_DIR.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()

        # 开启外键约束（SQLite 默认是关的）
        cur.execute("PRAGMA foreign_keys = ON;")

        cur.executescript(
        """
        -- 玩家表
        CREATE TABLE IF NOT EXISTS players (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            steam_id    TEXT NOT NULL UNIQUE,
            steam_name  TEXT NOT NULL,
            current_elo_BVR REAL NOT NULL DEFAULT 2000,
            current_elo_BFM REAL NOT NULL DEFAULT 50,
            current_elo_PVE REAL NOT NULL DEFAULT 2000,
            created_at  TEXT DEFAULT (datetime('now')),
            is_banned   INTEGER NOT NULL DEFAULT 0,
            is_archived INTEGER NOT NULL DEFAULT 0
        );

        -- 玩家历史昵称
        CREATE TABLE IF NOT EXISTS player_names (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            player_id     INTEGER NOT NULL,
            name          TEXT NOT NULL,
            first_seen_at TEXT,
            last_seen_at  TEXT,
            FOREIGN KEY (player_id) REFERENCES players(id)
        );

        -- 回放
        CREATE TABLE IF NOT EXISTS replays (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            file_name   TEXT NOT NULL,
            map_name    TEXT NOT NULL,
            played_at   TEXT NOT NULL,              -- ISO 字符串，比如 2025-11-15T20:30:00
            meta_blob   BLOB,                       -- 或者你之后改成 meta_path TEXT
            created_at  TEXT DEFAULT (datetime('now'))
        );

        -- 全局事件
        CREATE TABLE IF NOT EXISTS events (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            replay_id   INTEGER NOT NULL,
            event_type  TEXT NOT NULL,              -- 事件类型: BVR_KILL / BFM_KILL / PVE_KILL / ...
            time_local  TEXT NOT NULL,              -- 相对于回放的本地时间（[hh:mm:ss])
            is_valid    INTEGER NOT NULL DEFAULT 1, -- 0/1 当 bool 用
            extra_data  TEXT,                       -- JSON 字符串占位
            weapon      TEXT,                       -- 武器类型（非 KILL 事件可为 NULL）
            kill_type   TEXT,                       -- 击杀类型: 4Gen-4Gen / 4Gen-5Gen /...

            FOREIGN KEY (replay_id) REFERENCES replays(id)
        );

        -- 事件详情（可选扩展 JSON）
        CREATE TABLE IF NOT EXISTS event_details (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id    INTEGER NOT NULL,
            details     TEXT NOT NULL,
            FOREIGN KEY (event_id) REFERENCES events(id)
        );

        -- 玩家-事件关系（谁以什么角色参与了哪条事件）
        CREATE TABLE IF NOT EXISTS player_events (
            player_id   INTEGER NOT NULL,
            event_id    INTEGER NOT NULL,
            role        TEXT NOT NULL,              -- killer / victim / assistant 等

            PRIMARY KEY (player_id, event_id, role),
            FOREIGN KEY (player_id) REFERENCES players(id),
            FOREIGN KEY (event_id) REFERENCES events(id)
        );

        -- Elo 历史
        CREATE TABLE IF NOT EXISTS player_elo_history (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            player_id   INTEGER NOT NULL,
            event_id    INTEGER,
            replay_id   INTEGER,
            at_time     TEXT NOT NULL,              -- 时间戳
            elo_before  REAL,
            elo_after   REAL NOT NULL,

            FOREIGN KEY (player_id) REFERENCES players(id),
            FOREIGN KEY (event_id) REFERENCES events(id),
            FOREIGN KEY (replay_id) REFERENCES replays(id)
        );
        """
    )
        conn.commit()
        conn.close()

    def get_player_by_steam_id(self, steam_id: str, steam_name: str, playername: str) -> Union[dict, None]:
        conn = self.get_conn()
        conn.row_factory = sqlite3.Row  # dict-like row
        cur = conn.cursor()

        # check if player exists
        cur.execute("SELECT * FROM players WHERE steam_id = ?", (steam_id,))
        row = cur.fetchone()

        # if player exists, return player info
        if row is not None:
            player_id = row["id"]

            # get player_names
            name_row = cur.execute(
                "SELECT * FROM player_names WHERE player_id = ?",
                (player_id,)
            ).fetchone()

            if name_row:
                name_list = json.loads(name_row["name"])
            else:
                # create new record
                name_list = []

            # if new name is not in the list, add it
            if playername not in name_list:
                name_list.append(playername)
                cur.execute(
                    "UPDATE player_names SET name = ? WHERE player_id = ?",
                    (json.dumps(name_list), player_id)
                )
                conn.commit()

            # return player info + history names
            result = dict(row)
            result["name_history"] = name_list

            conn.close()
            return result

        # if player does not exist, create new player
        cur.execute(
            "INSERT INTO players (steam_id, steam_name) VALUES (?, ?)",
            (steam_id, steam_name)
        )
        conn.commit()

        # get new player
        cur.execute("SELECT * FROM players WHERE steam_id = ?", (steam_id,))
        new_row = cur.fetchone()
        player_id = new_row["id"]

        # initialize name history
        name_list = [playername]
        cur.execute(
            "INSERT INTO player_names (player_id, name) VALUES (?, ?)",
            (player_id, json.dumps(name_list))
        )
        conn.commit()

        result = dict(new_row)
        result["name_history"] = name_list

        conn.close()
        return result


    def player_join(self, steam_id: str, steam_name: str,playername: str) -> dict:
        #Add more things here if needed
        player = self.get_player_by_steam_id(steam_id, steam_name, playername)
        return player

    def save_global_event_history(self, global_event: list, replay_info: dict, flightlog: list):
        """
        保存全局事件历史
        :param global_event: 事件列表，每个事件包含 event_type, datetime, killer_id, killer_name, 等信息
        :param replay_info: 回放信息字典，包含 file_name, map_name, played_at, meta_blob
        :param flightlog: 原始飞行日志列表
        :return: True/False 表示是否成功
        """
        try:
            conn = self.get_conn()
            cur = conn.cursor()
            valid_map_types = ["BVR", "BFM", "PVE"]
            elo_type = ELO_TYPE.get(replay_info.get("map_type"), "Unknown") #default to BVR
            if elo_type == "Unknown":
                print(f"[ERROR] Unknown map type: {replay_info.get('map_type')}")
                raise ValueError(f"Unknown map type: {replay_info.get('map_type')}")
            # 先存储replay信息
            cur.execute(
                """
                INSERT INTO replays (file_name, map_name, played_at, meta_blob) 
                VALUES (?, ?, ?, ?)
                """,
                (
                    replay_info.get("file_name", ""),
                    replay_info.get("map_name", ""),
                    replay_info.get("played_at", ""),
                    replay_info.get("meta_blob", "")
                )
            )
            replay_id = cur.lastrowid
            
            # 再处理event list
            for event in global_event:
                # 插入事件到 events 表
                cur.execute(
                    """
                    INSERT INTO events 
                    (replay_id, event_type, time_local, is_valid, extra_data, weapon, kill_type) 
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        replay_id,
                        event.get("event_type", ""),
                        event.get("datetime", ""),  # time_local
                        1,  # is_valid - 默认有效
                        json.dumps(event),  # extra_data - 将整个事件序列化为JSON
                        event.get("weapon", ""),
                        self._determine_kill_type(event.get("killer_aircraft", ""), event.get("victim_aircraft", ""))
                    )
                )
                event_id = cur.lastrowid
                
                # 处理 player_events - killer
                if event.get("killer_id"):
                    killer_player = self.get_player_by_steam_id(
                        event.get("killer_id", ""),
                        event.get("killer_name", ""),
                        event.get("killer_name", "")
                    )
                    if killer_player:
                        cur.execute(
                            """
                            INSERT INTO player_events (player_id, event_id, role) 
                            VALUES (?, ?, ?)
                            """,
                            (killer_player["id"], event_id, "killer")
                        )
                
                # 处理 player_events - victim
                if event.get("victim_id"):
                    victim_player = self.get_player_by_steam_id(
                        event.get("victim_id", ""),
                        event.get("victim_name", ""),
                        event.get("victim_name", "")
                    )
                    if victim_player:
                        cur.execute(
                            """
                            INSERT INTO player_events (player_id, event_id, role) 
                            VALUES (?, ?, ?)
                            """,
                            (victim_player["id"], event_id, "victim")
                        )
                
                # 插入 event_details
                cur.execute(
                    """
                    INSERT INTO event_details (event_id, details) 
                    VALUES (?, ?)
                    """,
                    (event_id, json.dumps(event))
                )
                
                # 处理 player_elo_history - killer
                if event.get("killer_id") and killer_player:
                    elo_delta = event.get("elo_delta", 0)
                    cur.execute(
                        """
                        INSERT INTO player_elo_history 
                        (player_id, event_id, replay_id, at_time, elo_before, elo_after) 
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            killer_player["id"],
                            event_id,
                            replay_id,
                            event.get("datetime", ""),
                            killer_player[elo_type],  # 根据事件类型选择相应的ELO
                            killer_player[elo_type] + elo_delta
                        )
                    )
                
                # 处理 player_elo_history - victim
                if event.get("victim_id") and victim_player:
                    elo_delta = event.get("elo_delta", 0)
                    cur.execute(
                        """
                        INSERT INTO player_elo_history 
                        (player_id, event_id, replay_id, at_time, elo_before, elo_after) 
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            victim_player["id"],
                            event_id,
                            replay_id,
                            event.get("datetime", ""),
                            victim_player[elo_type],
                            victim_player[elo_type] - elo_delta
                        )
                    )
            
            conn.commit()
            conn.close()
            return True
            
        except Exception as e:
            print(f"Error saving global event history: {e}")
            conn.rollback()
            conn.close()
            return False
    
    def _determine_kill_type(self, killer_aircraft: str, victim_aircraft: str) -> str:
        """
        根据击杀者和受害者的飞机类型确定击杀类型
        """
        #need more specificaiton here
        kill_type = "General"
        return kill_type

    def update_player_elo(self, online_players: list, map_type:str):
        """
        Update player Elo based on the online players list
        :param online_players: list of online players
        :param map_type: string of map type (BVR, BFM, PVE)
        """
        conn = self.get_conn()
        cur = conn.cursor()
        elo_type = ELO_TYPE.get(map_type, "Unknown")
        for player in online_players:
            steam_id = player.get("steam_id")
            player_name = player.get("name")
            player_elo = player.get("in_game_elo")
            player_elo_history = sum(player.get("ingame_elo_history"))
            cur.execute(
                f"""
                SELECT {elo_type} FROM players WHERE steam_id = ?
                """,
                (steam_id,)
            )
            db_elo = cur.fetchone()
            if db_elo is not player_elo:
                print(f"[ERROR] Player {player_name} (ID: {steam_id}) Elo is not correct: {player_elo} != {cur.fetchone()}")
                print("[Database] Database contains wrong Elo value")
                raise ValueError(f"Player {player_name} (ID: {steam_id}) Elo is not correct: {player_elo} != {cur.fetchone()}")
            else:
                cur.execute(
                    f"""
                    UPDATE players SET {elo_type} = ? WHERE steam_id = ?
                    """,
                    (player_elo_history + db_elo, steam_id)
                )
                conn.commit()
                print(f"[Database] Player {player_name} (ID: {steam_id}) Elo updated to {player_elo_history + db_elo}")
        
        conn.close()
        return True
            



db_flightlog = flightlogDB()

if __name__ == "__main__":
    db_flightlog.init_db()
    conn = db_flightlog.get_conn()
    cur = conn.cursor()
    print(cur.execute("PRAGMA table_info(players)").fetchall())
    conn.close()
    print(f"数据库初始化完成：{DB_PATH}")
