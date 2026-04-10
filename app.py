"""
羽毛球比分记录应用 - Python Flask后端
"""
import logging
import os
import sqlite3
import urllib.parse
from datetime import datetime, timedelta
from functools import lru_cache, wraps
import re
import json

from flask import Flask, render_template, request, jsonify, redirect, session
from itsdangerous import URLSafeTimedSerializer as Serializer, SignatureExpired, BadSignature
from werkzeug.security import generate_password_hash, check_password_hash

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', os.urandom(24).hex())
app.config['APPLICATION_ROOT'] = os.environ.get('APPLICATION_ROOT', '/')

DATABASE = os.environ.get('DATABASE_PATH', 'badminton.db')

# 认证配置
API_KEY = os.environ.get('API_KEY', None)  # None表示禁用认证
DISABLE_AUTH = os.environ.get('DISABLE_AUTH', 'false').lower() == 'true'

# 登录配置
LOGIN_USER = os.environ.get('LOGIN_USER', 'admin')
LOGIN_PASSWORD = os.environ.get('LOGIN_PASSWORD', 'badminton123')

# ELO 评分系统配置
DEFAULT_ELO = 1500
K_FACTOR_NEW = 32      # 新玩家（<30场）
K_FACTOR_ESTABLISHED = 16  # 成熟玩家（>=30场）

# Session serializer
serializer = Serializer(app.config['SECRET_KEY'], salt='badminton-login')

def require_auth(f):
    """API认证装饰器"""
    @wraps(f)
    def decorated(*args, **kwargs):
        # 如果禁用认证或未配置API_KEY，则跳过认证
        if DISABLE_AUTH or API_KEY is None:
            return f(*args, **kwargs)

        auth_header = request.headers.get('Authorization', '')

        # 支持 Bearer Token 格式
        if auth_header.startswith('Bearer '):
            token = auth_header[7:]
            if token == API_KEY:
                return f(*args, **kwargs)

        # 也支持简单的 key 参数
        provided_key = request.args.get('key', '')
        if provided_key == API_KEY:
            return f(*args, **kwargs)

        logger.warning(f"Unauthorized access attempt to {request.path}")
        return jsonify({'error': 'Unauthorized'}), 401

    return decorated

def get_current_user():
    """获取当前登录用户信息"""
    auth_header = request.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        token = auth_header[7:]
        # 跳过登录的访客token
        if token.startswith('demo_skip_') or token.startswith('guest_'):
            return None
        data = verify_token(token)
        return data  # {'user': username, 'is_admin': bool}
    return None

def is_guest():
    """检测是否为访客（未登录或跳过登录）"""
    return get_current_user() is None

def is_admin():
    """检测是否为管理员"""
    user_data = get_current_user()
    return user_data is not None and user_data.get('is_admin', False)

# =============================================================================
# ELO Rating System Functions
# =============================================================================

def get_k_factor(games_played):
    """根据已玩游戏数返回K因子：新玩家32，成熟玩家16"""
    return K_FACTOR_NEW if games_played < 30 else K_FACTOR_ESTABLISHED

def calculate_expected_score(player_rating, opponent_rating):
    """计算预期得分：1 / (1 + 10^((opponent - player) / 400))"""
    return 1 / (1 + 10 ** ((opponent_rating - player_rating) / 400))

