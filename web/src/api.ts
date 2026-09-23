import type {
  FractionOut,
  SliceRequest,
  SliceResponse,
  ValidationIssue,
} from "./types";

export class ApiError extends Error {
  status: number;
  issues: ValidationIssue[];

  constructor(status: number, message: string, issues: ValidationIssue[] = []) {
    super(message);
    this.status = status;
    this.issues = issues;
  }
}

export async function postSlice(req: SliceRequest): Promise<SliceResponse> {
  let res: Response;
  try {
    res = await fetch("/api/slice", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    });
  } catch (networkErr) {
    throw new ApiError(0, `网络错误：无法连接到复核服务（${networkErr}）`);
  }

  if (res.status === 422) {
    const body = await res.json().catch(() => null);
    const detail = body?.detail;
    if (Array.isArray(detail)) {
      const issues: ValidationIssue[] = detail.map((d: any) => ({
        loc: Array.isArray(d.loc) ? d.loc : [],
        msg: String(d.msg ?? "输入无效"),
      }));
      throw new ApiError(422, "输入校验未通过（422）", issues);
    }
    throw new ApiError(422, "输入校验未通过（422）");
  }
  if (!res.ok) {
    throw new ApiError(res.status, `复核服务返回 ${res.status}`);
  }
  return (await res.json()) as SliceResponse;
}

/** Exact decimal rendering: numerator/denominator via BigInt long division. */
export function fractionToDecimal(f: FractionOut, maxDigits = 8): string {
  const neg = f.numerator < 0;
  let n = BigInt(Math.abs(f.numerator));
  const d = BigInt(f.denominator);
  const intPart = n / d;
  n = (n - intPart * d) * 10n;
  const digits: string[] = [];
  let repeatStart = -1;
  const seen = new Map<bigint, number>();
  while (n > 0n && digits.length < maxDigits) {
    if (seen.has(n)) {
      repeatStart = seen.get(n)!;
      break;
    }
    seen.set(n, digits.length);
    digits.push(String(n / d));
    n = (n - (n / d) * d) * 10n;
  }
  const sign = neg ? "-" : "";
  if (digits.length === 0) return `${sign}${intPart}`;
  if (repeatStart >= 0) {
    const head = digits.slice(0, repeatStart).join("");
    const tail = digits.slice(repeatStart).join("");
    return `${sign}${intPart}.${head}(${tail})…`;
  }
  const approx = n > 0n ? "…" : "";
  return `${sign}${intPart}.${digits.join("")}${approx}`;
}

export function formatFraction(f: FractionOut): string {
  return `${f.numerator}/${f.denominator}`;
}

export function formatTime(v: string): string {
  // 'YYYY-MM-DDTHH:MM' -> 'MM-DD HH:MM'
  const [d, t] = v.split("T");
  return `${d.slice(5)} ${t}`;
}
