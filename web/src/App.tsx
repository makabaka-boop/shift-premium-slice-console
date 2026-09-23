import { useMemo, useState } from "react";
import {
  ApiError,
  formatFraction,
  formatTime,
  fractionToDecimal,
  postSlice,
} from "./api";
import type {
  RuleInput,
  SegmentOut,
  SliceResponse,
  ValidationIssue,
} from "./types";

const WEEKDAYS = [
  { v: 0, label: "一" },
  { v: 1, label: "二" },
  { v: 2, label: "三" },
  { v: 3, label: "四" },
  { v: 4, label: "五" },
  { v: 5, label: "六" },
  { v: 6, label: "日" },
];

const WEEKDAY_CN = ["一", "二", "三", "四", "五", "六", "日"];

// Deterministic palette keyed by rule id so a rule keeps its color.
const PALETTE = [
  "#4f7cff",
  "#e07b39",
  "#2f9e44",
  "#c2255c",
  "#7048e8",
  "#0c8599",
  "#f08c00",
  "#5c940d",
];
function ruleColor(id: string | null): string {
  if (id === null) return "#868e96";
  let h = 0;
  for (const ch of id) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return PALETTE[h % PALETTE.length];
}

function minutesToHHMM(m: number): string {
  const h = Math.floor(m / 60);
  const mm = m % 60;
  return `${String(h).padStart(2, "0")}:${String(mm).padStart(2, "0")}`;
}
function hhmmToMinutes(v: string): number {
  const [h, m] = v.split(":").map(Number);
  return h * 60 + m;
}

interface RuleDraft {
  id: string;
  weekdays: Set<number>;
  start: string; // HH:MM
  end: string; // HH:MM
  priority: string;
  basisPoints: string;
}

const emptyRule = (n: number): RuleDraft => ({
  id: `rule-${n}`,
  weekdays: new Set([0, 1, 2, 3, 4]),
  start: "22:00",
  end: "06:00",
  priority: "1",
  basisPoints: "13000",
});

