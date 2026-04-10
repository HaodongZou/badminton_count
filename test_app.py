"""
测试羽毛球比分记录应用
"""
import pytest
import sys
import os
import tempfile

# 设置测试数据库路径（临时文件）
_temp_db = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
TEST_DATABASE_PATH = _temp_db.name
_temp_db.close()
os.environ['DATABASE_PATH'] = TEST_DATABASE_PATH

sys.path.insert(0, os.path.dirname(__file__))

from app import app, parse_match_input, determine_winner, init_db

# 初始化测试数据库
init_db()

class TestWinRateCalculation:
    """测试胜率计算"""

    def test_full_win(self):
        """全胜情况"""
        scores = [[21, 15], [21, 18]]
        assert determine_winner(scores) == 'me'

    def test_full_lose(self):
        """全负情况"""
        scores = [[15, 21], [18, 21]]
        assert determine_winner(scores) == 'opponent'

    def test_one_each(self):
        """1胜1负情况"""
        scores = [[21, 15], [15, 21]]
        assert determine_winner(scores) == 'draw'

    def test_zero_games(self):
        """0场比赛"""
        scores = []
        assert determine_winner(scores) == 'draw'

    def test_three_games_full_win(self):
        """三场全胜"""
        scores = [[21, 15], [21, 18], [21, 10]]
        assert determine_winner(scores) == 'me'

    def test_three_games_one_win_two_lose(self):
        """三场1胜2负"""
        scores = [[15, 21], [21, 18], [15, 21]]
        assert determine_winner(scores) == 'opponent'


class TestParseMatchInput:
    """测试比赛输入解析"""

    def test_doubles_match(self):
        """双打比赛解析"""
        text = "我和张田打三哥和奔波霸，第一局21:15，第二局21:18"
        result = parse_match_input(text)

        assert '我' in result['my_team']
        assert '张田' in result['my_team']
        assert '三哥' in result['opponent_team']
        assert '奔波霸' in result['opponent_team']
        assert len(result['scores']) == 2
        assert result['scores'][0] == [21, 15]
        assert result['scores'][1] == [21, 18]
        assert result['match_type'] == 'doubles'

    def test_singles_match(self):
        """单打比赛解析"""
        text = "我打张三，第一局21:18，第二局15:21"
        result = parse_match_input(text)

        assert '我' in result['my_team']
        assert '张三' in result['opponent_team']
        assert result['match_type'] == 'singles'

    def test_compound_opponent_names(self):
        """复合对手名字测试 - 三哥和奔波霸 应该是两个独立的名字"""
        text = "我和甜甜打三哥和奔波霸，第一局21:15"
        result = parse_match_input(text)

        # 验证对手是两个人
        assert len(result['opponent_team']) == 2, f"Expected 2 opponents, got {result['opponent_team']}"
        assert '三哥' in result['opponent_team']
        assert '奔波霸' in result['opponent_team']

    def test_singles_single_name(self):
        """单打单名字"""
        text = "我打李四，第一局21:10"
        result = parse_match_input(text)

        assert result['my_team'] == ['我']
        assert result['opponent_team'] == ['李四']
        assert result['match_type'] == 'singles'

    def test_doubles_without_he(self):
        """双打但对手名字包含和"""
        text = "我和王五打赵六和孙七，第一局21:15"
        result = parse_match_input(text)

        assert len(result['opponent_team']) == 2
        assert '赵六' in result['opponent_team']
        assert '孙七' in result['opponent_team']

    def test_scores_parsing(self):
        """比分解析"""
        text = "我和甜甜打张三李四，第一局21:11，第二局21:15"
        result = parse_match_input(text)

        assert result['scores'] == [[21, 11], [21, 15]]

    def test_three_games(self):
        """三局比赛"""
        text = "我打王五，第一局21:15，第二局18:21，第三局21:19"
        result = parse_match_input(text)

        assert len(result['scores']) == 3
        assert result['scores'] == [[21, 15], [18, 21], [21, 19]]