def get_player_rating(player_name):
    """获取玩家ELO评分（新玩家返回默认1500）"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT elo_rating, games_played FROM player_ratings WHERE player_name = ?', (player_name,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {'elo': row['elo_rating'], 'games': row['games_played']}
    return {'elo': DEFAULT_ELO, 'games': 0}

def initialize_player_rating(conn, cursor, player_name):
    """初始化玩家ELO（如果不存在）"""
    cursor.execute('SELECT elo_rating FROM player_ratings WHERE player_name = ?', (player_name,))
    if not cursor.fetchone():
        cursor.execute(
            'INSERT INTO player_ratings (player_name, elo_rating, games_played) VALUES (?, ?, 0)',
            (player_name, DEFAULT_ELO)
        )

def update_ratings_after_match(my_team, opp_team, my_won, conn=None):
    """
    比赛结束后更新双方ELO评分
    my_team: 我方玩家列表
    opp_team: 对方玩家列表
    my_won: True表示我方获胜
    """
    close_conn = False
    if conn is None:
        conn = get_db()
        close_conn = True

    cursor = conn.cursor()
    all_players = my_team + opp_team

    # 获取所有玩家当前评分
    ratings = {}
    for p in all_players:
        cursor.execute('SELECT elo_rating, games_played FROM player_ratings WHERE player_name = ?', (p,))
        row = cursor.fetchone()
        if row:
            ratings[p] = {'elo': row['elo_rating'], 'games': row['games_played']}
        else:
            ratings[p] = {'elo': DEFAULT_ELO, 'games': 0}
            cursor.execute(
                'INSERT INTO player_ratings (player_name, elo_rating, games_played) VALUES (?, ?, 0)',
                (p, DEFAULT_ELO)
            )

    # 确定胜负双方
    winner_team = my_team if my_won else opp_team
    loser_team = opp_team if my_won else my_team

    # 计算双方平均ELO
    winner_avg = sum(ratings[p]['elo'] for p in winner_team) / len(winner_team)
    loser_avg = sum(ratings[p]['elo'] for p in loser_team) / len(loser_team)

    # 计算ELO变化（基于总场次平均值）
    total_games = sum(ratings[p]['games'] for p in all_players) / len(all_players)
    k = get_k_factor(int(total_games))
    expected = calculate_expected_score(winner_avg, loser_avg)
    change = round(k * (1 - expected))

    # 应用变化
    for p in winner_team:
        ratings[p]['elo'] += change
        ratings[p]['games'] += 1
    for p in loser_team:
        ratings[p]['elo'] -= change
        ratings[p]['games'] += 1

    # 持久化
    for p, data in ratings.items():
        cursor.execute('''
            INSERT INTO player_ratings (player_name, elo_rating, games_played, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(player_name) DO UPDATE SET
                elo_rating = ?, games_played = ?, updated_at = CURRENT_TIMESTAMP
        ''', (p, data['elo'], data['games'], data['elo'], data['games']))

    conn.commit()
    if close_conn:
        conn.close()

    return {p: ratings[p]['elo'] for p in all_players}

def recalculate_all_ratings():
    """从比赛历史重新计算所有玩家ELO"""
    conn = get_db()
    cursor = conn.cursor()

    # 重置所有评分
    cursor.execute('DELETE FROM player_ratings')
    conn.commit()

    # 按时间顺序重放所有比赛（逐局更新ELO）
    cursor.execute('SELECT * FROM matches ORDER BY date ASC')
    for match in cursor.fetchall():
        my_team = [p.strip() for p in match['my_team'].split(',') if p.strip()]
        opp_team = [p.strip() for p in match['opponent_team'].split(',') if p.strip()]
        scores = json.loads(match['scores']) if match['scores'] else []

        for p in my_team + opp_team:
            initialize_player_rating(conn, cursor, p)
        conn.commit()

        # 逐局更新ELO
        for game in scores:
            my_score, opp_score = game[0], game[1]
            my_won = my_score > opp_score
            update_ratings_after_match(my_team, opp_team, my_won, conn)

    conn.close()

def get_rankings():
    """获取所有玩家排名列表"""
    conn = get_db()
    cursor = conn.cursor()

    # 获取所有玩家评分
    cursor.execute('SELECT * FROM player_ratings ORDER BY elo_rating DESC, games_played DESC')
    ratings = [dict(row) for row in cursor.fetchall()]

    # 获取每个玩家的胜率统计（逐局计算）
    cursor.execute('SELECT my_team, opponent_team, scores FROM matches')
    matches = cursor.fetchall()

    player_stats = {}
    for match in matches:
        my_team = [p.strip() for p in match['my_team'].split(',') if p.strip()]
        opp_team = [p.strip() for p in match['opponent_team'].split(',') if p.strip()]
        scores = json.loads(match['scores']) if match['scores'] else []

        for p in my_team + opp_team:
            if p not in player_stats:
                player_stats[p] = {'wins': 0, 'losses': 0}

        # 逐局计算胜负
        for game in scores:
            my_score, opp_score = game[0], game[1]
            if my_score > opp_score:
                # 我方赢了这一局
                for p in my_team:
                    player_stats[p]['wins'] += 1
                for p in opp_team:
                    player_stats[p]['losses'] += 1
            else:
                # 对方赢了这一局
                for p in opp_team:
                    player_stats[p]['wins'] += 1
                for p in my_team:
                    player_stats[p]['losses'] += 1

    # 构建排名列表
    rankings = []
    for row in ratings:
        p = row['player_name']
        stats = player_stats.get(p, {'wins': 0, 'losses': 0})
        total = stats['wins'] + stats['losses']
        win_rate = round(stats['wins'] / total * 100, 1) if total > 0 else 0.0
        rankings.append({
            'rank': 0,
            'player_name': p,
            'elo_rating': row['elo_rating'],
            'wins': stats['wins'],
            'losses': stats['losses'],
            'win_rate': win_rate,
            'games_played': row['games_played']
        })

    # 排序：ELO降序 > 场次降序 > 名字字母升序
    rankings.sort(key=lambda x: (-x['elo_rating'], -x['games_played'], x['player_name']))

    # 添加排名
    for i, r in enumerate(rankings, 1):
        r['rank'] = i

    conn.close()
    return rankings

def get_db():
    """获取数据库连接"""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """初始化数据库"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS matches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date DATETIME DEFAULT CURRENT_TIMESTAMP,
            my_team TEXT NOT NULL,
            opponent_team TEXT NOT NULL,
            scores TEXT NOT NULL,
            winner TEXT NOT NULL,
            match_type TEXT DEFAULT 'doubles'
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS player_aliases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alias TEXT NOT NULL UNIQUE,
            canonical_name TEXT NOT NULL
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS player_ratings (
            player_name TEXT PRIMARY KEY,
            elo_rating INTEGER DEFAULT 1500,
            games_played INTEGER DEFAULT 0,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # 检查并添加 created_by 字段（向后兼容）
    cursor.execute("PRAGMA table_info(matches)")
    columns = [col[1] for col in cursor.fetchall()]
    if 'created_by' not in columns:
        cursor.execute("ALTER TABLE matches ADD COLUMN created_by TEXT DEFAULT 'admin'")

    # 创建索引以提升查询性能
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_matches_date ON matches(date)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_matches_my_team ON matches(my_team)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_matches_opponent_team ON matches(opponent_team)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_ratings_elo ON player_ratings(elo_rating DESC)')

    conn.commit()
    conn.close()

    # 迁移现有数据
    migrate_existing_data()

def migrate_existing_data():
    """迁移现有数据，设置 created_by 字段"""
    conn = get_db()
    cursor = conn.cursor()

    # 检查是否有 created_by 字段
    cursor.execute("PRAGMA table_info(matches)")
    columns = [col[1] for col in cursor.fetchall()]

    if 'created_by' not in columns:
        # 添加字段
        cursor.execute("ALTER TABLE matches ADD COLUMN created_by TEXT DEFAULT 'admin'")
        conn.commit()
        logger.info("Migrated matches table: added created_by column")

    # 检查是否需要初始化现有记录的 created_by
    cursor.execute("SELECT COUNT(*) FROM matches WHERE created_by IS NULL OR created_by = ''")
    if cursor.fetchone()[0] > 0:
        cursor.execute("UPDATE matches SET created_by = 'admin' WHERE created_by IS NULL OR created_by = ''")
        conn.commit()
        logger.info("Migrated matches: set created_by='admin' for existing records")

    conn.close()

@lru_cache(maxsize=1)
def get_alias_map():
    """获取别名映射表 {alias: canonical_name}（带缓存）"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT alias, canonical_name FROM player_aliases')
    rows = cursor.fetchall()
    conn.close()
    return {row['alias']: row['canonical_name'] for row in rows}

def clear_alias_cache():
    """清除别名缓存（当别名变更时调用）"""
    get_alias_map.cache_clear()

def resolve_player_name(name):
    """解析选手名称，返回规范化的名称"""
    alias_map = get_alias_map()
    return alias_map.get(name, name)

def resolve_team(team_list):
    """解析队伍中的所有选手名称"""
    return [resolve_player_name(p) for p in team_list]

# =============================================================================
# 胜负解析辅助函数
# =============================================================================

CHINESE_NUMBERS = {
    '零': 0, '一': 1, '二': 2, '三': 3, '四': 4,
    '五': 5, '六': 6, '七': 7, '八': 8, '九': 9, '十': 10,
    '两': 2, '几': 3,  # 两=2, 几≈3
    '0': 0, '1': 1, '2': 2, '3': 3, '4': 4,
    '5': 5, '6': 6, '7': 7, '8': 8, '9': 9
}

def _parse_chinese_number(text):
    """将中文数字或阿拉伯数字转换为整数"""
    if text.isdigit():
        return int(text)
    total = 0
    for char in text:
        if char in CHINESE_NUMBERS:
            total = total * 10 + CHINESE_NUMBERS[char]
    return total

def _parse_win_loss_pattern(text):
    """
    检测并解析胜负模式，返回 (我的胜局数, 我的负局数) 或 None
    支持格式:
      - "1:1", "2:0", "0:2", "2:1" (半角/全角冒号)
      - "一比一", "二比零", "二比一"
      - "一胜一负", "两胜", "一负", "三胜"
      - "赢一输一", "输一赢一"
      - "两局都赢了", "两局都输了"
      - "都赢了", "都输了"
      - "第一局赢了", "第二局输了"
      - "赢了输了" (没有局数标记)
      - "平局" (1胜1负)
    """
    text_no_space = re.sub(r'\s+', '', text)

    # 格式1: X:Y 或 X比Y (X和Y是数字，且<10才视为胜负)
    m = re.search(r'(\d+)[:：](\d+)', text_no_space)
    if m:
        wins = int(m.group(1))
        losses = int(m.group(2))
        # 排除明显的真实比分（如 21:15, 11:0 等）
        if wins >= 10 or losses >= 10:
            pass
        else:
            return wins, losses

    # 格式2: 一比一、二比零
    m = re.search(r'([零一二三四五六七八九十两]+)比([零一二三四五六七八九十两]+)', text_no_space)
    if m:
        wins = _parse_chinese_number(m.group(1))
        losses = _parse_chinese_number(m.group(2))
        return wins, losses

    # 格式3a: 一胜一负 (number first)
    m = re.search(r'([零一二三四五六七八九十两]+)[胜赢]([零一二三四五六七八九十两]+)?[负输]?', text_no_space)
    if m:
        wins = _parse_chinese_number(m.group(1))
        if m.group(2):
            losses = _parse_chinese_number(m.group(2))
        return wins, losses

    # 格式3b: 赢一输一、输一赢一 (win/loss first, like "win one lose one")
    m = re.search(r'(赢|输|胜|负)([零一二三四五六七八九十两]+)(?:(赢|输|胜|负)([零一二三四五六七八九十两]+))?', text_no_space)
    if m:
        first_outcome = m.group(1)
        first_num = _parse_chinese_number(m.group(2))
        if first_outcome in ['赢', '胜']:
            wins = first_num
        else:
            wins = 0
        if first_outcome in ['输', '负']:
            losses = first_num
        else:
            losses = 0
        if m.group(3):
            second_outcome = m.group(3)
            second_num = _parse_chinese_number(m.group(4))
            if second_outcome in ['赢', '胜']:
                wins += second_num
            else:
                losses += second_num
        return wins, losses

    # 格式4: 单独的 N胜 或 N负
    m = re.search(r'([零一二三四五六七八九十两]+)[胜赢](?![负输])', text_no_space)
    if m:
        wins = _parse_chinese_number(m.group(1))
        return wins, 0

    m = re.search(r'([零一二三四五六七八九十两]+)[负输](?![胜赢])', text_no_space)
    if m:
        losses = _parse_chinese_number(m.group(1))
        return 0, losses

    # 格式5: 两局都赢了、两局都输了、都赢了、都输了
    if '两局都赢了' in text_no_space or '都赢了' in text_no_space:
        return 2, 0
    if '两局都输了' in text_no_space or '都输了' in text_no_space:
        return 0, 2

    # 格式6: 平局
    if '平局' in text_no_space or '平' == text_no_space[-1] if text_no_space else False:
        return 1, 1

    # 格式7: 第一局赢了/输了、第二局赢了/输了
    ju_win_losses = []
    ju_pattern = r'第([零一二三四五六七八九十两\d]+)局[赢了输]'
    for m in re.finditer(ju_pattern, text_no_space):
        outcome = m.group(0)[-1]
        ju_win_losses.append(outcome)

    if ju_win_losses:
        wins = sum(1 for o in ju_win_losses if o in ['赢', '胜'])
        losses = sum(1 for o in ju_win_losses if o in ['输', '负'])
        return wins, losses

    # 格式8: 赢了输了 (无局数标记)
    if '赢了' in text_no_space and '输了' in text_no_space:
        win_count = len(re.findall(r'赢了', text_no_space))
        loss_count = len(re.findall(r'输了', text_no_space))
        return win_count, loss_count

    # 格式9: 只有赢了 或 只有输了 (单局)
    if '赢了' in text_no_space and '输了' not in text_no_space:
        return 1, 0
    if '输了' in text_no_space and '赢了' not in text_no_space:
        return 0, 1

    return None


def _parse_ju_results(text):
    """
    提取每局的胜负结果，返回 [(outcome), ...] 列表
    用于补充真实比分，比如"第一局21:15，第二局赢了"
    outcome: 'win' 或 'loss'
    """
    text_no_space = re.sub(r'\s+', '', text)
    results = []

    # 匹配第X局赢了/输了（赢了/输了可能有两个字）
    ju_pattern = r'第([零一二三四五六七八九十两\d]+)局[赢了输][了]*'
    for m in re.finditer(ju_pattern, text_no_space):
        outcome = m.group(0)[-1]
        results.append('win' if outcome in ['赢', '胜'] else 'loss')

    # 两局都赢了/输了
    if '两局都赢了' in text_no_space or '都赢了' in text_no_space:
        results = ['win', 'win']
    elif '两局都输了' in text_no_space or '都输了' in text_no_space:
        results = ['loss', 'loss']

    return results

def _parse_ju_results_with_game_numbers(text):
    """
    提取每局的胜负结果，返回 {game_num: outcome} 字典
    用于补充真实比分，比如"第一局21:15，第二局赢了"
    game_num: 1-based integer
    outcome: 'win' 或 'loss'
    """
    text_no_space = re.sub(r'\s+', '', text)
    results = {}

    # 匹配第X局赢了/输了（赢了/输了可能有两个字）
    ju_pattern = r'第([零一二三四五六七八九十两\d]+)局[赢了输][了]*'
    for m in re.finditer(ju_pattern, text_no_space):
        game_num_str = m.group(1)
        game_num = _parse_chinese_number(game_num_str)
        outcome_char = m.group(0)[-2]  # 倒数第二个字符是赢/输
        results[game_num] = 'win' if outcome_char in ['赢', '胜'] else 'loss'

    # 两局都赢了/输了
    if '两局都赢了' in text_no_space or '都赢了' in text_no_space:
        results[1] = 'win'
        results[2] = 'win'
    elif '两局都输了' in text_no_space or '都输了' in text_no_space:
        results[1] = 'loss'
        results[2] = 'loss'

    return results

def _generate_scores_from_wins_losses(wins, losses):
    """根据胜负局数生成虚拟比分"""
    scores = []
    for _ in range(wins):
        scores.append([21, 0])  # 赢的局：21-0
    for _ in range(losses):
        scores.append([0, 21])  # 输的局：0-21
    return scores

def _determine_winner_from_scores(scores):
    """根据比分判断胜负"""
    my_wins = sum(1 for s in scores if s[0] > s[1])
    opp_wins = sum(1 for s in scores if s[1] > s[0])
    if my_wins > opp_wins:
        return 'me'
    elif opp_wins > my_wins:
        return 'opponent'
    else:
        return 'draw'

def get_time_filter_range(period):
    """获取时间过滤范围"""
    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    if period == 'today':
        return today_start, now
    elif period == 'week':
        week_start = today_start - timedelta(days=today_start.weekday())
        return week_start, now
    elif period == 'month':
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return month_start, now
    else:  # all
        return None, None

def parse_match_input(text):
    """
    解析自然语言输入（改进版）
    支持格式:
      - "我和张田打三哥和奔波霸，第一局21:15，第二局21:18"
      - "我打张三，第一局21:18，第二局15:21"
      - "张三李四打我和王五，第一局21:15"
      - "我张三李四打王五赵六，第二局21:18"
      - "我和张田打三哥，21:15"（无局数标记）

    验证规则:
      - 只能是1v1（单打）或2v2（双打）
      - 总人数必须是2（单打）或4（双打）

    返回: {'my_team': ['我', '张田'], 'opponent_team': ['三哥', '奔波霸'], 'scores': [[21, 15], [21, 18]], 'match_type': 'doubles', 'error': None}
          或 {'error': '错误信息'} 当解析失败时
    """
    result = {'my_team': [], 'opponent_team': [], 'scores': [], 'match_type': 'doubles', 'error': None}

    # 预处理：移除空白字符
    text = re.sub(r'\s+', '', text)

    # ========== 1. 先检测胜负模式 (在没有真实比分的情况下) ==========
    score_pattern = r'(\d{1,2})[:：](\d{1,2})'

    # 检查是否有真实比分（如 21:15, 11:0, 21：12 等，大于10的比分）
    has_real_scores = bool(re.search(r'\d{2,}[:：]\d{2,}', text))

    # 如果没有真实比分，尝试解析胜负模式
    if not has_real_scores:
        # 特殊处理：平局 (draw) - 生成 [[21, 21]]
        if '平局' in text:
            result['scores'] = [[21, 21]]
        else:
            win_loss = _parse_win_loss_pattern(text)
            if win_loss:
                wins, losses = win_loss
                result['scores'] = _generate_scores_from_wins_losses(wins, losses)
    else:
        # 有真实比分时，也要提取每局的胜负描述来补充
        extra_win_loss = _parse_win_loss_pattern(text)
        # 提取每局胜负标记（第一局赢了等）
        ju_results = _parse_ju_results(text)
        # 真实比分由下面单独提取
        result['scores'] = []

    # ========== 2. 提取比分 (真实比分) ==========
    # 匹配半角和全角冒号的比分
    if has_real_scores:
        score_matches = list(re.finditer(score_pattern, text))
        if score_matches:
            result['scores'] = [[int(m.group(1)), int(m.group(2))] for m in score_matches]

        # 补充：提取每局胜负标记（如"第二局赢了"）来补全比分
        ju_results = _parse_ju_results_with_game_numbers(text)
        if ju_results:
            # 真实比分有几局
            real_game_count = len(result['scores'])
            # ju_results 是 dict {game_num: outcome}，找到最大的游戏号
            max_ju_game = max(ju_results.keys()) if ju_results else 0
            # 如果最大游戏号大于真实比分数量，需要补全
            if max_ju_game > real_game_count:
                for game_i in range(1, max_ju_game + 1):
                    if game_i not in range(1, real_game_count + 1):
                        # 这个游戏没有真实比分，使用ju_results中的胜负
                        if ju_results.get(game_i, 'win') == 'win':
                            result['scores'].append([21, 0])
                        else:
                            result['scores'].append([0, 21])

    # ========== 3. 移除比分和局数标记，得到纯选手文本 ==========
    # 移除局数标记和胜负结果：第1局赢了、第2局输了、两局都赢了 等
    ju_pattern = r'第[一二三四五六七八九十零\d]+局[赢了输]*|两局都[赢了输]+|都[赢了输]+|平局'
    players_text = re.sub(ju_pattern, '', text)  # 移除局数标记和胜负
    players_text = re.sub(score_pattern, '', players_text)  # 移除比分
    players_text = players_text.rstrip('，,。.')

    # ========== 3. 按"打"字分割 ==========
    da_pos = players_text.find('打')
    if da_pos == -1:
        result['error'] = '无法找到"打"字，请检查格式'
        return result

    before_da = players_text[:da_pos].strip('，,。.')
    after_da = players_text[da_pos + 1:].strip('，,。.')

    # 清理队伍文本中的胜负/比分残余文字
    # 格式: N胜M负(如一胜一负), N比M(如二比零), X:Y(如1:1), 两局都赢了, 都赢了, 平局, 赢一输一 等
    num_class = r'[\d零一二三四五六七八九十两]'
    win_loss_class = r'(?:胜|负|赢|输)'
    # Both orders: number first (一胜一负) or win/loss first (赢一输一, 输一赢一)
    wl_both_orders = rf'(?:(?:{num_class}+{win_loss_class}{{1,2}})+|(?:{win_loss_class}+{num_class}+)+)'
    trailing_pattern = rf'[，,。.\s]*(?:两局都[赢了输]+|都[赢了输]+|平局|{num_class}+比{num_class}+|{num_class}+[:：]{num_class}+|{wl_both_orders}|{win_loss_class}+了?)[，,。.\s]*$'
    before_da = re.sub(trailing_pattern, '', before_da)
    after_da = re.sub(trailing_pattern, '', after_da)

    # ========== 4. 解析己方队伍 ==========
    # "我"如果在before_da中，则己方在"打"前面；否则在"打"后面
    if '我' in before_da:
        result['my_team'] = _parse_team(before_da, '我')
        result['opponent_team'] = _parse_team(after_da)
    elif '我' in after_da:
        result['opponent_team'] = _parse_team(before_da)
        result['my_team'] = _parse_team(after_da, '我')
    else:
        result['my_team'] = _parse_team(before_da)
        result['opponent_team'] = _parse_team(after_da)

    # ========== 5. 验证人数组合（必须是1v1或2v2） ==========
    # 清理空名字（但保留"我"）
    result['my_team'] = [p for p in result['my_team'] if p and p != '我']
    result['opponent_team'] = [p for p in result['opponent_team'] if p]

    # 如果输入中包含"我"，确保"我"在己方队伍中
    if '我' in text and '我' not in result['my_team']:
        result['my_team'].insert(0, '我')

    my_count = len(result['my_team'])
    opp_count = len(result['opponent_team'])

    # 验证：单打必须是1v1，双打必须是2v2
    if my_count == 1 and opp_count == 1:
        result['match_type'] = 'singles'
    elif my_count == 2 and opp_count == 2:
        result['match_type'] = 'doubles'
    else:
        result['error'] = f'人数组合无效：{my_count}v{opp_count}，只能是1v1（单打）或2v2（双打）'
        return result

    # 如果有比分，确定胜负
    if result['scores']:
        result['winner'] = determine_winner(result['scores'])

    return result


def _parse_team(text, anchor=None):
    """
    解析队伍文本，返回选手列表

    规则：
    - 用"和"分割
    - 如果有anchor（如"我"），anchor属于当前队伍
    - 单打（无"和"，无anchor）：整段是一个选手
    - 无"和"但有anchor：尝试智能分割（按2-4字分割中文名）
    """
    if not text:
        return []

    text = text.strip('，,。.')
    if not text:
        return []

    # 如果有anchor（如"我"），则anchor前面的是队友，后面的是对手
    if anchor and anchor in text:
        idx = text.index(anchor)
        before = text[:idx]
        after = text[idx + len(anchor):]

        team = []
        if before:
            parts = _split_by_and(before)
            # 如果before只有一段且较长，尝试按2-4字分割中文名
            if len(parts) == 1 and len(parts[0]) > 2 and _is_chinese_names(parts[0]):
                parts = _split_chinese_names(parts[0])
            team.extend(parts)
        if anchor:
            team.append(anchor)
        if after:
            parts = _split_by_and(after)
            # 如果after只有一段且较长，尝试按2-4字分割中文名
            if len(parts) == 1 and len(parts[0]) > 2 and _is_chinese_names(parts[0]):
                parts = _split_chinese_names(parts[0])
            team.extend(parts)
        return team

    # 没有anchor，直接用"和"分割
    parts = _split_by_and(text)
    # 如果只有一段且较长，尝试按2-4字分割中文名
    if len(parts) == 1 and len(parts[0]) > 2 and _is_chinese_names(parts[0]):
        parts = _split_chinese_names(parts[0])
    return parts


def _is_chinese_names(text):
    """判断文本是否像中文名字（不含数字、字母）"""
    return bool(re.match(r'^[\u4e00-\u9fa5]+$', text))


def _split_chinese_names(text, expected_count=None):
    """将连续的中文名字分割成单独的名字

    策略：
    - 1-2字：直接返回（单个名字）
    - 3字：直接返回（单个名字，如"奔波霸"）
    - 4+字且偶数：按2字分割
    - 4+字且奇数：按2字分割，剩余1-3字作为整体
    """
    if not text:
        return []
    if len(text) <= 3:
        return [text]

    # 尝试按2字分割
    result = []
    i = 0
    while i < len(text):
        if i + 2 <= len(text):
            result.append(text[i:i+2])
            i += 2
        else:
            # 剩余1-3字，作为一个整体
            result.append(text[i:])
            break

    return result


def _split_by_and(text):
    """用'和'分割选手名字，处理边界情况"""
    if not text:
        return []

    parts = text.split('和')
    result = []
    for part in parts:
        part = part.strip('，,。. \t\n\r')
        if part:
            result.append(part)
    return result


def _cn_to_digit(cn_char):
    """中文数字转阿拉伯数字"""
    cn_map = {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
              '六': 6, '七': 7, '八': 8, '九': 9, '十': 10}
    return cn_map.get(cn_char, 0)

def determine_winner(scores):
    """根据比分确定胜负（每场21分，打两场）
    返回: 'me'(赢), 'opponent'(输), 'draw'(平)"""
    if not scores:
        return "draw"

    my_wins = sum(1 for s in scores if s[0] > s[1])
    opp_wins = sum(1 for s in scores if s[1] > s[0])

    if my_wins > opp_wins:
        return "me"
    elif opp_wins > my_wins:
        return "opponent"
    else:
        return "draw"

def generate_token(username, is_admin=False):
    """生成会话token"""
    return serializer.dumps({'user': username, 'is_admin': is_admin})

def verify_token(token, max_age=86400 * 7):  # 7 days default
    """验证token并返回用户信息"""
    try:
        data = serializer.loads(token, max_age=max_age)
        return data
    except (SignatureExpired, BadSignature):
        return None

@app.route('/login')
def login_page():
    """返回登录页面"""
    return render_template('login.html')

@app.route('/api/login', methods=['POST'])
def api_login():
    """登录API"""
    data = request.get_json()
    username = data.get('username', '').strip()
    password = data.get('password', '')

    # 优先检查管理员账号
    if username == LOGIN_USER and password == LOGIN_PASSWORD:
        token = generate_token(username, is_admin=True)
        session['user'] = username
        session['is_admin'] = True
        logger.info(f"Admin {username} logged in successfully")
        return jsonify({'token': token, 'user': username, 'is_admin': True})

    # 检查注册用户
    if verify_user_password(username, password):
        token = generate_token(username, is_admin=False)
        session['user'] = username
        session['is_admin'] = False
        logger.info(f"User {username} logged in successfully")
        return jsonify({'token': token, 'user': username, 'is_admin': False})

    logger.warning(f"Failed login attempt for user: {username}")
    return jsonify({'error': '用户名或密码错误'}), 401

def get_user_by_username(username):
    """根据用户名获取用户信息"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE username = ?', (username,))
    user = cursor.fetchone()
    conn.close()
    return dict(user) if user else None

def verify_user_password(username, password):
    """验证用户名密码"""
    user = get_user_by_username(username)
    if not user:
        return False
    return check_password_hash(user['password_hash'], password)

@app.route('/api/register', methods=['POST'])
def api_register():
    """注册新用户"""
    data = request.get_json()
    username = data.get('username', '').strip()
    password = data.get('password', '')
    confirm_password = data.get('confirm_password', '')

    # 验证输入
    if not username or not password:
        return jsonify({'error': '用户名和密码不能为空'}), 400

    if len(username) < 2 or len(username) > 20:
        return jsonify({'error': '用户名长度需要在2-20个字符之间'}), 400

    if password != confirm_password:
        return jsonify({'error': '两次密码输入不一致'}), 400

    if len(password) < 6:
        return jsonify({'error': '密码长度至少6个字符'}), 400

    # 检查用户名是否已存在
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT id FROM users WHERE username = ?', (username,))
    if cursor.fetchone():
        conn.close()
        return jsonify({'error': '用户名已存在'}), 400

    # 检查是否与管理员用户名冲突
    if username == LOGIN_USER:
        conn.close()
        return jsonify({'error': '用户名已存在'}), 400

    # 创建用户
    password_hash = generate_password_hash(password)
    cursor.execute(
        'INSERT INTO users (username, password_hash) VALUES (?, ?)',
        (username, password_hash)
    )
    conn.commit()
    conn.close()

    logger.info(f"New user registered: {username}")
    return jsonify({'success': True, 'message': '注册成功'}), 201

@app.route('/api/logout', methods=['POST'])
def api_logout():
    """登出API"""
    session.clear()
    return jsonify({'success': True})

@app.route('/api/me', methods=['GET'])
def api_me():
    """获取当前登录用户"""
    auth_header = request.headers.get('Authorization', '')

    if auth_header.startswith('Bearer '):
        token = auth_header[7:]
        # 检查是否是访客token（跳过登录设置的）
        if token.startswith('demo_skip_') or token.startswith('guest_'):
            return jsonify({'user': '访客', 'is_guest': True, 'is_admin': False})

        data = verify_token(token)
        if data:
            return jsonify({
                'user': data.get('user'),
                'is_admin': data.get('is_admin', False),
                'is_guest': False
            })

    return jsonify({'user': None, 'is_guest': True, 'is_admin': False}), 401

@app.route('/')
def index():
    """返回主页（需登录）"""
    if 'user' not in session:
        return redirect('/login')
    return render_template('index.html')

@app.route('/api/matches', methods=['GET'])
def get_matches():
    """获取所有比赛记录（支持筛选）"""
    filter_type = request.args.get('filter', 'all')  # all, admin, mine

    conn = get_db()
    cursor = conn.cursor()

    if filter_type == 'mine':
        user_data = get_current_user()
        if user_data:
            cursor.execute(
                'SELECT * FROM matches WHERE created_by = ? ORDER BY date DESC',
                (user_data['user'],)
            )
        else:
            cursor.execute('SELECT * FROM matches WHERE 1=0 ORDER BY date DESC')
    elif filter_type == 'admin':
        cursor.execute(
            "SELECT * FROM matches WHERE created_by = ? ORDER BY date DESC",
            (LOGIN_USER,)
        )
    else:
        cursor.execute('SELECT * FROM matches ORDER BY date DESC')

    matches = [dict(row) for row in cursor.fetchall()]
    conn.close()

    for m in matches:
        m['scores'] = json.loads(m['scores'])

    return jsonify(matches)

@app.route('/api/matches/preview', methods=['POST'])
@require_auth
def preview_match():
    """预览比赛解析结果"""
    data = request.get_json()
    text = data.get('text', '')

    logger.info(f"Preview match input: {text[:50]}...")

    parsed = parse_match_input(text)

    # 检查解析错误
    if parsed.get('error'):
        logger.warning(f"Preview parse error: {parsed['error']}")
        return jsonify({'error': parsed['error']}), 400

    if not parsed['my_team'] or not parsed['opponent_team'] or not parsed['scores']:
        logger.warning("Preview failed: missing required fields")
        return jsonify({'error': '无法解析输入，请检查格式'}), 400

    game_results = []
    for i, score in enumerate(parsed['scores']):
        if score[0] > score[1]:
            game_results.append({'game': i + 1, 'my_score': score[0], 'opp_score': score[1], 'result': '赢'})
        else:
            game_results.append({'game': i + 1, 'my_score': score[0], 'opp_score': score[1], 'result': '输'})

    logger.info(f"Preview parsed: {parsed['my_team']} vs {parsed['opponent_team']}")
    return jsonify({
        'original_text': text,
        'parsed': {
            'my_team': parsed['my_team'],
            'opponent_team': parsed['opponent_team'],
            'scores': parsed['scores'],
            'match_type': parsed['match_type']
        },
        'game_results': game_results
    })

@app.route('/api/matches', methods=['POST'])
@require_auth
def add_match():
    """添加比赛记录"""
    data = request.get_json()
    text = data.get('text', '')

    logger.info(f"Adding match: {text[:50]}...")

    parsed = parse_match_input(text)

    # 检查解析错误
    if parsed.get('error'):
        logger.warning(f"Add match parse error: {parsed['error']}")
        return jsonify({'error': parsed['error']}), 400

    if not parsed['my_team'] or not parsed['opponent_team'] or not parsed['scores']:
        logger.warning("Add match failed: missing required fields")
        return jsonify({'error': '无法解析输入，请检查格式'}), 400

    my_team_resolved = resolve_team(parsed['my_team'])
    opp_team_resolved = resolve_team(parsed['opponent_team'])

    winner = determine_winner(parsed['scores'])
    match_type = parsed['match_type']

    # 获取当前用户
    user_data = get_current_user()
    if not user_data:
        return jsonify({'error': '无权限'}), 403
    created_by = user_data['user']

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO matches (my_team, opponent_team, scores, winner, match_type, created_by)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (
        ','.join(my_team_resolved),
        ','.join(opp_team_resolved),
        json.dumps(parsed['scores']),
        winner,
        match_type,
        created_by
    ))
    conn.commit()

    match_id = cursor.lastrowid

    # 更新ELO评分（逐局更新）
    all_elo_changes = {}
    for game in parsed['scores']:
        my_score, opp_score = game[0], game[1]
        my_won = my_score > opp_score
        game_elo_changes = update_ratings_after_match(my_team_resolved, opp_team_resolved, my_won, conn)
        # 累加每局的变化（只记录方向）
        for p, new_elo in game_elo_changes.items():
            if p not in all_elo_changes:
                all_elo_changes[p] = new_elo

    cursor.execute('SELECT * FROM matches WHERE id = ?', (match_id,))
    match = dict(cursor.fetchone())
    match['scores'] = json.loads(match['scores'])
    conn.close()

    logger.info(f"Match added: id={match_id}, {parsed['my_team']} vs {parsed['opponent_team']}, ELO: {all_elo_changes}")
    return jsonify({**match, 'elo_changes': all_elo_changes}), 201

