"""
羽毛球比赛自然语言解析 — LLM 调用封装
使用 httpx 调用 MiniMax API（Anthropic 兼容格式）
"""
import os
import logging
import json
import httpx

logger = logging.getLogger(__name__)

# LLM 配置（从环境变量读取）
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.minimaxi.com/anthropic")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "sk-cp-w9Bp5jaIhRjRzJj5016ALUHoD9IJ3WYrVgyzEeKvF1aXSpm21fHa5bEB9i0rxVdyWboxNoZMarsyiAJ4kkxrsc7WusvAji1nZSaGQCEv_fPUI-KsdGAkWxE")
LLM_MODEL = os.environ.get("LLM_MODEL", "MiniMax-M2.7")

PARSE_SYSTEM_PROMPT = """你是一个羽毛球比赛记录解析器。用户会用自然语言描述一场羽毛球比赛，你需要提取出结构化信息。

## 输入格式
用户输入是一段中文自然语言，描述一场羽毛球比赛的结果。

## 输出格式
必须严格返回 JSON，不要有任何其他文字。格式如下：
{
  "my_team": ["球员A"],
  "opponent_team": ["球员B"],
  "scores": [[21, 15]],
  "match_type": "singles"
}

### 字段说明
- my_team: 我方球员列表。"我"字表示说话人自己，必须保留在列表中
- opponent_team: 对方球员列表
- scores: 每局比分数组，[我方得分, 对方得分]。没有具体比分时，赢的局记为 [21, 0]，输的局记为 [0, 21]
- match_type: "singles"（单打，1v1）或 "doubles"（双打，2v2）

## 规则
1. 找到"打"字作为两队分隔符。"打"前面的是我方，后面是对方。但如果"我"在"打"后面，则"我"所在一方是我方
2. 球员名之间用"和"分隔，如果"我"在队伍中，"我"本身就是一个球员
3. 只支持 1v1（单打）或 2v2（双打），其他人数组合视为错误
4. 比分格式多样，如 "21:15"、"21：15"、"21比15"、"第一局21:15"，都要正确提取
5. 如果没有具体比分，只有胜负描述（如"赢了"、"2:0"、"一胜一负"），按以下规则生成虚拟比分：
   - 赢的局: [21, 0]
   - 输的局: [0, 21]
6. "平局"生成 [[21, 21]]
7. 球员名字保持原样，不要修改
8. 如果输入无法解析，返回 {"error": "错误原因描述"}

## 示例

输入: "我和张三打李四和王五，第一局21:15，第二局21:18"
输出: {"my_team": ["我", "张三"], "opponent_team": ["李四", "王五"], "scores": [[21, 15], [21, 18]], "match_type": "doubles"}

输入: "我打张三，第一局赢了，第二局输了"
输出: {"my_team": ["我"], "opponent_team": ["张三"], "scores": [[21, 0], [0, 21]], "match_type": "singles"}

输入: "我和张三打李四和赵五，2:0"
输出: {"my_team": ["我", "张三"], "opponent_team": ["李四", "赵五"], "scores": [[21, 0], [21, 0]], "match_type": "doubles"}

输入: "张三和李四打我和王五，21:15，18:21，15:21"
输出: {"my_team": ["我", "王五"], "opponent_team": ["张三", "李四"], "scores": [[15, 21], [21, 18], [21, 15]], "match_type": "doubles"}

输入: "我和张三打李四，一胜一负"
输出: {"my_team": ["我", "张三"], "opponent_team": ["李四"], "scores": [[21, 0], [0, 21]], "match_type": "doubles"}

输入: "我打张三，平局"
输出: {"my_team": ["我"], "opponent_team": ["张三"], "scores": [[21, 21]], "match_type": "singles"}
"""


def call_llm_parse(text: str) -> dict:
    """
    调用 LLM 解析自然语言比赛描述。

    Args:
        text: 用户输入的中文比赛描述

    Returns:
        解析后的结构化 dict，失败返回 {"error": "..."}
    """
    if not LLM_API_KEY:
        logger.error("LLM_API_KEY environment variable not set")
        return {"error": "LLM API 未配置（LLM_API_KEY 环境变量未设置）"}

    if not text or not text.strip():
        return {"error": "输入为空"}

    url = f"{LLM_BASE_URL}/v1/messages"
    headers = {
        "Authorization": f"Bearer {LLM_API_KEY}",
        "Content-Type": "application/json",
        "anthropic-version": "2023-06-01",
    }
    payload = {
        "model": LLM_MODEL,
        "max_tokens": 1024,
        "system": PARSE_SYSTEM_PROMPT,
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": text}]}
        ],
    }

    try:
        with httpx.Client(timeout=20.0, trust_env=False) as client:
            response = client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            result = response.json()

        # 提取 LLM 返回的 content（Anthropic 格式）
        content_blocks = result.get("content", [])
        if not content_blocks:
            logger.error(f"LLM response has no content: {result}")
            return {"error": "LLM 返回格式异常"}

        # 取第一个 text 块
        text_content = ""
        for block in content_blocks:
            if block.get("type") == "text":
                text_content = block.get("text", "")
                break

        if not text_content:
            logger.error(f"LLM response has no text block: {result}")
            return {"error": "LLM 返回内容为空"}

        # 去掉可能的 markdown code fence
        content = text_content.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1])
        content = content.strip()

        parsed = json.loads(content)
        return parsed

    except json.JSONDecodeError as e:
        logger.error(f"LLM returned non-JSON: {text_content[:200] if text_content else str(e)}")
        return {"error": "LLM 返回了非 JSON 内容，请尝试手动录入"}
    except httpx.TimeoutException:
        logger.error("LLM request timed out")
        return {"error": "LLM 请求超时，请尝试手动录入"}
    except httpx.HTTPStatusError as e:
        logger.error(f"LLM HTTP error: {e.response.status_code} - {e.response.text[:200]}")
        return {"error": f"LLM 请求失败（{e.response.status_code}），请尝试手动录入"}
    except Exception as e:
        logger.exception(f"Unexpected error calling LLM: {e}")
        return {"error": f"LLM 调用异常：{str(e)}，请尝试手动录入"}
