const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const read = (rel) => fs.readFileSync(path.resolve(__dirname, rel), "utf8");

const todayLoading = read("../app/today/loading.tsx");
const jobsLoading = read("../app/jobs/loading.tsx");
const savedLoading = read("../app/saved/loading.tsx");

// 页头文案是一个字符串在多处出现，怎么防漂：
//   /today 走「共读同一个常量」（app/today/hero.ts），结构上不可能漂；
//   其余页仍是两处字面量（page.tsx + loading.tsx 骨架屏），靠下面的逐对比较兜住。
// （2026-09-06 就是这么漏的：改了 page.tsx 的页头，loading.tsx 里那份还挂着旧句子，
//   流式渲染时先闪一下旧文案。）
test("today loading copy matches real page", () => {
  const todayPage = read("../app/today/page.tsx");
  const hero = read("../app/today/hero.ts");
  for (const [name, src] of [["loading", todayLoading], ["page", todayPage]]) {
    assert.ok(src.includes('from "./hero"'), `today ${name} 应从 ./hero 取页头文案`);
    assert.ok(src.includes("TODAY_HERO.title"), `today ${name} 缺 TODAY_HERO.title`);
  }
  // 页头先于「画像就绪与否」渲染，所以不许写成「已按你的目标筛过」这类宣称——对新用户是假话。
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
  assert.ok(jobsLoading.includes("职位"), "jobs loading missing title");
  assert.ok(!jobsLoading.includes("刷新"), "jobs loading must not say 刷新");
  assert.ok(!jobsLoading.includes("发掘"), "jobs loading must not say 发掘");
});

// 2026-09-09「和大厂对齐」后 saved 的叫法从「值得投」改成「收藏」——这条断言的方向也跟着反了。
// 旧断言（必须是「值得投」、不许出现「收藏」）保留在 git 历史里，别照着它改回去。
test("saved loading uses 收藏, not 值得投", () => {
  assert.ok(savedLoading.includes("收藏"), "saved loading missing 收藏");
  assert.ok(!savedLoading.includes("值得投"), "saved loading must not say 值得投");
});

const heroTitles = (src) =>
  [...src.matchAll(/\btitle[=:]\s*(?:\{)?["`]([^"`]+)["`]/g)].map((m) => m[1]);

// 页头只有「图标 + 页面名」一层：没有眉标、没有说明小字（2026-09-09 创始人拍板，照大厂做法改）。
// 实测 BOSS直聘 / 智联 / 猎聘的岗位列表页连大标题都没有，页面身份全靠导航项那两三个字。
// ProductHero 已经不收 eyebrow / description prop，这条断言是给「有人把 prop 加回去」留的
// 第二道门——它扫的是调用方，TS 只挡得住类型。
test("页头只剩一个页面名，没有眉标和说明小字", () => {
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
      for (const banned of ["description", "eyebrow"]) {
        assert.ok(
          !new RegExp(`\\b${banned}[=:]`).test(m[0]),
          `${path.relative(appDir, file)} 的页头又挂上 ${banned} 了：${m[0].slice(0, 120)}`,
        );
      }
    }
  }
  assert.ok(checked >= 15, `只扫到 ${checked} 个 ProductHero，正则可能没匹配上`);
});

// 大厂铁律：页面名 == 导航项名。点「收藏」进来看到「值得投」是割裂。
// 所以页头标题直接钉在 lib/i18n.ts 的导航词表上——改了导航名而没改页头，这里直接红。
const NAV_TITLE_PAGES = {
  jobs: "app/jobs",
  campus: "app/campus",
  insights: "app/insights",
  programs: "app/programs",
  me: "app/me",
  saved: "app/saved",
  applied: "app/applied",
};
test("页面名与导航项逐字一致", () => {
  const dict = read("../lib/i18n.ts");
  const navLabel = (key) =>
    new RegExp(`\\b${key}:\\s*\\{\\s*zh:\\s*"([^"]+)"`).exec(dict)?.[1];

  // /today 的页头走常量，单独比
  assert.equal(heroTitles(read("../app/today/hero.ts"))[0], navLabel("today"));
  // /sources 不在主导航里，标题跟 i18n 的 sources 词条走
  assert.ok(heroTitles(read("../app/sources/page.tsx")).includes(navLabel("sources")));

  for (const [key, dir] of Object.entries(NAV_TITLE_PAGES)) {
    const label = navLabel(key);
    assert.ok(label, `lib/i18n.ts 里读不到导航项 ${key}`);
    for (const file of [`../${dir}/page.tsx`, `../${dir}/loading.tsx`]) {
      const titles = heroTitles(read(file));
      assert.ok(
        titles.includes(label),
        `${file} 的页头标题应为导航名「${label}」，实际读到：${titles.join(" / ") || "（空）"}`,
      );
    }
  }
});

// 骨架屏与真实页头必须逐字一致，否则流式渲染时会先闪一下旧文案。
// /admin/health 的真实标题带 tab 后缀（`管理员看板 · ${tabLabel}`），故用前缀匹配。
for (const page of ["jobs", "campus", "programs", "insights", "saved", "applied", "me", "admin/health"]) {
  test(`${page} loading 页头与 page 一致`, () => {
    const [skeleton] = heroTitles(read(`../app/${page}/loading.tsx`));
    assert.ok(skeleton, `app/${page}/loading.tsx 里读不到 title`);
    const candidates = heroTitles(read(`../app/${page}/page.tsx`));
    assert.ok(
      candidates.some((c) => c === skeleton || c.startsWith(skeleton)),
      `app/${page} 骨架屏标题「${skeleton}」在 page.tsx 里找不到（page 有：${candidates.join(" / ")}）`,
    );
  });
}
