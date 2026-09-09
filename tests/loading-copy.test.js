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
    for (const field of ["eyebrow", "title"]) {
      assert.ok(src.includes(`TODAY_HERO.${field}`), `today ${name} 缺 TODAY_HERO.${field}`);
    }
  }
  assert.ok(hero.includes("今天先看这些"), "hero 缺标题");
  assert.ok(hero.includes("今日机会"), "hero 缺眉标");
  // 页头先于「画像就绪与否」渲染，所以不许声称已按用户目标筛过——对新用户是假话。
  // 只看 title 的字面值，别扫整个文件：注释里正是在解释这条禁令，扫全文会自己咬自己。
  const title = /title:\s*"([^"]*)"/.exec(hero)?.[1];
  assert.ok(title, "hero.ts 里找不到 title 字面量");
  assert.ok(
    !/已按你的目标|按你的目标.*筛/.test(title),
    `页头不得声称已按用户目标筛选（新用户看到的是热门兜底），实际："${title}"`,
  );
  assert.ok(todayLoading.includes("count={3}"), "today loading should have 3 metric skeletons");
});

test("jobs loading copy matches real page and avoids refresh/discovery wording", () => {
  assert.ok(jobsLoading.includes("整个岗位库，自己筛"), "jobs loading missing title");
  assert.ok(jobsLoading.includes("搜索岗位"), "jobs loading missing eyebrow");
  assert.ok(!jobsLoading.includes("刷新"), "jobs loading must not say 刷新");
  assert.ok(!jobsLoading.includes("发掘"), "jobs loading must not say 发掘");
});

test("saved loading uses 值得投, not 已收藏", () => {
  assert.ok(savedLoading.includes("值得投"), "saved loading missing 值得投");
  assert.ok(!savedLoading.includes("已收藏"), "saved loading must not say 已收藏");
});

// 页头只有「眉标 + 一句标题」，没有说明小字（2026-09-09 创始人拍板：那段解释性文案
// 读起来像产品在自我介绍，且与眉标 + 标题重复）。ProductHero 已经不收 description prop，
// 这条断言是给「有人把 prop 加回去」留的第二道门——它扫的是调用方，TS 只挡得住类型。
test("ProductHero 页头不带说明小字", () => {
  const appDir = path.resolve(__dirname, "../app");
  const walk = (dir) =>
    fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
      const full = path.join(dir, e.name);
      return e.isDirectory() ? walk(full) : full.endsWith(".tsx") ? [full] : [];
    });
  let checked = 0;
  for (const file of walk(appDir)) {
    const src = fs.readFileSync(file, "utf8");
    // 抓每个 <ProductHero …> 开标签（到第一个 > 为止），只看它自己的 props。
    for (const m of src.matchAll(/<ProductHero\b[\s\S]*?>/g)) {
      checked += 1;
      assert.ok(
        !/\bdescription[=:]/.test(m[0]),
        `${path.relative(appDir, file)} 的页头又挂上说明小字了：${m[0].slice(0, 120)}`,
      );
    }
  }
  assert.ok(checked >= 15, `只扫到 ${checked} 个 ProductHero，正则可能没匹配上`);
});

// loading.tsx 是 page.tsx 的骨架屏，页头必须逐字一致，否则流式渲染时会先闪一下旧文案。
// /today 已靠共读 TODAY_HERO 从结构上杜绝漂移；其余页仍是两处字面量，这里逐对校验。
// /admin/health 的真实标题带 tab 后缀（`管理员看板 · ${tabLabel}`），故用前缀匹配。
const heroStrings = (src, key) =>
  [...src.matchAll(new RegExp(`\\b${key}[=:]\\s*(?:\\{)?["\`]([^"\`]+)["\`]`, "g"))].map((m) => m[1]);

for (const page of ["jobs", "campus", "programs", "insights", "saved", "applied", "me", "admin/health"]) {
  test(`${page} loading 页头与 page 一致`, () => {
    const loading = read(`../app/${page}/loading.tsx`);
    const real = read(`../app/${page}/page.tsx`);
    for (const key of ["eyebrow", "title"]) {
      const [skeleton] = heroStrings(loading, key);
      assert.ok(skeleton, `app/${page}/loading.tsx 里读不到 ${key}`);
      const candidates = heroStrings(real, key);
      assert.ok(
        candidates.some((c) => c === skeleton || c.startsWith(skeleton)),
        `app/${page} 骨架屏 ${key}「${skeleton}」在 page.tsx 里找不到（page 有：${candidates.join(" / ")}）`,
      );
    }
  });
}
