import { NextRequest, NextResponse } from "next/server";
import { createServerSupabase } from "@/lib/auth";
import { INSIGHT_DIMENSIONS } from "@/lib/insight-bundle";
import llm from "@/lib/llm";

export const runtime = "nodejs";

// AI 辅助职业洞察起草（与简历 AI 解析共用 SiliconFlow 出口 lib/llm）。
// 账单控制：① 仅 admin 可调；② 每次仅 1 次 LLM 调用、max_tokens 收紧；③ 不进每日 cron、不按用户/不按浏览触发。
// 安全：产出**只是草稿**，强制回填到表单（status≠active），必须管理员核对 + 补真实来源后才能过校验门展示。
const { chatJSON, llmConfig } = llm as any;

// 各维度给模型的写作指引（与 lib/insight-verification 的归因 / 去标识 / 分级口径对齐）
const DIM_GUIDE: Record<string, string> = {
  timing: "招聘时机：校招/社招节奏、提前批与正式批的大致月份窗口。grade 用 fact。",
  listing:
    "上市状态：是否已上市、交易所与股票代码、上市年份；或未上市/已递表/筹备上市。" +
    "严禁编造任何实时股价、涨跌幅、市值数字；quote_url 留空由人工填。grade 用 fact。",
  compensation_intensity:
    "薪资/强度：公开讨论里的薪资带与工作强度的群体性印象。grade 用 experience，需注明这是群体反馈非定性。",
  path: "进入路径：常见进入通道（校招/社招/内推/外包转正等）的公开观察。grade 视证据用 fact 或 experience。",
  culture: "公司文化：公开讨论里的文化/节奏群体性印象，措辞中性、温馨提示口吻。grade 用 experience。",
};

async function requireAdmin() {
  const supabase = await createServerSupabase();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) return { error: NextResponse.json({ ok: false, error: "Unauthorized" }, { status: 401 }) };
  const { data: profileRow } = await supabase
    .from("profiles")
    .select("role")
    .eq("id", user.id)
    .maybeSingle();
  if (profileRow?.role !== "admin") {
    return { error: NextResponse.json({ ok: false, error: "forbidden" }, { status: 403 }) };
  }
  return { user };
}

export async function POST(request: NextRequest) {
  const guard = await requireAdmin();
  if (guard.error) return guard.error;

  let body: any;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ ok: false, error: "invalid_json" }, { status: 400 });
  }

  const company = String(body.company || "").trim();
  const dimension = String(body.dimension || "").trim();
  if (!company || !INSIGHT_DIMENSIONS.includes(dimension as any)) {
    return NextResponse.json({ ok: false, error: "missing_required_fields" }, { status: 400 });
  }
  if (!llmConfig().configured) {
    return NextResponse.json({ ok: false, error: "llm_not_configured" }, { status: 503 });
  }

  const guide = DIM_GUIDE[dimension] || "";
  const messages = [
    {
      role: "system",
      content:
        "你是求职信息策展助手，为「职业洞察」的人工录入起草**草稿**。硬性要求：" +
        "1) 只用公开、可聚合的信息，全部用归因式表述（如「据公开披露」「据公开讨论」），" +
        "禁止以产品口吻下断言（不得出现「我们认为/认定」「毫无疑问」等）；" +
        "2) 严禁编造具体数字（股价、市值、薪资精确值、涨跌幅）；不确定就说不确定；" +
        "3) 不得指向任何具体自然人，保持去标识；" +
        "4) 只输出 JSON，不要解释。",
    },
    {
      role: "user",
      content:
        `公司：${company}\n维度：${dimension}\n维度指引：${guide}\n\n` +
        "请输出如下 JSON：\n" +
        "{\n" +
        '  "title": "不超过 20 字的小标题",\n' +
        '  "content": "1-3 句归因式正文，仅供参考口吻",\n' +
        '  "grade": "fact | experience",\n' +
        '  "time_window": "时效窗口文本，如「2025–2026 观察」或「上市状态截至 2026 年」",\n' +
        '  "sample_size": "若 grade=experience 给一个>=5的整数，否则留空字符串",\n' +
        '  "listing": {"status":"listed|filed|pre_ipo|private","exchange":"","ticker":""},\n' +
        '  "sources": [{"url":"公开来源链接(尽量官方/权威，不确定就留空数组)","publisher":"来源名"}]\n' +
        "}\n" +
        "listing 字段仅在维度为 listing 时填，其余维度给空对象。不要编造 url。",
    },
  ];

  try {
    const draft = await chatJSON(messages, { temperature: 0.2, maxTokens: 700 });
    return NextResponse.json({ ok: true, draft });
  } catch (e: any) {
    console.error("[insights-ai-draft] LLM 起草失败", e?.code || e?.message);
    return NextResponse.json(
      { ok: false, error: e?.code || "llm_error", detail: String(e?.detail || e?.message || "").slice(0, 200) },
      { status: 502 },
    );
  }
}
