// 点击时校验门的撤岗判定 golden 用例：与 Python crawler/enrich.py 的撤岗信号同口径
// （wt req_state=9501 / hotjob state=1017 / detail 404·410）。
// 安全不变量：**只在明确撤岗信号才判 dead**；拿不准一律 unknown（放行），绝不误判活岗为死。
// mock global.fetch，不打真网络（同 tests/enrich-client.test.js 模式）。
const assert = require("node:assert/strict");
const test = require("node:test");
const { checkLiveness, livenessSupported } = require("../lib/liveness-client.js");

function mockFetch(handler) {
  const orig = global.fetch;
  global.fetch = handler;
  return () => {
    global.fetch = orig;
  };
}

test("livenessSupported: 只 wt/hotjob/workday，其余源放行(unknown)", () => {
  assert.equal(livenessSupported("wt"), true);
  assert.equal(livenessSupported("hotjob"), true);
  assert.equal(livenessSupported("workday"), true);
  assert.equal(livenessSupported("moka"), false);
  assert.equal(livenessSupported("beisen"), false);
});

test("不支持的源 → unknown（不探测、直接放行）", async () => {
  const restore = mockFetch(async () => {
    throw new Error("不该被调用");
  });
  assert.equal(await checkLiveness("moka", { jd_url: "https://x/y" }), "unknown");
  restore();
});

test("wt: req_state=9501 → dead", async () => {
  const restore = mockFetch(async (url) => {
    assert.match(url, /\/wt\/feihe\/web\/json\/position\/detail/);
    assert.match(url, /postId=P9/);
    return { ok: true, status: 200, json: async () => ({ req_state: 9501, req_msg: "该职位招聘已经关闭" }) };
  });
  const v = await checkLiveness("wt", {
    jd_url: "https://job.feihe.com/wt/feihe/mobweb/position/detail?recruitType=2&postIdsAry=P9",
  });
  restore();
  assert.equal(v, "dead");
});

test("wt: req_state=9200 + postInfo → alive", async () => {
  const restore = mockFetch(async () => ({
    ok: true,
    status: 200,
    json: async () => ({ req_state: 9200, postInfo: { workContent: "负责研发" } }),
  }));
  const v = await checkLiveness("wt", {
    jd_url: "https://job.feihe.com/wt/feihe/mobweb/position/detail?recruitType=2&postIdsAry=P1",
  });
  restore();
  assert.equal(v, "alive");
});

test("wt: 未知 req_state 且无 postInfo → unknown（安全：绝不误判为 dead）", async () => {
  const restore = mockFetch(async () => ({ ok: true, status: 200, json: async () => ({ req_state: 8888 }) }));
  const v = await checkLiveness("wt", {
    jd_url: "https://job.feihe.com/wt/feihe/mobweb/position/detail?postIdsAry=P2",
  });
  restore();
  assert.equal(v, "unknown");
});

test("wt: detail 端点 404 → dead", async () => {
  const restore = mockFetch(async () => ({ ok: false, status: 404, json: async () => ({}) }));
  const v = await checkLiveness("wt", {
    jd_url: "https://job.feihe.com/wt/feihe/mobweb/position/detail?postIdsAry=P3",
  });
  restore();
  assert.equal(v, "dead");
});

test("hotjob: state=1017 → dead", async () => {
  const restore = mockFetch(async (url, init) => {
    assert.match(url, /\/wecruit\/positionInfo\/listPositionDetail\/SU1$/);
    assert.match(init.body, /postId=P1/);
    return { ok: true, status: 200, json: async () => ({ state: "1017", msg: "招聘已经关闭" }) };
  });
  const v = await checkLiveness("hotjob", {
    jd_url: "https://wecruit.hotjob.cn/SU1/pb/posDetail.html?postId=P1&postType=society",
  });
  restore();
  assert.equal(v, "dead");
});

test("hotjob: 有 data → alive", async () => {
  const restore = mockFetch(async () => ({
    ok: true,
    status: 200,
    json: async () => ({ data: { workContent: "算法研发" } }),
  }));
  const v = await checkLiveness("hotjob", {
    jd_url: "https://wecruit.hotjob.cn/SU1/pb/posDetail.html?postId=P1&postType=campus",
  });
  restore();
  assert.equal(v, "alive");
});

test("workday: detail 404 → dead", async () => {
  const restore = mockFetch(async () => ({ ok: false, status: 404, json: async () => ({}) }));
  const v = await checkLiveness("workday", {
    jd_url: "https://co.wd1.myworkdayjobs.com/en-US/Careers/job/Beijing/Eng_R-1",
    source_url: "https://co.wd1.myworkdayjobs.com/wday/cxs/co/Careers/jobs",
  });
  restore();
  assert.equal(v, "dead");
});

test("workday: 200 + jobPostingInfo → alive", async () => {
  const restore = mockFetch(async (url) => {
    assert.equal(url, "https://co.wd1.myworkdayjobs.com/wday/cxs/co/Careers/job/Beijing/Eng_R-1");
    return { ok: true, status: 200, json: async () => ({ jobPostingInfo: { jobDescription: "do" } }) };
  });
  const v = await checkLiveness("workday", {
    jd_url: "https://co.wd1.myworkdayjobs.com/en-US/Careers/job/Beijing/Eng_R-1",
    source_url: "https://co.wd1.myworkdayjobs.com/wday/cxs/co/Careers/jobs",
  });
  restore();
  assert.equal(v, "alive");
});

test("网络错误/超时 → unknown（拿不准放行，不卡用户、不误判）", async () => {
  const restore = mockFetch(async () => {
    throw new Error("network boom");
  });
  const v = await checkLiveness("wt", {
    jd_url: "https://job.feihe.com/wt/feihe/mobweb/position/detail?postIdsAry=P4",
  });
  restore();
  assert.equal(v, "unknown");
});
