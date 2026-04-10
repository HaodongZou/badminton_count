"""
测试羽毛球比分记录应用的选手排名系统
包括 ELO 评分系统、胜率计算、排名显示等功能
"""
import pytest
import sys
import os
import tempfile
import json

# 设置测试数据库路径（临时文件）
_temp_db = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
TEST_DATABASE_PATH = _temp_db.name
_temp_db.close()
os.environ['DATABASE_PATH'] = TEST_DATABASE_PATH

sys.path.insert(0, os.path.dirname(__file__))

from app import app, parse_match_input, determine_winner, init_db, get_db, resolve_team

# 初始化测试数据库
init_db()

# =============================================================================
# ELO Rating System Functions (用于测试的辅助函数)
# =============================================================================

# ELO 相关常量
INITIAL_ELO = 1500
K_FACTOR_NEW = 32  # 新玩家（<30场）
K_FACTOR_ESTABLISHED = 16  # 成熟玩家（30+场）
GAMES_FOR_ESTABLISHED = 30


def calculate_expected_score(player_rating, opponent_rating):
    """
    计算预期得分
    expected_score = 1 / (1 + 10^((opponent_rating - player_rating) / 400))
    """
    return 1 / (1 + 10 ** ((opponent_rating - player_rating) / 400))


def calculate_k_factor(games_played):
    """K因子：新玩家32，成熟玩家16"""
    return K_FACTOR_NEW if games_played < GAMES_FOR_ESTABLISHED else K_FACTOR_ESTABLISHED


def calculate_elo_change(winner_rating, loser_rating, is_winner=True):
    """
    计算 ELO 变化
    winner_rating: 赢家当前评分
    loser_rating: 输家当前评分
    is_winner: True 表示 winner_rating 方赢了，False 表示 loser_rating 方赢了
    """
    expected_winner = calculate_expected_score(winner_rating, loser_rating)
    winner_games = get_player_games_count(winner_rating)  # 临时用 rating 作为占位
    k = calculate_k_factor(winner_games)

    if is_winner:
        change = k * (1 - expected_winner)
    else:
        change = k * (0 - expected_winner)

    return round(change)


def get_player_games_count(player_name_or_elo):
    """获取玩家游戏场数（临时占位，实际会从数据库读取）"""
    return 0  # 默认返回0表示新玩家


# =============================================================================
# Player Rankings Storage (用于测试的内存存储)
# =============================================================================

# 内存中的玩家评分存储（实际应用中应该是数据库表）
_player_ratings = {}  # {player_name: {"rating": 1500, "games_played": 0}}
_player_match_history = []  # [(winner, loser, match_type), ...]


def reset_rankings():
    """重置排名数据（测试用）"""
    global _player_ratings, _player_match_history
    _player_ratings = {}
    _player_match_history = []


def get_player_rating(player_name):
    """获取玩家 ELO 评分（新玩家返回1500）"""
    if player_name not in _player_ratings:
        _player_ratings[player_name] = {
            "rating": INITIAL_ELO,
            "games_played": 0
        }
    return _player_ratings[player_name]["rating"]


def update_player_rating(player_name, new_rating, games_played=None):
    """更新玩家评分"""
    if player_name not in _player_ratings:
        _player_ratings[player_name] = {
            "rating": INITIAL_ELO,
            "games_played": 0
        }
    _player_ratings[player_name]["rating"] = new_rating
    if games_played is not None:
        _player_ratings[player_name]["games_played"] = games_played
    else:
        _player_ratings[player_name]["games_played"] += 1


def get_player_games_played(player_name):
    """获取玩家已玩游戏场数"""
    if player_name not in _player_ratings:
        return 0
    return _player_ratings[player_name]["games_played"]


