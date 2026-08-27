// SiliconFlow（硅基流动）Chat Completions 客户端。
// 全项目唯一的 LLM 出口；env 缺失或网络失败时抛带 code 的错误，由调用方决定降级。
//
// 需要的环境变量（写在 .env.local / EdgeOne，绝不入库）：
//   SILICONFLOW_API_KEY   必填
//   SILICONFLOW_BASE_URL  可选，默认 https://api.siliconflow.cn/v1
//   SILICONFLOW_MODEL     可选，默认 Qwen/Qwen3-30B-A3B-Instruct-2507
//                         注意：必须是 https://cloud.siliconflow.cn/models 里「存在且你账号可用」
//                         的确切 id（不存在会报 20012 模型不存在）。
//   SILICONFLOW_FALLBACK_MODEL 可选，主模型被限流时降级用（默认 THUDM/GLM-4-32B-0414）
//   ⚠️ 这两个 env 一旦在 Vercel / GitHub 里被显式设成旧值，下面的默认值就不生效——换模型后要顺手清掉。

const DEFAULT_BASE_URL = "https://api.siliconflow.cn/v1";
// 主模型（2026-08-27 换）：简历解析就是「结构化 JSON 抽取」，不需要顶级推理，且解析失败还有规则兜底。
// ¥0.7/M 输入、¥2.8/M 输出（旧 Pro/deepseek-ai/DeepSeek-V3.1 是 ¥4/¥12，省 ~80%）。
// ⚠️ 不带 `Pro/` 前缀：`Pro/` 不是更好的档，只是**只能扣充值余额**；非 Pro 同名模型还能吃赠费余额。
// live 实测（2026-08-27，同一 JSON 抽取 prompt）：in=43 / out=14，JSON 正确、无思考前缀。
const DEFAULT_MODEL = "Qwen/Qwen3-30B-A3B-Instruct-2507";
// 备用模型：主模型被 SiliconFlow 服务端限流（429 code 50609「System is too busy now」）时降级。
// 刻意选**不同厂商**（智谱 GLM vs 阿里 Qwen）——2026-07-31 起 DeepSeek-V3 整个系列被挤爆、
// 持续 3 天 100% 429，期间简历解析静默退回规则兜底。同厂系兜底救不了这种故障。
// ⚠️ 降级模型**必须非思考模式**：思考模型先吐一大段推理再给 JSON，会把 max_tokens 撑爆导致截断。
// live 实测（2026-08-27）：GLM-4-32B-0414 out=15、无 reasoning_content → 非思考；
// 反例 tencent/Hunyuan-A13B-Instruct out=159、Qwen/Qwen3-8B out=269 → 一律不用。
const DEFAULT_FALLBACK_MODEL = "THUDM/GLM-4-32B-0414";

function llmConfig() {
  const apiKey = process.env.SILICONFLOW_API_KEY || "";
  return {
    apiKey,
    baseUrl: (process.env.SILICONFLOW_BASE_URL || DEFAULT_BASE_URL).replace(/\/+$/, ""),
    model: process.env.SILICONFLOW_MODEL || DEFAULT_MODEL,
    fallbackModel: process.env.SILICONFLOW_FALLBACK_MODEL || DEFAULT_FALLBACK_MODEL,
    configured: Boolean(apiKey),
  };
}

function llmError(code, extra) {
  const err = new Error(code);
  err.code = code;
  if (extra) Object.assign(err, extra);
  return err;
}

// 从模型返回里尽量稳地取出 JSON 对象（先直接 parse，失败再抠第一个 {...} 块）。
function parseJsonLoose(content) {
  const text = String(content || "").trim();
  try {
    return JSON.parse(text);
  } catch {
    const match = text.match(/\{[\s\S]*\}/);
    if (match) {
      try {
        return JSON.parse(match[0]);
      } catch {
        /* fallthrough */
      }
    }
  }
  throw llmError("llm_bad_json", { detail: text.slice(0, 300) });
}

// 用量台账（2026-08-27 加）：以前**没有任何地方读 API 返回的 usage**，花费只能按字符数瞎估，
// 账户欠费都要事后才发现。这里把真实 token 数打成固定格式的一行，日志里 grep `[llm-usage]` 即可聚合。
function formatUsageLog(model, usage, tag) {
  const u = usage && typeof usage === "object" ? usage : {};
  const int = (v) => (Number.isFinite(Number(v)) ? Number(v) : 0);
  return `[llm-usage] model=${model} tag=${tag || "-"} `
    + `in=${int(u.prompt_tokens)} out=${int(u.completion_tokens)}`;
}

function logUsage(model, usage, tag) {
  try {
    console.log(formatUsageLog(model, usage, tag));
  } catch {
    /* 记账绝不能阻断主流程 */
  }
}

async function chatJSON(messages, { temperature = 0.1, maxTokens = 2048, signal, tag = "" } = {}) {
  const cfg = llmConfig();
  if (!cfg.configured) throw llmError("llm_not_configured");

  // 单次请求；useJsonFormat=false 时去掉 response_format（部分模型不支持会返回 400）。
  async function call(useJsonFormat, model) {
    const body = {
      model,
      messages,
      temperature,
      max_tokens: maxTokens,
    };
    if (useJsonFormat) body.response_format = { type: "json_object" };
    try {
      return await fetch(`${cfg.baseUrl}/chat/completions`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${cfg.apiKey}`,
        },
        body: JSON.stringify(body),
        signal,
      });
    } catch (err) {
      throw llmError("llm_network_error", { detail: String(err && err.message) });
    }
  }

  // 兜底：模型不支持 json_object 时 SiliconFlow 返回 400 → 去掉该字段重试一次
  // （prompt 已强约束只输出 JSON，parseJsonLoose 也能容忍多余字符）。
  async function tryModel(model) {
    const r = await call(true, model);
    return r.status === 400 ? call(false, model) : r;
  }

  let usedModel = cfg.model;
  let resp = await tryModel(cfg.model);
  // 主模型被服务端限流(429)/过载(503) → 换备用模型再试一次。这是**用户面**路径（简历解析），
  // 不能像 cron 那样退避几秒了事：整个模型被挤爆会持续数天，只有换模型救得回来。
  if ((resp.status === 429 || resp.status === 503)
      && cfg.fallbackModel && cfg.fallbackModel !== cfg.model) {
    usedModel = cfg.fallbackModel;
    resp = await tryModel(cfg.fallbackModel);
  }

  if (!resp.ok) {
    const detail = await resp.text().catch(() => "");
    throw llmError("llm_http_error", { status: resp.status, detail: detail.slice(0, 300) });
  }

  const data = await resp.json().catch(() => null);
  logUsage(usedModel, data && data.usage, tag);
  const content = data && data.choices && data.choices[0] && data.choices[0].message
    ? data.choices[0].message.content
    : "";
  return parseJsonLoose(content);
}

module.exports = {
  DEFAULT_BASE_URL,
  DEFAULT_MODEL,
  DEFAULT_FALLBACK_MODEL,
  llmConfig,
  parseJsonLoose,
  formatUsageLog,
  chatJSON,
};
