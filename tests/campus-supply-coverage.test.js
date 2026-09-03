const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const { loadTs } = require("./_load-ts");
const C = loadTs(path.join(__dirname, "..", "lib", "campus-supply-coverage.ts"));

// 「必投 30 家的校招供给打通了几家」——此前**全站没有任何地方能回答这个问题**：
// 看板的「校招供给」卡只报任务跑没跑、有多少家岗位数变了，不报覆盖。
// 没有度量就谈不上「稳定」，也没法发现某家哪天断了。
//
// 分档阈值来自真实库分布（2026-09-03，必投互联网 30 家的 (校招+实习)/社招 比例）：
//   ≤3.0%：vivo 0 / 快手 0.1 / 京东 0.1 / 中兴 0.4 / B站 0.4 / 小米 0.6 / 阿里 0.9 / SHEIN 3.0
//   ≥6.9%：科大讯飞 6.9 / 腾讯 9.3 / 得物 11.2 / 大疆 13.9 / 携程 25.2 / 百度 33.2 …
// 3.0 与 6.9 之间是干净的断层，且低端那 8 家全部已被独立证实是漏了校招板块。

test("健康：校招供给相对社招体量正常", () => {
  const r = C.classifyCampusSupply({ campusJobs: 2607, internJobs: 5553, socialJobs: 12482, hasCampusSource: true, hasAnySource: true });
  assert.equal(r.state, "healthy");
  assert.equal(r.blame, null, "健康的不该归咎于任何一方");
});

test("疑似漏板块：有社招体量却几乎没有校招岗 → 判定是我们的锅", () => {
  // 京东实测 2 : 1864；jd.py 里白纸黑字写着「校招/实习在 campus.jd.com 独立门户，本 adapter 只抓社招」
  const jd = C.classifyCampusSupply({ campusJobs: 0, internJobs: 2, socialJobs: 1864, hasCampusSource: true, hasAnySource: true });
  assert.equal(jd.state, "thin");
  assert.equal(jd.blame, "ours");
  assert.ok(jd.ratioPct < 1);

  // 快手 1:1753、中兴 1:247、B站 3:784、小米 11:1879、阿里 21:2326、SHEIN 32:1077
  for (const [cam, soc] of [[1, 1753], [1, 247], [3, 784], [11, 1879], [21, 2326], [32, 1077]]) {
    const r = C.classifyCampusSupply({ campusJobs: cam, internJobs: 0, socialJobs: soc, hasCampusSource: true, hasAnySource: true });
    assert.equal(r.state, "thin", `${cam}:${soc} 应判 thin`);
  }
  // ⚠️ vivo 是 0:484 —— 一个校招岗都没有，属于 no_supply 而非 thin。
  // 两者的处置不同：thin 是「接了但漏板块」，no_supply 是「压根没供给」，别混为一谈。
  const vivo = C.classifyCampusSupply({ campusJobs: 0, internJobs: 0, socialJobs: 484, hasCampusSource: false, hasAnySource: true });
  assert.equal(vivo.state, "no_supply");
  assert.equal(vivo.blame, "ours", "只有社招源、没有校招通道 = 我们的锅");
});

test("断层另一侧的都不该被误判成漏板块", () => {
  for (const [cam, soc] of [[57, 828], [294, 3176], [60, 536], [147, 1056], [73, 510], [254, 1009]]) {
    const r = C.classifyCampusSupply({ campusJobs: cam, internJobs: 0, socialJobs: soc, hasCampusSource: true, hasAnySource: true });
    assert.equal(r.state, "healthy", `${cam}:${soc} 不该判 thin`);
  }
});

test("社招基数太小时不用比例判——小样本比例不可靠", () => {
  // 深信服 30:23、金山办公 26:33 —— 比例 >100% 但基数小，靠比例判毫无意义
  const r = C.classifyCampusSupply({ campusJobs: 1, internJobs: 0, socialJobs: 20, hasCampusSource: true, hasAnySource: true });
  assert.notEqual(r.state, "thin", "社招基数 <100 不启用比例判据");
});

test("零供给必须分清是我们没接通道，还是对方没开", () => {
  // 这个区分是本产品的诚实底线：把「对方没开校招」算成我们的缺口，会让指标失真、也会误导排期。
  const noChannel = C.classifyCampusSupply({ campusJobs: 0, internJobs: 0, socialJobs: 0, hasCampusSource: false, hasAnySource: false });
  assert.equal(noChannel.state, "no_supply");
  assert.equal(noChannel.blame, "ours", "连源都没有 = 我们的锅");

  const channelOk = C.classifyCampusSupply({ campusJobs: 0, internJobs: 0, socialJobs: 300, hasCampusSource: true, hasAnySource: true });
  assert.equal(channelOk.state, "no_supply");
  assert.equal(channelOk.blame, "theirs", "校招通道接好了还是 0 岗 = 对方没开");

  const socialOnly = C.classifyCampusSupply({ campusJobs: 0, internJobs: 0, socialJobs: 300, hasCampusSource: false, hasAnySource: true });
  assert.equal(socialOnly.blame, "ours", "只有社招源 = 校招通道没接，是我们的锅");
});

test("汇总：打通率只算我们能负责的部分，不拿对方没开的充数也不甩锅", () => {
  const rows = [
    { company: "字节跳动", campusJobs: 2607, internJobs: 5553, socialJobs: 12482, hasCampusSource: true, hasAnySource: true },
    { company: "京东", campusJobs: 0, internJobs: 2, socialJobs: 1864, hasCampusSource: true, hasAnySource: true },
    { company: "联想", campusJobs: 0, internJobs: 0, socialJobs: 0, hasCampusSource: false, hasAnySource: false },
    { company: "某已接通但对方没开", campusJobs: 0, internJobs: 0, socialJobs: 300, hasCampusSource: true, hasAnySource: true },
  ];
  const s = C.summarizeCampusSupply(rows);
  assert.equal(s.total, 4);
  assert.equal(s.healthy, 1);
  assert.equal(s.thin, 1);
  assert.equal(s.noSupply, 2);
  assert.equal(s.ourGap, 2, "京东(漏板块) + 联想(无源) = 2 家是我们的锅");
  assert.equal(s.theirGap, 1, "对方没开的单独计，不进我们的缺口");
  // 打通率的分母剔掉「对方没开」的——那不是我们能修的
  assert.equal(s.reachablePct, 33, "4 家里 1 家健康、3 家中 1 家对方没开 → 1/3");
  assert.deepEqual(s.ourGapCompanies, ["京东", "联想"]);
});

test("脏值不炸", () => {
  assert.equal(C.classifyCampusSupply({}).state, "no_supply");
  assert.equal(C.summarizeCampusSupply(null).total, 0);
  assert.equal(C.summarizeCampusSupply([]).reachablePct, null, "没有可达样本时不编造百分比");
});