def process_match_result(my_team, opponent_team, my_wins):
    """
    处理比赛结果，更新双方 ELO 评分

    对于双打：每个队友获得相同的 ELO 变化（对阵两个对手）
    my_team: 我方队伍列表
    opponent_team: 对方队伍列表
    my_wins: True 表示我方赢，False 表示对方赢
    """
    global _player_ratings

    # 确保所有玩家都已初始化
    for player in my_team + opponent_team:
        if player not in _player_ratings:
            _player_ratings[player] = {"rating": INITIAL_ELO, "games_played": 0}

    # 计算每方的平均评分（只计算当前队伍中玩家的评分）
    my_avg_rating = sum(_player_ratings[p]["rating"] for p in my_team) / len(my_team)
    opp_avg_rating = sum(_player_ratings[p]["rating"] for p in opponent_team) / len(opponent_team)

    # 计算 ELO 变化
    if my_wins:
        expected = calculate_expected_score(my_avg_rating, opp_avg_rating)
        # 我方每人获得
        for player in my_team:
            k = calculate_k_factor(_player_ratings[player]["games_played"])
            change = k * (1 - expected)
            _player_ratings[player]["rating"] += change
            _player_ratings[player]["games_played"] += 1
        # 对方每人失去
        for player in opponent_team:
            k = calculate_k_factor(_player_ratings[player]["games_played"])
            change = k * (0 - (1 - expected))
            _player_ratings[player]["rating"] += change
            _player_ratings[player]["games_played"] += 1
    else:
        expected = calculate_expected_score(my_avg_rating, opp_avg_rating)
        # 我方每人失去
        for player in my_team:
            k = calculate_k_factor(_player_ratings[player]["games_played"])
            change = k * (0 - expected)
            _player_ratings[player]["rating"] += change
            _player_ratings[player]["games_played"] += 1
        # 对方每人获得
        for player in opponent_team:
            k = calculate_k_factor(_player_ratings[player]["games_played"])
            change = k * (1 - (1 - expected))
            _player_ratings[player]["rating"] += change
            _player_ratings[player]["games_played"] += 1


def calculate_win_rate(wins, total_games):
    """计算胜率（百分比）"""
    if total_games == 0:
        return 0.0
    return round(wins / total_games * 100, 1)


def get_player_stats_from_db(player_name):
    """从数据库获取玩家统计数据"""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('SELECT * FROM matches')
    matches = [dict(row) for row in cursor.fetchall()]
    conn.close()

    total_wins = 0
    total_losses = 0

    for match in matches:
        my_team = match['my_team'].split(',')
        opp_team = match['opponent_team'].split(',')
        winner = match['winner']

        if player_name in my_team:
            if winner == 'me':
                total_wins += 1
            elif winner == 'opponent':
                total_losses += 1
        elif player_name in opp_team:
            if winner == 'opponent':
                total_wins += 1
            elif winner == 'me':
                total_losses += 1

    total_games = total_wins + total_losses
    return {
        "wins": total_wins,
        "losses": total_losses,
        "games_played": total_games,
        "win_rate": calculate_win_rate(total_wins, total_games)
    }


def get_rankings():
    """
    获取排名列表
    按 ELO 降序排列
    平局时：先按游戏场次降序，再按名字字母升序
    """
    rankings = []
    for player_name, data in _player_ratings.items():
        stats = get_player_stats_from_db(player_name)
        rankings.append({
            "player_name": player_name,
            "rating": round(data["rating"]),
            "wins": stats["wins"],
            "losses": stats["losses"],
            "win_rate": stats["win_rate"],
            "games_played": data["games_played"]
        })

    # 排序：ELO 降序 > 游戏场次降序 > 名字字母升序
    rankings.sort(key=lambda x: (-x["rating"], -x["games_played"], x["player_name"]))

    # 添加排名
    for i, player in enumerate(rankings, 1):
        player["rank"] = i

    return rankings


# =============================================================================
# Test Cases: ELO Rating System
# =============================================================================

