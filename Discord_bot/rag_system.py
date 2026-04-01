"""
RAG (Retrieval-Augmented Generation) 系统
用于自然语言查询 -> SQL -> AI 总结的完整流程
"""

import sqlite3
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
import sys

# 添加父目录到路径
sys.path.append(str(Path(__file__).parent.parent))
from DB import FLIGHTLOG_DB_PATH, ELO_TYPE


@dataclass
class QueryPlan:
    sql: str
    params: List[Any]


class IntentDetector:
    """意图识别器 - 将自然语言转换为结构化意图"""
    
    # 意图类型定义
    INTENT_TYPES = {
        "player_recent_performance": "查询玩家最近表现",
        "player_stats_summary": "查询玩家统计摘要",
        "player_elo_trend": "查询玩家Elo趋势",
        "map_leaderboard": "查询地图排行榜",
        "recent_battles": "查询最近战斗",
        "weapon_analysis": "查询武器分析",
        "player_comparison": "玩家对比",
        "battle_report": "战报生成",
        "activity_analysis": "活跃度分析",
        "combat_style": "战斗风格分析",
    }
    
    # 关键词映射
    KEYWORDS = {
        "player_recent_performance": [("表现", 3), ("战绩", 3), ("成绩", 3), ("最近", 1), ("近期", 1)],
        "player_stats_summary": [("统计", 3), ("数据", 2), ("总览", 3), ("概况", 3), ("信息", 1)],
        "player_elo_trend": [("elo", 4), ("分数", 3), ("趋势", 4), ("变化", 3), ("排名", 1)],
        "map_leaderboard": [("排行", 4), ("排名", 3), ("最好", 3), ("最强", 3), ("第一", 4), ("榜单", 4)],
        "recent_battles": [("战斗", 3), ("对局", 3), ("比赛", 2), ("交战", 3)],
        "weapon_analysis": [("武器", 4), ("装备", 2), ("导弹", 3), ("枪", 2)],
        "player_comparison": [("对比", 4), ("比较", 4), ("vs", 4)],
        "battle_report": [("战报", 5), ("总结", 3), ("报告", 2), ("战况", 5), ("复盘", 4)],
        "activity_analysis": [("活跃", 5), ("在线", 3), ("参与", 3)],
        "combat_style": [("风格", 4), ("打法", 4), ("特点", 3), ("习惯", 3)],
    }
    
    # 地图类型关键词
    MAP_TYPES = {
        "BVR": ["bvr", "超视距", "远程"],
        "BFM": ["bfm", "格斗", "近战", "狗斗"],
        "PVE": ["pve", "ai", "电脑"],
    }
    
    def detect(self, query: str) -> Dict[str, Any]:
        """
        检测用户查询的意图
        :param query: 用户的自然语言查询
        :return: 结构化的意图字典
        """
        query_lower = query.lower()
        
        # 提取玩家名称（简单实现，可以改进）
        player_names = self._extract_player_names(query)
        
        # 提取地图类型
        map_type = self._extract_map_type(query_lower)
        
        # 提取时间范围
        time_range = self._extract_time_range(query_lower)
        
        # 提取数量限制
        limit = self._extract_limit(query_lower)
        
        # 检测意图类型
        intent_type = self._detect_intent_type(query_lower)
        
        return {
            "intent": intent_type,
            "players": player_names,
            "map_type": map_type,
            "time_range": time_range,
            "limit": limit,
            "original_query": query,
        }
    
    def _detect_intent_type(self, query: str) -> str:
        """检测意图类型"""
        if "战况" in query or ("总结" in query and ("这局" in query or "最近" in query)):
            return "battle_report"

        scores = {}
        for intent, keywords in self.KEYWORDS.items():
            score = sum(weight for keyword, weight in keywords if keyword in query)
            if score > 0:
                scores[intent] = score
        
        if scores:
            return max(scores, key=scores.get)
        return "player_stats_summary"  # 默认意图
    
    def _extract_player_names(self, query: str) -> List[str]:
        """提取玩家名称（简单实现）"""
        candidates = []

        quoted_names = re.findall(r'["“](.+?)["”]', query)
        candidates.extend(quoted_names)

        explicit_player = re.findall(r'玩家[:：]?\s*([^\s，。！？,]{1,20})', query)
        candidates.extend(explicit_player)

        latin_tokens = re.findall(r'[A-Za-z][A-Za-z0-9_\-]{1,31}', query)
        ignored = {"BVR", "BFM", "PVE", "AI", "SQL"}
        for token in latin_tokens:
            if token.upper() not in ignored:
                candidates.append(token)

        unique_candidates = []
        for candidate in candidates:
            normalized = candidate.strip()
            if normalized and normalized not in unique_candidates:
                unique_candidates.append(normalized)
        return unique_candidates
    
    def _extract_map_type(self, query: str) -> Optional[str]:
        """提取地图类型"""
        for map_type, keywords in self.MAP_TYPES.items():
            if any(keyword in query for keyword in keywords):
                return map_type
        return None
    
    def _extract_time_range(self, query: str) -> Optional[str]:
        """提取时间范围"""
        if "今天" in query or "今日" in query:
            return "today"
        elif "昨天" in query:
            return "yesterday"
        elif "最近一周" in query or "近一周" in query or "最近7天" in query:
            return "this_week"
        elif "本周" in query or "这周" in query:
            return "this_week"
        elif "上周" in query:
            return "last_week"
        elif "本月" in query or "这个月" in query:
            return "this_month"
        return None
    
    def _extract_limit(self, query: str) -> int:
        """提取数量限制"""
        # 查找数字
        numbers = re.findall(r'\d+', query)
        if numbers:
            return min(int(numbers[0]), 50)  # 最大50条
        return 20  # 默认20条


