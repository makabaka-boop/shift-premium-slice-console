export interface RuleInput {
  id: string
  weekdays: number[] // 0=周一 ... 6=周日
  startMinute: number // 0..1439
  endMinute: number // 1..1440（1440=24:00）
  priority: number
  basisPoints: number
}

export interface ShiftPayload {
  start: string
  end: string
  baseRateCents: number
  rules: RuleInput[]
}

export interface FractionJson {
  numerator: number
  denominator: number
  decimal: string
}

export interface SegmentJson {
  start: string
  end: string
  minutes: number
  weekday: number
  ruleId: string | null
  basisPoints: number
  pay: FractionJson
}

export interface CalculateResponse {
  segments: SegmentJson[]
  total: FractionJson
  totalMinutes: number
}

export interface ValidationIssue {
  loc: (string | number)[]
  msg: string
}