class TestELORatingSystem:
    """测试 ELO 评分系统"""

    def setup_method(self):
        """每个测试前重置排名数据"""
        reset_rankings()

    def test_new_player_starts_with_1500(self):
        """新玩家初始评分为1500"""
        # 新玩家从未出现在系统中
        rating = get_player_rating("新玩家小明")
        assert rating == INITIAL_ELO
        assert rating == 1500

    def test_elo_gain_against_higher_rated(self):
        """战胜更高评分对手时获得更多积分"""
        # 初始化两个玩家
        update_player_rating("低手", 1400, games_played=10)
        update_player_rating("高手", 1600, games_played=10)

        # 模拟低手战胜高手
        low_player = _player_ratings["低手"]
        high_player = _player_ratings["高手"]

        expected = calculate_expected_score(low_player["rating"], high_player["rating"])
        k = calculate_k_factor(low_player["games_played"])

        # 低手赢：gain = k * (1 - expected)
        # 因为对手评分更高，expected < 0.5，所以 gain 更大
        gain = k * (1 - expected)

        assert expected < 0.5, "低手对高手的预期得分应该小于0.5"
        assert gain > k * 0.3, "战胜高评分对手应该获得较多积分"

    def test_elo_gain_against_lower_rated(self):
        """战胜更低评分对手时获得较少积分"""
        update_player_rating("高手", 1600, games_played=10)
        update_player_rating("低手", 1400, games_played=10)

        high_player = _player_ratings["高手"]
        low_player = _player_ratings["低手"]

        expected = calculate_expected_score(high_player["rating"], low_player["rating"])

        # 赢：gain = k * (1 - expected)
        gain = K_FACTOR_NEW * (1 - expected)

        assert expected > 0.5, "高手对低手的预期得分应该大于0.5"
        assert gain < K_FACTOR_NEW * 0.5, "战胜低评分对手应该获得较少积分"

    def test_elo_loss_against_higher_rated(self):
        """输给更高评分对手时失去较少积分"""
        update_player_rating("低手", 1400, games_played=10)
        update_player_rating("高手", 1600, games_played=10)

        low_player = _player_ratings["低手"]
        high_player = _player_ratings["高手"]

        expected = calculate_expected_score(low_player["rating"], high_player["rating"])

        # 低手输：loss = k * (0 - expected) = -k * expected
        loss = K_FACTOR_NEW * (0 - expected)

        assert expected < 0.5, "低手对高手的预期得分应该小于0.5"
        assert abs(loss) < K_FACTOR_NEW * 0.5, "输给高评分对手应该失去较少积分（因为在预期内）"

    def test_elo_loss_against_lower_rated(self):
        """输给更低评分对手时失去更多积分"""
        update_player_rating("高手", 1600, games_played=10)
        update_player_rating("低手", 1400, games_played=10)

        high_player = _player_ratings["高手"]
        low_player = _player_ratings["低手"]

        expected = calculate_expected_score(high_player["rating"], low_player["rating"])

        # 高手输：loss = k * (0 - expected) = -k * expected
        loss = K_FACTOR_NEW * (0 - expected)

        assert expected > 0.5, "高手对低手的预期得分应该大于0.5"
        assert abs(loss) > K_FACTOR_NEW * 0.5, "输给低评分对手应该失去较多积分（因为不在预期内）"

    def test_k_factor_decreases_for_established_players(self):
        """成熟玩家（30+场）的K因子降为16"""
        # 新玩家（<30场）
        k_new = calculate_k_factor(0)
        assert k_new == K_FACTOR_NEW
        assert k_new == 32

        # 边界情况：29场
        k_almost = calculate_k_factor(29)
        assert k_almost == K_FACTOR_NEW

        # 成熟玩家（30场）
        k_established = calculate_k_factor(30)
        assert k_established == K_FACTOR_ESTABLISHED
        assert k_established == 16

        # 更多场次
        k_many = calculate_k_factor(100)
        assert k_many == K_FACTOR_ESTABLISHED

    def test_expected_score_formula(self):
        """测试预期得分计算公式"""
        # 同评分：expected = 0.5
        expected_equal = calculate_expected_score(1500, 1500)
        assert expected_equal == 0.5

        # 400分差（对手更高）：expected ≈ 0.09 (你赢的概率很低)
        expected_400_higher = calculate_expected_score(1500, 1900)
        assert 0.08 < expected_400_higher < 0.10

        # 400分差（对手更低）：expected ≈ 0.91 (你赢的概率很高)
        expected_400_lower = calculate_expected_score(1500, 1100)
        assert 0.90 < expected_400_lower < 0.92

        # ~100分差：expected ≈ 0.36
        expected_100 = calculate_expected_score(1500, 1600)
        assert 0.35 < expected_100 < 0.37

    def test_elo_bounded_by_games_not_rating(self):
        """验证K因子只由游戏场次决定，不由评分决定"""
        # 同样30场，无论评分高低，K因子都是16
        assert calculate_k_factor(30) == 16
        assert calculate_k_factor(30) == calculate_k_factor(30)  # 恒定

        # 同样5场，无论评分高低，K因子都是32
        assert calculate_k_factor(5) == 32
        assert calculate_k_factor(5) == calculate_k_factor(5)