class SQLGenerator:
    """SQL 生成器 - 根据意图生成 SQL 查询"""
    
    def __init__(self, db_path=FLIGHTLOG_DB_PATH):
        self.db_path = db_path
    
    def generate(self, intent: Dict[str, Any]) -> str:
        return self.generate_plan(intent).sql

    def generate_plan(self, intent: Dict[str, Any]) -> QueryPlan:
        """
        根据意图生成SQL查询
        :param intent: 意图字典
        :return: SQL查询字符串
        """
        intent_type = intent.get("intent", "player_stats_summary")
        
        # 根据不同意图生成不同的SQL
        generators = {
            "player_recent_performance": self._gen_recent_performance,
            "player_stats_summary": self._gen_stats_summary,
            "player_elo_trend": self._gen_elo_trend,
            "map_leaderboard": self._gen_leaderboard,
            "recent_battles": self._gen_recent_battles,
            "weapon_analysis": self._gen_weapon_analysis,
            "player_comparison": self._gen_player_comparison,
            "battle_report": self._gen_battle_report,
            "activity_analysis": self._gen_activity_analysis,
            "combat_style": self._gen_combat_style,
        }
        
        generator = generators.get(intent_type, self._gen_stats_summary)
        return generator(intent)

    def _build_filter_clauses(
        self,
        intent: Dict[str, Any],
        *,
        player_expr: str,
        player_id_expr: str,
        event_type_expr: Optional[str],
        time_expr: str,
    ) -> Tuple[List[str], List[Any]]:
        clauses: List[str] = []
        params: List[Any] = []

        players = intent.get("players", [])
        if players:
            player_clauses = []
            for player in players:
                player_clauses.append(
                    f"(LOWER({player_expr}) LIKE LOWER(?) OR EXISTS ("
                    f"SELECT 1 FROM player_names pn WHERE pn.player_id = {player_id_expr} AND LOWER(pn.name) LIKE LOWER(?)"
                    f"))"
                )
                pattern = f"%{player}%"
                params.extend([pattern, pattern])
            clauses.append("(" + " OR ".join(player_clauses) + ")")

        map_type = intent.get("map_type")
        if map_type and event_type_expr:
            clauses.append(f"{event_type_expr} LIKE ?")
            params.append(f"{map_type.upper()}_%")

        time_clauses, time_params = self._build_time_filters(intent.get("time_range"), time_expr)
        clauses.extend(time_clauses)
        params.extend(time_params)
        return clauses, params

    def _build_time_filters(self, time_range: Optional[str], time_expr: str) -> Tuple[List[str], List[str]]:
        if not time_range:
            return [], []

        now = datetime.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        clauses: List[str] = []
        params: List[str] = []

        if time_range == "today":
            clauses.append(f"{time_expr} >= ?")
            params.append(today_start.strftime("%Y%m%d_%H%M%S"))
        elif time_range == "yesterday":
            yesterday_start = today_start - timedelta(days=1)
            clauses.extend([f"{time_expr} >= ?", f"{time_expr} < ?"])
            params.extend([
                yesterday_start.strftime("%Y%m%d_%H%M%S"),
                today_start.strftime("%Y%m%d_%H%M%S"),
            ])
        elif time_range == "this_week":
            week_start = today_start - timedelta(days=today_start.weekday())
            clauses.append(f"{time_expr} >= ?")
            params.append(week_start.strftime("%Y%m%d_%H%M%S"))
        elif time_range == "last_week":
            this_week_start = today_start - timedelta(days=today_start.weekday())
            last_week_start = this_week_start - timedelta(days=7)
            clauses.extend([f"{time_expr} >= ?", f"{time_expr} < ?"])
            params.extend([
                last_week_start.strftime("%Y%m%d_%H%M%S"),
                this_week_start.strftime("%Y%m%d_%H%M%S"),
            ])
        elif time_range == "this_month":
            month_start = today_start.replace(day=1)
            clauses.append(f"{time_expr} >= ?")
            params.append(month_start.strftime("%Y%m%d_%H%M%S"))

        return clauses, params

    def _compose_query(self, base_sql: str, clauses: List[str], order_and_limit_sql: str, params: List[Any]) -> QueryPlan:
        sql = base_sql
        if clauses:
            sql += "\nWHERE " + "\n  AND ".join(clauses)
        sql += "\n" + order_and_limit_sql.strip() + "\n"
        return QueryPlan(sql=sql, params=params)
    
    def _gen_recent_performance(self, intent: Dict) -> QueryPlan:
        """生成最近表现查询"""
        limit = intent.get("limit", 20)
        
        base_sql = """
        SELECT 
            p.steam_name,
            r.map_name,
            r.played_at,
            e.event_type,
            e.weapon,
            e.kill_type,
            pe.role,
            eh.elo_before,
            eh.elo_after,
            (eh.elo_after - eh.elo_before) as elo_change
        FROM player_events pe
        JOIN events e ON pe.event_id = e.id
        JOIN replays r ON e.replay_id = r.id
        JOIN players p ON pe.player_id = p.id
        LEFT JOIN player_elo_history eh ON eh.event_id = e.id AND eh.player_id = p.id
        """
        clauses, params = self._build_filter_clauses(
            intent,
            player_expr="p.steam_name",
            player_id_expr="p.id",
            event_type_expr="e.event_type",
            time_expr="r.played_at",
        )
        return self._compose_query(
            base_sql,
            clauses,
            f"ORDER BY r.played_at DESC, e.time_local DESC\nLIMIT {limit}",
            params,
        )
    
    def _gen_stats_summary(self, intent: Dict) -> QueryPlan:
        """生成统计摘要查询"""
        limit = intent.get("limit", 20)
        
        base_sql = """
        SELECT 
            p.id,
            p.steam_name,
            p.current_elo_BVR,
            p.current_elo_BFM,
            p.current_elo_PVE,
            COUNT(DISTINCT CASE WHEN pe.role = 'killer' THEN e.id END) as total_kills,
            COUNT(DISTINCT CASE WHEN pe.role = 'victim' THEN e.id END) as total_deaths,
            COUNT(DISTINCT r.id) as total_matches,
            MAX(r.played_at) as last_played
        FROM players p
        LEFT JOIN player_events pe ON p.id = pe.player_id
        LEFT JOIN events e ON pe.event_id = e.id
        LEFT JOIN replays r ON e.replay_id = r.id
        """
        clauses, params = self._build_filter_clauses(
            intent,
            player_expr="p.steam_name",
            player_id_expr="p.id",
            event_type_expr="e.event_type",
            time_expr="r.played_at",
        )
        return self._compose_query(
            base_sql,
            clauses,
            f"GROUP BY p.id\nORDER BY p.current_elo_BVR DESC\nLIMIT {limit}",
            params,
        )
    
    def _gen_elo_trend(self, intent: Dict) -> QueryPlan:
        """生成Elo趋势查询"""
        limit = intent.get("limit", 50)
        
        base_sql = """
        SELECT 
            p.steam_name,
            eh.at_time,
            eh.elo_before,
            eh.elo_after,
            (eh.elo_after - eh.elo_before) as elo_change,
            e.event_type,
            r.map_name
        FROM player_elo_history eh
        JOIN players p ON eh.player_id = p.id
        LEFT JOIN events e ON eh.event_id = e.id
        LEFT JOIN replays r ON r.id = COALESCE(eh.replay_id, e.replay_id)
        """
        clauses, params = self._build_filter_clauses(
            intent,
            player_expr="p.steam_name",
            player_id_expr="p.id",
            event_type_expr="e.event_type",
            time_expr="eh.at_time",
        )
        return self._compose_query(
            base_sql,
            clauses,
            f"ORDER BY eh.at_time DESC\nLIMIT {limit}",
            params,
        )
    
    def _gen_leaderboard(self, intent: Dict) -> QueryPlan:
        """生成排行榜查询"""
        limit = intent.get("limit", 10)
        map_type = (intent.get("map_type") or "BVR").upper()
        elo_field = ELO_TYPE.get(map_type, ELO_TYPE["BVR"])
        
        base_sql = f"""
        SELECT 
            p.steam_name,
            p.{elo_field} as elo,
            COUNT(DISTINCT CASE WHEN pe.role = 'killer' THEN e.id END) as kills,
            COUNT(DISTINCT CASE WHEN pe.role = 'victim' THEN e.id END) as deaths,
            ROUND(
                CAST(COUNT(DISTINCT CASE WHEN pe.role = 'killer' THEN e.id END) AS FLOAT) / 
                NULLIF(COUNT(DISTINCT CASE WHEN pe.role = 'victim' THEN e.id END), 0),
                2
            ) as kd_ratio
        FROM players p
        LEFT JOIN player_events pe ON p.id = pe.player_id
        LEFT JOIN events e ON pe.event_id = e.id
        LEFT JOIN replays r ON e.replay_id = r.id
        """
        clauses, params = self._build_filter_clauses(
            intent,
            player_expr="p.steam_name",
            player_id_expr="p.id",
            event_type_expr="e.event_type",
            time_expr="r.played_at",
        )
        clauses.insert(0, "p.is_archived = 0")
        return self._compose_query(
            base_sql,
            clauses,
            f"GROUP BY p.id\nORDER BY p.{elo_field} DESC\nLIMIT {limit}",
            params,
        )
    
    def _gen_recent_battles(self, intent: Dict) -> QueryPlan:
        """生成最近战斗查询"""
        limit = intent.get("limit", 10)
        
        base_sql = """
        SELECT 
            r.id as replay_id,
            r.map_name,
            r.played_at,
            COUNT(DISTINCT e.id) as total_events,
            COUNT(DISTINCT pe.player_id) as total_players,
            GROUP_CONCAT(DISTINCT p.steam_name) as players
        FROM replays r
        LEFT JOIN events e ON r.id = e.replay_id
        LEFT JOIN player_events pe ON e.id = pe.event_id
        LEFT JOIN players p ON pe.player_id = p.id
        """
        clauses, params = self._build_filter_clauses(
            intent,
            player_expr="p.steam_name",
            player_id_expr="p.id",
            event_type_expr="e.event_type",
            time_expr="r.played_at",
        )
        return self._compose_query(
            base_sql,
            clauses,
            f"GROUP BY r.id\nORDER BY r.played_at DESC\nLIMIT {limit}",
            params,
        )
    
    def _gen_weapon_analysis(self, intent: Dict) -> QueryPlan:
        """生成武器分析查询"""
        limit = intent.get("limit", 20)
        
        base_sql = """
        SELECT 
            e.weapon,
            COUNT(*) as usage_count,
            COUNT(DISTINCT pe.player_id) as unique_users,
            e.kill_type,
            AVG(eh.elo_after - eh.elo_before) as avg_elo_change
        FROM events e
        JOIN player_events pe ON e.id = pe.event_id AND pe.role = 'killer'
        JOIN players p ON pe.player_id = p.id
        JOIN replays r ON e.replay_id = r.id
        LEFT JOIN player_elo_history eh ON e.id = eh.event_id AND pe.player_id = eh.player_id
        """
        clauses, params = self._build_filter_clauses(
            intent,
            player_expr="p.steam_name",
            player_id_expr="p.id",
            event_type_expr="e.event_type",
            time_expr="r.played_at",
        )
        clauses.insert(0, "e.weapon IS NOT NULL AND e.weapon != ''")
        return self._compose_query(
            base_sql,
            clauses,
            f"GROUP BY e.weapon, e.kill_type\nORDER BY usage_count DESC\nLIMIT {limit}",
            params,
        )
    
    def _gen_player_comparison(self, intent: Dict) -> QueryPlan:
        """生成玩家对比查询"""
        # 这个需要特殊处理，暂时返回基础统计
        return self._gen_stats_summary(intent)
    
    def _gen_battle_report(self, intent: Dict) -> QueryPlan:
        """生成战报查询"""
        clauses, params = self._build_filter_clauses(
            intent,
            player_expr="p.steam_name",
            player_id_expr="p.id",
            event_type_expr="e.event_type",
            time_expr="r.played_at",
        )
        where_sql = ""
        if clauses:
            where_sql = "WHERE " + " AND ".join(clauses)

        sql = f"""
        WITH latest_replay AS (
            SELECT r.id
            FROM replays r
            JOIN events e ON r.id = e.replay_id
            LEFT JOIN player_events pe ON e.id = pe.event_id
            LEFT JOIN players p ON pe.player_id = p.id
            {where_sql}
            GROUP BY r.id
            ORDER BY r.played_at DESC
            LIMIT 1
        )
        SELECT 
            r.id,
            r.map_name,
            r.played_at,
            e.event_type,
            e.time_local,
            p_killer.steam_name as killer_name,
            p_victim.steam_name as victim_name,
            e.weapon,
            e.kill_type,
            ed.details
        FROM latest_replay lr
        JOIN replays r ON lr.id = r.id
        JOIN events e ON r.id = e.replay_id
        LEFT JOIN player_events pe_killer ON e.id = pe_killer.event_id AND pe_killer.role = 'killer'
        LEFT JOIN player_events pe_victim ON e.id = pe_victim.event_id AND pe_victim.role = 'victim'
        LEFT JOIN players p_killer ON pe_killer.player_id = p_killer.id
        LEFT JOIN players p_victim ON pe_victim.player_id = p_victim.id
        LEFT JOIN event_details ed ON e.id = ed.event_id
        ORDER BY e.time_local ASC
        """
        return QueryPlan(sql=sql, params=params)
    
    def _gen_activity_analysis(self, intent: Dict) -> QueryPlan:
        """生成活跃度分析查询"""
        limit = intent.get("limit", 10)
        
        base_sql = """
        SELECT 
            p.steam_name,
            COUNT(DISTINCT r.id) as matches_played,
            COUNT(DISTINCT substr(r.played_at, 1, 8)) as active_days,
            MIN(r.played_at) as first_match,
            MAX(r.played_at) as last_match,
            COUNT(DISTINCT e.id) as total_events
        FROM players p
        JOIN player_events pe ON p.id = pe.player_id
        JOIN events e ON pe.event_id = e.id
        JOIN replays r ON e.replay_id = r.id
        """
        clauses, params = self._build_filter_clauses(
            intent,
            player_expr="p.steam_name",
            player_id_expr="p.id",
            event_type_expr="e.event_type",
            time_expr="r.played_at",
        )
        return self._compose_query(
            base_sql,
            clauses,
            f"GROUP BY p.id\nORDER BY matches_played DESC\nLIMIT {limit}",
            params,
        )
    
    def _gen_combat_style(self, intent: Dict) -> QueryPlan:
        """生成战斗风格分析查询"""
        base_sql = """
        SELECT 
            p.steam_name,
            e.weapon,
            COUNT(*) as weapon_usage,
            e.kill_type,
            COUNT(DISTINCT r.map_name) as maps_played,
            AVG(eh.elo_after - eh.elo_before) as avg_elo_per_kill
        FROM players p
        JOIN player_events pe ON p.id = pe.player_id AND pe.role = 'killer'
        JOIN events e ON pe.event_id = e.id
        JOIN replays r ON e.replay_id = r.id
        LEFT JOIN player_elo_history eh ON e.id = eh.event_id AND p.id = eh.player_id
        """
        clauses, params = self._build_filter_clauses(
            intent,
            player_expr="p.steam_name",
            player_id_expr="p.id",
            event_type_expr="e.event_type",
            time_expr="r.played_at",
        )
        return self._compose_query(
            base_sql,
            clauses,
            "GROUP BY p.id, e.weapon, e.kill_type\nORDER BY weapon_usage DESC\nLIMIT 50",
            params,
        )


