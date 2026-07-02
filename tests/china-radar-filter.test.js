const test = require("node:test");
const assert = require("node:assert/strict");
const { keepForChinaRadar, resolveInlineAtsSource } = require("../lib/live-search");

// P2-B：外企 ATS(greenhouse/lever) 内联抓取时必须只保留大中华区岗位，
// 否则用户不填城市就会把看板灌满全球岗位。对齐 crawler normalizer.keep_for_china_radar。

test("中国城市/省/中文地点 → 保留", () => {
  for (const loc of [
    "Beijing, China",
    "Shanghai",
    "上海",
    "Shenzhen",
    "Hong Kong",
    "杭州",
    "Chengdu, Sichuan",
    "Greater China",
  ]) {
    assert.equal(keepForChinaRadar(loc), true, loc);
  }
});

test("海外地点 → 丢弃", () => {
  for (const loc of [
    "San Francisco, CA",
    "London, United Kingdom",
    "Tokyo, Japan",
    "Singapore",
    "New York",
    "Bengaluru, India",
  ]) {
    assert.equal(keepForChinaRadar(loc), false, loc);
  }
});

test("台湾地点 → 维持不抓，不归入国内或海外范围", () => {
  for (const loc of ["Taiwan", "Taipei, Taiwan", "台北, 台湾"]) {
    assert.equal(keepForChinaRadar(loc), false, loc);
  }
});

test("子串陷阱：Humacao(波多黎各) 不被 macao 词边界误命中", () => {
  assert.equal(keepForChinaRadar("Humacao, Puerto Rico"), false);
});

test("逗号/连字符分隔的 Hong-Kong / Hong, Kong 仍命中", () => {
  assert.equal(keepForChinaRadar("Hong-Kong"), true);
  assert.equal(keepForChinaRadar("Hong, Kong"), true);
});

test("未绑定海外的 remote → 保留；绑定海外的 remote → 丢弃", () => {
  assert.equal(keepForChinaRadar("Remote"), true);
  assert.equal(keepForChinaRadar("Remote - US"), false);
  assert.equal(keepForChinaRadar("Remote, Singapore"), false);
});

test("空/缺失 → 丢弃", () => {
  assert.equal(keepForChinaRadar(""), false);
  assert.equal(keepForChinaRadar(null), false);
  assert.equal(keepForChinaRadar(undefined), false);
});

// resolveInlineAtsSource：把真实 sources 行解析成 { provider, url }；非内联源/坏 host 返回 null。
test("greenhouse 真实源 → 解析 provider+url", () => {
  const r = resolveInlineAtsSource({
    adapter_name: "greenhouse",
    source_url: "https://boards-api.greenhouse.io/v1/boards/elastic/jobs?content=true",
  });
  assert.equal(r.provider, "greenhouse");
  assert.match(r.url, /boards-api\.greenhouse\.io\/v1\/boards\/elastic\/jobs/);
  assert.match(r.url, /content=true/);
});

test("lever 真实源 → 解析 provider+url", () => {
  const r = resolveInlineAtsSource({
    adapter_name: "lever",
    source_url: "https://api.lever.co/v0/postings/binance?mode=json",
  });
  assert.equal(r.provider, "lever");
  assert.match(r.url, /api\.lever\.co\/v0\/postings\/binance/);
  assert.match(r.url, /mode=json/);
});

test("浏览器源(moka/workday/beisen) → null(不可内联)", () => {
  assert.equal(
    resolveInlineAtsSource({ adapter_name: "moka", source_url: "https://app.mokahr.com/x" }),
    null,
  );
  assert.equal(
    resolveInlineAtsSource({ adapter_name: "workday", source_url: "https://x.wd1.myworkdayjobs.com/y" }),
    null,
  );
  assert.equal(
    resolveInlineAtsSource({ adapter_name: "beisen", source_url: "https://x.zhiye.com/z" }),
    null,
  );
});

test("host 与 adapter 不符 → null(防 SSRF/脏数据)", () => {
  assert.equal(
    resolveInlineAtsSource({
      adapter_name: "greenhouse",
      source_url: "https://evil.example.com/jobs",
    }),
    null,
  );
  assert.equal(
    resolveInlineAtsSource({ adapter_name: "lever", source_url: "https://api.lever.co.evil.com/x" }),
    null,
  );
});

test("缺 source_url / 非法 url → null", () => {
  assert.equal(resolveInlineAtsSource({ adapter_name: "greenhouse" }), null);
  assert.equal(resolveInlineAtsSource({ adapter_name: "greenhouse", source_url: "not a url" }), null);
  assert.equal(resolveInlineAtsSource(null), null);
});