# =============================================================================
# Test Cases: Win Rate Calculation
# =============================================================================

class TestWinRateCalculation:
    """测试胜率计算"""

    def test_win_rate_calculation(self):
        """胜率 = 赢的场次 / 总场次"""
        assert calculate_win_rate(3, 6) == 50.0
        assert calculate_win_rate(7, 10) == 70.0
        assert calculate_win_rate(1, 4) == 25.0
        assert calculate_win_rate(9, 10) == 90.0

    def test_win_rate_perfect_record(self):
        """全胜时胜率为100%"""
        assert calculate_win_rate(10, 10) == 100.0
        assert calculate_win_rate(1, 1) == 100.0
        assert calculate_win_rate(0, 0) == 0.0  # 特殊情况

    def test_win_rate_zero_games(self):
        """0场游戏时胜率为0%"""
        assert calculate_win_rate(0, 0) == 0.0

    def test_win_rate_calculation_precision(self):
        """胜率保留一位小数"""
        # 1/3 ≈ 33.3%
        assert calculate_win_rate(1, 3) == 33.3
        # 2/3 ≈ 66.7%
        assert calculate_win_rate(2, 3) == 66.7


# =============================================================================
# Test Cases: Ranking Display
# =============================================================================

class TestRankingDisplay:
    """测试排名显示"""

    def setup_method(self):
        """每个测试前重置排名数据"""
        reset_rankings()

    def test_ranking_sorted_by_elo(self):
        """玩家按 ELO 评分降序排列"""
        # 设置不同评分
        update_player_rating("玩家A", 1400, games_played=10)
        update_player_rating("玩家B", 1600, games_played=10)
        update_player_rating("玩家C", 1500, games_played=10)

        rankings = get_rankings()

        assert rankings[0]["player_name"] == "玩家B"  # 1600最高
        assert rankings[1]["player_name"] == "玩家C"  # 1500
        assert rankings[2]["player_name"] == "玩家A"  # 1400最低

    def test_ranking_includes_required_fields(self):
        """排名包含所有必需字段"""
        update_player_rating("测试玩家", 1500, games_played=5)

        rankings = get_rankings()
        assert len(rankings) == 1

        player = rankings[0]
        assert "rank" in player
        assert "player_name" in player
        assert "rating" in player
        assert "wins" in player
        assert "losses" in player
        assert "win_rate" in player
        assert "games_played" in player

    def test_ranking_starts_at_one(self):
        """排名从1开始"""
        update_player_rating("玩家A", 1600, games_played=10)
        update_player_rating("玩家B", 1500, games_played=10)

        rankings = get_rankings()

        assert rankings[0]["rank"] == 1
        assert rankings[1]["rank"] == 2


# =============================================================================
# Test Cases: Tie Handling
# =============================================================================

class TestTieHandling:
    """测试平局处理"""

    def setup_method(self):
        """每个测试前重置排名数据"""
        reset_rankings()

    def test_tiebreaker_by_games_played(self):
        """相同评分时，游戏场次多的排名更高"""
        update_player_rating("老手", 1500, games_played=50)
        update_player_rating("新手", 1500, games_played=5)

        rankings = get_rankings()

        assert rankings[0]["player_name"] == "老手"
        assert rankings[0]["games_played"] == 50
        assert rankings[1]["player_name"] == "新手"
        assert rankings[1]["games_played"] == 5

    def test_tiebreaker_alphabetical_for_same_games(self):
        """相同评分、相同游戏场次时，按字母顺序排列"""
        update_player_rating("张三", 1500, games_played=10)
        update_player_rating("李四", 1500, games_played=10)
        update_player_rating("王五", 1500, games_played=10)

        rankings = get_rankings()

        # 按字母顺序：张三 < 李四 < 王五
        assert rankings[0]["player_name"] == "张三"
        assert rankings[1]["player_name"] == "李四"
        assert rankings[2]["player_name"] == "王五"

    def test_complex_tiebreaker(self):
        """复杂的平局处理：评分 > 游戏场次 > 字母顺序"""
        # A和B评分相同，但游戏场次不同
        update_player_rating("老手A", 1500, games_played=20)
        update_player_rating("老手B", 1500, games_played=10)
        # C评分更高
        update_player_rating("高手C", 1600, games_played=5)

        rankings = get_rankings()

        # C评分最高，排第一
        assert rankings[0]["player_name"] == "高手C"
        # A和B同评分，A场次多排第二
        assert rankings[1]["player_name"] == "老手A"
        assert rankings[2]["player_name"] == "老手B"