class RAGExecutor:
    """RAG 执行器 - 执行 SQL 并准备数据供 AI 总结"""
    
    def __init__(self, db_path=FLIGHTLOG_DB_PATH):
        self.db_path = db_path
    
    def execute(self, sql: str, params: Optional[List[Any]] = None) -> Tuple[List[Dict], List[str]]:
        """
        执行SQL查询
        :param sql: SQL查询字符串
        :return: (数据列表, 列名列表)
        """
        sql_to_run = sql.strip()
        # 只允许只读查询，避免执行非 SELECT 语句
        if not sql_to_run.lower().startswith(("select", "with")):
            print(f"[ERROR] 仅允许执行SELECT查询，收到: {sql_to_run[:50]}...")
            return [], []

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        try:
            cur.execute(sql, params or [])
            rows = cur.fetchall()
            
            if not rows:
                return [], []
            
            # 获取列名
            columns = [description[0] for description in cur.description]
            
            # 转换为字典列表
            results = [dict(row) for row in rows]
            
            return results, columns
            
        except Exception as e:
            print(f"[ERROR] SQL执行错误: {e}")
            print(f"[ERROR] SQL: {sql}")
            return [], []
        finally:
            conn.close()
    
    def format_for_llm(self, data: List[Dict], columns: List[str], intent: Dict) -> str:
        """
        将查询结果格式化为适合LLM处理的文本
        :param data: 查询结果数据
        :param columns: 列名
        :param intent: 原始意图
        :return: 格式化的文本
        """
        if not data:
            return "没有找到相关数据。"
        
        # 构建上下文
        context = f"用户查询：{intent.get('original_query', '')}\n\n"
        context += f"查询意图：{intent.get('intent', '')}\n\n"
        context += f"查询结果（共{len(data)}条记录）：\n\n"
        
        # 格式化数据
        for i, row in enumerate(data, 1):
            context += f"记录 {i}:\n"
            for key, value in row.items():
                context += f"  {key}: {value}\n"
            context += "\n"
        
        # 添加总结指令
        context += "\n请根据以上数据，用简洁清晰的中文生成总结或战报。"
        
        return context


