const test = require("node:test");
const assert = require("node:assert");
const {
  recruitmentCategory,
  hasExplicitRecruitmentType,
} = require("../lib/china-keyword-expansion");

test("recruitmentCategory 三桶穷尽分类（实习 / 校招 / 社招）", () => {
  // 实习
  assert.equal(recruitmentCategory({ job_type: "暑期实习" }), "实习");
  assert.equal(recruitmentCategory({ job_type: "日常实习" }), "实习");
  assert.equal(recruitmentCategory({ title: "数据分析实习生" }), "实习");

  // 校招（含管培生 / 留学生专项 / 应届，过去会漏桶）
  assert.equal(recruitmentCategory({ job_type: "校招" }), "校招");
  assert.equal(recruitmentCategory({ job_type: "管培生" }), "校招");
  assert.equal(recruitmentCategory({ job_type: "留学生专项" }), "校招");
  assert.equal(recruitmentCategory({ title: "2025届校园招聘 算法工程师" }), "校招");
  assert.equal(recruitmentCategory({ title: "应届生 后端开发" }), "校招");

  // 社招（含研究岗 / 全职 / 无信号，过去会漏桶）
  assert.equal(recruitmentCategory({ job_type: "研究岗" }), "社招");
  assert.equal(recruitmentCategory({ job_type: "全职", title: "高级工程师" }), "社招");
  assert.equal(recruitmentCategory({ job_type: "社招" }), "社招");
  assert.equal(recruitmentCategory({ title: "产品经理（5年经验）" }), "社招");
  assert.equal(recruitmentCategory({}), "社招");
});

test("recruitmentCategory 实习优先于校园字样", () => {
  assert.equal(recruitmentCategory({ title: "2025 暑期实习 · 校园招聘" }), "实习");
});

test("英文 intern/graduate 词边界：internal/international/internet/undergraduate 不误判（治全职岗被标实习/校招）", () => {
  // 本次线上真因：Intel 全职高级工程师 JD 含 "internal" 被标实习
  assert.equal(
    recruitmentCategory({ title: "Senior Gen AI Software Solutions Engineer", summary: "Works with internal engineering teams and external partners to deliver AI." }),
    "社招",
  );
  assert.equal(recruitmentCategory({ title: "Business Manager", summary: "Lead international expansion." }), "社招");
  assert.equal(recruitmentCategory({ title: "Backend Engineer", summary: "Build internet-scale services." }), "社招");
  assert.equal(recruitmentCategory({ title: "Software Engineer", summary: "Undergraduate degree required, 5 yrs experience." }), "社招");
  // 真·实习/校招仍判得出（不过度修正）
  assert.equal(recruitmentCategory({ title: "Software Engineering Intern" }), "实习");
  assert.equal(recruitmentCategory({ title: "Summer Internship Program 2026" }), "实习");
  assert.equal(recruitmentCategory({ title: "Research Interns wanted" }), "实习");
  assert.equal(recruitmentCategory({ title: "Software Engineer", summary: "Open to new grads and recent graduates." }), "校招");
});

test("P1-D: url 拼音路径 + 源名信号补全校招/实习（治 59% 空 job_type 误堆社招）", () => {
  // jd_url 拼音路径（/shixi /xiaozhao），标题本身无招聘类型字样
  assert.equal(recruitmentCategory({ title: "研发工程师", jd_url: "https://x.com/zp/shixi/123" }), "实习");
  assert.equal(recruitmentCategory({ title: "电气工程师", jd_url: "https://x.com/zp/xiaozhao/9" }), "校招");
  // jd_url 英文路径（已支持，回归确认）
  assert.equal(recruitmentCategory({ title: "软件工程师", jd_url: "https://x.com/campus/job/1" }), "校招");
  // 源/公司名显式标注（如库里的"华润电力 CR Power 校招"）
  assert.equal(recruitmentCategory({ title: "电气工程师", company: "华润电力 CR Power 校招" }), "校招");
  // 回归：普通公司/岗位不被误判
  assert.equal(recruitmentCategory({ title: "后端开发", company: "字节跳动" }), "社招");
});

