// on-demand 富化 TS 反推器 golden 用例：与 Python crawler/enrich.py 同口径（jd_url→detail 端点）。
// 错了 = 给用户灌错 summary，最危险 → 必须钉死。mock global.fetch，不打真网络。
const assert = require("node:assert/strict");
const test = require("node:test");
const {
  cleanSummary,
  detailWorkday,
  detailHotjob,
  enrichClientClass,
} = require("../lib/enrich-client.js");

function mockFetch(handler) {
  const orig = global.fetch;
  global.fetch = handler;
  return () => {
    global.fetch = orig;
  };
}

test("cleanSummary: 去标签 + 短文本→null", () => {
  assert.equal(cleanSummary("<p>负责后端服务设计与开发维护</p>"), "负责后端服务设计与开发维护");
  assert.equal(cleanSummary("短"), null);
  assert.equal(cleanSummary(null), null);
  assert.equal(cleanSummary(""), null);
});

test("enrichClientClass: 只 workday/hotjob 是 httpx，其余 null", () => {
  assert.equal(enrichClientClass("workday"), "httpx");
  assert.equal(enrichClientClass("hotjob"), "httpx");
  assert.equal(enrichClientClass("moka"), null);
  assert.equal(enrichClientClass("beisen"), null);
});

test("detailWorkday: jd_url → cxs detail 端点", async () => {
  let captured;
  const restore = mockFetch(async (url) => {
    captured = url;
    return { ok: true, json: async () => ({ jobPostingInfo: { jobDescription: "<p>do things here ok</p>" } }) };
  });
  const body = await detailWorkday({
    jd_url: "https://co.wd1.myworkdayjobs.com/en-US/Careers/job/Beijing/Eng_R-1",
    source_url: "https://co.wd1.myworkdayjobs.com/wday/cxs/co/Careers/jobs",
  });
  restore();
  assert.equal(captured, "https://co.wd1.myworkdayjobs.com/wday/cxs/co/Careers/job/Beijing/Eng_R-1");
  assert.match(body, /do things here ok/);
});

test("detailHotjob: POST listPositionDetail，recruitType 由 postType 推回（campus→1）", async () => {
  const cap = {};
  const restore = mockFetch(async (url, init) => {
    cap.url = url;
    cap.body = init.body;
    return { ok: true, json: async () => ({ data: { workContent: "负责算法研发与优化", serviceCondition: "本科以上学历" } }) };
  });
  const body = await detailHotjob({
    jd_url: "https://wecruit.hotjob.cn/SU123/pb/posDetail.html?postId=P9&postType=campus",
  });
  restore();
  assert.match(cap.url, /\/wecruit\/positionInfo\/listPositionDetail\/SU123$/);
  assert.match(cap.body, /postId=P9/);
  assert.match(cap.body, /recruitType=1/); // campus → 1
  assert.match(body, /负责算法研发与优化/);
});

test("detailHotjob: 源站已关闭 state=1017 → null（不灌错）", async () => {
  const restore = mockFetch(async () => ({ ok: true, json: async () => ({ state: "1017", msg: "招聘已经关闭" }) }));
  const body = await detailHotjob({
    jd_url: "https://wecruit.hotjob.cn/SU1/pb/posDetail.html?postId=P1&postType=society",
  });
  restore();
  assert.equal(body, null);
});