@app.route('/api/matches/<int:match_id>', methods=['DELETE'])
@require_auth
def delete_match(match_id):
    """删除比赛记录"""
    user_data = get_current_user()
    if not user_data:
        return jsonify({'error': '无权限'}), 403

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT created_by FROM matches WHERE id = ?', (match_id,))
    match = cursor.fetchone()

    if not match:
        conn.close()
        return jsonify({'error': '记录不存在'}), 404

    # 权限检查：管理员可以删除任何记录，普通用户只能删除自己的
    if not user_data.get('is_admin', False) and match['created_by'] != user_data['user']:
        conn.close()
        return jsonify({'error': '无权限删除此记录'}), 403

    cursor.execute('DELETE FROM matches WHERE id = ?', (match_id,))
    conn.commit()
    deleted = cursor.rowcount > 0
    conn.close()

    if deleted:
        # 重新计算所有ELO
        recalculate_all_ratings()
        return jsonify({'success': True, 'ratings_updated': True})
    else:
        return jsonify({'error': '记录不存在'}), 404

@app.route('/api/matches/<int:match_id>', methods=['PUT'])
@require_auth
def update_match(match_id):
    """更新比赛记录"""
    data = request.get_json()

    logger.info(f"Updating match: id={match_id}")

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('SELECT * FROM matches WHERE id = ?', (match_id,))
    existing = cursor.fetchone()

    if not existing:
        conn.close()
        logger.warning(f"Match not found for update: id={match_id}")
        return jsonify({'error': '记录不存在'}), 404

    # 只有管理员可以更新比分
    user_data = get_current_user()
    if not user_data or not user_data.get('is_admin', False):
        conn.close()
        return jsonify({'error': '无权限编辑比分'}), 403

    new_scores = data.get('scores')
    old_winner = existing['winner']

    if new_scores:
        winner = determine_winner(new_scores)
        cursor.execute('''
            UPDATE matches SET scores = ?, winner = ? WHERE id = ?
        ''', (json.dumps(new_scores), winner, match_id))
    else:
        cursor.execute('SELECT winner FROM matches WHERE id = ?', (match_id,))
        winner = cursor.fetchone()['winner']

    conn.commit()

    # 如果比分或胜负结果改变，重新计算所有ELO
    winner_changed = winner != old_winner
    if winner_changed or new_scores:
        recalculate_all_ratings()

    cursor.execute('SELECT * FROM matches WHERE id = ?', (match_id,))
    match = dict(cursor.fetchone())
    match['scores'] = json.loads(match['scores'])
    conn.close()

    logger.info(f"Match updated: id={match_id}, new_scores={new_scores}, winner_changed={winner_changed}")
    return jsonify({**match, 'ratings_updated': winner_changed})

