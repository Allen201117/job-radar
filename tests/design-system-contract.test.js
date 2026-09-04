// 组件库契约测试。
//
// 为什么用「读源码 + 加载变体表」而不是引 eslint-plugin-tailwindcss：
// 那个插件会对全站存量的 763 处硬编码色值一起报警，等于装了个永远红的灯；而这里能**精确
// 限定只管 components/ui 与 lib/ui**，且零新依赖。库外的存量按「碰到再换」的节奏迁移。
//
// 变体表之所以住在 lib/ui/variants.ts（.ts 而非 .tsx），就是为了这里能真的 loadTs 进来断言，
// 而不是只能 grep 字符串——「ink 的小号不带落影」这种规则必须被机器验证，不能靠人记得。
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const { loadTs } = require("./_load-ts");

const repoRoot = path.resolve(__dirname, "..");
const uiDir = path.join(repoRoot, "components/ui");
const libUiDir = path.join(repoRoot, "lib/ui");

const read = (abs) => fs.readFileSync(abs, "utf8");

/** components/ui 下的组件文件（不含 deprecated 子目录与 barrel 自身）。 */
function componentFiles() {
  return fs
    .readdirSync(uiDir, { withFileTypes: true })
    .filter((e) => e.isFile() && /\.tsx?$/.test(e.name) && e.name !== "index.ts")
    .map((e) => e.name);
}

const variants = loadTs(path.join(libUiDir, "variants.ts"));

/* ─────────── 1. 库内零硬编码颜色 ─────────── */