test("硬门：明确要求 ≥2 年经验 → 强制社招（治『社招要3年经验却被标校招』）", () => {
  // ① summary/JD 正文里的『毕业生/应届/graduate』字样污染 → 被经验门纠正回社招
  assert.equal(
    recruitmentCategory({
      title: "高级算法工程师",
      summary: "3年以上相关工作经验，985/211高校毕业生优先，硕士学历。",
    }),
    "社招",
  );
  assert.equal(
    recruitmentCategory({
      title: "智慧校园解决方案专家",
      summary: "本科及以上学历，5年以上教育行业、智慧校园 ToB/ToG 工作经验。",
    }),
    "社招",
  );
  assert.equal(
    recruitmentCategory({
      title: "Software Engineer",
      summary: "Graduate degree preferred. 5+ years of experience building services.",
    }),
    "社招",
  );
  // ② 源 job_type 本身把资深岗错标成校招 → 被经验门纠正回社招
  assert.equal(
    recruitmentCategory({
      title: "光刻工艺资深/主任工程师",
      job_type: "校招",
      summary: "负责光刻工艺研发，8年以上半导体制造经验。",
    }),
    "社招",
  );
  // 数字范围写法（3-5年）下限 ≥2 也纠正
  assert.equal(
    recruitmentCategory({ title: "产品经理", summary: "3-5年经验，应届生亦可培养。" }),
    "社招",
  );
});

test("硬门不过度修正：真实校招/实习 + 无 ≥2 年经验硬要求 → 保持原判", () => {
  // 真校招（应届、无年限要求）保持校招
  assert.equal(
    recruitmentCategory({ title: "2025届校园招聘 算法工程师", summary: "面向应届毕业生。" }),
    "校招",
  );
  // “毕业2年内 / 0-2年 / 1-3年” 下限 <2，不触发硬门（不把校招误纠成社招）
  assert.equal(
    recruitmentCategory({ title: "管培生", summary: "面向毕业2年内的应届及往届生。" }),
    "校招",
  );
  assert.equal(
    recruitmentCategory({ title: "校园招聘 后端", summary: "0-2年经验，欢迎应届。" }),
    "校招",
  );
  // 真实习保持实习（哪怕正文提到团队多年经验）
  assert.equal(
    recruitmentCategory({ title: "算法实习生", summary: "在校生，随团队3年+资深工程师学习。" }),
    "实习",
  );
});

test("弱词不再误判校招：毕业生/graduate/校园 在正文里 → 保持社招（精度优先）", () => {
  // "985毕业生优先" 是社招常见语，不该判校招
  assert.equal(
    recruitmentCategory({ title: "后端开发工程师", summary: "重点院校毕业生优先，扎实的算法功底。" }),
    "社招",
  );
  // "graduate degree"=硕士学历，不是校招
  assert.equal(
    recruitmentCategory({ title: "Data Scientist", summary: "Graduate degree in CS or related field." }),
    "社招",
  );
  // "智慧校园" 产品里的"校园" 不是校招
  assert.equal(
    recruitmentCategory({ title: "解决方案经理", summary: "负责智慧校园产品在高校的推广落地。" }),
    "社招",
  );
});

test("ATS 门户路径对称：/social 门户里正文写『应届亦可』仍判社招（治 beisen ~3000 岗误判）", () => {
  // 北森 /social 门户 = 社会招聘，正文的"应届亦可"不该把它翻成校招
  assert.equal(
    recruitmentCategory({
      title: "工艺技术员",
      jd_url: "https://hoshine.zhiye.com/social/detail?jobAdId=abc",
      summary: "负责生产工艺控制；本科及以上，应届亦可。",
    }),
    "社招",
  );
  // /campus 门户仍判校招（对称，回归）
  assert.equal(
    recruitmentCategory({ title: "电修管理员", jd_url: "https://xiangyu.zhiye.com/campus/detail?jobAdId=x" }),
    "校招",
  );
  // /experienced 门户判社招
  assert.equal(
    recruitmentCategory({ title: "算法工程师", jd_url: "https://jobs.bytedance.com/experienced/position/1/detail" }),
    "社招",
  );
});

test("年限只在「经验」语境里才算硬门槛——成长路径/派驻时长不是经验要求", () => {
  // 校招 JD 高频写法：管培生的晋升周期、培养周期、外派时长。旧实现拿无上下文的
  // /(\d{1,2})[-~至到](\d{1,2})年/ 匹配，把这些当成 ≥2 年经验 → 明确的校招岗被层2 判成社招。
  const campusUrl = "https://app.mokahr.com/campus-recruitment/acme/1#/job/z";
  for (const summary of [
    "管培生培养计划，2~3年晋升为管理者，带团队！任职要求：应届统招硕士学历。",
    "通过 2-3 年的配套加速培养机制，成长为具有全局思维的新生代管理者。",
    "选拔绩优、高潜的校招生进入现场管理发展通道，优秀者 2-3 年发展成为一线主管。",
    "本科及以上学历；需要派往墨西哥工作 3-5 年。",
  ]) {
    assert.equal(recruitmentCategory({ title: "销售管培生", jd_url: campusUrl, summary }), "校招", summary);
  }
  // 反向保住原意图：真的写「N 年经验」仍然强制社招（层2 的存在理由）
  assert.equal(
    recruitmentCategory({
      title: "硬件工程师",
      jd_url: campusUrl,
      summary: "有 2 年以上在实验室硬件或软件设计开发经验，有产品成功上市者优先。",
    }),
    "社招",
  );
  assert.equal(
    recruitmentCategory({ title: "结构工程师", summary: "任职要求：5 年以上相关工作经验。" }),
    "社招",
  );
});