@app.route('/api/aliases', methods=['GET'])
def get_aliases():
    """获取所有别名映射"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM player_aliases ORDER BY canonical_name')
    aliases = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify(aliases)

@app.route('/api/aliases', methods=['POST'])
@require_auth
def add_alias():
    """添加选手别名"""
    data = request.get_json()
    alias = data.get('alias', '').strip()
    canonical_name = data.get('canonical_name', '').strip()

    if not alias or not canonical_name:
        return jsonify({'error': '别名和真名不能为空'}), 400

    if alias == canonical_name:
        return jsonify({'error': '别名和真名不能相同'}), 400

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('SELECT * FROM player_aliases WHERE alias = ? OR canonical_name = ?', (alias, alias))
    if cursor.fetchone():
        conn.close()
        return jsonify({'error': '该名称已被使用'}), 400

    cursor.execute('''
        INSERT INTO player_aliases (alias, canonical_name) VALUES (?, ?)
    ''', (alias, canonical_name))
    conn.commit()
    conn.close()

    # 清除别名缓存
    clear_alias_cache()

    return jsonify({'success': True, 'alias': alias, 'canonical_name': canonical_name}), 201

@app.route('/api/aliases/<int:alias_id>', methods=['DELETE'])
@require_auth
def delete_alias(alias_id):
    """删除别名"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM player_aliases WHERE id = ?', (alias_id,))
    conn.commit()
    deleted = cursor.rowcount > 0
    conn.close()

    # 清除别名缓存
    if deleted:
        clear_alias_cache()

    if deleted:
        return jsonify({'success': True})
    else:
        return jsonify({'error': '别名不存在'}), 404

