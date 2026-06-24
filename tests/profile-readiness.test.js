// 画像 readiness v3 必改（04 spec §4 / 05 spec §4.5）：城市非硬门——只看 content。
// 身份、强度都不参与 readiness（profileReadiness 只接受 RadarProfile，不读 stage/intensity）。
const assert = require("node:assert/strict");
const test = require("node:test");
const { loadOpp } = require("./_load-ts");

const { buildRadarProfile, profileReadiness, isProfileReady } = loadOpp("profile");

function prof(over = {}) {
  return buildRadarProfile(
    "u",
    {
      user_id: "u",
      target_locations: [],
      target_roles: [],
      target_keywords: [],
      exclude_keywords: [],
      target_companies: [],
      target_industries: [],
      daily_limit: 20,
      ...over,
    },
    null
  );
}

test("只填 target role、无城市 → profile_ready=true（v3：城市非硬门）", () => {
  const r = profileReadiness(prof({ target_roles: ["产品经理"] }));
  assert.equal(r.ready, true);
  assert.equal(isProfileReady(prof({ target_roles: ["产品经理"] })), true);
});

test("缺城市：missingLocation=true 仅作软提示、ready 不受影响", () => {
  const r = profileReadiness(prof({ target_keywords: ["AI"] }));
  assert.equal(r.ready, true);
  assert.equal(r.missingLocation, true);
  assert.equal(r.missingContent, false);
});

test("content 全空（roles/keywords/companies 全空）→ profile_ready=false，即便有城市", () => {
  const r = profileReadiness(prof({ target_locations: ["上海", "北京"] }));
  assert.equal(r.ready, false);
  assert.equal(r.missingContent, true);
});

test("仅 target_companies 也算 content → ready=true", () => {
  assert.equal(profileReadiness(prof({ target_companies: ["字节跳动"] })).ready, true);
});
