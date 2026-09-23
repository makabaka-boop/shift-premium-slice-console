export interface RuleInput {
  id: string;
  weekdays: number[]; // Mon=0..Sun=6
  startMinute: number;
  endMinute: number;
  priority: number;
  basisPoints: number;
}

export interface SliceRequest {
  start: string; // 'YYYY-MM-DDTHH:MM'
  end: string;
  baseRateCents: number;
  rules: RuleInput[];
}

export interface FractionOut {
  numerator: number;
  denominator: number;
}

export interface SegmentOut {
  index: number;
  startOffset: number;
  endOffset: number;
  start: string;
  end: string;
  weekday: number;
  weekdayName: string;
  minutes: number;
  ruleId: string | null;
  basisPoints: number;
  pay: FractionOut;
}

export interface MinuteOut {
  offset: number;
  time: string;
  weekday: number;
  minuteOfDay: number;
  ruleId: string | null;
  basisPoints: number;
}

export interface SliceResponse {
  request: { start: string; end: string; baseRateCents: number };
  totalMinutes: number;
  totalPay: FractionOut;
  segments: SegmentOut[];
  minutes: MinuteOut[];
  baselineBasisPoints: number;
}

export interface ValidationIssue {
  loc: (string | number)[];
  msg: string;
}