@app.route('/api/stats/<player_name>', methods=['GET'])
def get_player_stats(player_name):
    """获取指定选手的统计信息（支持时间过滤）
    按单个对手统计，不论队友是谁"""
    period = request.args.get('period', 'all')  # today, week, month, all
    opponent_filter = request.args.get('opponent', None)

    canonical_name = resolve_player_name(player_name)

    # 构建SQL查询，使用SQL层过滤
    conn = get_db()
    cursor = conn.cursor()

    # 构建WHERE子句：只查询包含当前选手的比赛
    sql = 'SELECT * FROM matches WHERE (my_team LIKE ? OR opponent_team LIKE ?)'
    params = [f'%{canonical_name}%', f'%{canonical_name}%']

    # 时间过滤（SQL层）
    if period == 'today':
        sql += " AND date >= date('now', 'localtime')"
    elif period == 'week':
        sql += " AND date >= date('now', '-7 days')"
    elif period == 'month':
        sql += " AND date >= date('now', '-30 days')"

    sql += ' ORDER BY date DESC'

    cursor.execute(sql, params)
    all_matches = [dict(row) for row in cursor.fetchall()]
    conn.close()

    for m in all_matches:
        m['scores'] = json.loads(m['scores'])

    # 对手过滤（解析为规范名）
    if opponent_filter:
        opponent_filter = resolve_player_name(opponent_filter)

    # 按单个对手统计：key是对手名称，value是该对手的战绩
    opponent_stats = {}
    total_games_won = 0
    total_games_lost = 0

    for match in all_matches:
        my_team = match['my_team'].split(',')
        opp_team = match['opponent_team'].split(',')

        my_team_resolved = resolve_team(my_team)
        opp_team_resolved = resolve_team(opp_team)

        # 确定当前选手在哪一方
        if canonical_name in my_team_resolved:
            is_my_side = True
            opponents = opp_team_resolved  # 对手列表
        elif canonical_name in opp_team_resolved:
            is_my_side = False
            opponents = my_team_resolved  # 我方变成对手
        else:
            continue  # 当前选手不在这场比赛中

        # 对手过滤：检查是否包含过滤的对手
        if opponent_filter and opponent_filter not in opponents:
            continue

        # 统计小局
        for game in match['scores']:
            if is_my_side:
                if game[0] > game[1]:
                    total_games_won += 1
                elif game[1] > game[0]:
                    total_games_lost += 1
            else:
                if game[1] > game[0]:
                    total_games_won += 1
                elif game[0] > game[1]:
                    total_games_lost += 1

        # 对每个对手单独统计
        for opp in opponents:
            if opp not in opponent_stats:
                opponent_stats[opp] = {'games_won': 0, 'games_lost': 0}

            for game in match['scores']:
                if is_my_side:
                    if game[0] > game[1]:
                        opponent_stats[opp]['games_won'] += 1
                    elif game[1] > game[0]:
                        opponent_stats[opp]['games_lost'] += 1
                else:
                    if game[1] > game[0]:
                        opponent_stats[opp]['games_won'] += 1
                    elif game[0] > game[1]:
                        opponent_stats[opp]['games_lost'] += 1

    result = {
        'player_name': canonical_name,
        'period': period,
        'total_games_won': total_games_won,
        'total_games_lost': total_games_lost,
        'total_games': total_games_won + total_games_lost,
        'win_rate': round(total_games_won / (total_games_won + total_games_lost) * 100, 1) if (total_games_won + total_games_lost) > 0 else 0,
        'opponents': []
    }

    for opp_name, stats in opponent_stats.items():
        total = stats['games_won'] + stats['games_lost']
        result['opponents'].append({
            'name': opp_name,
            'games_won': stats['games_won'],
            'games_lost': stats['games_lost'],
            'games': total,
            'win_rate': round(stats['games_won'] / total * 100, 1) if total > 0 else 0
        })

    result['opponents'].sort(key=lambda x: x['games'], reverse=True)

    return jsonify(result)