export default function App() {
  const [start, setStart] = useState("2026-09-25T22:00");
  const [end, setEnd] = useState("2026-09-26T06:00");
  const [baseRate, setBaseRate] = useState("1000");
  const [drafts, setDrafts] = useState<RuleDraft[]>([
    {
      id: "night",
      weekdays: new Set(WEEKDAYS.map((w) => w.v)),
      start: "22:00",
      end: "06:00",
      priority: "1",
      basisPoints: "13000",
    },
  ]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string[] | null>(null);
  const [result, setResult] = useState<SliceResponse | null>(null);
  const [hoverMinute, setHoverMinute] = useState<number | null>(null);

  const updateDraft = (idx: number, patch: Partial<RuleDraft>) => {
    setDrafts((ds) => ds.map((d, i) => (i === idx ? { ...d, ...patch } : d)));
  };
  const toggleWeekday = (idx: number, v: number) => {
    setDrafts((ds) =>
      ds.map((d, i) => {
        if (i !== idx) return d;
        const next = new Set(d.weekdays);
        if (next.has(v)) next.delete(v);
        else next.add(v);
        return { ...d, weekdays: next };
      }),
    );
  };

  const localIssues = useMemo((): string[] => {
    const out: string[] = [];
    if (!start || !end) out.push("起止时间不能为空");
    else if (end <= start) out.push("结束时间必须晚于开始时间");
    if (!Number.isInteger(Number(baseRate)) || Number(baseRate) < 1)
      out.push("baseRateCents 必须是正整数");
    const ids = new Set<string>();
    drafts.forEach((d, i) => {
      if (!d.id.trim()) out.push(`规则 #${i + 1}：id 不能为空`);
      if (ids.has(d.id)) out.push(`规则 id 重复：${d.id}`);
      ids.add(d.id);
      if (d.weekdays.size === 0) out.push(`规则 ${d.id}：星期集合不能为空`);
      if (d.start === "00:00" && d.end === "00:00")
        out.push(`规则 ${d.id}：窗口不能为 00:00→00:00（结束 00:00 表示当日午夜 24:00）`);
      if (!Number.isInteger(Number(d.priority)))
        out.push(`规则 ${d.id}：priority 必须是整数`);
      if (!Number.isInteger(Number(d.basisPoints)) || Number(d.basisPoints) < 1)
        out.push(`规则 ${d.id}：basisPoints 必须是正整数`);
    });
    return out;
  }, [start, end, baseRate, drafts]);

  const submit = async () => {
    if (localIssues.length) {
      // Invalid input: stale results are cleared, per the review contract.
      setResult(null);
      setError(localIssues);
      return;
    }
    const rules: RuleInput[] = drafts.map((d) => ({
      id: d.id,
      weekdays: [...d.weekdays].sort((a, b) => a - b),
      startMinute: hhmmToMinutes(d.start),
      endMinute: hhmmToMinutes(d.end) === 0 ? 1440 : hhmmToMinutes(d.end),
      priority: Number(d.priority),
      basisPoints: Number(d.basisPoints),
    }));
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await postSlice({
        start,
        end,
        baseRateCents: Number(baseRate),
        rules,
      });
      setResult(res);
    } catch (e) {
      // On any error (incl. 422) old results must not remain on screen.
      setResult(null);
      if (e instanceof ApiError && e.status === 422) {
        setError([
          "后端返回 422，已清除上一次复核结果：",
          ...e.issues.map((it: ValidationIssue) => {
            const where = it.loc
              .filter((p) => p !== "body")
              .join(" → ");
            return where ? `· ${where}: ${it.msg}` : `· ${it.msg}`;
          }),
        ]);
      } else if (e instanceof ApiError) {
        setError([e.message]);
      } else {
        setError([String(e)]);
      }
    } finally {
      setLoading(false);
    }
  };

  const ruleIds = useMemo(
    () => (result ? new Set(result.segments.map((s) => s.ruleId).filter(Boolean)) : new Set()),
    [result],
  );

  return (
    <div style={{ fontFamily: "system-ui, sans-serif", margin: "24px auto", maxWidth: 1080, color: "#1a1a1a" }}>
      <h1>值班津贴复核台</h1>
      <p style={{ color: "#555" }}>
        同一分钟只采用最高 priority 的规则；priority 并列时取 id 的 UTF-8 字节序最小者；无规则按 10000 bps
        基线计。分段与总额均以<strong>不可约分数</strong>返回，全程不做四舍五入。
      </p>

      <section
        style={{ border: "1px solid #ddd", borderRadius: 8, padding: 16, marginBottom: 16 }}
      >
        <h2 style={{ marginTop: 0 }}>① 录入值班区间与规则</h2>
        <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
          <label>
            开始（本地时间，精确到分）
            <br />
            <input
              type="datetime-local"
              value={start}
              step={60}
              onChange={(e) => setStart(e.target.value)}
            />
          </label>
          <label>
            结束
            <br />
            <input
              type="datetime-local"
              value={end}
              step={60}
              onChange={(e) => setEnd(e.target.value)}
            />
          </label>
          <label>
            baseRateCents（每小时，正整数）
            <br />
            <input
              type="number"
              min={1}
              step={1}
              value={baseRate}
              style={{ width: 120 }}
              onChange={(e) => setBaseRate(e.target.value)}
            />
          </label>
        </div>

        <h3>每周重复规则（{drafts.length}/20，窗口结束早于开始表示跨午夜）</h3>
        {drafts.map((d, idx) => (
          <div
            key={idx}
            data-testid={`rule-row-${idx}`}
            style={{
              border: "1px solid #e3e3e3",
              borderRadius: 6,
              padding: 12,
              marginBottom: 8,
              background: "#fafafa",
            }}
          >
            <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center" }}>
              <label>
                id{" "}
                <input
                  value={d.id}
                  onChange={(e) => updateDraft(idx, { id: e.target.value })}
                />
              </label>
              <span>
                星期{" "}
                {WEEKDAYS.map((w) => (
                  <button
                    type="button"
                    key={w.v}
                    onClick={() => toggleWeekday(idx, w.v)}
                    style={{
                      width: 30,
                      marginLeft: 2,
                      border: "1px solid #999",
                      borderRadius: 4,
                      background: d.weekdays.has(w.v) ? ruleColor(d.id) : "#fff",
                      color: d.weekdays.has(w.v) ? "#fff" : "#333",
                      cursor: "pointer",
                    }}
                  >
                    {w.label}
                  </button>
                ))}
              </span>
              <label>
                窗口{" "}
                <input
                  type="time"
                  step={60}
                  value={d.start}
                  onChange={(e) => updateDraft(idx, { start: e.target.value })}
                />{" "}
                –{" "}
                <input
                  type="time"
                  step={60}
                  value={d.end === "24:00" ? "00:00" : d.end}
                  onChange={(e) => updateDraft(idx, { end: e.target.value })}
                />
              </label>
              <label>
                priority{" "}
                <input
                  type="number"
                  value={d.priority}
                  style={{ width: 80 }}
                  onChange={(e) => updateDraft(idx, { priority: e.target.value })}
                />
              </label>
              <label>
                basisPoints{" "}
                <input
                  type="number"
                  min={1}
                  value={d.basisPoints}
                  style={{ width: 110 }}
                  onChange={(e) => updateDraft(idx, { basisPoints: e.target.value })}
                />
              </label>
              <button
                type="button"
                onClick={() => setDrafts((ds) => ds.filter((_, i) => i !== idx))}
              >
                删除
              </button>
            </div>
          </div>
        ))}
        <div style={{ marginTop: 8 }}>
          <button
            type="button"
            disabled={drafts.length >= 20}
            onClick={() => setDrafts((ds) => [...ds, emptyRule(ds.length + 1)])}
          >
            + 添加规则
          </button>
          <button
            type="button"
            style={{ marginLeft: 12, fontWeight: 700 }}
            disabled={loading}
            onClick={submit}
            data-testid="submit"
          >
            {loading ? "复核中…" : "提交精确切片"}
          </button>
        </div>
      </section>

      {error && (
        <section
          data-testid="error-panel"
          style={{
            border: "1px solid #c2255c",
            background: "#fff0f4",
            borderRadius: 8,
            padding: 12,
            marginBottom: 16,
          }}
        >
          {error.map((line, i) => (
            <div key={i}>{line}</div>
          ))}
        </section>
      )}

      {result && <ResultView result={result} ruleIds={ruleIds as Set<string>} hoverMinute={hoverMinute} setHoverMinute={setHoverMinute} />}
    </div>
  );
}

