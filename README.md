# 羽毛球比分记录应用 (Badminton Score Recorder)

一个基于 Flask 的 Web 应用，用于通过自然语言记录羽毛球比赛比分。

## 功能特点

- 🌐 中文自然语言输入，如：`我和张三打李四，21:15`
- 👥 支持单打和双打比赛
- 📊 球员战绩统计（今日/本周/本月/全部）
- 🔄 别名系统（如"我"映射到真实姓名）
- 🔐 API 密钥认证保护

## 快速开始

### 本地运行

```bash
pip install -r requirements.txt
python app.py
```

访问 http://localhost:5000

### Docker 运行

```bash
docker-compose up --build
```

### 设置 API 密钥（可选）

```bash
export API_KEY="your-secret-key"
```

## 输入格式

**单打：**
```
我打张三，21:15
```

**双打：**
```
我和张三打李四和赵五，第一局21:15，第二局21:18
```

**我方为"我"：**
```
张三李四打我和王五
```

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 首页 |
| GET | `/api/matches` | 获取所有比赛 |
| POST | `/api/matches/preview` | 预览解析结果 |
| POST | `/api/matches` | 添加比赛 |
| PUT | `/api/matches/<id>` | 更新比赛 |
| DELETE | `/api/matches/<id>` | 删除比赛 |
| GET | `/api/aliases` | 获取别名列表 |
| POST | `/api/aliases` | 添加别名 |
| DELETE | `/api/aliases/<id>` | 删除别名 |
| GET | `/api/players` | 获取所有球员 |
| GET | `/api/stats/<player>` | 获取球员统计 |

## 技术栈

- **后端：** Flask + SQLite
- **前端：** 原生 JavaScript + CSS
- **数据库：** SQLite
