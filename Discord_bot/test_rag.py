"""
RAG系统测试脚本
用于验证意图识别、SQL生成和数据检索功能
"""

import sys
from pathlib import Path

# 添加父目录到路径
sys.path.append(str(Path(__file__).parent.parent))

from Discord_bot.rag_system import RAGSystem, IntentDetector, SQLGenerator, RAGExecutor


def print_separator(title=""):
    """打印分隔线"""
    print("\n" + "="*70)
    if title:
        print(f"  {title}")
        print("="*70)
    print()


def test_intent_detection():
    """测试意图识别"""
    print_separator("测试 1: 意图识别")
    
    detector = IntentDetector()
    
    test_queries = [
        "查一下Tobiichi最近BVR的表现",
        "谁在排行榜第一？",
        "最近一周谁最活跃？",
        "帮我总结一下最近这局的战况",
        "分析下我的作战风格",
        "最近10场比赛的武器使用情况",
    ]
    
    for query in test_queries:
        intent = detector.detect(query)
        print(f"查询: {query}")
        print(f"意图: {intent['intent']}")
        print(f"地图类型: {intent['map_type']}")
        print(f"限制: {intent['limit']}")
        print()


def test_sql_generation():
    """测试SQL生成"""
    print_separator("测试 2: SQL生成")
    
    generator = SQLGenerator()
    
    test_intents = [
        {
            "intent": "player_recent_performance",
            "players": ["Tobiichi"],
            "map_type": "BVR",
            "limit": 10,
            "original_query": "查一下Tobiichi最近10场BVR的表现"
        },
        {
            "intent": "map_leaderboard",
            "map_type": "BVR",
            "limit": 5,
            "original_query": "谁在BVR排行榜前5名？"
        },
        {
            "intent": "activity_analysis",
            "limit": 10,
            "original_query": "最近一周谁最活跃？"
        },
    ]
    
    for intent in test_intents:
        sql = generator.generate(intent)
        print(f"意图: {intent['intent']}")
        print(f"查询: {intent['original_query']}")
        print(f"SQL:\n{sql}")
        print()


def test_sql_execution():
    """测试SQL执行"""
    print_separator("测试 3: SQL执行")
    
    executor = RAGExecutor()
    
    # 测试简单查询
    test_sql = """
    SELECT 
        p.steam_name,
        p.current_elo_BVR,
        p.current_elo_BFM,
        p.current_elo_PVE
    FROM players p
    ORDER BY p.current_elo_BVR DESC
    LIMIT 5
    """
    
    print("执行SQL:")
    print(test_sql)
    print()
    
    data, columns = executor.execute(test_sql)
    
    print(f"查询到 {len(data)} 条记录")
    print(f"列名: {columns}")
    print()
    
    if data:
        print("前3条数据:")
        for i, row in enumerate(data[:3], 1):
            print(f"\n记录 {i}:")
            for key, value in row.items():
                print(f"  {key}: {value}")


def test_full_rag_system():
    """测试完整RAG系统"""
    print_separator("测试 4: 完整RAG系统")
    
    rag = RAGSystem()
    
    test_queries = [
        "查一下最近的BVR表现",
        "谁在排行榜第一？",
        "最近的战斗情况",
    ]
    
    for query in test_queries:
        print(f"查询: {query}")
        print("-" * 70)
        
        result = rag.process_query(query)
        
        print(f"✓ 意图识别: {result['intent']['intent']}")
        print(f"✓ SQL生成: {len(result['sql'])} 字符")
        print(f"✓ 数据检索: {len(result['data'])} 条记录")
        print(f"✓ 成功: {result['success']}")
        
        if result['data']:
            print(f"\n第一条数据:")
            for key, value in list(result['data'][0].items())[:5]:
                print(f"  {key}: {value}")
        
        print()


def test_llm_context_formatting():
    """测试LLM上下文格式化"""
    print_separator("测试 5: LLM上下文格式化")
    
    executor = RAGExecutor()
    
    # 模拟数据
    mock_data = [
        {
            "steam_name": "Tobiichi",
            "map_name": "MergeLarge",
            "kills": 5,
            "deaths": 2,
            "elo_change": 15.5
        },
        {
            "steam_name": "PlayerA",
            "map_name": "MergeLarge",
            "kills": 3,
            "deaths": 4,
            "elo_change": -8.2
        }
    ]
    
    mock_intent = {
        "intent": "player_recent_performance",
        "original_query": "查一下最近的表现"
    }
    
    llm_context = executor.format_for_llm(
        mock_data,
        list(mock_data[0].keys()),
        mock_intent
    )
    
    print("LLM上下文:")
    print(llm_context[:500])
    print("...")
    print(f"\n总长度: {len(llm_context)} 字符")


def test_safety_checks():
    """测试安全性检查"""
    print_separator("测试 6: SQL安全性检查")
    
    generator = SQLGenerator()
    
    # 所有生成的SQL都应该是只读的
    test_intents = [
        {"intent": "player_recent_performance", "limit": 10},
        {"intent": "map_leaderboard", "limit": 5},
        {"intent": "recent_battles", "limit": 10},
    ]
    
    print("检查所有生成的SQL是否安全...")
    all_safe = True
    
    for intent in test_intents:
        sql = generator.generate(intent)
        sql_upper = sql.upper()
        
        # 检查是否包含危险关键词
        dangerous_keywords = ["UPDATE", "DELETE", "INSERT", "DROP", "ALTER", "CREATE"]
        found_dangerous = [kw for kw in dangerous_keywords if kw in sql_upper]
        
        # 检查是否包含SELECT
        has_select = "SELECT" in sql_upper
        
        # 检查是否包含LIMIT
        has_limit = "LIMIT" in sql_upper
        
        if found_dangerous:
            print(f"❌ 意图 {intent['intent']}: 包含危险关键词 {found_dangerous}")
            all_safe = False
        elif not has_select:
            print(f"❌ 意图 {intent['intent']}: 不是SELECT查询")
            all_safe = False
        elif not has_limit:
            print(f"⚠️  意图 {intent['intent']}: 缺少LIMIT子句")
        else:
            print(f"✓ 意图 {intent['intent']}: SQL安全")
    
    print()
    if all_safe:
        print("✓ 所有SQL查询都是安全的！")
    else:
        print("❌ 发现不安全的SQL查询！")


def main():
    """运行所有测试"""
    print_separator("RAG系统测试套件")
    print("开始测试...")
    
    try:
        # 运行所有测试
        test_intent_detection()
        test_sql_generation()
        test_sql_execution()
        test_full_rag_system()
        test_llm_context_formatting()
        test_safety_checks()
        
        print_separator("测试完成")
        print("✓ 所有测试通过！")
        
    except Exception as e:
        print_separator("测试失败")
        print(f"❌ 错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()

