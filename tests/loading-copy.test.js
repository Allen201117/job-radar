const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const read = (rel) => fs.readFileSync(path.resolve(__dirname, rel), "utf8");

const todayLoading = read("../app/today/loading.tsx");
const jobsLoading = read("../app/jobs/loading.tsx");
const savedLoading = read("../app/saved/loading.tsx");

// /today 的页头文案不再两处各写一份字面量，改成共读 app/today/hero.ts 的 TODAY_HERO
// —— 这比「两边都含同一个字符串」更强：字面量断言只能在有人**记得改测试**时才拦得住漂移，
// 而共读同一个常量让漂移在结构上不可能发生。（2026-09-06 就是这么漏的：改了 page.tsx 的
// 页头，loading.tsx 里那份还挂着旧句子，流式渲染时先闪一下旧文案。）
test("today loading copy matches real page", () => {
  const todayPage = read("../app/today/page.tsx");
  const hero = read("../app/today/hero.ts");
  for (const [name, src] of [["loading", todayLoading], ["page", todayPage]]) {
    assert.ok(src.includes('from "./hero"'), `today ${name} 应从 ./hero 取页头文案`);
    for (const field of ["eyebrow", "title", "description"]) {
      assert.ok(src.includes(`TODAY_HERO.${field}`), `today ${name} 缺 TODAY_HERO.${field}`);
    }
  }
  assert.ok(hero.includes("今天值得处理的官方岗位"), "hero 缺标题");
  assert.ok(hero.includes("今日机会"), "hero 缺眉标");
  // 页头先于「画像就绪与否」渲染，所以不许声称已按用户目标筛过——对新用户是假话。
  // 只看 description 的字面值，别扫整个文件：注释里正是在解释这条禁令，扫全文会自己咬自己。
  const description = /description:\s*"([^"]*)"/.exec(hero)?.[1];
  assert.ok(description, "hero.ts 里找不到 description 字面量");
  assert.ok(
    !/已按你的目标|按你的目标.*筛/.test(description),
    `页头不得声称已按用户目标筛选（新用户看到的是热门兜底），实际："${description}"`,
  );
  assert.ok(todayLoading.includes("count={3}"), "today loading should have 3 metric skeletons");
});

test("jobs loading copy matches real page and avoids refresh/discovery wording", () => {
  assert.ok(jobsLoading.includes("探索完整官方岗位库"), "jobs loading missing title");
  assert.ok(jobsLoading.includes("搜索岗位"), "jobs loading missing eyebrow");
  assert.ok(!jobsLoading.includes("刷新"), "jobs loading must not say 刷新");
  assert.ok(!jobsLoading.includes("发掘"), "jobs loading must not say 发掘");
});

test("saved loading uses 值得投, not 已收藏", () => {
  assert.ok(savedLoading.includes("值得投"), "saved loading missing 值得投");
  assert.ok(!savedLoading.includes("已收藏"), "saved loading must not say 已收藏");
});
