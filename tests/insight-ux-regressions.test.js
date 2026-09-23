const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const read = (rel) => fs.readFileSync(path.join(__dirname, "..", rel), "utf8");
const drawer = read("components/CompanyInsightDrawer.tsx");
const submitForm = read("components/InsightSubmitForm.tsx");
const library = read("app/insights/insights-client.tsx");
const mePage = read("app/me/page.tsx");
const resumePanel = read("components/ResumeProfilePanel.tsx");
const appliedClient = read("app/applied/applied-client.tsx");
const jobCard = read("components/JobCard.tsx");

test("I1 公司洞察抽屉把焦点、读屏语义和滚动锁一起启用", () => {
  assert.match(drawer, /useFocusTrap\(panelRef, open\)/);
  assert.match(drawer, /<aside\s+ref=\{panelRef\}[\s\S]*?role="dialog"[\s\S]*?aria-modal="true"/);
  assert.match(drawer, /useBodyScrollLock\(open\)/);
});

test("I2 体验表单默认不选评分，Esc 收起后仍保留草稿", () => {
  assert.match(submitForm, /useState<number \| null>\(null\)/);
  assert.match(submitForm, /评分（1 很差 · 5 很好）/);
  assert.match(submitForm, /disabled=\{saving \|\| rating == null\}/);
  assert.match(library, /useEscapeKey\(\(\) => setContribute\(false\), contribute\)/);
  assert.match(library, /contributeWasOpened[\s\S]*?hidden=\{!contribute\}/);
  assert.match(drawer, /if \(submitOpen\) setSubmitOpen\(false\)/);
  assert.match(drawer, /submitWasOpened[\s\S]*?hidden=\{!submitOpen\}/);
});

test("I3 I5 洞察库的空态和筛选文案说人话", () => {
  assert.match(library, /洞察库还没收录「\$\{filters\.q\.trim\(\)\}」。/);
  assert.match(library, /没有公司同时满足这些条件/);
  assert.match(library, /placeholder="全部可信度"/);
  assert.match(library, /placeholder="全部话题"/);
  assert.match(library, /placeholder="全部公司"/);
  assert.match(library, /最近核实：/);
  assert.doesNotMatch(library, /没有主体同时满足/);
});

test("I4 I5 抽屉用骨架和可读提示条，不再暴露去标识黑话", () => {
  assert.match(drawer, /<InsightDrawerSkeleton\s*\/>/);
  assert.match(drawer, /import \{ InsightDrawerSkeleton \} from "@\/components\/Skeletons"/);
  assert.match(drawer, /<Banner tone="lilac"/);
  assert.match(drawer, /已隐去个人信息/);
  assert.match(drawer, /分享我的经历/);
  assert.doesNotMatch(drawer, /贡献一条/);
});

test("I6 中文 404 有顶栏和两个返回入口", () => {
  const file = path.join(__dirname, "..", "app", "not-found.tsx");
  assert.ok(fs.existsSync(file));
  const notFound = fs.readFileSync(file, "utf8");
  assert.match(notFound, /<Navbar\s*\/>/);
  assert.match(notFound, /href="\/today"/);
  assert.match(notFound, /href="\/jobs"/);
});

test("I7 I8 个人中心不拿 0 充当未知计数，简历页不展示模型名", () => {
  assert.match(mePage, /let savedCount: number \| null = null/);
  assert.match(mePage, /value=\{savedCount \?\? "—"\}/);
  assert.match(mePage, /value=\{appliedCount \?\? "—"\}/);
  assert.match(resumePanel, /AI 解析已就绪。/);
  assert.doesNotMatch(resumePanel, /llmModel|模型 \$\{/);
});

test("I9 已下线投递记录明确说明进展仍可记录", () => {
  assert.match(appliedClient, /该岗位已下线/);
  assert.match(appliedClient, /岗位已从官网下线，你的投递进展照常记录。/);
});

test("I10 岗位卡保留清晰时间事实，并降低长时间未确认岗位的视觉权重", () => {
  assert.match(jobCard, /超过 2 周没在官网看到它，投递前先确认/);
  assert.match(jobCard, /freshness\.stale && "opacity-75 hover:opacity-100"/);
  assert.match(jobCard, /官网发布于 \{postedLabel\}/);
  assert.match(jobCard, /const tierLabel = tier\.level === "related" \? "相关匹配" : tier\.label/);
  assert.match(jobCard, /whitespace-nowrap/);
  assert.doesNotMatch(jobCard, /relativeTimeLabel/);
});
