// ============================================================
// 招聘源 adapter / 抓取方式的白名单 + 录入校验（纯函数，可单测）
// adapter 值必须与 crawler/run.py 的 ADAPTERS 字典对齐，否则次日爬虫找不到 adapter。
// greenhouse / lever 是通用 ATS：只需填公司名 + ATS 地址，无需写代码。
// ============================================================

export interface AdapterOption {
  value: string;
  label: string;
  hint?: string;
}

export const SOURCE_ADAPTERS: AdapterOption[] = [
  { value: "apple", label: "Apple（全球官网）" },
  { value: "apple_cn", label: "Apple 中国" },
  { value: "baidu", label: "百度" },
  { value: "jd", label: "京东" },
  { value: "haier", label: "海尔" },
  { value: "siemens", label: "西门子" },
  { value: "tencent", label: "腾讯" },
  { value: "bytedance", label: "字节跳动" },
  { value: "bytedance_campus", label: "字节跳动 校招 / 实习" },
  { value: "nio_feishu", label: "蔚来（飞书系）" },
  { value: "xpeng_feishu", label: "小鹏（飞书系）" },
  { value: "horizon_feishu", label: "地平线（飞书系）" },
  { value: "xiaomi_feishu", label: "小米（飞书系）" },
  {
    value: "greenhouse",
    label: "Greenhouse（通用 ATS）",
    hint: "填公司名 + Greenhouse 招聘地址即可，无需写代码，次日爬虫自动抓",
  },
  {
    value: "lever",
    label: "Lever（通用 ATS）",
    hint: "填公司名 + Lever 招聘地址即可，无需写代码，次日爬虫自动抓",
  },
  {
    value: "ashby",
    label: "Ashby（通用 ATS）",
    hint: "填公司名 + Ashby 看板地址（api.ashbyhq.com/posting-api/job-board/{slug}），无需写代码",
  },
  {
    value: "smartrecruiters",
    label: "SmartRecruiters（通用 ATS · 外企主力）",
    hint: "填公司名 + 地址（api.smartrecruiters.com/v1/companies/{slug}/postings），在华跨国企业常用",
  },
  {
    value: "workday",
    label: "Workday（通用 ATS · 外企100强主力）",
    hint: "填公司名 + CXS 地址（{tenant}.wdN.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs），服务端按 location facet 过滤在华",
  },
  {
    value: "eightfold",
    label: "Eightfold（通用 ATS · 外企）",
    hint: "填公司名 + 接口地址（{tenant}.eightfold.ai/api/apply/v2/jobs?domain={domain}），服务端按 location 收窄在华",
  },
  {
    value: "oracle",
    label: "Oracle 招聘云（通用 ATS · 外企自建门户主力）",
    hint: "填公司名 + CE 接口（{tenant}.fa.{region}.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions?finder=findReqs;siteNumber=CX_xxxx），服务端按 locationsFacet 过滤在华",
  },
  {
    value: "moka",
    label: "Moka（通用 ATS · 本土）",
    hint: "填公司名 + Moka 招聘页地址（{公司}.mokahr.com / app.mokahr.com），浏览器拦截抓取",
  },
  {
    value: "beisen",
    label: "北森 Beisen（通用 ATS · 本土）",
    hint: "填公司名 + 北森招聘页地址（*.zhiye.com / *.italent.cn / 自有 careers 域名），浏览器拦截抓取",
  },
  {
    value: "feishu",
    label: "飞书招聘（通用 ATS · 本土，国内版 Workday）",
    hint: "填公司名 + 飞书招聘页地址（{公司}.jobs.feishu.cn/index/position 或 /{portal}），浏览器拦截 /api/v1/search/job/posts",
  },
  {
    value: "hotjob",
    label: "HotJob / wecruit（通用 ATS · 本土）",
    hint: "填公司名 + 招聘页地址（{子域}.hotjob.cn/{suiteKey}/pb/social.html｜school.html｜interns.html，社招/校招/实习三渠道各登记一条），直连 listPosition 接口，crawl_method 选 http",
  },
  {
    value: "company_spa",
    label: "企业官网 SPA（通用 · 本土长尾）",
    hint: "填公司名 + 官网招聘页地址，仅放行接口里带真实岗位链接的行，加源零代码",
  },
  {
    value: "amazon",
    label: "Amazon（自建 · 外企）",
    hint: "填公司名 + Amazon.jobs 搜索接口（www.amazon.jobs/en/search.json?normalized_country_code[]=CHN&result_limit=100）",
  },
  {
    value: "phenom",
    label: "Phenom（自建门户 · 外企）",
    hint: "填公司名 + Phenom 接口（{careers域名}/api/jobs，如 careers.amd.com/api/jobs），适配 AMD/L'Oréal 等自建门户",
  },
];

export const ADAPTER_VALUES: string[] = SOURCE_ADAPTERS.map((a) => a.value);

export const CRAWL_METHODS = ["http", "playwright", "manual"] as const;
export type CrawlMethod = (typeof CRAWL_METHODS)[number];

export function isValidAdapter(value: unknown): value is string {
  return typeof value === "string" && ADAPTER_VALUES.includes(value);
}

export function isValidCrawlMethod(value: unknown): value is CrawlMethod {
  return typeof value === "string" && (CRAWL_METHODS as readonly string[]).includes(value);
}

export interface SourceInput {
  company?: unknown;
  source_url?: unknown;
  adapter_name?: unknown;
  crawl_method?: unknown;
  notes?: unknown;
  enabled?: unknown;
}

export interface NormalizedSource {
  company: string;
  source_url: string;
  adapter_name: string;
  crawl_method: CrawlMethod;
  notes: string | null;
  enabled: boolean;
}

export interface SourceValidation {
  ok: boolean;
  errors: Record<string, string>;
  value?: NormalizedSource;
}

// 校验 + 归一化「添加源」表单输入。地址必须是 http(s) 链接，避免误填搜索/导航页时无法抓取。
export function validateSourceInput(input: SourceInput): SourceValidation {
  const errors: Record<string, string> = {};

  const company = typeof input.company === "string" ? input.company.trim() : "";
  if (!company) errors.company = "公司名不能为空";

  const sourceUrl = typeof input.source_url === "string" ? input.source_url.trim() : "";
  if (!sourceUrl) {
    errors.source_url = "招聘源地址不能为空";
  } else if (!/^https?:\/\/.+/i.test(sourceUrl)) {
    errors.source_url = "请填写完整的 http(s) 招聘源地址";
  }

  if (!isValidAdapter(input.adapter_name)) {
    errors.adapter_name = "请选择有效的 adapter";
  }

  const crawlMethod = input.crawl_method ?? "http";
  if (!isValidCrawlMethod(crawlMethod)) {
    errors.crawl_method = "抓取方式必须是 http / playwright / manual";
  }

  if (Object.keys(errors).length > 0) return { ok: false, errors };

  return {
    ok: true,
    errors,
    value: {
      company,
      source_url: sourceUrl,
      adapter_name: input.adapter_name as string,
      crawl_method: crawlMethod as CrawlMethod,
      notes:
        typeof input.notes === "string" && input.notes.trim()
          ? input.notes.trim()
          : null,
      enabled: input.enabled === false ? false : true,
    },
  };
}
