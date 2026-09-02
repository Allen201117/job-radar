// 独立裁判：用 LLM 判「推荐的岗位 vs 用户求职方向」的贴合度，**分两档报**。
// 刻意不复用 classifyJobFunction —— 那是被测对象，用它当裁判是循环论证。
//
// ⚠️ 为什么要分两档（2026-09-02 创始人打脸后加的）：
// 旧版只判「同一大方向」，判据里明写「不要求细分完全一致」。于是「产品运营」对「产品经理」
// 被判成同方向 → 计为正确 → 报出 97.3% 的漂亮数字。但创始人在生产上看到的就是
// 「产品运营岗被推给产品经理用户」，实测那一版里产品经理画像的 339 条展示里有 63 条（18.6%）
// 是产品运营。**数字没造假，是尺子太松**：它测的不是用户会不会去投。
// 所以现在判三档并分别报：
//   same_role   = 同一具体角色，这个人会真去投                → 严格准确率
//   same_family = 同大方向但不同角色（产品经理 vs 产品运营）→ 只计入宽松准确率
//   different   = 明显跑偏                                    → 两个都不计
//   unclear     = 标题信息不足以判断（如 "2026 Future Talent Program"）→ 单独报，不计入分母
const fs = require("fs"), path = require("path");
const ROOT = process.env.EVAL_ROOT || path.join(__dirname, "..", "..");
const { chatJSON } = require(path.join(ROOT, "lib/llm.js"));
const BATCH = 20;

async function judgeBatch(direction, items) {
  const list = items.map((t, i) => `${i + 1}. ${t.title}${t.company ? " @ " + t.company : ""}`).join("\n");
  const messages = [
    { role: "system", content: "你是招聘领域的岗位方向审核员。只输出 JSON，不要解释。" },
    { role: "user", content:
`求职者的求职方向是：「${direction}」。

把下面每个岗位判成四档之一（**站在这个求职者的角度：他会不会真的投这个岗**）：

- "same_role"：同一具体角色，他会投。
  例：求职方向「AI 产品经理」→「产品经理」「数据产品经理」「策略产品经理」都算。
  例：求职方向「算法工程师」→「机器学习工程师」「NLP 工程师」「推荐算法工程师」都算。
- "same_family"：同一个大方向但**不是同一个角色**，多半不会投。
  例：求职方向「产品经理」→「产品运营」「项目经理」只算 same_family，**不算 same_role**。
  例：求职方向「算法工程师」→「测试开发」「运维工程师」只算 same_family。
  例：求职方向「银行柜员」→「信贷审批」「保险理赔」只算 same_family。
- "different"：明显跑偏，方向不同。
  例：求职方向「产品经理」→「后端开发」「销售代表」「装配工」。
- "unclear"：标题里根本没有岗位信息，判不出来。
  例：「2026 Future Talent Program」「Lead」「Supervisor」「某某事业部」。

⚠️ 关键：**别因为两个岗位都带「产品」两个字就判 same_role**。判据是「这个求职者会不会投」。

岗位列表：
${list}

输出 JSON：{"results":[{"i":1,"verdict":"same_role","job_direction":"该岗位真实的岗位方向，如 后端研发/产品运营/项目管理"}]}
verdict 必须是 same_role / same_family / different / unclear 之一。
必须为每个岗位都给一条，i 与序号一一对应。` },
  ];
  const raw = await chatJSON(messages, { tag: "match-judge", maxTokens: 3000 });
  const map = new Map();
  for (const r of raw?.results || []) if (r && Number.isFinite(Number(r.i))) map.set(Number(r.i), r);
  const VERDICTS = new Set(["same_role", "same_family", "different", "unclear"]);
  return items.map((t, i) => {
    const r = map.get(i + 1);
    const v = r && VERDICTS.has(r.verdict) ? r.verdict : null;
    return { ...t, verdict: v, job_direction: r?.job_direction || null };
  });
}

async function judgeAll(direction, items) {
  const out = [];
  for (let i = 0; i < items.length; i += BATCH) {
    let tries = 0, res = null;
    while (tries++ < 2 && !res) {
      try { res = await judgeBatch(direction, items.slice(i, i + BATCH)); }
      catch (e) { console.error("  judge err:", e.message); }
    }
    out.push(...(res || items.slice(i, i + BATCH).map((t) => ({ ...t, verdict: null, job_direction: null }))));
  }
  return out;
}
module.exports = { judgeAll };

if (require.main === module) {
  (async () => {
    const inFile = process.argv[2] || path.join(__dirname, "eval-raw.json");
    const TOPN = Number(process.env.TOPN || 25);
    const results = JSON.parse(fs.readFileSync(inFile, "utf8"));
    const report = [];
    for (const r of results) {
      if (r.error) continue;
      const direction = (r.profile.targetRoles || []).join(" / ") || "(未填)";
      const items = r.shown.slice(0, TOPN).map((s) => ({ title: s.title, company: s.company, score: s.score, tier: s.tier, jobFn: s.jobFn, roleMatchLabel: s.roleMatchLabel }));
      if (!items.length) { report.push({ label: r.label, direction, n: 0, acc: null, judged: [] }); continue; }
      const judged = await judgeAll(direction, items);
      // unclear 不计入分母：标题没写岗位信息，判它对错都是瞎猜，单独报数量即可。
      const unclear = judged.filter((j) => j.verdict === "unclear").length;
      const valid = judged.filter((j) => j.verdict && j.verdict !== "unclear");
      const strictOk = valid.filter((j) => j.verdict === "same_role").length;
      const looseOk = valid.filter((j) => j.verdict === "same_role" || j.verdict === "same_family").length;
      const strict = valid.length ? strictOk / valid.length : null;
      const loose = valid.length ? looseOk / valid.length : null;
      const pct = (x) => (x == null ? "  -  " : (x * 100).toFixed(1) + "%");
      console.error(`${r.label}  方向=${direction}  展示=${r.shownCount}  计分=${valid.length}(unclear ${unclear})  严格=${pct(strict)}  宽松=${pct(loose)}`);
      report.push({ label: r.label, direction, shownCount: r.shownCount, recalled: r.recalled, filtered: r.filtered, n: valid.length, unclear, strictOk, looseOk, strict, loose, judged });
    }
    fs.writeFileSync(path.join(__dirname, path.basename(inFile).replace(/\.json$/, "") + "-judged.json"), JSON.stringify(report, null, 2));
    console.log("\n==== 汇总 ====");
    console.log("严格 = 同一具体角色（会真去投）；宽松 = 同大方向即可（旧口径）");
    const pct = (x) => (x == null ? "  -  " : (x * 100).toFixed(1) + "%");
    for (const r of report)
      console.log(
        `${r.label.padEnd(28)} 展示=${String(r.shownCount ?? 0).padStart(4)}  严格=${pct(r.strict)}  宽松=${pct(r.loose)}`,
      );
  })();
}