@app.route('/api/rankings', methods=['GET'])
def get_rankings_endpoint():
    """获取玩家排名列表"""
    limit = request.args.get('limit', None, type=int)
    rankings = get_rankings()
    if limit:
        rankings = rankings[:limit]
    return jsonify({
        'rankings': rankings,
        'total_players': len(rankings),
        'default_elo': DEFAULT_ELO
    })

@app.route('/api/players', methods=['GET'])
def get_all_players():
    """获取所有选手列表"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT DISTINCT my_team, opponent_team FROM matches')
    rows = cursor.fetchall()

    players = set()
    alias_map = get_alias_map()

    for row in rows:
        for team in [row['my_team'], row['opponent_team']]:
            for player in team.split(','):
                if player:
                    resolved = resolve_player_name(player.strip())
                    players.add(resolved)

    conn.close()
    return jsonify(sorted(list(players)))

@app.route('/api/players/<name>', methods=['DELETE'])
@require_auth
def delete_player(name):
    """删除选手及其所有数据（别名和比赛记录）"""
    conn = get_db()
    cursor = conn.cursor()

    # Decode URL encoding
    player_name = urllib.parse.unquote(name)

    # Validate player name (only allow Chinese, letters, numbers)
    if not re.match(r'^[\u4e00-\u9fa5a-zA-Z0-9]+$', player_name):
        conn.close()
        return jsonify({'error': '无效的选手名称'}), 400

    # Delete aliases where this player is canonical_name or alias
    cursor.execute('DELETE FROM player_aliases WHERE canonical_name = ? OR alias = ?', (player_name, player_name))

    # Delete matches where player is in my_team or opponent_team (use parameterized query safely)
    cursor.execute('DELETE FROM matches WHERE my_team LIKE ? OR opponent_team LIKE ?',
                   (f'%{player_name}%', f'%{player_name}%'))

    conn.commit()
    deleted = cursor.rowcount
    conn.close()

    # 清除别名缓存
    clear_alias_cache()

    return jsonify({'success': True, 'deleted_count': deleted})

@app.route('/health', methods=['GET'])
def health_check():
    """健康检查端点"""
    return jsonify({'status': 'ok'})

if __name__ == '__main__':
    import os
    debug_mode = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    init_db()
    app.run(debug=debug_mode, port=18080, host='0.0.0.0')
