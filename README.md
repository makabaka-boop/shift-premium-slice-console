# 值班津贴复核台（Duty Pay Review Console）

跨午夜值班同时命中夜班、周末与专项津贴时，倍率不能直接相加、也不能漏过午夜与规则
边界。本项目提供一个轻量全栈复核台：

- **web/**：React + Vite + TypeScript，编辑每周重复规则、展示彩色时间轴、分段明细和
  逐分钟采用规则（最终复核员可以解释每一分钟按哪条规则计费）。
- **backend/**：FastAPI 精确切片服务，午夜与规则边界强制分段，工资与总额以
  **不可约分数**返回，全程 `fractions.Fraction`，不做任何中途四舍五入。
- **docker-compose.yml**：`web`（nginx 静态托管 + 反代）与 `api`（uvicorn）两个服务。

## 计费规则（与实现一一对应）

一次请求包含：

| 字段 | 说明 |
| --- | --- |
| `start` / `end` | 本地墙钟时间 `YYYY-MM-DDTHH:MM`，精确到分钟，无秒、无时区 |
| `baseRateCents` | 正整数，每小时基础工资（分） |
| `rules` | 至多 20 条，字段：`id`（唯一非空）、`weekdays`（非空，Mon=0..Sun=6）、`startMinute`/`endMinute`（日内分钟，结束早于开始表示跨午夜，如 22:00→06:00）、`priority`（整数，大者优先）、`basisPoints`（正整数，10000 = 1.0×） |

每一分钟：

1. 取所有覆盖该分钟的规则中 `priority` 最大者；
2. `priority` 并列时取 `id` 的 **UTF-8 字节序**最小者；
3. 无任何规则命中按隐式基线 **10000 bps** 计费。

分段规则：在**每个午夜**以及**中标规则发生变化**的分钟边界切段；即使午夜两侧中标规则
相同（例如都是基线）也照样切段。第 `k` 段工资为

```
pay = baseRateCents · 分钟数/60 · basisPoints/10000
```

总额为各段（等价于各分钟）精确分数之和，约分后返回 `{numerator, denominator}`。

无效日历日期（如 2026-02-29）、空星期集合、`end <= start`、区间超过 36 小时、重复 id、
非正整数费率等一律返回 **422**；页面在收到 422（或本地预检失败）时清除上一次结果。

## 运行

```bash
docker compose up --build
# web: http://localhost:8080   api: http://localhost:8000  (GET /health)
```

本地开发（无需 Docker）：

```bash
# 后端
cd backend && pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# 前端（/api 自动代理到 8000）
cd web && npm install && npm run dev   # http://localhost:5173
```

## 测试

**pytest —— 逐分钟对拍。** 测试内置一个独立 oracle（以
`sort(key=(-priority, id.encode('utf-8')))` 重新选出每分钟中标规则，逐分钟累加分数），
再校验：每分钟 trace 与 oracle 一致、切段恰好落在午夜与中标变化处、分段/总额为不可约
分数且等于逐分钟之和；另含全部 422 边界与 HTTP 层用例。

```bash
cd backend && pytest
```

**Playwright —— 只走一次录入与结果展示。** 一条完整业务流（录入跨午夜夜班 + 周六专项
规则 → 一次提交 → 校验精确总额、三段切分、午夜边界与悬停解释），一条 422 清结果流。

```bash
cd web
npx playwright install chromium
E2E_BASE_URL=http://localhost:8080 npx playwright test   # compose 栈
# 本地 dev 栈：E2E_BASE_URL=http://localhost:5173 npx playwright test
```

## API 摘要

`POST /api/slice`

```json
{
  "start": "2026-09-25T22:00",
  "end": "2026-09-26T06:00",
  "baseRateCents": 1000,
  "rules": [
    {"id": "night", "weekdays": [0,1,2,3,4,5,6],
     "startMinute": 1320, "endMinute": 360,
     "priority": 1, "basisPoints": 13000}
  ]
}
```

响应含 `totalPay`、`segments[]`（每段的偏移/墙钟起止、星期、分钟、`ruleId`、bps、
精确 `pay`）以及 `minutes[]` 逐分钟中标明细；无命中时 `ruleId` 为 `null`、bps 为 10000。
页面上的小数仅为长除法展示（循环/截断处以 `…` 标注），**金额以分数为准**。
