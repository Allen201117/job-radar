"use client";

import * as React from "react";
import {
  Accordion,
  AlertDialog,
  Badge,
  Banner,
  Button,
  EmptyState,
  Field,
  Input,
  Modal,
  Popover,
  DropdownMenu,
  Progress,
  Segmented,
  Select,
  Separator,
  Sheet,
  Spinner,
  Stepper,
  Switch,
  TabPanel,
  Tabs,
  Textarea,
  Tooltip,
  TONES,
  type Tone,
} from "@/components/ui";
import { useAsyncAction, useClipboard } from "@/lib/ui/hooks";
import { cn } from "@/lib/utils";
import { Compass, DotsThree, PencilSimple, Trash, Warning } from "@phosphor-icons/react";

/** 每个区块统一的外壳：标题 + 一句「什么时候用它」+ 展示区。 */
function Section({
  id,
  title,
  usage,
  children,
}: {
  id: string;
  title: string;
  usage: string;
  children: React.ReactNode;
}) {
  return (
    <section id={id} className="surface scroll-mt-24 p-5 sm:p-6">
      <h2 className="t-h2 ink-1">{title}</h2>
      <p className="t-body-sm ink-3 mt-1.5">{usage}</p>
      <div className="mt-5 space-y-5">{children}</div>
    </section>
  );
}

/** 一行样例：左边一句「这一行在演示什么」，右边是真实组件。 */
function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-2.5 sm:grid-cols-[9rem_1fr] sm:items-start sm:gap-4">
      <p className="t-caption pt-1.5">{label}</p>
      <div className="flex flex-wrap items-center gap-2.5">{children}</div>
    </div>
  );
}

const TONE_USAGE: Record<Tone, string> = {
  neutral: "不表态",
  sky: "社招 / 岗位聚合",
  green: "校招 / 已核实",
  amber: "实习 / 内容转陈",
  teal: "招聘动态",
  rose: "失败 / 风险",
  lilac: "职业洞察",
};