test("门户令牌带 -/_ 后缀也要认（moka /campus-recruitment 漏判 31.6% 的真因）", () => {
  // moka 的门户路径是 /campus-recruitment/ 与 /campus_apply/，令牌后跟的是 - 或 _ 而非 /。
  // 旧正则要求令牌后紧跟 / ? $ → 对 moka 整个层4 失效，校招岗被层7 兜底成「社招」，
  // 2026-08-07 实测该门户 5525 个在招岗里 31.6% 中招、进不了校招专区。
  for (const url of [
    "https://app.mokahr.com/campus-recruitment/catlhr/148948#/job/0f6a4c5a",
    "https://app.mokahr.com/campus_apply/feiyu/142123#/job/cb2832de",
    "https://app-tc.mokahr.com/campus-recruitment/xcmg/148091#/job/64e1fa14",
  ]) {
    assert.equal(recruitmentCategory({ title: "人力资源主管", jd_url: url }), "校招", url);
  }
  // 对称：社招门户后缀同样要认
  assert.equal(
    recruitmentCategory({ title: "工艺工程师", jd_url: "https://app.mokahr.com/social-recruitment/acme/123#/job/x" }),
    "社招",
  );
  // ⚠️ 安全边界：层2（≥2 年经验强制社招）优先级高于本层，放宽门户令牌不能让资深岗混进校招
  assert.equal(
    recruitmentCategory({
      title: "资深结构工程师",
      jd_url: "https://app.mokahr.com/campus-recruitment/acme/1#/job/y",
      summary: "任职要求：5 年以上结构设计经验。",
    }),
    "社招",
  );
});

test("信任来源自报 job_type：不被正文杂词污染", () => {
  // 源渠道=社会招聘，正文顺带提"可转正实习/毕业生" → 仍社招（信任源头，实习标记只认标题/url）
  assert.equal(
    recruitmentCategory({
      title: "供应链经理",
      job_type: "社会招聘",
      summary: "团队接收优秀应届毕业生与实习生，本岗面向社会招聘。",
    }),
    "社招",
  );
  // 源渠道=校招 且无经验硬要求 → 尊重来源判校招
  assert.equal(recruitmentCategory({ title: "研发工程师", job_type: "校招" }), "校招");
  // job_type 是"职能类别"（非招聘类型）→ 不误当类型，走后续信号/兜底
  assert.equal(recruitmentCategory({ title: "算法工程师", job_type: "研发" }), "社招");
});

test("hasExplicitRecruitmentType：≥2 年经验硬要求算『明确类型』（让校招筛选能真正踢掉它）", () => {
  // 空 job_type + 正文含毕业生字样，但要 3 年经验 → 视为明确（社招），筛校招时应被淘汰
  assert.equal(
    hasExplicitRecruitmentType({ title: "数据工程师", summary: "3年以上经验，重点院校毕业生优先。" }),
    true,
  );
  // 纯信息不足（无类型、无年限）仍是『类型未知』→ 筛选时放行降级，不误杀
  assert.equal(hasExplicitRecruitmentType({ title: "后端开发工程师" }), false);
});

test("wecruit/hotjob 查询参数 postType 是门户自报渠道：campus→校招、intern→实习、society→社招", () => {
  const base = "https://career.honor.com/SU60eea919bef57c1023f6fe78/pb/posDetail.html?postId=6a83c53a&postType=";
  assert.strictEqual(recruitmentCategory({ title: "大模型算法工程师", job_type: "研发类", jd_url: base + "campus" }), "校招");
  assert.strictEqual(recruitmentCategory({ title: "大模型算法工程师", job_type: "研发类", jd_url: base + "intern" }), "实习");
  assert.strictEqual(recruitmentCategory({ title: "大模型算法工程师", job_type: "研发类", jd_url: base + "society" }), "社招");
  // society 不做对称规则：社招门户里标题写明届别的岗仍按标题判校招（宁可信标题，也别把改动做成双向）
  assert.strictEqual(recruitmentCategory({ title: "硬件工程师（研发）-27届", jd_url: base + "society" }), "校招");
  // 层2 仍在前：校招门户里要 3 年经验的岗照样判社招（源头错标不放行）
  assert.strictEqual(recruitmentCategory({ title: "资深架构师", jd_url: base + "campus", experience: "3年以上工作经验" }), "社招");
  // 层1 仍在前：校招门户里标题写明实习的判实习
  assert.strictEqual(recruitmentCategory({ title: "算法实习生", jd_url: base + "campus" }), "实习");
});

