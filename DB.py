import sqlite3
import os
from pathlib import Path
import json
import datetime
import re 

FLIGHTLOG_DB_PATH = Path(__file__).parent /"DB"/"flightlogDB.sqlite"
TEST_PATH = Path(__file__).parent /"MergeLarge_20251114_120521"/"flightlog.json"
DB_DIR = Path(__file__).parent /"DB"
#DB_PATH = Path(__file__).parent / "game.db"
DB_PATH = FLIGHTLOG_DB_PATH

class flightlogDB:
    def __init__(self, db_path: Path | str = DB_PATH):
        self.db_path = db_path
        self.init_db()
        
    def get_conn(self):
        """获取一个启用了外键约束的 SQLite 连接"""
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def init_db(self, db_path: Path | str = DB_PATH):
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
            current_elo REAL,
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
            map_name    TEXT NOT NULL,
            played_at   TEXT NOT NULL,              -- ISO 字符串，比如 2025-11-15T20:30:00
            meta_blob   BLOB,                       -- 或者你之后改成 meta_path TEXT
            created_at  TEXT DEFAULT (datetime('now'))
        );

        -- 全局事件
        CREATE TABLE IF NOT EXISTS events (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            replay_id   INTEGER NOT NULL,
            event_type  TEXT NOT NULL,              -- 事件类型: KILL / MISSILE_LAUNCH / ...
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


def insert_kill_event(
    replay_id: int,
    time_ms: int,
    killer_player_id: int,
    victim_player_id: int,
    weapon: str | None = None,
    kill_type: str | None = None,
    extra_data: str | None = None,
) -> int:
    """
    往数据库插入一条 KILL 事件。
    整个过程是一个事务：要么全部成功，要么全部回滚。
    返回新插入的 event_id。
    """
    conn = flightlogDB.get_conn()
    cur = conn.cursor()

    try:
        # 开启事务
        conn.execute("BEGIN")

        # 1. 插入 events 表
        cur.execute(
            """
            INSERT INTO events (
                replay_id,
                event_type,
                time_ms,
                is_valid,
                extra_data,
                weapon,
                kill_type
            )
            VALUES (?, ?, ?, 1, ?, ?, ?)
            """,
            (replay_id, "KILL", time_ms, extra_data, weapon, kill_type),
        )
        event_id = cur.lastrowid

        # 2. 插入 player_events：killer
        cur.execute(
            """
            INSERT INTO player_events (player_id, event_id, role)
            VALUES (?, ?, ?)
            """,
            (killer_player_id, event_id, "killer"),
        )

        # 3. 插入 player_events：victim
        cur.execute(
            """
            INSERT INTO player_events (player_id, event_id, role)
            VALUES (?, ?, ?)
            """,
            (victim_player_id, event_id, "victim"),
        )

        # 全部 OK → 提交事务
        conn.commit()
        return event_id

    except Exception:
        # 任意一步失败 → 回滚之前所有修改
        conn.rollback()
        raise

    finally:
        conn.close()



db_flightlog = flightlogDB()

if __name__ == "__main__":
    db_flightlog.init_db()
    print(f"数据库初始化完成：{DB_PATH}")