function ResultView({
  result,
  ruleIds,
  hoverMinute,
  setHoverMinute,
}: {
  result: SliceResponse;
  ruleIds: Set<string>;
  hoverMinute: number | null;
  setHoverMinute: (v: number | null) => void;
}) {
  const total = result.totalPay;
  const hovered: SegmentOut | null =
    hoverMinute === null
      ? null
      : result.segments.find((s) => s.startOffset <= hoverMinute && hoverMinute < s.endOffset) ?? null;

  return (
    <section data-testid="result-panel">
      <h2>② 复核结果</h2>
      <div
        style={{
          border: "1px solid #2f9e44",
          background: "#f0fdf4",
          borderRadius: 8,
          padding: 12,
          marginBottom: 12,
        }}
      >
        <div data-testid="total-fraction" style={{ fontSize: 22, fontWeight: 700 }}>
          总工资（精确）：{formatFraction(total)} 分
        </div>
        <div style={{ color: "#444" }}>
          ≈ {fractionToDecimal(total)} 分（长除法展示，循环或截断处标 …）
        </div>
        <div>总时长：{result.totalMinutes} 分钟（{formatTime(result.request.start)} → {formatTime(result.request.end)}）</div>
      </div>

      <h3>时间轴（午夜处强制切段）</h3>
      <Legend ruleIds={ruleIds} />
      <div
        style={{ display: "flex", width: "100%", height: 44, borderRadius: 6, overflow: "hidden", border: "1px solid #999" }}
        data-testid="timeline"
        onMouseLeave={() => setHoverMinute(null)}
      >
        {result.segments.map((s) => (
          <div
            key={s.index}
            data-testid={`seg-${s.index}`}
            onMouseEnter={() => setHoverMinute(s.startOffset)}
            title={`${formatTime(s.start)}–${formatTime(s.end)} · ${s.ruleId ?? "基线 10000"} · ${s.basisPoints} bps · ${s.minutes} 分钟`}
            style={{
              width: `${(s.minutes / result.totalMinutes) * 100}%`,
              background: ruleColor(s.ruleId),
              color: "#fff",
              fontSize: 11,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              borderRight: "1px solid rgba(255,255,255,.6)",
              cursor: "default",
            }}
          >
            {s.minutes >= 30 ? s.ruleId ?? "base" : ""}
          </div>
        ))}
      </div>
      {hovered && (
        <div data-testid="hover-info" style={{ margin: "8px 0", color: "#333" }}>
          {formatTime(hovered.start)}–{formatTime(hovered.end)}（周{WEEKDAY_CN[hovered.weekday]}）：
          规则 <strong>{hovered.ruleId ?? "（无命中，10000 bps 基线）"}</strong>，
          倍率 {hovered.basisPoints} bps，{hovered.minutes} 分钟，
          本段工资 <strong>{formatFraction(hovered.pay)}</strong> 分
        </div>
      )}

      <h3>分段明细</h3>
      <table border={1} cellPadding={6} style={{ borderCollapse: "collapse", width: "100%", fontSize: 14 }}>
        <thead>
          <tr>
            <th>#</th><th>起</th><th>止</th><th>星期</th><th>分钟</th>
            <th>采用规则</th><th>bps</th><th>本段工资（不可约分数，分）</th>
          </tr>
        </thead>
        <tbody>
          {result.segments.map((s) => (
            <tr key={s.index} data-testid={`seg-row-${s.index}`}>
              <td>{s.index + 1}</td>
              <td>{formatTime(s.start)}</td>
              <td>{formatTime(s.end)}</td>
              <td>{s.weekdayName}</td>
              <td>{s.minutes}</td>
              <td style={{ color: ruleColor(s.ruleId), fontWeight: 700 }}>
                {s.ruleId ?? "基线（无命中）"}
              </td>
              <td>{s.basisPoints}</td>
              <td>{formatFraction(s.pay)}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h3>逐分钟可解释性（悬停时间轴定位）</h3>
      <MinuteGrid result={result} setHoverMinute={setHoverMinute} hoverMinute={hoverMinute} />
    </section>
  );
}

function Legend({ ruleIds }: { ruleIds: Set<string> }) {
  return (
    <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginBottom: 6, fontSize: 13 }}>
      <span>
        <span style={{ display: "inline-block", width: 12, height: 12, background: ruleColor(null), borderRadius: 2 }} />{" "}
        基线 10000
      </span>
      {[...ruleIds].map((id) => (
        <span key={id}>
          <span style={{ display: "inline-block", width: 12, height: 12, background: ruleColor(id), borderRadius: 2 }} />{" "}
          {id}
        </span>
      ))}
    </div>
  );
}

function MinuteGrid({
  result,
  hoverMinute,
  setHoverMinute,
}: {
  result: SliceResponse;
  hoverMinute: number | null;
  setHoverMinute: (v: number | null) => void;
}) {
  const [page, setPage] = useState(0);
  const pageSize = 60;
  const pages = Math.ceil(result.minutes.length / pageSize);
  const cur = Math.min(page, pages - 1);
  const rows = result.minutes.slice(cur * pageSize, (cur + 1) * pageSize);
  return (
    <div>
      <div style={{ marginBottom: 6 }}>
        <button disabled={cur === 0} onClick={() => setPage(cur - 1)}>上一页</button>{" "}
        第 {cur + 1}/{pages} 页（每页 {pageSize} 分钟）{" "}
        <button disabled={cur >= pages - 1} onClick={() => setPage(cur + 1)}>下一页</button>
        {hoverMinute !== null && (
          <span style={{ marginLeft: 12 }}>
            定位：第 {Math.floor(hoverMinute / pageSize) + 1} 页
            <button style={{ marginLeft: 6 }} onClick={() => setPage(Math.floor(hoverMinute / pageSize))}>跳转</button>
          </span>
        )}
      </div>
      <table border={1} cellPadding={4} style={{ borderCollapse: "collapse", fontSize: 12, width: "100%" }}>
        <thead>
          <tr><th>偏移</th><th>本地时间</th><th>星期</th><th>日内分钟</th><th>采用规则</th><th>bps</th></tr>
        </thead>
        <tbody>
          {rows.map((m) => (
            <tr
              key={m.offset}
              onMouseEnter={() => setHoverMinute(m.offset)}
              style={{ background: hoverMinute === m.offset ? "#eef3ff" : undefined }}
            >
              <td>{m.offset}</td>
              <td>{formatTime(m.time)}</td>
              <td>{WEEKDAYS[m.weekday].label}</td>
              <td>{m.minuteOfDay}（{minutesToHHMM(m.minuteOfDay)}）</td>
              <td style={{ color: ruleColor(m.ruleId), fontWeight: 700 }}>
                {m.ruleId ?? "基线"}
              </td>
              <td>{m.basisPoints}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
