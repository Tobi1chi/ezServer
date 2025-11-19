from operator import ge
import sqlite3
import os
from pathlib import Path
from typing import List, Dict, Union
import json
import datetime
import re 

FLIGHTLOG_DB_PATH = Path(__file__).parent /"DataBase"/"flightlogDB.sqlite"
TEST_PATH = Path(__file__).parent /"MergeLarge_20251114_120521"/"flightlog.json"
DB_DIR = Path(__file__).parent /"DataBase"
#DB_PATH = Path(__file__).parent / "game.db"
DB_PATH = FLIGHTLOG_DB_PATH

class flightlogDB:
    def __init__(self, db_path: Union[Path, str] = DB_PATH):
        self.db_path = db_path
        self.init_db()
        
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
            time_ms     INTEGER NOT NULL,           -- 相对时间（毫秒）
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

    




db_flightlog = flightlogDB()

if __name__ == "__main__":
    db_flightlog.init_db()
    conn = db_flightlog.get_conn()
    cur = conn.cursor()
    print(cur.execute("PRAGMA table_info(players)").fetchall())
    conn.close()
    print(f"数据库初始化完成：{DB_PATH}")