export default function DesignSystemClient() {
  const [modalOpen, setModalOpen] = React.useState(false);
  const [popoverOpen, setPopoverOpen] = React.useState(false);
  const popoverAnchor = React.useRef<HTMLButtonElement>(null);
  const [stage, setStage] = React.useState<"intern" | "campus" | "social">("campus");
  const [fieldValue, setFieldValue] = React.useState("");
  const { copied, copy } = useClipboard();
  const [sheetOpen, setSheetOpen] = React.useState(false);
  const [confirmOpen, setConfirmOpen] = React.useState(false);
  const [confirmPending, setConfirmPending] = React.useState(false);
  const [switchA, setSwitchA] = React.useState(true);
  const [switchB, setSwitchB] = React.useState(false);
  const [tab, setTab] = React.useState("today");
  const [progress, setProgress] = React.useState(38);

  // 演示三态用：随机成功 / 失败，好让人看清失败长什么样。
  const demoSubmit = React.useCallback(async () => {
    await new Promise((r) => setTimeout(r, 900));
    if (Math.random() < 0.35) throw new Error("演示用的失败");
    return true;
  }, []);
  const submit = useAsyncAction(demoSubmit);

  return (
    <div className="mt-6 space-y-5 pb-16">
      <Banner tone="sky" live={null}>
        <p className="t-body-sm">
          这一页的组件都从 <code className="t-caption">@/components/ui</code> 导入，和产品页面用的是同一份代码与同一份样式。
          新增组件请读 <code className="t-caption">components/ui/index.ts</code> 顶部的维护规矩。
        </p>
      </Banner>

      {/* ─────────────── 颜色令牌 ─────────────── */}
      <Section
        id="tones"
        title="语义色调（tone）"
        usage="七族颜色，各有固定含义。选颜色时按「这条信息是什么意思」选，不要按「哪个好看」选——颜色在这个产品里是有语义的。明暗两套值都在 globals.css 的 --tone-* 变量里，切主题自动跟随。"
      >
        <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-3">
          {TONES.map((tone) => (
            <div
              key={tone}
              className="flex items-center justify-between gap-3 rounded-xl border border-tone-neutral-border bg-tone-neutral-bg px-3 py-2.5"
            >
              <Badge tone={tone} size="sm">
                {tone}
              </Badge>
              <span className="t-caption">{TONE_USAGE[tone]}</span>
            </div>
          ))}
        </div>
      </Section>

      {/* ─────────────── 排版 ─────────────── */}
      <Section
        id="type"
        title="字阶与墨色"
        usage="字号、行高、字重、颜色四件事一次给全，调用方不要再各写各的。字重只用 400/500/600/700 四档，正文一律 400。"
      >
        <div className="space-y-2">
          <p className="t-display ink-1">t-display — 页面主标题</p>
          <p className="t-h1 ink-1">t-h1 — 一级标题</p>
          <p className="t-h2 ink-1">t-h2 — 区块标题</p>
          <p className="t-h3 ink-1">t-h3 — 卡片 / 组标题</p>
          <p className="t-body ink-2">t-body — 正文 15px，中文行高 1.7</p>
          <p className="t-body-sm ink-2">t-body-sm — 次正文 14px</p>
          <p className="t-label">t-label — 表单标签 / 按钮 13px</p>
          <p className="t-caption">t-caption — 元信息 12px</p>
          <p className="t-micro">t-micro — 徽标 11px</p>
          <p className="t-num ink-1">t-num — 12,847 等宽数字，用于要对齐扫读的计数</p>
        </div>
        <div className="grid gap-2 sm:grid-cols-4">
          {(["ink-1", "ink-2", "ink-3", "ink-4"] as const).map((ink) => (
            <div key={ink} className="surface-soft p-3">
              <p className={cn("t-body-sm", ink)}>{ink}</p>
              <p className="t-caption mt-0.5">
                {ink === "ink-1"
                  ? "主文本"
                  : ink === "ink-2"
                    ? "正文"
                    : ink === "ink-3"
                      ? "标签 / 元信息"
                      : "占位 / 禁用"}
              </p>
            </div>
          ))}
        </div>
      </Section>

      {/* ─────────────── 按钮 ─────────────── */}
      <Section
        id="button"
        title="按钮 Button"
        usage="一屏只该有一个 ink 主按钮。需要 <Link> 长成按钮样子时，别硬套本组件，直接用 buttonVariants({ variant, size }) 拿类名。"
      >
        <Row label="variant 四种">
          <Button variant="ink">主操作</Button>
          <Button variant="soft">次操作</Button>
          <Button variant="ghost">描边次操作</Button>
          <Button variant="quiet">退让操作</Button>
        </Row>
        <Row label="size 四档">
          <Button size="xs">xs</Button>
          <Button size="sm">sm</Button>
          <Button size="md">md（默认）</Button>
          <Button size="lg">lg</Button>
        </Row>
        <Row label="状态">
          <Button loading>提交中</Button>
          <Button disabled>已禁用</Button>
          <Button variant="soft" leading={<Compass size={15} weight="bold" />}>
            带图标
          </Button>
        </Row>
        <Row label="三态演示">
          <Button
            loading={submit.pending}
            onClick={() => {
              void submit.run();
            }}
          >
            {submit.status === "success" ? "成功了" : submit.pending ? "提交中" : "点我提交"}
          </Button>
          {submit.status === "error" ? (
            <Banner tone="rose" size="sm" live="assertive">
              {submit.error?.message ?? "失败了"}
            </Banner>
          ) : null}
          <Button variant="quiet" onClick={submit.reset}>
            重置
          </Button>
        </Row>
      </Section>

      {/* ─────────────── 徽标 ─────────────── */}
      <Section
        id="badge"
        title="徽标 Badge"
        usage="状态与维度小标签。tone 决定语义，size 决定大小；11px（xs）是全站最常用的一档。"
      >
        <Row label="全部 tone">
          {TONES.map((tone) => (
            <Badge key={tone} tone={tone}>
              {TONE_USAGE[tone]}
            </Badge>
          ))}
        </Row>
        <Row label="size 四档">
          <Badge tone="sky" size="xs">
            xs 11px
          </Badge>
          <Badge tone="sky" size="sm">
            sm 12px
          </Badge>
          <Badge tone="sky" size="md">
            md 13px
          </Badge>
          <Badge tone="sky" size="lg">
            lg
          </Badge>
        </Row>
      </Section>

      {/* ─────────────── 提示条 ─────────────── */}
      <Section
        id="banner"
        title="提示条 Banner"
        usage="整块说明：表单报错、能力不可用。报错传 live=&quot;assertive&quot;（读屏立刻播报），一般提示用默认的 polite。"
      >
        <Banner tone="rose" icon={<Warning size={16} weight="bold" />} live="assertive">
          保存失败，已还原成修改前的内容，请重试。
        </Banner>
        <Banner tone="amber">这家公司的洞察还在核验中，先给你看已确认的部分。</Banner>
        <Banner tone="sky" size="sm">
          小号提示条，用在卡片内部。
        </Banner>
      </Section>

      {/* ─────────────── 表单 ─────────────── */}
      <Section
        id="field"
        title="表单 Field / Input / Textarea / Select"
        usage="Field 负责把标签、说明、错误用 aria 串到控件上——读屏用户才听得到「这一栏为什么红了」。外观仍由 .field-soft 提供。"
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="公司名" hint="填官方全称，别填简称" required>
            <Input
              placeholder="例：字节跳动"
              value={fieldValue}
              onChange={(e) => setFieldValue(e.target.value)}
            />
          </Field>
          <Field label="出错的样子" error="这个网址打不开，检查一下有没有漏掉 https://">
            <Input defaultValue="zhaopin.example" />
          </Field>
          <Field label="下拉选择">
            <Select defaultValue="campus">
              <option value="intern">实习</option>
              <option value="campus">校招</option>
              <option value="social">社招</option>
            </Select>
          </Field>
          <Field label="多行文本" hint="Textarea 与 Input 同一套外观">
            <Textarea rows={3} placeholder="说点什么" />
          </Field>
        </div>
      </Section>

      {/* ─────────────── 分段控件 ─────────────── */}
      <Section
        id="segmented"
        title="分段控件 Segmented"
        usage="互斥选项组。ariaLabel 是必填 prop——从类型上堵死「读屏听到一堆孤立按钮、不知道这组在选什么」。"
      >
        <Row label="求职阶段">
          <Segmented
            ariaLabel="求职阶段"
            value={stage}
            onChange={setStage}
            options={[
              { value: "intern", label: "实习" },
              { value: "campus", label: "校招" },
              { value: "social", label: "社招" },
            ]}
          />
        </Row>
        <Row label="含禁用项">
          <Segmented
            ariaLabel="求职范围"
            value="domestic"
            onChange={() => {}}
            size="xs"
            options={[
              { value: "domestic", label: "国内" },
              { value: "overseas", label: "海外（未开通）", disabled: true },
            ]}
          />
        </Row>
      </Section>

      {/* ─────────────── 弹层 ─────────────── */}
      <Section
        id="overlay"
        title="弹层 Modal / Popover"
        usage="Modal 默认带焦点陷阱、ESC 关闭、锁滚动、role=dialog——改造前全站 5 个弹层一个焦点陷阱都没有。Popover 一定要 portal 到 body，绝不能 absolute 定位在滚动容器里。"
      >
        <Row label="试一下">
          <Button variant="soft" onClick={() => setModalOpen(true)}>
            打开 Modal
          </Button>
          <Button
            ref={popoverAnchor}
            variant="soft"
            onClick={() => setPopoverOpen((v) => !v)}
          >
            打开 Popover
          </Button>
          <Button variant="quiet" onClick={() => void copy("https://example.com")}>
            {copied ? "已复制" : "试试 useClipboard"}
          </Button>
        </Row>
        <p className="t-caption">
          Modal 打开后按 Tab 试试：焦点会锁在弹层里循环，按 ESC 关闭后焦点自动回到刚才那颗按钮上。
        </p>

        <Modal
          open={modalOpen}
          onClose={() => setModalOpen(false)}
          ariaLabel="组件库示例弹窗"
          className="surface w-full max-w-md p-6"
        >
          <h3 className="t-h3 ink-1">这是一个 Modal</h3>
          <p className="t-body-sm ink-2 mt-2">
            按 Tab 会在这两颗按钮之间循环，不会跑到背后的页面上去。按 ESC 或点遮罩关闭。
          </p>
          <div className="mt-5 flex justify-end gap-2">
            <Button variant="quiet" size="sm" onClick={() => setModalOpen(false)}>
              取消
            </Button>
            <Button size="sm" onClick={() => setModalOpen(false)}>
              知道了
            </Button>
          </div>
        </Modal>

        <Popover
          open={popoverOpen}
          onClose={() => setPopoverOpen(false)}
          anchorRef={popoverAnchor}
          ariaLabel="组件库示例浮层"
          className="surface w-56 p-3"
        >
          <p className="t-body-sm ink-2">
            滚一下页面：它会跟着触发按钮走。再点一次那颗按钮能关掉（触发按钮被豁免了「点外部关闭」）。
          </p>
        </Popover>
      </Section>


      {/* ─────────────── 动效基座 ─────────────── */}
      <Section
        id="motion"
        title="动效基座（弹簧曲线 + 按压反馈）"
        usage="标杆是 iPhone。iOS 动效有质感的核心不是「时长调得好」，是用弹簧而不是贝塞尔——加速减速符合物理直觉。下面四条曲线是按 SwiftUI 的 spring(response:dampingFraction:) 方程解出来的，不是抄的。"
      >
        <Row label="按住看看">
          <button className="press-feedback btn-ink-sm px-5 py-2.5">按住我（scale 0.97）</button>
          <button className="press-feedback-subtle surface-soft rounded-xl px-5 py-3">
            整卡可点时用更轻的一档（0.99）
          </button>
        </Row>
        <div className="space-y-2">
          {(
            [
              ["smooth", "状态切换 / 淡入淡出", "不过冲——回弹会让「变了个色」显得轻浮"],
              ["snappy", "开关 / 弹层 / 折叠", "过冲 0.6%，干脆，最常用"],
              ["bouncy", "数字变化 / 正反馈", "过冲 8.3%，传达「成了」的愉悦"],
              ["press", "按压松手回弹", "最短，只用于 :active 之后"],
            ] as const
          ).map(([name, use, note]) => (
            <div key={name} className="surface-soft flex items-center gap-3 p-3">
              <code className="t-caption w-20 shrink-0">--spring-{name}</code>
              <span className="t-body-sm ink-2 w-40 shrink-0">{use}</span>
              <span className="t-caption min-w-0">{note}</span>
            </div>
          ))}
        </div>
        <p className="t-caption">
          调手感改 <code>scripts/gen-spring-easing.py</code> 里的档位参数跑一次，把输出粘回 globals.css。
        </p>
      </Section>

      {/* ─────────────── 开关 ─────────────── */}
      <Section
        id="switch"
        title="开关 Switch"
        usage="按住滑块看细节：它会横向拉长再回圆——这是 iOS 开关最标志性的一处，只做位移不做形变就没有「被推着走」的感觉。"
      >
        <Row label="两档尺寸">
          <Switch checked={switchA} onChange={setSwitchA} ariaLabel="示例开关大" />
          <Switch checked={switchB} onChange={setSwitchB} ariaLabel="示例开关小" size="sm" />
        </Row>
        <Row label="忙碌 / 禁用">
          <Switch checked busy onChange={() => {}} ariaLabel="正在保存" />
          <Switch checked={false} disabled onChange={() => {}} ariaLabel="不可用" />
        </Row>
      </Section>

      {/* ─────────────── 标签页与折叠 ─────────────── */}
      <Section
        id="tabs"
        title="标签页 Tabs / 折叠面板 Accordion"
        usage="Tabs 的选中态用下划线不用实心块——一屏只允许一个墨色实心块，那是主操作的信号。方向键可以在 tab 间移动。"
      >
        <Tabs
          ariaLabel="示例视图切换"
          value={tab}
          onChange={setTab}
          items={[
            { value: "today", label: "今日", badge: 12 },
            { value: "jobs", label: "岗位库", badge: 348 },
            { value: "campus", label: "校招" },
            { value: "off", label: "已停用", disabled: true },
          ]}
        >
          <TabPanel value="today" className="t-body-sm ink-2 pt-4">
            当前是「今日」面板。用左右方向键试试切换。
          </TabPanel>
          <TabPanel value="jobs" className="t-body-sm ink-2 pt-4">
            当前是「岗位库」面板。
          </TabPanel>
          <TabPanel value="campus" className="t-body-sm ink-2 pt-4">
            当前是「校招」面板。
          </TabPanel>
        </Tabs>
        <Accordion
          items={[
            {
              value: "a",
              title: "这家公司的招聘节奏",
              meta: <Badge tone="teal" size="xs">招聘动态</Badge>,
              content: "展开时高度是弹簧过渡的，不是直接跳出来。",
            },
            { value: "b", title: "薪酬与强度", content: "一次只能开一个（mode=single）。" },
          ]}
        />
      </Section>

      {/* ─────────────── 浮层 ─────────────── */}
      <Section
        id="overlay2"
        title="提示 Tooltip / 菜单 DropdownMenu / 抽屉 Sheet / 确认 AlertDialog"
        usage="Sheet 是移动端主力弹层，可以按住把手往下拖——松手时按「距离 + 速度」判定去留，快速下甩即使没拖多远也会关。"
      >
        <Row label="试一下">
          <Tooltip content="这条岗位最近一次被确认在招是 2 天前">
            <button className="press-feedback btn-soft">悬停我看提示</button>
          </Tooltip>
          <DropdownMenu
            ariaLabel="示例操作菜单"
            trigger={
              <button
                aria-label="更多操作"
                className="press-feedback btn-soft grid size-9 place-items-center p-0"
              >
                <DotsThree size={18} weight="bold" />
              </button>
            }
            items={[
              { key: "e", label: "编辑", icon: <PencilSimple size={15} /> },
              { key: "d", label: "删除", icon: <Trash size={15} />, destructive: true },
            ]}
          />
          <Button variant="soft" size="sm" onClick={() => setSheetOpen(true)}>
            打开底部抽屉
          </Button>
          <Button variant="soft" size="sm" onClick={() => setConfirmOpen(true)}>
            打开确认框
          </Button>
        </Row>
        <p className="t-caption">
          确认框里「取消」是默认焦点（破坏性操作时）——连按回车不会误删，想删的人多按一次 Tab。
        </p>

        <Sheet open={sheetOpen} onClose={() => setSheetOpen(false)} ariaLabel="示例底部抽屉">
          <h3 className="t-h3 ink-1">按住上面的把手往下拖</h3>
          <p className="t-body-sm ink-2 mt-2">
            往上拖会有橡皮筋阻尼（拉得动但明显在抗拒）。内容没滚到顶时不会接管拖拽——
            否则你想滚列表却把整个面板拖走了。
          </p>
          <div className="mt-4 space-y-2">
            {Array.from({ length: 8 }).map((_, i) => (
              <div key={i} className="surface-soft t-body-sm p-3">
                列表项 {i + 1}
              </div>
            ))}
          </div>
        </Sheet>

        <AlertDialog
          open={confirmOpen}
          destructive
          pending={confirmPending}
          title="确定要下架这条洞察吗"
          description="下架后用户不再看得到它。这个操作可以在后台恢复，但已经看过的用户不会收到更正。"
          confirmLabel="下架"
          onCancel={() => setConfirmOpen(false)}
          onConfirm={async () => {
            setConfirmPending(true);
            await new Promise((r) => setTimeout(r, 900));
            setConfirmPending(false);
            setConfirmOpen(false);
          }}
        />
      </Section>

      {/* ─────────────── 进度与步骤 ─────────────── */}
      <Section
        id="progress"
        title="进度 Progress / 步骤条 Stepper / 分隔线 Separator"
        usage="进度条只在能给出真实百分比时用。给不出却硬放一条，走到 90% 卡住比转圈更伤信任——不确定时长传 value=null 走扫掠态。"
      >
        <Row label="确定 / 不确定">
          <div className="w-48 space-y-2">
            <Progress value={progress} ariaLabel="简历解析进度" />
            <Progress value={null} ariaLabel="正在刷新公司库" size="sm" />
          </div>
          <Button
            variant="quiet"
            size="xs"
            onClick={() => setProgress((v) => (v >= 100 ? 0 : v + 22))}
          >
            推进一格
          </Button>
        </Row>
        <Separator />
        <Row label="投递进展">
          <Stepper
            ariaLabel="投递进展"
            current={2}
            className="w-full max-w-md"
            steps={[
              { key: "1", label: "已投递", meta: "8/21" },
              { key: "2", label: "笔试", meta: "8/26" },
              { key: "3", label: "面试" },
              { key: "4", label: "offer" },
            ]}
          />
        </Row>
      </Section>

      {/* ─────────────── 状态 ─────────────── */}
      <Section
        id="state"
        title="加载与空状态"
        usage="空状态必须说清「为什么空」和「下一步做什么」，只写「暂无数据」等于把用户丢在原地。"
      >
        <Row label="Spinner">
          <Spinner />
          <Spinner size={24} />
          <span className="t-caption">默认带读屏播报，装饰性场景传 label={"{null}"} 关掉</span>
        </Row>
        <div className="surface-soft">
          <EmptyState
            icon={<Compass size={28} weight="light" />}
            title="还没有值得投的岗位"
            description="在「今日」里看到合适的岗位时点一下「值得投」，它就会出现在这里，方便你集中投递。"
            action={<Button size="sm">去今日看看</Button>}
          />
        </div>
      </Section>
    </div>
  );
}
