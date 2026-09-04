---
version: beta
name: warm-editorial-design-system
description: >
  Job Radar's implemented brand language is a warm-paper editorial system, not an
  Apple-blue tool. A calm parchment canvas (#f4efe6) with soft pastel wash and faint
  grain; one ink-black action color (#1a1714) as the single "click me" signal; a
  pure system sans stack (no webfonts, deliberately — see Typography); warm-white
  translucent surfaces with hairline borders and soft shadows; pastels used only as
  small status/dimension accents. Decoration (gradient wash, grain, polaroid fragments,
  float) is concentrated on the marketing / login pages; in-product surfaces stay calm
  so official-source data can be trusted at a glance.
source_of_truth: app/globals.css  # this doc describes what globals.css implements; if they disagree, the CSS wins
supersedes: the prior "Apple-design-analysis / Action Blue #0066cc / photography-first" spec (never implemented)
---

# Job Radar — Design System (warm editorial)

> This file documents the **implemented** brand language. The authoritative tokens live in
> `app/globals.css` (component classes `.btn-ink`, `.surface`, `.chip`, `.field-soft`, `.bg-editorial`…)
> and `tailwind.config`. Treat the CSS as source of truth; this doc explains intent and usage.

## Brand in one line

Calm, precise, trustworthy — a focused instrument for official-job discovery. Warm paper, ink action,
quiet pastels. It should feel premium and editorial, never like a flashy third-party job board or a
purple-blue AI-SaaS landing page.

## Colors

The action color is **ink, not blue.** A single high-contrast ink pill is the only primary CTA signal;
everything else recedes. Pastels appear only as small chips and the background wash.

```
canvas / paper        #f4efe6   editorial background (.bg-editorial base), chips, navbar
ink (action + text)   #1a1714   primary buttons (.btn-ink), headings, active nav pill
ink-hover             #2b2520
on-ink (text on ink)  #f7f1e6
text-secondary        #3f3a33
text-muted            #5f594e / #6b655a
text-faint            #8a8275 / #9a9184
surface               rgba(255,255,255,0.70)  warm-white translucent card (.surface)
surface-soft          rgba(255,255,255,0.55)
hairline border       rgba(0,0,0,0.06–0.08)
```

Pastel accent families are now **design tokens**, not literals. Values live in
`app/globals.css` as `--tone-<family>-{fg,bg,border}` with a light and a dark set; use them
through the Tailwind classes `text-tone-sky-fg` / `bg-tone-sky-bg` / `border-tone-sky-border`.

```
family   light fg   light bg   light border   dark accent   meaning
sky      #3f7cc0    #dceafa    #b7d2ee        #7fb2e8       社招 / 岗位聚合 / timing
green    #4f6f2a    #e6f2d6    #bcdcae        #a3d06a       校招 / fact / 新鲜
amber    #8a6312    #fbeecb    #e7c98a        #e0b15a       实习 / experience / 转陈
teal     #2f8a63    #dcf2e8    #a9d8c4        #6cc99e       hiring / 招聘动态
rose     #9c4a3c    #f7e6e1    #e0b4ac        #e6a99f       失败 / 风险 / 报错
lilac    #6a4fa0    #efe9f8    #cfc0e6        #c3b1e6       职业洞察 / path
neutral  #5f594e    #f4efe6    rgba(0,0,0,.06) —           不表态
```

In dark mode a family collapses to **one accent at three opacities** — text 100%, background 15%,
border 30% — which is what the codebase already did by hand. `rose` is the one exception: its dark
background is solid `#3a201a` (an error banner needs an opaque bed to stay legible).

> The table above previously listed `#2f6299 / #2f7d8a / #a84f63 / #dcf0f2 / #f8e6ea`. Those values
> were never in `globals.css` — the doc had drifted from the code. Fixed 2026-09-04 by reading the
> values back out of the implementation.

Background wash (`.bg-editorial`): paper + three soft radial pastels (sky / lemon-green / warm-orange),
plus an optional ~4% grain (`.grain`). This is a **marketing/login** flourish; keep product pages calmer.

`:root` keeps a residual `--primary` token (**`153 96% 36%` — a green, not the blue this doc used to
claim**) used **only** for the focus-visible ring and `::selection`. It is an accessibility/system
accent, not the brand action color.

## Typography

One unified **system sans** stack for the whole product — no webfonts. This is deliberate:
webfonts (e.g. Google Fonts) are unreliable behind the GFW and would break offline builds. On Mac this
resolves to SF Pro Display/Text + PingFang SC for Chinese; on Windows to Segoe UI + Microsoft YaHei.

```
--font-display: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
  "SF Pro Display", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "Segoe UI", sans-serif
```

`.display-tight` headings: same stack, letter-spacing -0.02em, antialiased. Body copy is Chinese-first,
plain and scannable. Use tabular figures for counts / match scores / diagnostics.

## Shape, surface, motion

- **Radius:** pills (`rounded-full`) for actions and chips; ~1.4rem cards (`.surface`), 1.25rem soft
  cards, 1.15rem polaroid. Global `--radius: 0.75rem`.
- **Surfaces:** warm-white translucent + hairline border + soft long shadow. `.surface-hover` lifts
  -4px on hover (reduced-motion safe).
- **Motion:** `.rise` entrance, `.float-soft` 8s drift, hover lifts — all gated by
  `prefers-reduced-motion`. Keep motion subtle and purposeful.
- **Texture flourishes (marketing/login only):** `.polaroid` product fragments, grain, the pastel wash.

## Buttons

```
.btn-ink / .btn-ink-sm   ink-black solid pill — the single primary action
.btn-ghost               outlined ghost pill — secondary
.btn-soft                warm-white soft pill — in-card / inline secondary
```

One primary ink action per view. Don't introduce competing accent-colored buttons.

## Design principles

1. **Official-source loop, legible layers.** "查已有岗位 / 更新关注公司 / 扩大官方搜索范围" read as
   distinct, understandable steps (progressive disclosure), not opaque engineering modes.
2. **Task-first product surface.** Scan jobs, compare match signals, act — without decorative friction.
   Pastels and texture stay as accents; product pages favor calm warm-white surfaces + ink.
3. **Ink restraint.** One ink action color, strong hierarchy, generous whitespace, precise type, careful
   motion. (This replaces the old "one blue action color" — blue is only the focus ring.)
4. **Trust through copy and state.** Failures, empty results, cached results, pending parsers, and
   insight availability are explained near the action that caused them, in plain Chinese — never raw
   error codes. This is the core "official / trustworthy" signal.
5. **Let data breathe.** Counts, match scores, source diagnostics use tabular figures and compact
   structure, not noisy cards.

## Official-trust signals (what makes it feel verified, not casual)

- The ink-only CTA + warm-white surfaces read as an instrument, not an ad.
- Source quality is explicit: official-source framing, fact / experience / derived chips are color-coded
  and labeled; insight cards carry attribution and a single "聚合·去标识" disclaimer.
- No third-party-jobboard flash, no purple-blue gradient AI-SaaS marketing, no decorative dashboard clutter.

## Accessibility

WCAG AA contrast, visible focus ring (`--primary` at `:focus-visible`), keyboard-reachable
controls, `prefers-reduced-motion`-safe transitions, responsive mobile layouts. Chinese-first copy;
lightweight i18n scaffolding (`lib/i18n.ts`) is retained but the language switch is hidden until key
pages are translated (avoid a half-translated illusion).

---

# 组件库（Component Library）

> 2026-09-04 建立。这一节是**给人看的运维手册**，讲清楚组件库怎么用、怎么加、怎么退役。
> 上面的英文部分讲「品牌长什么样」，这一节讲「怎么把它维持住」。

## 为什么要有它

改造前的病根不是「没规范」，而是**规范没有尺寸轴**。`.btn-ink` / `.chip` / `.field-soft`
写得都很好、连暗色都配齐了，但每个类只有一个写死的尺寸。想要小一号的按钮就只能把整串样式
连暗色一起抄出来——实测墨色按钮被手抄成 **11 种尺寸**、白底次按钮 **10 种**，而 CSS 只提供
2 种和 1 种。`today-client.tsx` 里手写的 `dark:bg-[#f3ecdf] dark:text-[#16130f]` 和
`.dark .btn-ink` 的定义逐字节相同，纯粹是为了换个 padding。

代价（改前 grep 实测）：1,474 处硬编码色值、208 个不同色值；28 个文件各写各的 `<button>`；
9 个各写各的转圈；6 个各写各的「锁滚动 + ESC」；`inputCls` 同一串样式存在**三份**；
全站 5 个弹层**一个焦点陷阱都没有**。

## 三层结构

| 层 | 位置 | 放什么 |
|---|---|---|
| 令牌 | `app/globals.css` + `tailwind.config.js` | 颜色、字阶、墨色、遮罩。**唯一事实源** |
| 原语 | `components/ui/*.tsx` | 无业务的通用组件，一组件一文件 |
| 行为 | `lib/ui/hooks.ts` | 被反复解决过的交互逻辑 |
| 变体 | `lib/ui/variants.ts` | cva 变体表（放 `.ts` 才能被单测加载） |

调用一律从 barrel 进：`import { Button, Badge } from "@/components/ui"`，不要深链到具体文件。

## 现有组件

`Button`（ink / soft / ghost / quiet × xs / sm / md / lg）· `Badge`（七族 tone × 四档）·
`Banner` · `Field` + `Input` + `Textarea` + `Select` · `Segmented` · `Modal` · `Popover` ·
`Spinner` · `EmptyState` · `AnimateNumber` · `AnimatedStat`

Hooks：`useBodyScrollLock` · `useEscapeKey` · `useFocusTrap` · `useClickOutside` ·
`useAnchoredPosition` · `useClipboard` · `useAsyncAction`

**活文档在 `/design`**（需要管理员）。那一页的组件就是产品里真实运行的那一个、用的是同一份
CSS，所以它不会说谎——改了组件库，那一页立刻跟着变。

## 加一个新组件

1. 建 `components/ui/<name>.tsx`（**一个文件，不建目录**——不发 npm 包、不写 story，
   拆成目录只是徒增路径长度。shadcn/ui 也是一组件一文件）。
2. 变体（variant / size / tone）写进 `lib/ui/variants.ts`，用 cva。
3. 在 `components/ui/index.ts` 登记导出。**漏登记会被契约测试判红**。
4. 在 `/design` 加一段展示：所有变体 × 尺寸 × 禁用/加载/出错态都要能看见。
5. 跑 `node --test tests/design-system-contract.test.js`。

## 四条硬规矩

1. **组件库内禁止出现 hex 色值。** 颜色一律走 `--tone-*` / `--ink-*` 变量，或复用
   `.btn-*` / `.field-soft` / `.surface` 这些既有类。要加新颜色 → 先在 `globals.css` 定义
   变量（明暗各一套）、在 `tailwind.config.js` 登记，再用语义类名引用。契约测试会扫。
2. **变体表只加尺寸，不重抄颜色。** 靠 Tailwind 的层序（components 在 utilities 之前）让
   padding 工具类覆盖 CSS 类自带的值，颜色则原样继承。这样颜色永远只有一份定义。
3. **可访问性做进原语，不靠调用方记得。** Modal 默认带焦点陷阱 + `role="dialog"` +
   `aria-modal` + 锁滚动 + ESC；`Segmented` 的 `ariaLabel` 是**必填 prop**，从类型上堵死漏写。
   凡是「靠人记得写」的 aria，迟早会漏——改造前 4 处分段控件有 3 处漏了组标签。
4. **失败绝不静默。** 见 CLAUDE.md「点击反馈分档」：重提交用 `SaveToast`，就地操作用
   `ActionToast`，取数用按钮内 pending + 骨架屏。`useAsyncAction` 提供 pending/success/error
   三态，不要自己 try/catch 完就算了。

## 废弃一个组件

**搬到 `components/ui/deprecated/`，不要直接删**（做法学自 GitHub Primer 的 `src/deprecated/`）。
直接删会把「组件库改版」变成「全站必须同一天跟着改完」，几个人的团队做不到，
结果就是没人敢改组件库。详细步骤见 `components/ui/deprecated/README.md`。

## 门禁

`tests/design-system-contract.test.js`（13 条）。用「读源码 + 加载变体表」而不是引
`eslint-plugin-tailwindcss`：那个插件会对全站存量的硬编码色值一起报警，等于装了个永远红的灯；
契约测试能**精确限定只管 `components/ui` 与 `lib/ui`**，且零新依赖。

刻意**没有**引入的东西，以及为什么：

| 没引 | 理由 |
|---|---|
| Storybook | 要单独跑进程、单独配构建。Primer 用它是为了支撑 30+ 人和多主题多色盲对齐，这个规模不值 |
| Playwright 截图回归 | 设计还在打磨期，快照会天天失效，维护成本远超收益。等设计稳定再说 |
| Style Dictionary 令牌流水线 | 那是为了同时输出 iOS / Android / Figma 多格式。这里只有 Web，CSS 变量直接就是事实源 |
| CSS-in-JS（Ant Design 那套） | 解决的是「同页多主题」和 SSR 不闪，代价是 bundle 和 hydration 复杂度。Tailwind + CSS 变量已经够 |
| 每组件一个目录 | 那是为了对齐 Figma 组件库和内部文档站，规模不到，只会让 import 路径更长 |

## 存量迁移的节奏

**新代码必须用组件库；老代码碰到再换。** 不做一次性全站替换——`JobCard`(906 行)、
`InsightsAdminClient`(1466 行)、`CompanyInsightDrawer`(794 行) 这些巨型文件回归面太大。

已完成：247 个类串的颜色收成令牌（32 个文件，硬编码 1474 → 980）；6 处锁滚动 + ESC 收编；
3 份 `inputCls` 与 2 份 `CHIP_TONE` 合并成单一定义。

**迁移的判据是「能不能证明像素不变」**，不是「看起来差不多」。只有亮暗成对出现在同一个类串里
才替换成令牌；只有亮色没有 `dark:` 的地方一律跳过（换了会让它在暗色下变色，那是像素改动）。
真要统一那些「差一点点」的同类颜色，是一次**有意的视觉决定**，得单独提出来，不能顺手改掉。