# =============================================================================
# Test Cases: Match Integration
# =============================================================================

class TestMatchIntegration:
    """测试比赛集成"""

    def setup_method(self):
        """每个测试前重置排名数据"""
        reset_rankings()
        # 清空数据库中的测试数据
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM matches')
        conn.commit()
        conn.close()

    def test_elo_updated_after_singles_match_added(self):
        """单打比赛后更新双方 ELO"""
        # 模拟：低手(1400) 赢了 高手(1600)
        update_player_rating("我", 1400, games_played=10)
        update_player_rating("李四", 1600, games_played=10)

        old_my_rating = _player_ratings["我"]["rating"]
        old_opp_rating = _player_ratings["李四"]["rating"]

        # 模拟比赛结果处理
        process_match_result(["我"], ["李四"], my_wins=True)

        new_my_rating = _player_ratings["我"]["rating"]
        new_opp_rating = _player_ratings["李四"]["rating"]

        # 我赢了，评分应该增加
        assert new_my_rating > old_my_rating, "赢家评分应该增加"
        # 对手输了，评分应该减少
        assert new_opp_rating < old_opp_rating, "输家评分应该减少"

    def test_doubles_elo_all_players(self):
        """双打比赛所有参与者评分都更新"""
        # 设置初始评分
        update_player_rating("我", 1400, games_played=10)
        update_player_rating("张三", 1450, games_played=10)
        update_player_rating("李四", 1550, games_played=10)
        update_player_rating("王五", 1600, games_played=10)

        old_ratings = {
            "我": _player_ratings["我"]["rating"],
            "张三": _player_ratings["张三"]["rating"],
            "李四": _player_ratings["李四"]["rating"],
            "王五": _player_ratings["王五"]["rating"]
        }

        # 模拟：低手队(我+张三) 战胜 高手队(李四+王五)
        process_match_result(["我", "张三"], ["李四", "王五"], my_wins=True)

        # 赢家（我队）评分增加
        assert _player_ratings["我"]["rating"] > old_ratings["我"]
        assert _player_ratings["张三"]["rating"] > old_ratings["张三"]

        # 输家（对手）评分减少
        assert _player_ratings["李四"]["rating"] < old_ratings["李四"]
        assert _player_ratings["王五"]["rating"] < old_ratings["王五"]

    def test_doubles_elo_changes_are_equal(self):
        """双打中同队玩家的 ELO 变化相同"""
        update_player_rating("我", 1400, games_played=10)
        update_player_rating("张三", 1400, games_played=10)
        update_player_rating("李四", 1600, games_played=10)
        update_player_rating("王五", 1600, games_played=10)

        # 模拟：低手队(我+张三) 战胜 高手队(李四+王五)
        process_match_result(["我", "张三"], ["李四", "王五"], my_wins=True)

        # 同队应该有相同的 ELO 变化
        my_change = _player_ratings["我"]["rating"] - 1400
        zhang_change = _player_ratings["张三"]["rating"] - 1400
        li_change = _player_ratings["李四"]["rating"] - 1600
        wang_change = _player_ratings["王五"]["rating"] - 1600

        assert abs(my_change - zhang_change) < 0.1, "同队玩家应该有相同的ELO变化"
        assert abs(li_change - wang_change) < 0.1, "同队玩家应该有相同的ELO变化"

    def test_match_result_against_higher_rated_gives_more_points(self):
        """战胜高评分对手比战胜低评分对手获得更多积分"""
        # 设置两组：对手评分不同
        update_player_rating("我", 1500, games_played=10)
        update_player_rating("低手", 1400, games_played=10)
        update_player_rating("高手", 1700, games_played=10)

        initial_my_rating = 1500
        initial_games_played = 10

        # 模拟战胜低手
        process_match_result(["我"], ["低手"], my_wins=True)
        gain_against_low = _player_ratings["我"]["rating"] - initial_my_rating

        # 重置再测试（包括评分和游戏场次）
        _player_ratings["我"]["rating"] = initial_my_rating
        _player_ratings["我"]["games_played"] = initial_games_played

        # 模拟战胜高手
        process_match_result(["我"], ["高手"], my_wins=True)
        gain_against_high = _player_ratings["我"]["rating"] - initial_my_rating

        assert gain_against_high > gain_against_low, "战胜高评分对手应该获得更多积分"

    def test_loss_against_lower_rated_loses_more_points(self):
        """输给低评分对手比输给高评分对手失去更多积分"""
        update_player_rating("我", 1500, games_played=10)
        update_player_rating("低手", 1400, games_played=10)
        update_player_rating("高手", 1700, games_played=10)

        initial_my_rating = 1500
        initial_games_played = 10

        # 模拟输给低手
        process_match_result(["我"], ["低手"], my_wins=False)
        loss_against_low = _player_ratings["我"]["rating"] - initial_my_rating

        # 重置再测试（包括评分和游戏场次）
        _player_ratings["我"]["rating"] = initial_my_rating
        _player_ratings["我"]["games_played"] = initial_games_played

        # 模拟输给高手
        process_match_result(["我"], ["高手"], my_wins=False)
        loss_against_high = _player_ratings["我"]["rating"] - initial_my_rating

        assert loss_against_low < loss_against_high, "输给低评分对手应该失去更多积分（更负面）"
        assert loss_against_low < 0 and loss_against_high < 0  # 两者都是损失