test("老版 wt（hotjob）查询参数 recruitType 是平台渠道常量：1→校招、12→实习、2 不做对称规则", () => {
  // 老版 WinTalent 的详情页形如 …/mobweb/position/detail?brandCode=1&safe=Y&recruitType={rt}&postIdsAry={id}
  // rt 是**平台常量**（1=校招 / 2=社招 / 12=实习，见 crawler/adapters/wt.py 顶部注释），且值就在 jd_url 里。
  // 为什么 adapter 已经把标签拼进 job_type 了还要认 URL：job_type 是可变派生字段，
  // 一旦那步回退 / 源停抓 / 老代码写的旧值被 _PRESERVE_IF_EMPTY 保留，结论就静默退回「社招」。
  // 2026-09-18 live 全库实测：rt=1 的 5,373 个在招岗里仍有 83 行 job_type 不带标签。
  const wt = (rt) => `https://goodwe.hotjob.cn/wt/goodwe/mobweb/position/detail?brandCode=1&safe=Y&recruitType=${rt}&postIdsAry=908`;
  assert.strictEqual(recruitmentCategory({ title: "硬件助理工程师", job_type: "技术族", jd_url: wt(1) }), "校招");
  assert.strictEqual(recruitmentCategory({ title: "测试工程师", job_type: "管理族", jd_url: wt(12) }), "实习");

  // ⚠️ 1 后面必须有否定数字前瞻，否则 12（实习）会被前面的 1（校招）先吃掉。
  assert.notStrictEqual(recruitmentCategory({ title: "前台接待", job_type: "管理族", jd_url: wt(12) }), "校招");

  // 🚫 rt=2 刻意不判社招（与 postType=society 同一取舍）：社招本来就是层7 默认态，
  // 加了只会让层4 抢在层5 前面，把「社招板块里标题写明届别」的岗压回社招。
  // 2026-09-18 全库：rt=2 的 13,201 个在招岗里有 168 个靠标题被层5 判成校招、89 个被层1 判成实习。
  assert.strictEqual(recruitmentCategory({ title: "整车电控工程师（2027届）", job_type: "技术族", jd_url: wt(2) }), "校招");
  assert.strictEqual(recruitmentCategory({ title: "财务实习生", job_type: "职能类", jd_url: wt(2) }), "实习");
  assert.strictEqual(recruitmentCategory({ title: "客户经理", job_type: "营销族", jd_url: wt(2) }), "社招");

  // 层2（≥2 年经验）仍排在 rt=1 令牌之前：源头把资深岗挂进校招板块也不放行。
  // ⚠️ 年限必须写在「经验/经历/从业」语境里才会被层2 认出来（见 _minRequiredExperienceYears）。
  // wt 的 experience 列常是**裸值**「3-5年」「5年」，那种写法层2 认不出 —— 2026-09-18 全库实测：
  // rt=1/12 里 experience 整体是 ≥2 年的 34 行，层2 只兜住 17 行。这是既有口径，本次不动。
  assert.strictEqual(
    recruitmentCategory({ title: "结构工程师", job_type: "技术族", jd_url: wt(1), experience: "3年以上相关工作经验" }),
    "社招",
  );

  // 别的平台把 recruitType 写成非数字（美的 recruitType=social，线上 1,043 个在招岗）→ 一条都不许命中。
  assert.strictEqual(
    recruitmentCategory({
      title: "供应链管理岗",
      jd_url: "https://recruit.midea.com/recruitOut/ihr/social/jobApplication?positionId=8a5e&recruitType=social",
    }),
    "社招",
  );
});

