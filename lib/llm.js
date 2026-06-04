// SiliconFlow（硅基流动）Chat Completions 客户端。
// 全项目唯一的 LLM 出口；env 缺失或网络失败时抛带 code 的错误，由调用方决定降级。
//
// 需要的环境变量（写在 .env.local / EdgeOne，绝不入库）：
//   SILICONFLOW_API_KEY   必填
//   SILICONFLOW_BASE_URL  可选，默认 https://api.siliconflow.cn/v1
//   SILICONFLOW_MODEL     可选，默认 deepseek-ai/DeepSeek-V3
//                         （想用 DeepSeek V4 时把它设成控制台里的确切模型 id）

const DEFAULT_BASE_URL = "https://api.siliconflow.cn/v1";
const DEFAULT_MODEL = "deepseek-ai/DeepSeek-V3";

function llmConfig() {
  const apiKey = process.env.SILICONFLOW_API_KEY || "";
  return {
    apiKey,
    baseUrl: (process.env.SILICONFLOW_BASE_URL || DEFAULT_BASE_URL).replace(/\/+$/, ""),
    model: process.env.SILICONFLOW_MODEL || DEFAULT_MODEL,
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

async function chatJSON(messages, { temperature = 0.1, maxTokens = 2048, signal } = {}) {
  const cfg = llmConfig();
  if (!cfg.configured) throw llmError("llm_not_configured");

  let resp;
  try {
    resp = await fetch(`${cfg.baseUrl}/chat/completions`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${cfg.apiKey}`,
      },
      body: JSON.stringify({
        model: cfg.model,
        messages,
        temperature,
        max_tokens: maxTokens,
        response_format: { type: "json_object" },
      }),
      signal,
    });
  } catch (err) {
    throw llmError("llm_network_error", { detail: String(err && err.message) });
  }

  if (!resp.ok) {
    const detail = await resp.text().catch(() => "");
    throw llmError("llm_http_error", { status: resp.status, detail: detail.slice(0, 300) });
  }

  const data = await resp.json().catch(() => null);
  const content = data && data.choices && data.choices[0] && data.choices[0].message
    ? data.choices[0].message.content
    : "";
  return parseJsonLoose(content);
}

module.exports = {
  DEFAULT_BASE_URL,
  DEFAULT_MODEL,
  llmConfig,
  parseJsonLoose,
  chatJSON,
};