test("组件库内部不许出现 hex 色值——颜色一律走 --tone-* / --ink-* 或既有 .btn-* 类", () => {
  const offenders = [];
  const scan = (dir, names) => {
    for (const name of names) {
      const abs = path.join(dir, name);
      const source = read(abs);
      // 去掉注释再扫：注释里为了讲清来历会写具体色值（如「照搬 dark:bg-[#3a201a]」），那不是代码。
      const code = source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
      const hits = code.match(/#[0-9a-fA-F]{3,8}\b/g);
      if (hits) offenders.push(`${name}: ${[...new Set(hits)].join(", ")}`);
    }
  };
  scan(uiDir, componentFiles());
  scan(
    libUiDir,
    fs.readdirSync(libUiDir).filter((n) => n.endsWith(".ts")),
  );
  assert.deepEqual(
    offenders,
    [],
    `组件库里出现了硬编码颜色。新增颜色请先在 app/globals.css 加 --tone-* 变量、` +
      `在 tailwind.config.js 登记，再用语义类名引用：\n${offenders.join("\n")}`,
  );
});

/* ─────────── 2. 新组件必须登记进 barrel ─────────── */

test("components/ui 下每个组件都要从 index.ts 导出（漏登记 = 别人找不到，只能自己再手写一个）", () => {
  const barrel = read(path.join(uiDir, "index.ts"));
  const missing = componentFiles()
    .map((name) => name.replace(/\.tsx?$/, ""))
    .filter((stem) => !barrel.includes(`"./${stem}"`));
  assert.deepEqual(missing, [], `这些组件没在 components/ui/index.ts 里登记：${missing.join(", ")}`);
});

test("废弃通道存在，且 index.ts 写明了「废弃搬走而不是直接删」的规矩", () => {
  assert.ok(
    fs.existsSync(path.join(uiDir, "deprecated/README.md")),
    "components/ui/deprecated/ 是组件的退役通道，别删",
  );
  const barrel = read(path.join(uiDir, "index.ts"));
  assert.match(barrel, /deprecated/, "index.ts 顶部要保留废弃流程说明");
});

/* ─────────── 3. 变体表的语义不变量（加载真实模块断言） ─────────── */

test("墨色按钮的落影只属于 lg：小号走无落影的 .btn-ink-sm，与 globals.css 的原设计一致", () => {
  const { buttonVariants } = variants;
  assert.match(buttonVariants({ variant: "ink", size: "lg" }), /\bbtn-ink\b/);
  for (const size of ["xs", "sm", "md"]) {
    const cls = buttonVariants({ variant: "ink", size });
    assert.match(cls, /\bbtn-ink-sm\b/, `ink + ${size} 应走 .btn-ink-sm`);
    assert.ok(
      !/\bbtn-ink\b(?!-sm)/.test(cls),
      `ink + ${size} 不该套上带落影的 .btn-ink（会比原设计多一层浮起）`,
    );
  }
});

test("按钮只加尺寸、不重抄颜色：变体表里不出现任何颜色工具类", () => {
  const { buttonVariants, SIZES } = variants;
  for (const variant of ["ink", "soft", "ghost", "quiet"]) {
    for (const size of SIZES) {
      const cls = buttonVariants({ variant, size });
      assert.ok(
        !/\b(bg|text|border)-(?!tone-)\[?#/.test(cls),
        `${variant}/${size} 里出现了颜色值；颜色应由 .btn-* 类提供`,
      );
    }
  }
});

test("七族 tone 在 Badge 与 Banner 里都齐全，且都指向 --tone-* 变量", () => {
  const { badgeVariants, bannerVariants, TONES } = variants;
  assert.equal(TONES.length, 7);
  for (const tone of TONES) {
    for (const [name, fn] of [
      ["badge", badgeVariants],
      ["banner", bannerVariants],
    ]) {
      const cls = fn({ tone });
      for (const slot of ["fg", "bg", "border"]) {
        assert.match(
          cls,
          new RegExp(`tone-${tone}-${slot}\\b`),
          `${name} 的 ${tone} 缺 ${slot}；三个槽位都要给，否则明暗切换会缺一块`,
        );
      }
    }
  }
});

/* ─────────── 4. 弹层的可访问性（这是全站原本的系统性缺口） ─────────── */

test("Modal 必须自带 role=dialog + aria-modal + 焦点陷阱 + 锁滚动 + ESC", () => {
  const modal = read(path.join(uiDir, "modal.tsx"));
  assert.match(modal, /role="dialog"/, "缺 role=dialog，读屏不会当它是对话框");
  assert.match(modal, /aria-modal="true"/);
  assert.match(modal, /useFocusTrap\(/, "缺焦点陷阱：键盘用户能 Tab 到被遮住的背景内容上");
  assert.match(modal, /useBodyScrollLock\(/);
  assert.match(modal, /useEscapeKey\(/);
  assert.match(modal, /createPortal\(/, "弹层必须 portal 到 body");
  // 遮罩不能是可聚焦/可读的语义元素，它只是视觉遮挡。
  assert.match(modal, /aria-hidden="true"/);
});

test("Popover 必须 portal 到 body、捕获阶段监听滚动、并豁免触发按钮自己", () => {
  const popover = read(path.join(uiDir, "popover.tsx"));
  const hooks = read(path.join(libUiDir, "hooks.ts"));
  assert.match(popover, /createPortal\(/, "absolute 定位在筛选条里会被 overflow-x-auto 裁掉");
  assert.match(popover, /useClickOutside\([\s\S]*?anchorRef\)/, "点外部关闭要豁免触发按钮");
  assert.match(
    hooks,
    /addEventListener\("scroll", place, true\)/,
    "滚动监听必须用 capture：祖先容器的滚动不冒泡到 window",
  );
});

test("焦点陷阱关闭时要把焦点还给触发者，否则键盘用户得从头 Tab", () => {
  const hooks = read(path.join(libUiDir, "hooks.ts"));
  assert.match(hooks, /restoreTo\?\.focus\?\.\(\)/);
});

/* ─────────── 5. 从类型上堵死漏写 aria 的可能 ─────────── */

test("Segmented 的 ariaLabel 是必填 prop（改造前 4 处手写里有 3 处漏了组标签）", () => {
  const segmented = read(path.join(uiDir, "segmented.tsx"));
  assert.match(segmented, /ariaLabel: string;/, "ariaLabel 不能是可选的");
  assert.ok(!/ariaLabel\?:/.test(segmented), "ariaLabel 变成可选就等于允许漏写");
  assert.match(segmented, /role="group"/);
  assert.match(segmented, /aria-pressed=\{active\}/);
});

test("Field 把说明与错误用 aria-describedby 接到控件上，报错带 role=alert", () => {
  const field = read(path.join(uiDir, "field.tsx"));
  assert.match(field, /aria-describedby/);
  assert.match(field, /aria-invalid/);
  assert.match(field, /role="alert"/, "错误文案要能被读屏播报");
});

test("Spinner 尊重 prefers-reduced-motion，并且默认对读屏说话", () => {
  const spinner = read(path.join(uiDir, "spinner.tsx"));
  assert.match(spinner, /motion-reduce:animate-none/);
  assert.match(spinner, /role="status"/);
});

/* ─────────── 6. 令牌层与 Tailwind 登记保持同步 ─────────── */

test("每个 --tone-* 变量都在 globals.css 的明暗两套里各定义一次，并在 tailwind 登记", () => {
  const css = read(path.join(repoRoot, "app/globals.css"));
  const tw = read(path.join(repoRoot, "tailwind.config.js"));
  const { TONES } = variants;
  for (const tone of TONES) {
    for (const slot of ["fg", "bg", "border"]) {
      const decl = new RegExp(`--tone-${tone}-${slot}:`, "g");
      const count = (css.match(decl) ?? []).length;
      assert.equal(
        count,
        2,
        `--tone-${tone}-${slot} 应在 :root 与 .dark 里各定义一次，实际 ${count} 次`,
      );
      assert.match(
        tw,
        new RegExp(`var\\(--tone-${tone}-${slot}\\)`),
        `tailwind.config.js 里没登记 --tone-${tone}-${slot}，语义类名不会被生成`,
      );
    }
  }
});
