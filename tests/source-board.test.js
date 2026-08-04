const { test } = require("node:test");
const assert = require("node:assert");
const path = require("node:path");
const { loadTs } = require("./_load-ts");

const { boardCoversCampus, CAMPUS_BOARDS } = loadTs(
  path.join(__dirname, "..", "lib", "source-board.ts"),
);

test("boardCoversCampus: campus 与 mixed 都算覆盖校招", () => {
  assert.equal(boardCoversCampus("campus"), true);
  // mixed = adapter 一次抓全社招+校招+实习（tencent/baidu/wt/beisen），照样覆盖校招
  assert.equal(boardCoversCampus("mixed"), true);
});

test("boardCoversCampus: social / intern 不算覆盖校招", () => {
  assert.equal(boardCoversCampus("social"), false);
  // 实习板块单独成桶，不等于校招（与 campusAdmission 的 intern 桶同口径）
  assert.equal(boardCoversCampus("intern"), false);
});

test("boardCoversCampus: 未知值/空值一律 false，不臆测", () => {
  // 迁移 187 前入库的行、或将来新增的板块值，宁可判「没覆盖」也不假阳性——
  // 假阳性会让校招专区把没接校招的公司显示成「已接入」，砸诚实徽章。
  assert.equal(boardCoversCampus(null), false);
  assert.equal(boardCoversCampus(undefined), false);
  assert.equal(boardCoversCampus(""), false);
  assert.equal(boardCoversCampus("unknown_future_board"), false);
});

test("CAMPUS_BOARDS 就是给 SQL/爬虫共用的那份白名单，值稳定", () => {
  // crawler/campus_lane.py 与 SQL 查询都按这两个值筛源，改动即为跨端契约变更。
  assert.deepEqual([...CAMPUS_BOARDS].sort(), ["campus", "mixed"]);
});
