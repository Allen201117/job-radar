const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const { loadTs } = require("./_load-ts");
const P = loadTs(path.join(__dirname, "..", "lib", "apply-programs.ts"));

// 项目制投递入口承载的是「这家公司客观上没有一岗一页」这类事实
// （中通校招=蓝天计划项目制投递，国有大行=公告制）。
// 最重要的不变量：**它不是岗位**，且**没核实过的入口链接绝不展示**。

const ROW = {
  id: "11111111-1111-1111-1111-111111111111",
  company: "中通快递",
  program_name: "蓝天计划（校园招聘）",
  program_type: "campus_program",
  entry_url: "https://hr.zto.com/campus",
  description: "按项目收简历",
  window_text: "毕业时间 2026/10/01-2027/09/30",
  industry: "物流/供应链",
  verified_at: "2026-09-04T00:00:00Z",
  enabled: true,
};

test("正常行映射出完整展示模型", () => {
  const p = P.toApplyProgram(ROW);
  assert.equal(p.company, "中通快递");
  assert.equal(p.programType, "campus_program");
  assert.equal(p.entryUrl, "https://hr.zto.com/campus");
  assert.equal(p.windowText, "毕业时间 2026/10/01-2027/09/30");
});

test("未核实的行不展示 —— 代价是用户点开死链，比不展示更伤", () => {
  assert.equal(P.toApplyProgram({ ...ROW, verified_at: null }), null);
});

test("停用的行不展示", () => {
  assert.equal(P.toApplyProgram({ ...ROW, enabled: false }), null);
});

test("非 http(s) 入口一律拒绝（防 javascript: 之类混进来）", () => {
  for (const bad of ["javascript:alert(1)", "/campus", "ftp://x.com", ""]) {
    assert.equal(P.toApplyProgram({ ...ROW, entry_url: bad }), null, bad);
  }
});

test("未知 program_type 不放行 —— 拿不准是什么就别展示给用户", () => {
  assert.equal(P.toApplyProgram({ ...ROW, program_type: "job" }), null);
  assert.equal(P.toApplyProgram({ ...ROW, program_type: undefined }), null);
});

test("缺公司名/项目名/入口的行丢弃", () => {
  assert.equal(P.toApplyProgram({ ...ROW, company: "  " }), null);
  assert.equal(P.toApplyProgram({ ...ROW, program_name: "" }), null);
  assert.equal(P.toApplyProgram({ ...ROW, entry_url: "" }), null);
});

test("批量转换丢掉不合格行且保持顺序", () => {
  const out = P.toApplyPrograms([
    ROW,
    { ...ROW, entry_url: "https://a.com/x", verified_at: null },
    { ...ROW, entry_url: "https://b.com/x", company: "中国银行", program_type: "announcement" },
  ]);
  assert.deepEqual(out.map((p) => p.company), ["中通快递", "中国银行"]);
});

test("toApplyPrograms 对非数组输入返回空数组", () => {
  for (const bad of [null, undefined, {}, "x", 3]) {
    assert.deepEqual(P.toApplyPrograms(bad), []);
  }
});

test("每种类型都有说人话的徽章与「为什么没有岗位列表」的解释", () => {
  for (const t of ["campus_program", "announcement", "talent_pool"]) {
    assert.ok(P.PROGRAM_TYPE_LABEL[t], t);
    assert.ok(P.PROGRAM_TYPE_HINT[t].length > 10, t);
    assert.ok(P.PROGRAM_TYPE_TONE[t], t);
  }
});

test("徽章文案不得出现「岗位」字样 —— 它不是岗位，措辞不许可被误读", () => {
  for (const label of Object.values(P.PROGRAM_TYPE_LABEL)) {
    assert.ok(!label.includes("岗位"), label);
  }
});

test("分组按固定顺序、空组不出现", () => {
  const programs = P.toApplyPrograms([
    { ...ROW, entry_url: "https://b.com/x", company: "中国银行", program_type: "announcement" },
    ROW,
  ]);
  const groups = P.groupByType(programs);
  assert.deepEqual(groups.map((g) => g.type), ["campus_program", "announcement"]);
  assert.deepEqual(groups.map((g) => g.items.length), [1, 1]);
});

// ── 公告制入口必须指到「打开就看得见公告」的那一层 ────────────────────────
// 2026-09-07 创始人反馈：13 条公告制里 6 条点进去是企业官网/平台首页，不是公告页。
// 这里钉的是「这类错必须出声」，不是「自动丢行」——丢了用户连门户都进不去，更糟。

function announcement(entryUrl) {
  return P.toApplyProgram({ ...ROW, program_type: "announcement", entry_url: entryUrl });
}

test("公告制入口停在门户根 = 需要补更深的公告页", () => {
  assert.equal(P.needsDeeperAnnouncementLink(announcement("https://zhaopin.china-cdt.com")), true);
  assert.equal(P.needsDeeperAnnouncementLink(announcement("https://rencaishichang.chd.com.cn/")), true);
});

test("指到公告列表 / 公告全文 / hash 路由公告页都算合格", () => {
  const ok = [
    "https://zhaopin.chinacoal.com/notice",
    "https://zhaopin.china-cdt.com/zpgg_index.html",
    "https://zhaopin.sgcc.com.cn/sgcchr/static/recrAument.html",
    "https://www.bankofchina.com/aboutboc/bi4/202609/t20260903_25689311.html",
    // 华电是 hash 路由：路径在 # 后面，不能因为 pathname 是 /w3/ 就判它浅。
    "https://rencaishichang.chd.com.cn/w3/#/w3/notice/main_view?class_item_pk=10001",
  ];
  for (const url of ok) {
    assert.equal(P.needsDeeperAnnouncementLink(announcement(url)), false, url);
  }
});

test("门户根例外必须显式登记，且只对登记过的那一条生效", () => {
  // 华能：根视图本身就是招聘公告列表，更深路由反而无数据 —— 唯一的合法例外。
  assert.ok(P.PORTAL_ROOT_IS_ANNOUNCEMENT_LIST.has("https://zhaopin.chng.com.cn/"));
  assert.equal(P.needsDeeperAnnouncementLink(announcement("https://zhaopin.chng.com.cn/")), false);
  // 没登记的同类写法不因此被放过。
  assert.equal(P.needsDeeperAnnouncementLink(announcement("https://zhaopin.chng.com.cn")), true);
});

test("项目制 / 人才库不受这条约束（它们本来就投在一个入口上）", () => {
  const pool = P.toApplyProgram({ ...ROW, program_type: "talent_pool", entry_url: "https://www.bosideng.com" });
  assert.equal(P.needsDeeperAnnouncementLink(pool), false);
  assert.equal(P.needsDeeperAnnouncementLink(P.toApplyProgram(ROW)), false);
});