class TestEdgeCases:
    """边界情况测试"""

    def test_very_close_game(self):
        """很接近的比分 - 21:20算赢"""
        scores = [[21, 20], [20, 21]]
        assert determine_winner(scores) == 'draw'

    def test_blowout_game(self):
        """大比分获胜"""
        scores = [[21, 5], [21, 3]]
        assert determine_winner(scores) == 'me'

    def test_player_name_with_numbers(self):
        """选手名字包含数字"""
        text = "我和17打三哥和19，第一局21:15"
        result = parse_match_input(text)

        assert '17' in result['my_team']
        assert '19' in result['opponent_team']

    def test_chinese_numbers_in_games(self):
        """局数用中文数字"""
        text = "我打李四，第一局21:15，第二局21:18"
        result = parse_match_input(text)

        assert len(result['scores']) == 2


def test_register_success():
    """测试成功注册"""
    response = app.test_client().post('/api/register', json={
        'username': 'testuser_reg',
        'password': 'test123',
        'confirm_password': 'test123'
    })
    assert response.status_code == 201
    data = response.get_json()
    assert data['success'] == True

def test_register_duplicate_username():
    """测试重复用户名"""
    # 先注册
    app.test_client().post('/api/register', json={
        'username': 'duplicate_user',
        'password': 'test123',
        'confirm_password': 'test123'
    })
    # 再次注册同一用户名
    response = app.test_client().post('/api/register', json={
        'username': 'duplicate_user',
        'password': 'test123',
        'confirm_password': 'test123'
    })
    assert response.status_code == 400

def test_register_password_mismatch():
    """测试密码不一致"""
    response = app.test_client().post('/api/register', json={
        'username': 'newuser',
        'password': 'test123',
        'confirm_password': 'different'
    })
    assert response.status_code == 400

def test_login_registered_user():
    """测试注册用户登录"""
    # 先注册
    app.test_client().post('/api/register', json={
        'username': 'logintest_user',
        'password': 'test123',
        'confirm_password': 'test123'
    })
    # 登录
    response = app.test_client().post('/api/login', json={
        'username': 'logintest_user',
        'password': 'test123'
    })
    assert response.status_code == 200
    data = response.get_json()
    assert data['user'] == 'logintest_user'
    assert data['is_admin'] == False

def test_login_admin():
    """测试管理员登录"""
    response = app.test_client().post('/api/login', json={
        'username': 'admin',
        'password': 'badminton123'
    })
    assert response.status_code == 200
    data = response.get_json()
    assert data['user'] == 'admin'
    assert data['is_admin'] == True

def test_api_me_registered_user():
    """测试 /api/me 返回注册用户信息"""
    # 注册并登录
    app.test_client().post('/api/register', json={
        'username': 'apime_user',
        'password': 'test123',
        'confirm_password': 'test123'
    })
    login_resp = app.test_client().post('/api/login', json={
        'username': 'apime_user',
        'password': 'test123'
    })
    token = login_resp.get_json()['token']

    # 测试 /api/me
    resp = app.test_client().get('/api/me', headers={'Authorization': f'Bearer {token}'})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['user'] == 'apime_user'
    assert data['is_admin'] == False
    assert data.get('is_guest', False) == False

def test_api_me_guest():
    """测试 /api/me 返回访客信息"""
    resp = app.test_client().get('/api/me', headers={'Authorization': 'Bearer guest_12345'})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['is_guest'] == True

def test_guest_cannot_add_match():
    """访客不能添加比赛"""
    response = app.test_client().post('/api/matches',
        headers={'Authorization': 'Bearer guest_123'},
        json={'text': '我打李四，21:15'})
    assert response.status_code == 403

def test_user_can_add_match():
    """注册用户可以添加比赛"""
    # 注册
    app.test_client().post('/api/register', json={
        'username': 'testplayer',
        'password': 'test123',
        'confirm_password': 'test123'
    })
    # 登录
    login_resp = app.test_client().post('/api/login', json={
        'username': 'testplayer',
        'password': 'test123'
    })
    token = login_resp.get_json()['token']
    # 添加比赛
    response = app.test_client().post('/api/matches',
        headers={'Authorization': f'Bearer {token}'},
        json={'text': '我打李四，21:15'})
    assert response.status_code == 201
    data = response.get_json()
    assert data['created_by'] == 'testplayer'

