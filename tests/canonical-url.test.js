const test = require("node:test");
const assert = require("node:assert/strict");
const { canonicalizeJdUrl } = require("../lib/canonical-url");

// canonical_jd_url：把同一岗位的链接变体（tracking 参数 / 尾斜杠）归一到同一把冲突键，
// 用于 jobs 表 active 唯一性（partial unique index）与 crawler upsert 冲突键。
// 三处实现必须逐字一致：lib/canonical-url.js（本文件被测）/ crawler/normalizer.py /
// supabase/migrations canonicalize_jd_url(SQL)。任何规则改动三处同改、两套测试同补。

test("普通详情链接原样返回", () => {
  assert.equal(
    canonicalizeJdUrl("https://x.com/job/123"),
    "https://x.com/job/123",
  );
});

test("规范尾斜杠：去掉末尾 /", () => {
  assert.equal(canonicalizeJdUrl("https://x.com/job/123/"), "https://x.com/job/123");
  assert.equal(canonicalizeJdUrl("https://x.com/job/123//"), "https://x.com/job/123");
});

test("去掉 utm_* tracking 参数", () => {
  assert.equal(
    canonicalizeJdUrl("https://x.com/job/123?utm_source=li&utm_medium=x"),
    "https://x.com/job/123",
  );
});

test("tracking key 大小写不敏感", () => {
  assert.equal(
    canonicalizeJdUrl("https://x.com/job?UTM_Source=a&id=1"),
    "https://x.com/job?id=1",
  );
});

test("保留非 tracking 参数（如 id / requementId）", () => {
  assert.equal(
    canonicalizeJdUrl("https://x.com/job?id=5&utm_source=li"),
    "https://x.com/job?id=5",
  );
  assert.equal(
    canonicalizeJdUrl("https://zhaopin.jd.com/web/job-info-detail?requementId=99&spm=abc"),
    "https://zhaopin.jd.com/web/job-info-detail?requementId=99",
  );
});

test("去掉常见统计/广告 tracking（spm/scm/bd_vid/gclid/fbclid 等）", () => {
  assert.equal(canonicalizeJdUrl("https://x.com/p?spm=abc&id=9"), "https://x.com/p?id=9");
  assert.equal(canonicalizeJdUrl("https://x.com/p?id=9&gclid=zz"), "https://x.com/p?id=9");
  assert.equal(canonicalizeJdUrl("https://x.com/p?bd_vid=1&id=9"), "https://x.com/p?id=9");
});

test("尾斜杠 + tracking 同时存在", () => {
  assert.equal(
    canonicalizeJdUrl("https://x.com/job/1/?utm_source=a"),
    "https://x.com/job/1",
  );
});

test("SPA hash 路由（#/...）一律保守原样，不破坏真实详情链接", () => {
  // Moka / 北森 / 飞书 / 携程等的 hash 路由，fragment 才是岗位身份，绝不能动。
  const moka = "https://app.mokahr.com/apply/x/123#/job/456?utm_source=li";
  assert.equal(canonicalizeJdUrl(moka), moka);
  const ctrip = "https://careers.ctrip.com/#/experienced/job-detail/789";
  assert.equal(canonicalizeJdUrl(ctrip), ctrip);
});

test("空 / null / undefined 安全返回", () => {
  assert.equal(canonicalizeJdUrl(null), null);
  assert.equal(canonicalizeJdUrl(undefined), undefined);
  assert.equal(canonicalizeJdUrl(""), "");
  assert.equal(canonicalizeJdUrl("   "), "");
});

test("裸 flag 参数（无 =）保留", () => {
  assert.equal(canonicalizeJdUrl("https://x.com/job?foo"), "https://x.com/job?foo");
});

test("空参数段被清掉但保留有效参数", () => {
  assert.equal(canonicalizeJdUrl("https://x.com/job?a=1&&b=2"), "https://x.com/job?a=1&b=2");
});

test("尾部裸问号去掉", () => {
  assert.equal(canonicalizeJdUrl("https://x.com/job?"), "https://x.com/job");
});

test("前后空白先 trim 再归一", () => {
  assert.equal(canonicalizeJdUrl("  https://x.com/job/1/  "), "https://x.com/job/1");
});
