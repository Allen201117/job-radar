"use client";

import * as React from "react";
import {
  Badge,
  Banner,
  Button,
  EmptyState,
  Field,
  Input,
  Modal,
  Popover,
  Segmented,
  Select,
  Spinner,
  Textarea,
  TONES,
  type Tone,
} from "@/components/ui";
import { useAsyncAction, useClipboard } from "@/lib/ui/hooks";
import { cn } from "@/lib/utils";
import { Compass, Warning } from "@phosphor-icons/react";

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
