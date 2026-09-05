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

/* ─────────── 7. 动效基座（iOS 手感的物理基础） ─────────── */

test("四条弹簧曲线齐全，且过冲量符合各自的用途", () => {
  const css = read(path.join(repoRoot, "app/globals.css"));
  for (const name of ["smooth", "snappy", "bouncy", "press"]) {
    assert.match(css, new RegExp(`--spring-${name}: linear\\(`), `缺 --spring-${name}`);
    assert.match(css, new RegExp(`--spring-${name}-dur:`), `缺 --spring-${name}-dur`);
  }
  // smooth 用于颜色/状态切换，**绝不能过冲**——颜色回弹会让「变了个色」显得轻浮。
  const smooth = css.match(/--spring-smooth: linear\(([^)]*)\)/)?.[1] ?? "";
  const smoothPeak = Math.max(...smooth.split(",").map((n) => parseFloat(n)));
  assert.ok(smoothPeak <= 1.0001, `smooth 不该过冲，实测峰值 ${smoothPeak}`);
  // bouncy 用于正反馈，**必须**看得出回弹，否则和 smooth 没区别、白留一档。
  const bouncy = css.match(/--spring-bouncy: linear\(([^)]*)\)/)?.[1] ?? "";
  const bouncyPeak = Math.max(...bouncy.split(",").map((n) => parseFloat(n)));
  assert.ok(bouncyPeak > 1.03, `bouncy 过冲太小（${bouncyPeak}），和 smooth 就没区别了`);
});

test("按压反馈存在、克制（0.97 不是 0.9）、且尊重 reduced-motion", () => {
  const css = read(path.join(repoRoot, "app/globals.css"));
  assert.match(css, /\.press-feedback:active\s*\{[^}]*transform:\s*scale\(0\.97\)/);
  // 缩到 0.9 会读成「这东西要被删掉了」，传达破坏性而不是按压。
  assert.ok(
    !/\.press-feedback(-subtle)?:active\s*\{[^}]*scale\(0\.[0-8]\d?\)/.test(css),
    "按压缩放过大：iOS 的量级是 0.97，克制到几乎只在余光里感觉到",
  );
  assert.match(css, /prefers-reduced-motion[\s\S]{0,400}press-feedback/);
});

test("动效一律走令牌，组件里不许写死毫秒数或贝塞尔曲线", () => {
  const offenders = [];
  // animated-blur-number 自己注入一整份样式表、且已经用了自己调好的 linear() 弹簧曲线，
  // 建令牌层之前就在线上跑了。把它的曲线改成公共令牌会改变动画观感，属于有意的视觉改动，
  // 不能在「加一条 lint 规则」时顺手做掉。豁免它，等哪天要统一动效再单独处理。
  const MOTION_GRANDFATHERED = new Set(["animated-blur-number.tsx"]);
  for (const name of componentFiles()) {
    if (MOTION_GRANDFATHERED.has(name)) continue;
    const code = read(path.join(uiDir, name))
      .replace(/\/\*[\s\S]*?\*\//g, "")
      .replace(/^\s*\/\/.*$/gm, "");
    // 允许 cubic-bezier 作为 var() 的兜底值（linear() 在旧浏览器不支持），
    // 但不允许脱离 var() 单独出现——那就是绕过令牌自己调曲线了。
    for (const m of code.matchAll(/cubic-bezier\([^)]*\)/g)) {
      const before = code.slice(Math.max(0, m.index - 80), m.index);
      if (!before.includes("var(--spring-")) offenders.push(`${name}: ${m[0]}`);
    }
    for (const m of code.matchAll(/(?:transitionDuration|animationDuration):\s*"(\d+m?s)"/g)) {
      offenders.push(`${name}: 写死时长 ${m[1]}`);
    }
  }
  assert.deepEqual(offenders, [], `动效要走 --spring-* / --dur-* 令牌：\n${offenders.join("\n")}`);
});

/* ─────────── 8. 新增交互组件的行为底线 ─────────── */

test("Switch 的滑块颜色必须跟着轨道走，不能写死", () => {
  const sw = read(path.join(uiDir, "switch.tsx"));
  assert.match(sw, /role="switch"/);
  assert.match(sw, /aria-checked=\{checked\}/);
  // 踩过的坑：开态滑块写死白色，而暗色下轨道是米白 #f3ecdf → 白滑块躺在米白轨道上，看不见。
  // 只禁裸 bg-white；bg-white/[0.08] 是暗色轨道底，与滑块无关，别误伤。
  assert.ok(!/bg-white(?![/\w])/.test(sw), "滑块不能写死 bg-white，暗色轨道是浅色时会看不见");
  assert.match(sw, /checked \? "bg-action-ink-fg" : "bg-switch-knob"/);
});

test("Sheet 的关闭判定是「距离或速度」，不是只看距离", () => {
  const sheet = read(path.join(uiDir, "sheet.tsx"));
  // 只看距离：快速下甩只拖了 40px 也该关，却不关；只看速度：慢慢拖到底不关，很别扭。
  assert.match(sheet, /DISMISS_DISTANCE_RATIO/);
  assert.match(sheet, /DISMISS_VELOCITY/);
  assert.match(sheet, /dy > height \* DISMISS_DISTANCE_RATIO \|\| velocity > DISMISS_VELOCITY/);
  // 内容没滚到顶就接管拖拽 = 用户想滚列表却把面板拖走了。
  assert.match(sheet, /scrollRef\.current\?\.scrollTop \?\? 0\) > 0\) return/);
  // 拖拽中不能有 transition，否则不跟手。
  assert.match(sheet, /dragging\s*\?\s*"none"/);
});

test("AlertDialog 的破坏性操作默认焦点在「取消」上", () => {
  const dlg = read(path.join(uiDir, "alert-dialog.tsx"));
  // 连按回车不该误删；想删的人多按一次 Tab，代价不对等才是对的。
  assert.match(dlg, /if \(open && destructive\) cancelRef\.current\?\.focus\(\)/);
  // 提交中不许点遮罩/ESC 关掉，否则半路丢状态。
  assert.match(dlg, /closeOnBackdrop=\{!pending\}/);
  assert.match(dlg, /closeOnEscape=\{!pending\}/);
});

test("Progress 的不确定态必须说人话，不能让读屏念「进度 0%」", () => {
  const pg = read(path.join(uiDir, "progress.tsx"));
  assert.match(pg, /role="progressbar"/);
  assert.match(pg, /aria-valuetext=\{indeterminate \?/);
  assert.match(pg, /aria-valuenow=\{indeterminate \? undefined/);
});

test("Stepper 用有序列表 + 对勾，不靠颜色单独传达完成态", () => {
  const st = read(path.join(uiDir, "stepper.tsx"));
  assert.match(st, /<ol/, "步骤天然有顺序，读屏要能念「共 4 项，第 2 项」");
  assert.match(st, /aria-current=\{active \? "step" : undefined\}/);
  // WCAG 1.4.1：不能只用颜色传达信息，色觉障碍用户读不出来。
  assert.match(st, /done \? <Check/);
});

test("借鉴的第三方许可有留存（MIT 唯一强制要求就是保留版权声明）", () => {
  assert.ok(fs.existsSync(path.join(repoRoot, "LICENSES/LICENSE-radix-ui.txt")));
  const readme = read(path.join(repoRoot, "LICENSES/README.md"));
  // 这三个是明确不能用的，写进文档免得以后有人踩
  for (const banned of ["Tailwind UI", "Aceternity", "Magic UI"]) {
    assert.ok(readme.includes(banned), `LICENSES/README.md 要写明 ${banned} 不能用及原因`);
  }
});