class RAGSystem:
    """完整的 RAG 系统 - 整合所有组件"""
    
    def __init__(self, db_path=FLIGHTLOG_DB_PATH):
        self.intent_detector = IntentDetector()
        self.sql_generator = SQLGenerator(db_path)
        self.rag_executor = RAGExecutor(db_path)
    
    def process_query(self, query: str) -> Dict[str, Any]:
        """
        处理用户查询的完整流程
        :param query: 用户的自然语言查询
        :return: 包含所有中间结果和最终数据的字典
        """
        # 1. 意图识别
        intent = self.intent_detector.detect(query)
        print(f"[RAG] 检测到意图: {intent}")
        
        # 2. 生成SQL
        query_plan = self.sql_generator.generate_plan(intent)
        print(f"[RAG] 生成SQL: {query_plan.sql[:100]}...")
        
        # 3. 执行SQL
        data, columns = self.rag_executor.execute(query_plan.sql, query_plan.params)
        print(f"[RAG] 查询到 {len(data)} 条记录")
        
        # 4. 格式化为LLM上下文
        llm_context = self.rag_executor.format_for_llm(data, columns, intent)
        
        return {
            "intent": intent,
            "sql": query_plan.sql,
            "params": query_plan.params,
            "data": data,
            "columns": columns,
            "llm_context": llm_context,
            "success": len(data) > 0,
        }


# ============================================================
# 测试代码
# ============================================================

if __name__ == "__main__":
    rag = RAGSystem()
    
    # 测试查询
    test_queries = [
        "查一下最近的BVR表现",
        "谁在排行榜第一？",
        "最近一周谁最活跃？",
        "帮我总结一下最近这局的战况",
    ]
    
    for query in test_queries:
        print(f"\n{'='*60}")
        print(f"测试查询: {query}")
        print(f"{'='*60}")
        
        result = rag.process_query(query)
        
        print(f"\n意图: {result['intent']}")
        print(f"\nSQL:\n{result['sql']}")
        print(f"\n数据条数: {len(result['data'])}")
        if result['data']:
            print(f"\n第一条数据: {result['data'][0]}")
