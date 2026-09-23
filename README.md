# 值班津贴复核台

跨午夜值班同时命中夜班、周末、专项津贴时，**倍率不能直接相加**（会重复计费），
人工按整小时切段又会漏掉规则边界。本项目是一个轻量全栈复核台：

- **web/**：React + Vite + TypeScript，编辑值班区间与每周重复规则，展示分段时间轴与逐段明细。
- **backend/**：FastAPI，对区间**逐分钟裁决**，在午夜与规则边界处精确切片，
  每段工资与总额都以**不可约分数**返回，全程不四舍五入。
- **docker-compose.yml**：两个服务，`web`（nginx:8080）反代 `/api` 到 `api`（uvicorn:8000）。

## 裁决规则

1. 请求包含一个不超过 36 小时、精确到分钟的本地（无时区）值班区间、正整数
   `baseRateCents`，以及至多 20 条每周重复规则。
2. 规则字段：唯一 `id`、星期集合（0=周一 … 6=周日）、可跨午夜的分钟窗口
   `[startMinute, endMinute)`、`priority`、以 basisPoints 表示的倍率（10000 = 1.0×）。
   `endMinute < startMinute` 表示跨午夜；`endMinute = 1440` 即 24:00。
3. **同一分钟只采用一条规则**：取 `priority` 最大者；仍并列时取 `id` 的
   **UTF-8 字节序**最小者；无规则命中按 10000。
4. 相邻且裁决相同的分钟归并为一段；**午夜 00:00 一定断开**，即使两侧规则相同。
5. 段工资 = `分钟数 × baseRateCents × basisPoints / (10000 × 60)`，
   用 Python `Fraction` 累加，每段与总额都是不可约分数（另附仅用于展示的六位小数）。
6. 无效日期、空星期集合、空窗口（start==end）、结束不晚于开始、超过 36 小时、
   重复 id、超过 20 条规则等一律返回 **422**；前端每次提交先清除旧结果。

复核员通过每段的「开始/结束/星期/分钟数/规则 id/倍率/分数工资」即可解释其中的
**每一分钟**采用了哪条规则；页面时间轴悬停可见同样的信息。

## Docker Compose 运行

```bash
docker compose up --build
# web: http://localhost:8080   api: http://localhost:8000/api/health
```

## 本地开发

```bash
# 后端
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# 前端（dev server 已配置 /api 代理到 8000）
cd web
npm install
npm run dev          # http://localhost:5173
```

## 测试

**pytest 逐分钟对拍**（40 个随机种子 + 边界用例 + HTTP 校验用例）：

```bash
cd backend
pip install pytest httpx
pytest
```

`tests/test_slice.py` 内置一个与引擎实现相互独立的 oracle（独立的窗口覆盖判定与
排序裁决），逐分钟跑一遍后与引擎分段逐段对拍，包括分段边界、分钟数、分数总额、
不可约性、UTF-8 id 平局（含中文 id）。

**Playwright 浏览器测试**（一次录入与结果展示，另含一次 422 清除旧结果）：

```bash
cd web
npx playwright install chromium
E2E_BASE_URL=http://localhost:8080 npx playwright test   # compose 已启动
# 或开发模式：E2E_BASE_URL=http://localhost:5173 npx playwright test
```

## API

`POST /api/calculate`，请求体（camelCase）：

```json
{
  "start": "2026-09-25T22:00",
  "end": "2026-09-26T02:00",
  "baseRateCents": 6000,
  "rules": [
    {"id": "night",   "weekdays": [0,1,2,3,4,5,6], "startMinute": 1320, "endMinute": 360,  "priority": 1, "basisPoints": 12000},
    {"id": "weekend", "weekdays": [5,6],           "startMinute": 0,    "endMinute": 1440, "priority": 2, "basisPoints": 15000},
    {"id": "special", "weekdays": [4],             "startMinute": 1380, "endMinute": 1440, "priority": 3, "basisPoints": 20000}
  ]
}
```

上例（周五 22:00 → 周六 02:00）切成三段：22–23 night 7200 分、
23–24 special 12000 分、00–02 weekend 18000 分，总额 **37200/1 分**——
倍率从不相加，每分钟只由一条规则负责。
