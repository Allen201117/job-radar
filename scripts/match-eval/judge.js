// 独立裁判：用 LLM 判「推荐的岗位 vs 用户求职方向」是否同一大方向。
// 刻意不复用 classifyJobFunction —— 那是被测对象，用它当裁判是循环论证。
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

判断下面每个岗位是否属于**同一个大职业方向**（大方向相同即可，不要求细分完全一致；
例：求职方向「AI 产品经理」→「产品经理」「数据产品经理」算同方向；「后端开发工程师」「算法工程师」「运营专员」不算同方向。
例：求职方向「算法工程师」→「机器学习工程师」「NLP工程师」算同方向；「产品经理」「前端工程师」「销售」不算同方向）。

岗位列表：
${list}

输出 JSON：{"results":[{"i":1,"same":true,"job_direction":"该岗位真实的岗位方向，如 后端研发/产品经理/运营"}]}
必须为每个岗位都给一条，i 与序号一一对应。` },
  ];
  const raw = await chatJSON(messages, { tag: "match-judge", maxTokens: 3000 });
  const map = new Map();
  for (const r of raw?.results || []) if (r && Number.isFinite(Number(r.i))) map.set(Number(r.i), r);
  return items.map((t, i) => {
    const r = map.get(i + 1);
    return { ...t, same: r ? Boolean(r.same) : null, job_direction: r?.job_direction || null };
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
    out.push(...(res || items.slice(i, i + BATCH).map((t) => ({ ...t, same: null, job_direction: null }))));
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
      const valid = judged.filter((j) => j.same !== null);
      const ok = valid.filter((j) => j.same).length;
      const acc = valid.length ? ok / valid.length : null;
      console.error(`${r.label}  方向=${direction}  展示=${r.shownCount}  抽样=${valid.length}  准确=${ok}  → ${acc == null ? "-" : (acc*100).toFixed(1) + "%"}`);
      report.push({ label: r.label, direction, shownCount: r.shownCount, recalled: r.recalled, filtered: r.filtered, n: valid.length, ok, acc, judged });
    }
    fs.writeFileSync(path.join(__dirname, path.basename(inFile).replace(/\.json$/, "") + "-judged.json"), JSON.stringify(report, null, 2));
    console.log("\n==== 汇总 ====");
    for (const r of report) console.log(`${r.label.padEnd(28)} 展示=${String(r.shownCount ?? 0).padStart(4)}  方向准确率=${r.acc == null ? "  -  " : (r.acc*100).toFixed(1) + "%"}`);
  })();
}