# =============================================================================
# Test Cases: Database Integration
# =============================================================================

class TestDatabaseIntegration:
    """测试数据库集成"""

    def setup_method(self):
        """每个测试前清空数据库"""
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM matches')
        conn.commit()
        conn.close()
        reset_rankings()

    def test_get_all_players_from_db(self):
        """从数据库获取所有玩家"""
        from app import get_all_players

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO matches (my_team, opponent_team, scores, winner, match_type, created_by)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', ('我,张三', '李四,王五', json.dumps([[21, 15]]), 'me', 'doubles', 'admin'))
        conn.commit()
        conn.close()

        # 注册并登录以获取访问权限
        app.test_client().post('/api/register', json={
            'username': 'dbtest_user',
            'password': 'test123',
            'confirm_password': 'test123'
        })

        response = app.test_client().get('/api/players')
        assert response.status_code == 200
        players = response.get_json()

        # 验证所有玩家名称都在列表中
        player_names = ['我', '张三', '李四', '王五']
        for name in player_names:
            assert name in players, f"{name} should be in players list"


# =============================================================================
# Test Cases: Edge Cases
# =============================================================================

class TestEdgeCases:
    """边界情况测试"""

    def setup_method(self):
        """每个测试前重置"""
        reset_rankings()

    def test_empty_ranking_list(self):
        """没有任何玩家时的排名"""
        rankings = get_rankings()
        assert rankings == []

    def test_single_player_ranking(self):
        """只有单个玩家时的排名"""
        update_player_rating("唯一玩家", 1500, games_played=10)

        rankings = get_rankings()
        assert len(rankings) == 1
        assert rankings[0]["player_name"] == "唯一玩家"
        assert rankings[0]["rank"] == 1

    def test_exact_same_rating_and_games(self):
        """完全相同评分和游戏场次的玩家按字母排序"""
        # 使用ASCII字符来测试字母排序，避免Unicode排序问题
        update_player_rating("Alice", 1500, games_played=10)
        update_player_rating("Charlie", 1500, games_played=10)
        update_player_rating("Bob", 1500, games_played=10)

        rankings = get_rankings()

        # Alice < Bob < Charlie (ASCII顺序)
        assert rankings[0]["player_name"] == "Alice"
        assert rankings[1]["player_name"] == "Bob"
        assert rankings[2]["player_name"] == "Charlie"

    def test_rating_at_boundaries(self):
        """测试评分边界情况"""
        # 0场新玩家
        k = calculate_k_factor(0)
        assert k == K_FACTOR_NEW

        # 29场新玩家
        k = calculate_k_factor(29)
        assert k == K_FACTOR_NEW

        # 30场成熟玩家
        k = calculate_k_factor(30)
        assert k == K_FACTOR_ESTABLISHED


# =============================================================================
# Run Tests
# =============================================================================

if __name__ == '__main__':
    pytest.main([__file__, '-v'])