def test_user_can_only_delete_own_match():
    """普通用户只能删除自己的比赛"""
    # 注册用户A
    app.test_client().post('/api/register', json={
        'username': 'userA_del',
        'password': 'test123',
        'confirm_password': 'test123'
    })
    # 用户A登录并添加比赛
    login_resp = app.test_client().post('/api/login', json={
        'username': 'userA_del',
        'password': 'test123'
    })
    tokenA = login_resp.get_json()['token']

    add_resp = app.test_client().post('/api/matches',
        headers={'Authorization': f'Bearer {tokenA}'},
        json={'text': '我打李四，21:15'})
    match_id = add_resp.get_json()['id']

    # 注册用户B
    app.test_client().post('/api/register', json={
        'username': 'userB_del',
        'password': 'test123',
        'confirm_password': 'test123'
    })
    login_respB = app.test_client().post('/api/login', json={
        'username': 'userB_del',
        'password': 'test123'
    })
    tokenB = login_respB.get_json()['token']

    # 用户B尝试删除用户A的比赛
    response = app.test_client().delete(f'/api/matches/{match_id}',
        headers={'Authorization': f'Bearer {tokenB}'})
    assert response.status_code == 403

def test_admin_can_delete_any_match():
    """管理员可以删除任何比赛"""
    # 注册用户
    app.test_client().post('/api/register', json={
        'username': 'regularuser_del',
        'password': 'test123',
        'confirm_password': 'test123'
    })
    login_resp = app.test_client().post('/api/login', json={
        'username': 'regularuser_del',
        'password': 'test123'
    })
    token = login_resp.get_json()['token']

    add_resp = app.test_client().post('/api/matches',
        headers={'Authorization': f'Bearer {token}'},
        json={'text': '我打李四，21:15'})
    match_id = add_resp.get_json()['id']

    # 管理员登录
    admin_login = app.test_client().post('/api/login', json={
        'username': 'admin',
        'password': 'badminton123'
    })
    admin_token = admin_login.get_json()['token']

    # 管理员删除
    response = app.test_client().delete(f'/api/matches/{match_id}',
        headers={'Authorization': f'Bearer {admin_token}'})
    assert response.status_code == 200

def test_matches_filter_mine():
    """测试筛选我的记录"""
    # 注册用户
    app.test_client().post('/api/register', json={
        'username': 'filteruser',
        'password': 'test123',
        'confirm_password': 'test123'
    })
    login_resp = app.test_client().post('/api/login', json={
        'username': 'filteruser',
        'password': 'test123'
    })
    token = login_resp.get_json()['token']

    # 添加比赛
    app.test_client().post('/api/matches',
        headers={'Authorization': f'Bearer {token}'},
        json={'text': '我打李四，21:15'})

    # 筛选我的
    resp = app.test_client().get('/api/matches?filter=mine',
        headers={'Authorization': f'Bearer {token}'})
    assert resp.status_code == 200
    matches = resp.get_json()
    for m in matches:
        assert m['created_by'] == 'filteruser'

def test_matches_filter_admin():
    """测试筛选管理员记录"""
    login_resp = app.test_client().post('/api/login', json={
        'username': 'admin',
        'password': 'badminton123'
    })
    token = login_resp.get_json()['token']

    resp = app.test_client().get('/api/matches?filter=admin',
        headers={'Authorization': f'Bearer {token}'})
    assert resp.status_code == 200
    matches = resp.get_json()
    for m in matches:
        assert m['created_by'] == 'admin'

def test_user_cannot_update_match():
    """普通用户不能编辑比分"""
    # 注册用户
    app.test_client().post('/api/register', json={
        'username': 'noupdateuser',
        'password': 'test123',
        'confirm_password': 'test123'
    })
    login_resp = app.test_client().post('/api/login', json={
        'username': 'noupdateuser',
        'password': 'test123'
    })
    token = login_resp.get_json()['token']

    # 添加比赛
    add_resp = app.test_client().post('/api/matches',
        headers={'Authorization': f'Bearer {token}'},
        json={'text': '我打李四，21:15'})
    match_id = add_resp.get_json()['id']

    # 尝试更新
    resp = app.test_client().put(f'/api/matches/{match_id}',
        headers={'Authorization': f'Bearer {token}'},
        json={'scores': [[21, 18]]})
    assert resp.status_code == 403

if __name__ == '__main__':
    pytest.main([__file__, '-v'])
