const { test } = require("node:test");
const assert = require("node:assert");
const path = require("node:path");
const { loadTs } = require("./_load-ts");

const {
  buildIndustryIndex,
  industryOfCompany,
  normalizeTitle,
  pickPopularJobs,
  POPULAR_INDUSTRIES,
} = loadTs(path.join(__dirname, "..", "lib", "popular-picks.ts"));

// 「热门在招」是**没设过求职目标**的新用户在 /today 看到的东西（app/today/page.tsx）。
// 它没有画像可依，所以唯一能给的价值就是「知名公司 + 摊得开 + 点得开」。
// 下面钉死的三条不变量，任何一条破了，新用户第一屏就会退化成一家公司刷屏或重复岗刷屏。

function job(id, company, title, extra) {
  return Object.assign({ id, company, title, posted_at: null, last_seen_at: "2026-09-06T00:00:00Z" }, extra);
}

test("行业归属：更长的 pattern 胜出，一家公司只落一个行业", () => {
  const index = buildIndustryIndex();
  // 「腾讯音乐 TME」同时含 %腾讯% 与 %腾讯音乐%，必须归后者（否则它会在两个行业里各出一次）
  assert.strictEqual(industryOfCompany("腾讯音乐 TME", index), "传媒/文娱");
  assert.strictEqual(industryOfCompany("腾讯", index), "互联网/科技");
  // 不在必投清单里的公司整条丢弃，不进「其它」桶
  assert.strictEqual(industryOfCompany("某某不知名科技有限公司", index), null);
  assert.strictEqual(industryOfCompany("", index), null);
});

test("行业归属对全部候选都是单值：同一个公司名不会被算进两个行业", () => {
  const index = buildIndustryIndex();
  const names = ["腾讯", "腾讯音乐 TME", "京东", "京东方 BOE", "字节跳动", "美团", "建设银行"];
  for (const name of names) {
    const hits = POPULAR_INDUSTRIES.filter((ind) => {
      const only = index.filter((e) => e.industry === ind);
      return industryOfCompany(name, only) !== null;
    });
    // 允许 0（不在清单）或 ≥1（清单里多个行业都收了它），但 industryOfCompany 必须给出确定的那一个
    const resolved = industryOfCompany(name, index);
    if (hits.length > 0) assert.ok(hits.includes(resolved), `${name} 归属 ${resolved} 不在候选行业 ${hits}`);
  }
});

test("归一标题：门店/产线岗只差城市或编号时算同一个岗", () => {
  assert.strictEqual(normalizeTitle("店员-深圳金光华店"), normalizeTitle("店员 深圳金光华店"));
  assert.strictEqual(normalizeTitle("来料检验员(J16832)"), normalizeTitle("来料检验员(J99001)"));
  assert.strictEqual(normalizeTitle("星级咖啡师（杭州）"), normalizeTitle("星级咖啡师（上海）"));
  // 不同角色不能被压成同一个
  assert.notStrictEqual(normalizeTitle("后端工程师"), normalizeTitle("前端工程师"));
});

test("同一家公司的重复岗只出一条", () => {
  const picks = pickPopularJobs(
    [
      job("a", "美团", "配送站长（北京）"),
      job("b", "美团", "配送站长（上海）"),
      job("c", "美团", "配送站长（广州）"),
      job("d", "美团", "后端开发工程师"),
    ],
    { perCompany: 4, perIndustry: 20 },
  );
  assert.strictEqual(picks.length, 2, "三条同名门店岗应压成一条，加上后端岗共 2 条");
  assert.deepStrictEqual(picks.map((p) => p.id).sort(), ["a", "d"]);
});

test("perCompany 是硬上限：一家公司再大也压不住别人", () => {
  const many = [];
  for (let i = 0; i < 30; i++) many.push(job(`t${i}`, "腾讯", `岗位${String.fromCharCode(65 + i)}`));
  many.push(job("m1", "美团", "后端开发工程师"));
  many.push(job("b1", "字节跳动", "算法工程师"));
  const picks = pickPopularJobs(many, { perCompany: 2, perIndustry: 20 });
  assert.strictEqual(picks.filter((p) => p.company === "腾讯").length, 2);
  // 轮转的意义：前 N 条里每家公司**至多出现一次**（N = 有货的公司数），
  // 所以腾讯的第二条一定排在美团/字节各自的第一条之后。
  const companyCount = 3;
  const firstRound = picks.slice(0, companyCount).map((p) => p.company);
  assert.strictEqual(new Set(firstRound).size, companyCount, `第一轮应每家各一条，实际 ${firstRound}`);
  const secondTencentIdx = picks.map((p) => p.company).lastIndexOf("腾讯");
  assert.ok(secondTencentIdx >= companyCount, "腾讯的第二条必须排在第一轮之后");
});

test("perIndustry 是硬上限", () => {
  const many = [];
  for (let i = 0; i < 40; i++) many.push(job(`x${i}`, i % 2 ? "腾讯" : "美团", `岗位${i}`));
  const picks = pickPopularJobs(many, { perCompany: 10, perIndustry: 5 });
  assert.strictEqual(picks.filter((p) => p.industry === "互联网/科技").length, 5);
});

test("跨行业交错：第一屏不会是同一个行业刷屏", () => {
  const rows = [];
  for (let i = 0; i < 6; i++) rows.push(job(`i${i}`, "腾讯", `互联网岗${i}`));
  for (let i = 0; i < 6; i++) rows.push(job(`f${i}`, "建设银行", `金融岗${i}`));
  for (let i = 0; i < 6; i++) rows.push(job(`c${i}`, "比亚迪", `汽车岗${i}`));
  const picks = pickPopularJobs(rows, { perCompany: 6, perIndustry: 6 });
  const firstThree = new Set(picks.slice(0, 3).map((p) => p.industry));
  assert.strictEqual(firstThree.size, 3, `前 3 条应来自 3 个不同行业，实际 ${[...firstThree]}`);
});

test("同一批输入两次调用结果完全一致（无随机、可缓存）", () => {
  const rows = [
    job("a", "腾讯", "后端工程师", { posted_at: "2026-09-01T00:00:00Z" }),
    job("b", "美团", "数据分析师", { posted_at: "2026-09-01T00:00:00Z" }),
    job("c", "京东", "产品经理", { posted_at: "2026-09-01T00:00:00Z" }),
  ];
  assert.deepStrictEqual(pickPopularJobs(rows), pickPopularJobs(rows));
});

test("脏数据不炸：缺 id / 缺公司 / 缺标题的行直接跳过", () => {
  const picks = pickPopularJobs([
    { id: "", company: "腾讯", title: "x" },
    { id: "a", company: "", title: "x" },
    { id: "b", company: "腾讯", title: "" },
    null,
    undefined,
    job("ok", "腾讯", "后端工程师"),
  ]);
  assert.deepStrictEqual(picks.map((p) => p.id), ["ok"]);
});

test("新鲜的岗和新鲜的公司排在前面", () => {
  const picks = pickPopularJobs(
    [
      job("old", "腾讯", "旧岗", { posted_at: "2026-01-01T00:00:00Z" }),
      job("new", "腾讯", "新岗", { posted_at: "2026-09-05T00:00:00Z" }),
    ],
    { perCompany: 2, perIndustry: 5 },
  );
  assert.deepStrictEqual(picks.map((p) => p.id), ["new", "old"]);
});
