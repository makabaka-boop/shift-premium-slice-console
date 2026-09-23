import type { SegmentJson } from '../types'
import { weekdayName } from '../time'

interface Props {
  segments: SegmentJson[]
}

function segColor(ruleId: string | null, bp: number): string {
  if (ruleId === null) return 'var(--seg-default)'
  if (bp > 15000) return 'var(--seg-high)'
  if (bp >= 10000) return 'var(--seg-mid)'
  return 'var(--seg-low)'
}

function pad(n: number): string {
  return String(n).padStart(2, '0')
}

function axisLabel(iso: string): string {
  const d = new Date(iso)
  return `${d.getMonth() + 1}/${d.getDate()} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** 按段时长等比绘制的时间轴；hover 可见每段适用规则。 */
export function Timeline({ segments }: Props) {
  const total = segments.reduce((sum, s) => sum + s.minutes, 0)
  return (
    <div className="timeline-wrap" data-testid="timeline">
      <div className="timeline" role="img" aria-label="值班分段时间轴">
        {segments.map((s, i) => {
          const width = total === 0 ? 0 : (s.minutes / total) * 100
          const label = s.ruleId ?? '默认1.0×'
          return (
            <div
              key={i}
              className="timeline-seg"
              data-testid={`timeline-seg-${i}`}
              style={{ width: `${width}%`, background: segColor(s.ruleId, s.basisPoints) }}
              title={`${axisLabel(s.start)} → ${axisLabel(s.end)}（${weekdayName(s.weekday)}）
规则: ${label}
倍率: ${(s.basisPoints / 10000).toFixed(2)}×
时长: ${s.minutes} 分钟
工资: ${s.pay.numerator}/${s.pay.denominator} 分`}
            >
              <span className="timeline-label">{label}</span>
              <span className="timeline-min">{s.minutes}m</span>
            </div>
          )
        })}
      </div>
      <div className="timeline-axis">
        <span>{segments.length ? axisLabel(segments[0].start) : ''}</span>
        <span>{segments.length ? axisLabel(segments[segments.length - 1].end) : ''}</span>
      </div>
    </div>
  )
}