test("渠道自报的实习（job_type / postType=intern / recruitType=12 / 路径）排在层2 经验门之后：租户挪用实习频道挂社招岗时不再误标实习", () => {
  // 2026-09-18 live 实锤：中伟新材料 / 浙江华友钴业把 wt 平台的 recruitType=12（门户上就叫「实习生招聘」）
  // 当蓝领社招频道用——电工 3 年 / 钳工 3-5 年 / 投资高级经理 8 年 / 仓管员「仓储经验 3 年以上」，
  // 标题自带「实习」的比例 1.6% / 0%（正常租户 60~100%）。此前渠道信号与标题同在层1，
  // 抢在层2 之前拍板，经验门对这条路径完全失效：rt=12 且 experience 写着 ≥2 年的 23 个在招岗全部被标成实习。
  const wt = (rt) => `https://cngr.hotjob.cn/wt/CNGR/mobweb/position/detail?brandCode=1&safe=Y&recruitType=${rt}&postIdsAry=468106`;
  const wecruit = "https://career.honor.com/SU60/pb/posDetail.html?postId=6a83&postType=intern";
  // 四种渠道信号 × 明确的 ≥2 年经验要求 → 社招
  assert.strictEqual(
    recruitmentCategory({ title: "钳工", job_type: "操作职系 实习", jd_url: wt(12), experience: "3年", summary: "2、具备3年及以上化工、石化等行业机修经验" }),
    "社招",
  );
  assert.strictEqual(
    recruitmentCategory({ title: "仓管员", job_type: "生产管理序列 实习", jd_url: wt(12), summary: "3、有仓储工作经验2年及以上。" }),
    "社招",
  );
  assert.strictEqual(recruitmentCategory({ title: "电工", job_type: "暑期实习", experience: "3年以上电工相关工作经验" }), "社招");
  assert.strictEqual(recruitmentCategory({ title: "结构工程师", jd_url: wecruit, experience: "5年以上工作经验" }), "社招");
  assert.strictEqual(recruitmentCategory({ title: "研发工程师", jd_url: "https://x.com/zp/intern/123", summary: "3-5年研发经验" }), "社招");
  // 没有经验要求的照旧判实习（渠道信号本身不动，只是让位给经验门）
  assert.strictEqual(recruitmentCategory({ title: "研究所化工行业研究", job_type: "研究序列 实习", jd_url: wt(12) }), "实习");
  assert.strictEqual(recruitmentCategory({ title: "产品助理", job_type: "暑期实习" }), "实习");
  assert.strictEqual(recruitmentCategory({ title: "产品助理", jd_url: wecruit }), "实习");
  // 标题自报「实习」仍是层1、最权威：正文提到年限也不改判（与「实习优先于校园字样」既有口径一致）
  assert.strictEqual(recruitmentCategory({ title: "生产实习生", job_type: "操作职系 实习", jd_url: wt(12), summary: "有 3 年以上经验者优先" }), "实习");
  // 渠道实习仍排在「来源自报校招/社招」与 url 门户之前：校招门户里 job_type 说实习 → 实习
  assert.strictEqual(recruitmentCategory({ title: "数据分析", job_type: "实习", jd_url: "https://jobs.example.com/campus/1" }), "实习");
});

test("渠道自报的实习只让位给「写明数字年限」的经验要求：正文里的 senior / lead / staff 资历词不够格", () => {
  // 2026-09-18 全集对拍（32,545 行）暴露：把渠道实习挪到层2 之后，8 行是**只**靠资历词触发经验门翻成社招的，
  // 其中中金「【2027】人力资源岗」（正文 "staff development"）、日立「Entry Program」（"employs 1,900 staff"）、
  // 美敦力「IT_Intern」（"lead with purpose"）是明明白白的实习/应届岗。资历词是给英文标题（Staff/Senior Engineer）
  // 用的代理信号，出现在正文里不说明这岗要几年经验；推翻一个租户级声明必须拿岗位自己写的数字。
  const wecruit = "https://career.example.com/pb/posDetail.html?postId=1&postType=intern";
  assert.strictEqual(
    recruitmentCategory({ title: "【2027】人力资源岗", job_type: "实习", summary: "Support training, recruitment and selection, staff development etc." }),
    "实习",
  );
  assert.strictEqual(
    recruitmentCategory({ title: "General Project Management Entry Program", jd_url: wecruit, summary: "Hitachi Energy employs over 1,900 staff across 55 cities." }),
    "实习",
  );
  assert.strictEqual(recruitmentCategory({ title: "IT_Intern", job_type: "实习", summary: "You'll lead with purpose and report to senior management." }), "实习");
  // 没有渠道实习声明的行，资历词照旧算硬门槛（既有口径不变）
  assert.strictEqual(recruitmentCategory({ title: "Staff Software Engineer", job_type: "校园招聘" }), "社招");
  assert.strictEqual(recruitmentCategory({ title: "Senior Analyst", jd_url: "https://x.com/campus/1" }), "社招");
  // 写明数字年限的仍然推翻渠道声明
  assert.strictEqual(recruitmentCategory({ title: "Product Operation Manager", jd_url: wecruit, summary: "5+ years of experience in product operations." }), "社招");
});
