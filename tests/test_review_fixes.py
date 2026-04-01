import tempfile
import unittest
from pathlib import Path

from DB import flightlogDB
from Discord_bot.bot_commands import BotCommands, PlayerStatsService
from Discord_bot.rag_system import IntentDetector, RAGExecutor, SQLGenerator
from ezServer import EzServer, build_replay_info


class ReviewFixesTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "flightlog.sqlite"
        self.db = flightlogDB(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_save_global_event_history_handles_new_players_in_single_transaction(self):
        replay_info = {
            "file_name": "demo.zip",
            "map_name": "Demo",
            "played_at": "20260401_120000",
            "meta_blob": b"",
            "map_type": "BVR",
        }
        global_event = [
            {
                "event_type": "BVR_KILL",
                "datetime": "2026-04-01 12:10:00",
                "killer_id": "killer-steam",
                "killer_name": "Killer",
                "killer_aircraft": "F-45A",
                "victim_id": "victim-steam",
                "victim_name": "Victim",
                "victim_aircraft": "F/A-26B",
                "weapon": "AIM-120D",
                "elo_delta": 8.0,
            }
        ]

        self.assertTrue(self.db.save_global_event_history(global_event, replay_info, []))

        conn = self.db.get_conn()
        cur = conn.cursor()
        players = cur.execute("SELECT steam_id FROM players ORDER BY steam_id").fetchall()
        events = cur.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        conn.close()

        self.assertEqual(players, [("killer-steam",), ("victim-steam",)])
        self.assertEqual(events, 1)

    def test_player_name_resolution_prefers_exact_match_and_rejects_ambiguous_partial(self):
        self.db.get_player_by_steam_id("steam-1", "AlphaPilot", "Alpha")
        self.db.get_player_by_steam_id("steam-2", "AlphaWolf", "Wolf")
        service = PlayerStatsService(self.db_path)

        exact_player, exact_error = service.resolve_player_by_name("AlphaPilot")
        self.assertIsNotNone(exact_player)
        self.assertIsNone(exact_error)
        self.assertEqual(exact_player["steam_id"], "steam-1")

        ambiguous_player, ambiguous_error = service.resolve_player_by_name("Alph")
        self.assertIsNone(ambiguous_player)
        self.assertIn("匹配到多个玩家", ambiguous_error)

    def test_chat_embed_includes_short_ai_reply(self):
        cog = BotCommands.__new__(BotCommands)
        cog.chat_messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "world"},
        ]

        embed = BotCommands._build_chat_response_embed(cog, "hello", "short reply")
        fields = [(field.name, field.value) for field in embed.fields]

        self.assertIn(("🔮 AI回复", "short reply"), fields)

    def test_intent_detection_and_query_plan_apply_requested_filters(self):
        detector = IntentDetector()
        intent = detector.detect("查一下Tobiichi最近10场BVR的表现")
        plan = SQLGenerator().generate_plan(intent)

        self.assertEqual(intent["intent"], "player_recent_performance")
        self.assertEqual(intent["players"], ["Tobiichi"])
        self.assertEqual(intent["map_type"], "BVR")
        self.assertIn("LOWER(p.steam_name) LIKE LOWER(?)", plan.sql)
        self.assertIn("e.event_type LIKE ?", plan.sql)
        self.assertIn("%Tobiichi%", plan.params)
        self.assertIn("BVR_%", plan.params)

        activity_intent = detector.detect("最近一周谁最活跃？")
        self.assertEqual(activity_intent["intent"], "activity_analysis")
        self.assertEqual(activity_intent["time_range"], "this_week")

    def test_rag_executor_allows_cte_queries(self):
        executor = RAGExecutor(self.db_path)
        rows, columns = executor.execute(
            "WITH t AS (SELECT 1 AS value) SELECT value FROM t"
        )

        self.assertEqual(columns, ["value"])
        self.assertEqual(rows, [{"value": 1}])

    def test_rag_executor_rejects_mutating_cte_queries(self):
        executor = RAGExecutor(self.db_path)
        rows, columns = executor.execute(
            "WITH doomed AS (SELECT 1) DELETE FROM players"
        )

        self.assertEqual(rows, [])
        self.assertEqual(columns, [])

    def test_elo_trend_uses_history_timestamp_format_for_time_filters(self):
        detector = IntentDetector()
        intent = detector.detect("查看Tobiichi本周elo趋势")
        plan = SQLGenerator().generate_plan(intent)

        self.assertEqual(intent["intent"], "player_elo_trend")
        self.assertEqual(intent["time_range"], "this_week")
        self.assertRegex(plan.params[-1], r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")

    def test_elo_keyword_is_not_treated_as_player_name(self):
        detector = IntentDetector()
        intent = detector.detect("查看本周elo趋势")
        plan = SQLGenerator().generate_plan(intent)

        self.assertEqual(intent["intent"], "player_elo_trend")
        self.assertEqual(intent["players"], [])
        self.assertNotIn("%elo%", [str(param).lower() for param in plan.params])

    def test_missing_online_player_kill_event_returns_false_without_crashing(self):
        server = EzServer()
        try:
            server.current_state = "state2"
            server.online_players = [
                {
                    "playername": "Killer",
                    "steam_id": "killer-steam",
                    "in_game_elo": 2000,
                    "ingame_elo_history": [],
                    "Teams": "Allied",
                    "connected": True,
                }
            ]

            self.assertFalse(server._handle_kill_event("Killer", "F-45A", "MissingVictim", "AIM-120D"))
            self.assertEqual(server.global_event_history, [])
        finally:
            server.server.close()

    def test_build_replay_info_tolerates_missing_archive(self):
        replay_info = build_replay_info("state1", "20260401_120000", None)
        self.assertEqual(replay_info["meta_blob"], b"")
        self.assertEqual(replay_info["file_name"], "MergeLarge_20260401_120000.zip")


if __name__ == "__main__":
    unittest.main()
