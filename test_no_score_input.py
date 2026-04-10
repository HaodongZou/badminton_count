"""
测试羽毛球比分记录应用 - 无比分输入解析
测试解析没有具体比分的比赛结果输入，如"1:0"、"一胜一负"等
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

from app import parse_match_input, determine_winner, init_db

# 初始化测试数据库
init_db()


class TestNoScoreInput:
    """测试无比分输入解析 - 1:0/2:1等格式"""

    @pytest.mark.parametrize("input_text,expected", [
        # 2:0 格式 - 双打
        ("我和张三打李四和赵五，2:0", {
            'my_team': ['我', '张三'],
            'opponent_team': ['李四', '赵五'],
            'winner': 'me',
            'scores': [[21, 0], [21, 0]]
        }),
        # 0:2 格式 - 双打
        ("我和张三打李四和赵五，0:2", {
            'my_team': ['我', '张三'],
            'opponent_team': ['李四', '赵五'],
            'winner': 'opponent',
            'scores': [[0, 21], [0, 21]]
        }),
        # 1:1 格式 - 双打
        ("我和张三打李四和赵五，1:1", {
            'my_team': ['我', '张三'],
            'opponent_team': ['李四', '赵五'],
            'winner': 'draw',
            'scores': [[21, 0], [0, 21]]
        }),
        # 2:1 格式 - 双打
        ("我和张三打李四和赵五，2:1", {
            'my_team': ['我', '张三'],
            'opponent_team': ['李四', '赵五'],
            'winner': 'me',
            'scores': [[21, 0], [0, 21], [21, 0]]
        }),
        # 单打 1:0
        ("我打张三，1:0", {
            'my_team': ['我'],
            'opponent_team': ['张三'],
            'winner': 'me',
            'scores': [[21, 0]]
        }),
        # 单打 0:1
        ("我打张三，0:1", {
            'my_team': ['我'],
            'opponent_team': ['张三'],
            'winner': 'opponent',
            'scores': [[0, 21]]
        }),
        # 单打 1:1
        ("我打张三，1:1", {
            'my_team': ['我'],
            'opponent_team': ['张三'],
            'winner': 'draw',
            'scores': [[21, 0], [0, 21]]
        }),
        # 3:0 格式
        ("我和张三打李四，3:0", {
            'my_team': ['我', '张三'],
            'opponent_team': ['李四'],
            'winner': 'me',
            'scores': [[21, 0], [21, 0], [21, 0]]
        }),
    ])
    def test_numeric_score_format(self, input_text, expected):
        """测试数字比分格式 2:0, 1:1, 2:1 等"""
        result = parse_match_input(input_text)
        assert result.get('error') is None, f"解析错误: {result.get('error')}"
        assert result['my_team'] == expected['my_team'], f"my_team不匹配: {result['my_team']} vs {expected['my_team']}"
        assert result['opponent_team'] == expected['opponent_team'], f"opponent_team不匹配"
        assert result['winner'] == expected['winner'], f"winner不匹配: {result['winner']} vs {expected['winner']}"
        assert result['scores'] == expected['scores'], f"scores不匹配: {result['scores']} vs {expected['scores']}"


class TestFullWidthColon:
    """测试全角冒号（：）格式"""

    @pytest.mark.parametrize("input_text,expected", [
        # 全角冒号 2：0
        ("我和张三打李四和赵五，2：0", {
            'my_team': ['我', '张三'],
            'opponent_team': ['李四', '赵五'],
            'winner': 'me',
            'scores': [[21, 0], [21, 0]]
        }),
        # 全角冒号 1：1
        ("我和张三打李四和赵五，1：1", {
            'my_team': ['我', '张三'],
            'opponent_team': ['李四', '赵五'],
            'winner': 'draw',
            'scores': [[21, 0], [0, 21]]
        }),
        # 全角冒号 0：2
        ("我和张三打李四和赵五，0：2", {
            'my_team': ['我', '张三'],
            'opponent_team': ['李四', '赵五'],
            'winner': 'opponent',
            'scores': [[0, 21], [0, 21]]
        }),
        # 混合冒号
        ("我和张三打李四，1：0", {
            'my_team': ['我', '张三'],
            'opponent_team': ['李四'],
            'winner': 'me',
            'scores': [[21, 0]]
        }),
    ])
    def test_full_width_colon(self, input_text, expected):
        """测试全角冒号格式（１：１）"""
        result = parse_match_input(input_text)
        assert result.get('error') is None, f"解析错误: {result.get('error')}"
        assert result['my_team'] == expected['my_team']
        assert result['opponent_team'] == expected['opponent_team']
        assert result['winner'] == expected['winner']
        assert result['scores'] == expected['scores']


class TestChineseNumberText:
    """测试中文数字文本 - 一比一、二比零等"""

    @pytest.mark.parametrize("input_text,expected", [
        # 一比一 = 1:1
        ("我和张三打李四，一比一", {
            'my_team': ['我', '张三'],
            'opponent_team': ['李四'],
            'winner': 'draw',
            'scores': [[21, 0], [0, 21]]
        }),
        # 二比零 = 2:0
        ("我和张三打李四，二比零", {
            'my_team': ['我', '张三'],
            'opponent_team': ['李四'],
            'winner': 'me',
            'scores': [[21, 0], [21, 0]]
        }),
        # 二比一 = 2:1
        ("我和张三打李四，二比一", {
            'my_team': ['我', '张三'],
            'opponent_team': ['李四'],
            'winner': 'me',
            'scores': [[21, 0], [0, 21], [21, 0]]
        }),
        # 零比二 = 0:2
        ("我和张三打李四，零比二", {
            'my_team': ['我', '张三'],
            'opponent_team': ['李四'],
            'winner': 'opponent',
            'scores': [[0, 21], [0, 21]]
        }),
        # 三比零 = 3:0
        ("我和张三打李四，三比零", {
            'my_team': ['我', '张三'],
            'opponent_team': ['李四'],
            'winner': 'me',
            'scores': [[21, 0], [21, 0], [21, 0]]
        }),
        # 零比三 = 0:3
        ("我和张三打李四，零比三", {
            'my_team': ['我', '张三'],
            'opponent_team': ['李四'],
            'winner': 'opponent',
            'scores': [[0, 21], [0, 21], [0, 21]]
        }),
        # 单打 一比零
        ("我打张三，一比零", {
            'my_team': ['我'],
            'opponent_team': ['张三'],
            'winner': 'me',
            'scores': [[21, 0]]
        }),
        # 单打 零比一
        ("我打张三，零比一", {
            'my_team': ['我'],
            'opponent_team': ['张三'],
            'winner': 'opponent',
            'scores': [[0, 21]]
        }),
    ])
    def test_chinese_number_text(self, input_text, expected):
        """测试中文数字比分文本"""
        result = parse_match_input(input_text)
        assert result.get('error') is None, f"解析错误: {result.get('error')}"
        assert result['my_team'] == expected['my_team']
        assert result['opponent_team'] == expected['opponent_team']
        assert result['winner'] == expected['winner']
        assert result['scores'] == expected['scores']


class TestWinLossText:
    """测试胜负文字描述 - 赢了、输了、一胜一负等"""

    @pytest.mark.parametrize("input_text,expected", [
        # 一胜一负
        ("我和张三打李四和赵五，一胜一负", {
            'my_team': ['我', '张三'],
            'opponent_team': ['李四', '赵五'],
            'winner': 'draw',
            'scores': [[21, 0], [0, 21]]
        }),
        # 两胜
        ("我和张三打李四和赵五，两胜", {
            'my_team': ['我', '张三'],
            'opponent_team': ['李四', '赵五'],
            'winner': 'me',
            'scores': [[21, 0], [21, 0]]
        }),
        # 一负
        ("我和张三打李四和赵五，一负", {
            'my_team': ['我', '张三'],
            'opponent_team': ['李四', '赵五'],
            'winner': 'opponent',
            'scores': [[0, 21]]
        }),
        # 两负
        ("我和张三打李四和赵五，两负", {
            'my_team': ['我', '张三'],
            'opponent_team': ['李四', '赵五'],
            'winner': 'opponent',
            'scores': [[0, 21], [0, 21]]
        }),
        # 一胜（单场）
        ("我打张三，一胜", {
            'my_team': ['我'],
            'opponent_team': ['张三'],
            'winner': 'me',
            'scores': [[21, 0]]
        }),
        # 一负（单场）
        ("我打张三，一负", {
            'my_team': ['我'],
            'opponent_team': ['张三'],
            'winner': 'opponent',
            'scores': [[0, 21]]
        }),
        # 三胜
        ("我和张三打李四，三胜", {
            'my_team': ['我', '张三'],
            'opponent_team': ['李四'],
            'winner': 'me',
            'scores': [[21, 0], [21, 0], [21, 0]]
        }),
        # 三负
        ("我和张三打李四，三负", {
            'my_team': ['我', '张三'],
            'opponent_team': ['李四'],
            'winner': 'opponent',
            'scores': [[0, 21], [0, 21], [0, 21]]
        }),
    ])
    def test_win_loss_text(self, input_text, expected):
        """测试胜负文字描述"""
        result = parse_match_input(input_text)
        assert result.get('error') is None, f"解析错误: {result.get('error')}"
        assert result['my_team'] == expected['my_team']
        assert result['opponent_team'] == expected['opponent_team']
        assert result['winner'] == expected['winner']
        assert result['scores'] == expected['scores']


class TestWinLossPerGame:
    """测试每局胜负描述 - 第一局赢了、第二局输了"""

    @pytest.mark.parametrize("input_text,expected", [
        # 第一局赢了，第二局输了（双打）
        ("我和叁哥打张田和十七，第一局赢了，第二局输了", {
            'my_team': ['我', '叁哥'],
            'opponent_team': ['张田', '十七'],
            'winner': 'draw',
            'scores': [[21, 0], [0, 21]]
        }),
        # 第一局输了，第二局赢了（双打）
        ("我和叁哥打张田和十七，第一局输了，第二局赢了", {
            'my_team': ['我', '叁哥'],
            'opponent_team': ['张田', '十七'],
            'winner': 'draw',
            'scores': [[0, 21], [21, 0]]
        }),
        # 赢了（单场）
        ("我打张三，赢了", {
            'my_team': ['我'],
            'opponent_team': ['张三'],
            'winner': 'me',
            'scores': [[21, 0]]
        }),
        # 输了（单场）
        ("我打张三，输了", {
            'my_team': ['我'],
            'opponent_team': ['张三'],
            'winner': 'opponent',
            'scores': [[0, 21]]
        }),
        # 三局全赢
        ("我打张三，第一局赢了，第二局赢了，第三局赢了", {
            'my_team': ['我'],
            'opponent_team': ['张三'],
            'winner': 'me',
            'scores': [[21, 0], [21, 0], [21, 0]]
        }),
        # 三局两胜一负
        ("我打张三，第一局赢了，第二局输了，第三局赢了", {
            'my_team': ['我'],
            'opponent_team': ['张三'],
            'winner': 'me',
            'scores': [[21, 0], [0, 21], [21, 0]]
        }),
        # 只有一局输了
        ("我和王五打李四，第一局输了", {
            'my_team': ['我', '王五'],
            'opponent_team': ['李四'],
            'winner': 'opponent',
            'scores': [[0, 21]]
        }),
        # 赢了赢了（无局数标记）
        ("我和张三打李四，赢了赢了", {
            'my_team': ['我', '张三'],
            'opponent_team': ['李四'],
            'winner': 'me',
            'scores': [[21, 0], [21, 0]]
        }),
    ])
    def test_win_loss_per_game(self, input_text, expected):
        """测试每局胜负描述"""
        result = parse_match_input(input_text)
        assert result.get('error') is None, f"解析错误: {result.get('error')}"
        assert result['my_team'] == expected['my_team']
        assert result['opponent_team'] == expected['opponent_team']
        assert result['winner'] == expected['winner']
        assert result['scores'] == expected['scores']


class TestGeneratedScores:
    """测试生成的比分验证"""

    def test_generated_win_score(self):
        """验证生成的赢球比分是 [21, 0]"""
        result = parse_match_input("我打张三，1:0")
        assert result['scores'] == [[21, 0]]

    def test_generated_loss_score(self):
        """验证生成的输球比分是 [0, 21]"""
        result = parse_match_input("我打张三，0:1")
        assert result['scores'] == [[0, 21]]

    def test_generated_scores_for_draw(self):
        """验证平局时生成的比分"""
        result = parse_match_input("我打张三，1:1")
        assert result['scores'] == [[21, 0], [0, 21]]

    def test_generated_scores_for_2_1_win(self):
        """验证2:1胜利时生成的比分"""
        result = parse_match_input("我打张三，2:1")
        assert result['scores'] == [[21, 0], [0, 21], [21, 0]]


class TestMatchType:
    """测试比赛类型识别"""

    @pytest.mark.parametrize("input_text,expected_match_type", [
        ("我打张三，1:0", "singles"),
        ("我和张三打李四，2:0", "doubles"),
        ("我打张三，一胜", "singles"),
        ("我和张三打李四和赵五，一胜一负", "doubles"),
    ])
    def test_match_type_recognition(self, input_text, expected_match_type):
        """测试单打/双打类型识别"""
        result = parse_match_input(input_text)
        assert result.get('error') is None
        assert result['match_type'] == expected_match_type, f"match_type不匹配: {result['match_type']} vs {expected_match_type}"


class TestInvalidInputs:
    """测试无效输入"""

    @pytest.mark.parametrize("input_text", [
        # 无效的比分格式
        "我打张三，3:3",  # 不允许平分
        "我打张三，22:0",  # 超过21分
        "我打张三，21:22",  # 超过21分
        # 无效的人数组合
        "我打张三和李四，1:0",  # 3人队伍
        "我和张三李四打李四，1:0",  # 人数异常
    ])
    def test_invalid_inputs_return_error(self, input_text):
        """测试无效输入应该返回错误"""
        result = parse_match_input(input_text)
        # 无效输入应该返回error字段
        assert result.get('error') is not None, f"无效输入应该返回错误: {input_text}"


class TestRegressionExistingFormat:
    """回归测试 - 确保现有格式仍然正常工作"""

    def test_existing_score_format_still_works(self):
        """确保现有的比分格式 21:15 仍然正常"""
        result = parse_match_input("我和张三打李四，21:15")
        assert result.get('error') is None
        assert result['my_team'] == ['我', '张三']
        assert result['opponent_team'] == ['李四']
        assert result['scores'] == [[21, 15]]
        assert result['winner'] == 'me'

    def test_existing_multigame_format_still_works(self):
        """确保现有的多局格式仍然正常"""
        result = parse_match_input("我和张三打李四，第一局21:15，第二局21:18")
        assert result.get('error') is None
        assert result['scores'] == [[21, 15], [21, 18]]
        assert result['winner'] == 'me'

    def test_existing_singles_format_still_works(self):
        """确保现有的单打格式仍然正常"""
        result = parse_match_input("我打张三，21:18")
        assert result.get('error') is None
        assert result['my_team'] == ['我']
        assert result['opponent_team'] == ['张三']
        assert result['scores'] == [[21, 18]]
        assert result['match_type'] == 'singles'

    def test_existing_three_game_format_still_works(self):
        """确保现有的三局格式仍然正常"""
        result = parse_match_input("我打王五，第一局21:15，第二局18:21，第三局21:19")
        assert result.get('error') is None
        assert len(result['scores']) == 3
        assert result['scores'] == [[21, 15], [18, 21], [21, 19]]

    def test_existing_no_game_markers_still_works(self):
        """确保现有的无局数标记格式仍然正常"""
        result = parse_match_input("我和张田打三哥和奔波霸，21:15")
        assert result.get('error') is None
        assert result['scores'] == [[21, 15]]

    def test_existing_compound_opponent_names_still_works(self):
        """确保现有的复合对手名字格式仍然正常"""
        result = parse_match_input("我和甜甜打三哥和奔波霸，第一局21:15")
        assert result.get('error') is None
        assert len(result['opponent_team']) == 2
        assert '三哥' in result['opponent_team']
        assert '奔波霸' in result['opponent_team']


class TestEdgeCases:
    """边界情况测试"""

    def test_zero_games(self):
        """0场游戏不应该出现（需要至少1场）"""
        # 这种输入理论上不应该被解析成功
        result = parse_match_input("我打张三，")
        # 至少应该有一个分数
        if result.get('error') is None:
            assert len(result['scores']) >= 1

    def test_opponent_has_我(self):
        """对手包含"我"的情况"""
        result = parse_match_input("张三李四打我和王五，1:0")
        assert result.get('error') is None
        assert '我' in result['my_team']
        assert '王五' in result['my_team']
        assert '张三' in result['opponent_team']
        assert '李四' in result['opponent_team']

    def test_我和队友分打对面多人(self):
        """我和队友分打对面多人"""
        result = parse_match_input("我和张三李四打王五赵六，2:0")
        assert result.get('error') is None
        assert '我' in result['my_team']
        # 队伍识别可能有多种方式

    def test_high_score_win(self):
        """测试高分胜利 - 2:0"""
        result = parse_match_input("我打张三，2:0")
        assert result['winner'] == 'me'
        assert len(result['scores']) == 2
        for score in result['scores']:
            assert score[0] == 21
            assert score[1] == 0

    def test_high_score_loss(self):
        """测试高分失败 - 0:2"""
        result = parse_match_input("我打张三，0:2")
        assert result['winner'] == 'opponent'
        assert len(result['scores']) == 2
        for score in result['scores']:
            assert score[0] == 0
            assert score[1] == 21


class TestDetermineWinnerIntegration:
    """测试 determine_winner 与无比分输入的集成"""

    @pytest.mark.parametrize("scores,expected", [
        ([[21, 0]], 'me'),
        ([[0, 21]], 'opponent'),
        ([[21, 0], [21, 0]], 'me'),
        ([[0, 21], [0, 21]], 'opponent'),
        ([[21, 0], [0, 21]], 'draw'),
        ([[21, 0], [0, 21], [21, 0]], 'me'),
        ([[0, 21], [21, 0], [0, 21]], 'opponent'),
    ])
    def test_determine_winner_with_generated_scores(self, scores, expected):
        """测试 determine_winner 对生成的比分的处理"""
        assert determine_winner(scores) == expected


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
