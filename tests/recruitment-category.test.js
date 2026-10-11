const test = require("node:test");
const assert = require("node:assert");
const {
  recruitmentCategory,
  hasExplicitRecruitmentType,
  _minRequiredExperienceYears,
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
  // 回归：普通公司/岗位不被误判
  assert.equal(recruitmentCategory({ title: "后端开发", company: "字节跳动" }), "社招");
});

test("公司名不是招聘类型信号（2026-10-11 拆层6）：名字里带「校招 / 实习」也不改判，也不算「类型明确」", () => {
  // 原层6 会把这三行判成 校招 / 实习 / 实习。源名已不带渠道后缀（迁移 320），公司名里再出现这两个字只会是公司自己的名字。
  for (const company of ["华润电力 CR Power 校招", "TCL 实习", "实习僧", "神州信息—AI实习生", "某某校园招聘服务有限公司"]) {
    assert.equal(recruitmentCategory({ title: "电气工程师", company }), "社招", company);
    assert.equal(hasExplicitRecruitmentType({ title: "电气工程师", company }), false, company);
  }
  // 反方向：别的层照常起作用，公司名带不带这两个字结果一样
  for (const company of ["TCL", "TCL 校招"]) {
    const url = "https://wecruit.hotjob.cn/SUx/pb/posDetail.html?postId=1&postType=campus";
    assert.equal(recruitmentCategory({ title: "硬件工程师", company, jd_url: url }), "校招");
    assert.equal(recruitmentCategory({ title: "硬件工程师实习生", company }), "实习");
    assert.equal(hasExplicitRecruitmentType({ title: "硬件工程师", company, jd_url: url }), true);
  }
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

test("hasExplicitRecruitmentType 的 url 渠道正则与 recruitmentCategory 层1/层4 共用一份（moka 后缀门户 / 查询参数渠道）", () => {
  // 2026-09-18 live：moka `/campus-recruitment/` 6,906 个校招岗 recruitment_explicit=false，
  // 被 /jobs 校招筛选（要求 explicit and category）淘汰 —— 层4 在 08-07 放宽了后缀，这里没跟。
  const cases = [
    "https://app.mokahr.com/campus-recruitment/catlhr/148948#/job/abc",
    "https://app.mokahr.com/campus_apply/xx/1#/job/abc",
    "https://app.mokahr.com/social-recruitment/xx/1#/job/abc",
    "https://career.honor.com/SU60/pb/posDetail.html?postId=1&postType=campus",
    "https://career.honor.com/SU60/pb/posDetail.html?postId=1&postType=intern",
    "https://goodwe.hotjob.cn/wt/goodwe/mobweb/position/detail?brandCode=1&safe=Y&recruitType=1&postIdsAry=908",
    "https://goodwe.hotjob.cn/wt/goodwe/mobweb/position/detail?brandCode=1&safe=Y&recruitType=12&postIdsAry=908",
  ];
  for (const jd_url of cases) {
    const job = { title: "高级通用人工智能算法研发工程师（大模型方向）", jd_url };
    if (!/social-recruitment/.test(jd_url)) assert.notStrictEqual(recruitmentCategory(job), "社招", jd_url);
    assert.strictEqual(hasExplicitRecruitmentType(job), true, jd_url);
  }
  // 不是渠道令牌的路径不算（campusXX 无分隔、recruitType=2 刻意不判、社招兜底仍是"信息不足"）
  assert.strictEqual(hasExplicitRecruitmentType({ title: "后端", jd_url: "https://x.com/campusnews/1" }), false);
  assert.strictEqual(hasExplicitRecruitmentType({ title: "后端", jd_url: "https://x.hotjob.cn/d?recruitType=2&id=1" }), false);
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

test("按学历分档、应届占一档的写法不豁免经验门：仍判社招（2026-10-11 创始人定，三桶不动）", () => {
  // 全库实测 1,974 岗 / 14 家，比亚迪 1,957：挂在比亚迪自己的社招渠道里（校招是另一个渠道代码），1,236 岗本科应届投不了，
  // 近 3 天还在官网列表的只有 241。这批岗的 job_type=校招 是入库时从正文「应届」推出来的，不是对方自报——
  // 松开经验门、交给后面的层裁决，同模板的岗会按最后一次抓取带没带正文分到两边（1,577 校招 / 380 社招）。
  const byd = "https://job.byd.com/portal/pc/#/social/socialPositionDetails?p=abc";
  for (const summary of [
    "学历要求：大专\n工作经验：应届硕士生/本科2年/大专3年以上相关工作经验",
    "工作经验：应届本科生/大专2年以上相关工作经验",
    "工作经验：大专3年以上；本科2年以上；硕士应届生",
    "工作经验：应届博士/硕士2年/本科5年以上储能相关工作经验",
  ]) {
    assert.strictEqual(
      recruitmentCategory({ title: "高级机械工程师", job_type: "校招", jd_url: byd, experience: "应届/不限", summary }),
      "社招",
      summary,
    );
  }
  // 同句并列但不分档的写法同理（「经验为主，应届可放宽」，全库 146 岗 / 61 家）
  assert.strictEqual(
    recruitmentCategory({ title: "研究员", job_type: "校招", summary: "有2年以上的相关工作经验，特别突出的应届毕业生也可以考虑" }),
    "社招",
  );
});

test("年限读数：en dash 区间读下限、两位数年份不是年限、上限写法不是下限", () => {
  const years = _minRequiredExperienceYears;
  // ① 区间分隔符是 en dash / em dash / 全角波浪号时，原来只认出后半截（「1–3年」读成 3）
  assert.strictEqual(years("1–3年互联网产品相关经验"), 1);
  assert.strictEqual(years("具备1～2年门店服务经验者优先考虑"), 1);
  assert.strictEqual(years("具有1—2年行政服务相关工作经验"), 1);
  assert.strictEqual(years("3–5年高性能计算研发经验"), 3);
  // ② 两位数年份缩写（四位数年份 2026-09-18 已挡，见上面「2026年应届生」的注释）
  assert.strictEqual(years("硕士及以上学历，26、27年毕业应届生或1年工作经验的职场新锐均可"), 1);
  assert.strictEqual(years("相关岗位工作经验优先；毕业时间在23年7月至26年7月往届生和应届生"), null);
  // ③ 上限：只有上限、没有别的下限 → 0
  assert.strictEqual(years("应届生或2年以内工作经验"), 0);
  assert.strictEqual(years("应届毕业生或正式工作经验≤2年"), 0);
  assert.strictEqual(years("应届毕业生至3年工作经验"), 0);
  assert.strictEqual(years("工作经验3年以内，优秀校招应届生亦可"), 0);
  assert.strictEqual(years("工作经验：2年以下薪酬绩效工作经验"), 0);
  // 上限后面还有真下限 → 认后面那个
  assert.strictEqual(years("本科及以上学历，毕业5年内。2、1年以上团队管理经验"), 1);
  // 🚫 门：N≥3 的上限、前后没有应届 / 毕业 / 在校 / 往届字样 → 照旧读成 N（宁可漏判校招）
  assert.strictEqual(years("5年以内人力资源从业经验，年龄30以内"), 5);
  assert.strictEqual(years("能独立管理200头以上母猪场，5年内相关工作经验"), 5);
  // 🚫 长得像上限、其实不是
  assert.strictEqual(years("至少5年以内衣/母婴/家居等相关行业运营经验"), 5); // 至少 5 年 + 内衣
  assert.strictEqual(years("不少于3年相关工作经验"), 3); // 不少于 = 下限
  assert.strictEqual(years("工作经验不得少于2年"), 2); // 「不」和「少于」之间隔了一个字
  assert.strictEqual(years("不能低于3年工作经验，应届生勿扰"), 3);
  assert.strictEqual(years("3年内容运营经验"), 3); // 内容
  assert.strictEqual(years("5年内部审计工作经验"), 5); // 内部
  // 🚫 长得像年份缩写、其实是年限：后面的「应届 / 毕业」是工作内容
  assert.strictEqual(years("有2年以上应届生培养经验"), 2);
  assert.strictEqual(years("3年以上毕业生招聘经验"), 3);
  assert.strictEqual(years("具有3年应届生招聘经验"), 3);
});

test("年限读错不再把写明应届 / 届别的岗强制判成社招（全库 社招→校招 31 行，反方向 0）", () => {
  const campusUrl = "https://x.com/campus/job/1";
  // 年份缩写：先导智能「2027届校招」管培生、正大「毕业时间在23年7月至26年7月」
  assert.strictEqual(
    recruitmentCategory({
      title: "集团战略管培生-采购（2027届校招）",
      job_type: "校园招聘",
      jd_url: "https://x.zhiye.com/social/detail?jobAdId=1",
      summary: "【任职要求】1、硕士及以上学历，26、27年毕业应届生或1年以内工作经验的职场新锐均可",
    }),
    "校招",
  );
  assert.strictEqual(
    recruitmentCategory({
      title: "销售储备干部",
      job_type: "校招",
      summary: "2.有销售相关岗位工作经验优先；3.热爱营销工作。4.毕业时间在23年7月至26年7月往届生和应届生",
    }),
    "校招",
  );
  // 上限 + 应届字样
  for (const summary of [
    "1.本科及以上学历2.应届生或2年以内工作经验，具有相关物流行业销售经验者优先",
    "1、应届毕业生至3年工作经验，具备数据/商业分析相关教育背景或工作经验",
    "2.工作经验3年以内，优秀校招应届生亦可",
    "3、应届毕业生或正式工作经验≤2年（养殖/农牧领域从业者优先）",
  ]) {
    assert.strictEqual(recruitmentCategory({ title: "运营专员", job_type: "校招", summary }), "校招", summary);
  }
  // 校招门户里 N≤2 的上限（没有应届字样）
  assert.strictEqual(
    recruitmentCategory({ title: "绩效管理专员", jd_url: campusUrl, summary: "【任职要求】1.工作经验：2年以下薪酬绩效工作经验" }),
    "校招",
  );
  // en dash 区间读下限；下限 ≥2 的区间照旧强制社招
  assert.strictEqual(
    recruitmentCategory({ title: "直播专项策略运营", job_type: "校招", summary: "1–3年左右数据分析/策略相关经验，或优秀应届毕业生" }),
    "校招",
  );
  assert.strictEqual(
    recruitmentCategory({ title: "售后前台", jd_url: campusUrl, summary: "工作经验：具备1～2年门店服务经验者优先考虑。" }),
    "校招",
  );
  assert.strictEqual(recruitmentCategory({ title: "算法工程师", job_type: "校招", summary: "3–5年推荐算法相关经验" }), "社招");
  // 没有别的信号时只是不再算「明确类型」，仍兜底社招
  assert.strictEqual(recruitmentCategory({ title: "售后前台", summary: "具备1～2年门店服务经验者优先考虑" }), "社招");
  assert.strictEqual(hasExplicitRecruitmentType({ title: "售后前台", summary: "具备1～2年门店服务经验者优先考虑" }), false);

  // 🚫 反方向必须守住：不设「N≤2 或有应届字样」这道门，下面两个真社招会被放进校招（全库实测就是这两行）
  assert.strictEqual(
    recruitmentCategory({ title: "HRBP", job_type: "校招", summary: "1、本科及以上学历，专业不限；2、5年以内人力资源从业经验，年龄30以内" }),
    "社招",
  );
  assert.strictEqual(
    recruitmentCategory({ title: "场长", jd_url: campusUrl, summary: "能独立管理200头以上母猪场，5年内相关工作经验。" }),
    "社招",
  );
  // 长得像上限的下限照旧强制社招
  assert.strictEqual(
    recruitmentCategory({ title: "品类运营", job_type: "校招", summary: "1、至少5年以内衣/母婴/家居/配饰/服装等相关行业运营经验" }),
    "社招",
  );
  assert.strictEqual(recruitmentCategory({ title: "审计专员", job_type: "校招", summary: "不少于3年相关工作经验" }), "社招");
});

test("年限读数：中文数字与阿拉伯数字走同一套判断（下限 / 区间 / 上限），约数取下限", () => {
  const years = _minRequiredExperienceYears;
  assert.strictEqual(years("2.三年以上金融相关行业系统建设经验"), 3);
  assert.strictEqual(years("大专及以上学历，专业不限，两年及以上医疗行业销售经验"), 2);
  assert.strictEqual(years("硕士及以上学历，三年工作经验以上或者优秀应届博士生"), 3);
  assert.strictEqual(years("2、财务工作从业经验三年以上"), 3);
  assert.strictEqual(years("有较强的动手能力，有二年以上相关工作经验"), 2);
  assert.strictEqual(years("硕士以上学位,十年以上工作经验(含)优先"), 10);
  assert.strictEqual(years("十五年以上从业经验"), 15);
  assert.strictEqual(years("二十年行业经验"), 20);
  assert.strictEqual(years("二十五年以上相关经验"), 25);
  assert.strictEqual(years("具有三至五年相关工作经验"), 3);
  assert.strictEqual(years("3至五年相关工作经验"), 3);
  assert.strictEqual(years("三至5年相关工作经验"), 3); // 混写：「5年」前面没有中文数字紧挨着「年」，也要走带中文分支的正则
  assert.strictEqual(years("两三年相关工作经验"), 2); // 约数取下限
  assert.strictEqual(years("十五六年从业经历"), 15);
  assert.strictEqual(years("三两年工作经验"), 2);
  assert.strictEqual(years("要求二至5年，有销售经验"), 2); // 混写里的「5年」改前按窗口读得到，不能因为前面是中文数字就丢
  // 🚫 中文数字读到的不足 2 年（「一年」）不拍板：别处还有读数就让位，只在别处读不到时才用
  assert.strictEqual(years("一年以上工作经验"), 1);
  assert.strictEqual(years("一至3年相关工作经验"), 1);
  assert.strictEqual(years("3、一年及以上管理软件实施经验；或者2年财务审计相关工作经验"), 2); // 改前读 2，不变
  assert.strictEqual(years("入职一年内需取得基金从业资格，要求3年以上银行工作经验"), 3); // 「从业资格」带出了经验字样
  assert.strictEqual(years("具备一年以上细胞治疗病毒载体研发经验的博士，或三年以上相关经验的硕士"), 3);
  assert.strictEqual(years("一年以上相关经验。5+ years of experience in banking"), 5);
  // 不是年限：中文写的年份、年级、前面还连着百 / 千 / 别的数字
  assert.strictEqual(years("二〇二四年毕业，有实习经历"), null);
  assert.strictEqual(years("二零二五年入职，有项目经验"), null);
  assert.strictEqual(years("大学三年级以上，有实习经验"), null);
  assert.strictEqual(years("成立一百二十年，积累了丰富的行业经验"), null);
  assert.strictEqual(years("一二三四年的相关经验"), null); // 认不出的组合不猜
  assert.strictEqual(years("二六年毕业，有实习经验者优先"), null); // 年份缩写，不当成「两三年」那种约数
  // 上限：与阿拉伯数字同一条规则（只有上限 → 0）
  assert.strictEqual(years("机械/车辆工程/机电等相关专业应届生或工作经验两年内"), 0);
  assert.strictEqual(years("985/211及重点传媒院校本科毕业，工作经验不超过两年"), 0);
  // 🚫 N≥3 的上限、前后没有应届 / 毕业字样 → 照旧读成 N（那道门对中文数字同样生效）
  assert.strictEqual(years("五年以内人力资源从业经验，年龄30以内"), 5);
});

test("年限读数：中文数字只在同一小句里写着经验字样时才算（行文里的「一年 / 两年」太多）", () => {
  const years = _minRequiredExperienceYears;
  // 小句 = 到标点或下一条为止；经验二字离年限再远（超过阿拉伯数字用的 25 字窗口）也算
  assert.strictEqual(years("【任职要求】三年以上锂电设备（卷绕、涂布、辊压、模切、叠片、方形与圆柱组装线)调试经验"), 3);
  assert.strictEqual(years("2、工作经验：五年以上临床工作经验"), 5); // 冒号不是边界
  // 小句里没有经验字样 → 不算，哪怕隔一个逗号就有
  assert.strictEqual(years("硕士研究生，学制三年；有相关实习经验者优先"), null);
  assert.strictEqual(years("无需工作经验，两年内晋升为店长"), null);
  assert.strictEqual(years("公司成立二十年，为应届生提供丰富的实践经验"), null);
  assert.strictEqual(years("无论你是应届毕业生还是毕业两年内的学子，有教学经验优先"), null);
  assert.strictEqual(years("以688为晋升模式，两年内三级跳，将毫无经验的职场新人，培养成为餐厅经理"), null);
  // 🚫 不让行文里的「一年」抢在后面真正的年限之前（改前这两句读的是 3 / 2，不能变小）
  assert.strictEqual(years("试用期一年，岗位要求3年以上销售经验"), 3);
  assert.strictEqual(years("有一年以上驾龄，3年以上销售经验"), 3);
  // 库里的正文是压成一行存的，条目之间只有「空格 + 序号」——那也是边界
  assert.strictEqual(years("2、跳槽频率：拒绝一年两跳等频繁跳槽的应聘者 3、2年以上制造行业工作经历"), 2);
  assert.strictEqual(years("1.教育背景限制：临床医学专业，临床医学八年制优先 2.有医学评测经验更佳"), null);
  assert.strictEqual(years("通过三年培养计划成长为管理者\n有相关实习经验优先"), null);
  // 例外：写明了下限（N年以上 / 及以上 / 或以上 / 不低于N年）且 N≥2 的，经验字样隔着逗号也算（与阿拉伯数字同一个 25 字窗口）
  assert.strictEqual(years("从事两年或以上皮科领域，生物制剂或特药的销售经验"), 2);
  assert.strictEqual(years("2、三年以上自动驾驶，adas，移动机器人等实际开发经验"), 3);
  assert.strictEqual(years("2.工作经验：熟悉储能产品系统，从事相关工作三年及以上"), 3);
  assert.strictEqual(years("①全球资金管理经验，不低于五年"), 5);
  assert.strictEqual(years("有两年以上驾龄，有销售经验者优先"), null); // 驾龄不是工作年限
  // 没写「以上」的不享受这个例外
  assert.strictEqual(years("备注：此为短期项目招聘，暂定两年，有同类商品开发经验优先"), null);
  assert.strictEqual(years("具有相关工作经历，近两年个人绩效考核不低于良好"), null);
});

test("年限读数：学制 / 培养期 / 学习经历不是工作年限（中文数字、阿拉伯数字同一套）", () => {
  const years = _minRequiredExperienceYears;
  // ④ 学制 / 学历年限
  assert.strictEqual(years("1.教育背景限制：临床医学专业，硕士或博士学历，临床医学八年制优先。有相关经验更佳"), null);
  assert.strictEqual(years("3、全日制统招四年制本科毕业，学士学位；有管理经验"), null);
  assert.strictEqual(years("1、教育程度：全日制统招四年本科及以上学历，2、经验：熟悉山东地区教材内容"), null);
  assert.strictEqual(years("岗位要求：1、26/27年本科毕业，有用户运营、社群运营经验优先"), null);
  // ⑤ 培养期 / 轮岗时长
  assert.strictEqual(years("3、入职后配备经验资深、业务过硬的双导师，量身制定三年培养方案，助力转变角色、个人成长"), null);
  assert.strictEqual(years("每位TTDP（技术菁英）都会经历为期三年的轮岗，逐年担任三个不同的技术岗位"), null);
  assert.strictEqual(years("希望你了解，通过不低于1年的轮岗历练，积累基层业务经验"), null);
  // ⑥ 学习 / 留学经历
  assert.strictEqual(years("1、本科阶段须在美国高校就读，并具有累计不少于五年的美国学习经历"), null);
  assert.strictEqual(years("具有2年及以上系统学习经历"), null);
  assert.strictEqual(years("三年以上海外留学经历者优先"), null);
  assert.strictEqual(years("具有2年以上国内外学习经历"), null);
  assert.strictEqual(years("全日制硕士学制三年 有实习经历者优先"), null); // 学制N年：后面跟什么都不算
  // 学制写在上一条、经验写在下一条（压成一行后粘在一起）：阿拉伯数字同样不算
  assert.strictEqual(years("1.临床医学8年制优先 2.有医学评测经验更佳"), null);
  // 上限补的两种写法：N年内 + 亦 / 也 / 均 / 数字；紧跟在「毕业」后面的 N年内
  assert.strictEqual(years("2.有相关实习经验优先3.有大型企业实习经历优先4.毕业三年内亦可投递"), 0);
  assert.strictEqual(years("【任职要求】本科学历，毕业2年内(具有教育行业市场/咨询经验优先)"), 0);
  assert.strictEqual(years("以688为晋升模式，2年内3级跳，将毫无经验的职场新人，培养成为餐厅经理"), 0);

  // 🚫 长得像、其实是工作年限 —— 必须照旧读成 N
  assert.strictEqual(years("2.五年以上制造业知识产权工作相关经验"), 5); // 「年以上制」不是「年制」
  assert.strictEqual(years("三年制造业成本会计相关工作经验"), 3); // 年 + 制造
  assert.strictEqual(years("两年制药企业QA工作经验"), 2); // 年 + 制药
  assert.strictEqual(years("相关运维服务工作经验三年以上专科及以上学历"), 3); // 去空白后「以上」粘着「专科」
  assert.strictEqual(years("3年本科教学经验"), 3); // 这一小句里还有「经验」
  assert.strictEqual(years("三年培养体系搭建经验"), 3);
  assert.strictEqual(years("三年以上培养方案设计经验"), 3);
  assert.strictEqual(years("任职者应具备至少1年英语国家或地区工作学习经历"), 1); // 工作学习经历
  assert.strictEqual(years("3年以上机器学习经历"), 3); // 机器学习是工作内容
  assert.strictEqual(years("具有两年深度学习经历"), 2);
  assert.strictEqual(years("5年以上增强学习经历"), 5);
  assert.strictEqual(years("5年以上销售及海外留学经历者优先"), 5); // 留学经历前面还隔着别的工作内容
  assert.strictEqual(years("有人才培养经验；3年培养体系搭建能力"), 3); // 培养体系是工作内容
  assert.strictEqual(years("有培训经验，3年培养方案设计能力"), 3);
  assert.strictEqual(years("至少2年海外工作或学习经历"), 2); // 工作或学习
  assert.strictEqual(years("2年以上英国留学经历或同等工作经验"), 2); // 后面还跟着工作经验
  assert.strictEqual(years("5年以上工作年限\n有海外留学经历者优先"), 5); // 留学经历是下一条的事
  assert.strictEqual(years("5年以上工作年限 2、有海外留学经历者优先"), 5);
  assert.strictEqual(years("5年以上，有海外留学经历者优先"), 5);
  assert.strictEqual(years("工作经验3年\n本科及以上学历"), 3); // 「3年本科」是两条粘在一起，不是学历年限
  assert.strictEqual(years("工作经验3年本科及以上学历"), 3);
  assert.strictEqual(years("毕业后3年内容运营经验"), 3); // 内容
  // 「经验」离年限超过 25 字、靠窗口前半段的「留学经历」才被认出来的真社招：学习经历那道门不能动窗口
  assert.strictEqual(
    years(
      "任职要求：1、本科以上学历，英语可以作为工作语言（海外留学经历优先）；" +
        "2、具备4年以上物流、快递行业末端配送网络规划/运力管理/承运商采购/配送作业标准化管理等任一相关工作经验",
    ),
    4,
  );
});

test("认中文数字年限后的招聘类型：真社招不再留在校招 / 实习，培养期 / 学制写法的真校招不被误杀（全库 →社招 302 行、→校招 2 行）", () => {
  const campusUrl = "https://x.mokahr.com/campus-recruitment/x/1#/job/abc";
  // 社招岗挂在校招门户 / 校招渠道参数下（全库 234 行：小米、新产业、华大基因、扬子江、延锋…）
  for (const [title, summary] of [
    ["财务经理(J13285)", "【任职要求】1、统招本科以上毕业，五年以上工作经验"],
    ["销售经理-江西", "【任职要求】1.大专及以上学历，专业不限，两年及以上医疗行业销售经验"],
    ["YFS-芜湖-客户主管", "资质要求：大学本科及以上学历 工作经验：汽车行业两年以上相关工作经验"],
    ["产品经理（PLM）(J10702)", "PLM相关工作经验三年以上，至少具有1个PLM落地项目经验"],
    ["设备工程师(J11698)", "2、制药或精细化工类企业设备管理相关工作经验八年以上"],
  ]) {
    assert.strictEqual(recruitmentCategory({ title, jd_url: campusUrl, summary }), "社招", summary);
  }
  // 只靠正文里的「应届」字样 / job_type 写着校招
  assert.strictEqual(
    recruitmentCategory({ title: "理财经理(001124)", summary: "（1）大学本科及以上学历，两年以上证券从业经历；应届毕业生需通过证券从业资格考试" }),
    "社招",
  );
  assert.strictEqual(
    recruitmentCategory({ title: "大润发课级主管", job_type: "校招", experience: "应届/不限", summary: "全日制大专以上学历，35岁以下，两年以上管理工作经验" }),
    "社招",
  );
  // 渠道自报实习的行：写明的中文数字年限同样推翻渠道声明（层2 的 _statesPriorExperience）
  assert.strictEqual(
    recruitmentCategory({
      title: "焊工",
      job_type: "实习",
      jd_url: "https://x.hotjob.cn/wt/x/web/index/webPositionN300!getOnePosition?postId=1&recruitType=12",
      summary: "【任职要求】1.持有效焊工证2.有三年以上电焊或二保焊工作经验3.身体健康，服从管理",
    }),
    "社招",
  );
  // 「N 年经验、应届亦可」/ 标题自报届别而正文写年限：按既有口径判社招（阿拉伯数字写法今天就是这么判的）
  assert.strictEqual(
    recruitmentCategory({ title: "新业务部-音频算法工程师", job_type: "校招", summary: "硕士及以上学历，三年工作经验以上或者优秀应届博士生" }),
    "社招",
  );
  assert.strictEqual(
    recruitmentCategory({ title: "【27届校招】机械结构工程师", job_type: "校招", jd_url: campusUrl, summary: "2.具有至少三年机械设计、机器人、自动化设备或类似产品相关经验" }),
    "社招",
  );
  assert.strictEqual(
    recruitmentCategory({ title: "人寿-四川分公司-行政文秘岗（2027校招）", job_type: "校招", summary: "4、应届毕业生或两年以上金融行业或相关岗位从业经历" }),
    "社招",
  );
  // experience 字段的「3-5年」和正文开头的「本科…」是两个字段，不能粘成「3-5年本科」被当成学历年限（改前判社招，不能变）
  assert.strictEqual(
    recruitmentCategory({ title: "后端开发", job_type: "校招", experience: "3-5年", summary: "本科及以上学历，熟悉Java，有微服务项目经验" }),
    "社招",
  );
  // 没有别的信号的社招岗：从「类型依据不明」变成「明确」（全库 499 行）
  assert.strictEqual(hasExplicitRecruitmentType({ title: "区域销售", summary: "三年以上医疗器械销售经验" }), true);

  // 🚫 不是经验要求的写法：真校招照旧判校招（直接认会误杀 31 行，全是近 3 天还在官网的活岗）
  for (const [title, summary] of [
    ["软件开发工程师JSYJY/管理培训生", "6、入职后配备经验资深、业务过硬的双导师，量身制定三年培养方案，助力转变角色、个人成长"],
    ["TTDP 技术菁英管培生", "每位TTDP（技术菁英）都会经历为期三年的轮岗，逐年担任三个不同的技术岗位"],
    ["大模型医学评测", "1.教育背景限制：临床医学专业，硕士或博士学历，临床医学八年制优先。有医学评测经验更佳"],
    ["英语翻译专员", "任职要求：1、本科阶段须在美国高校就读，并具有累计不少于五年的美国学习经历"],
    ["济南-初中班课教师", "【任职要求】1、教育程度：全日制统招四年本科及以上学历，2、经验：熟悉山东地区教材内容，有教学经验者更佳"],
    ["中国区校招投递入口", "1.全日制本科及以上2.有相关实习经验优先3.有大型企业实习经历优先4.毕业三年内亦可投递"],
    ["肯德基餐厅储备经理", "★快速的成长晋升通路：以688为晋升模式，两年内三级跳，将毫无经验的职场新人，培养成为餐厅经理"],
  ]) {
    assert.strictEqual(recruitmentCategory({ title, job_type: "校招", jd_url: campusUrl, summary }), "校招", summary);
  }
  // 🚫 「一年」不拍板：用友这两行改前读的是后面的「2年」、判社招，认了中文数字也不许翻成校招
  assert.strictEqual(
    recruitmentCategory({
      title: "实施顾问-E035",
      job_type: "实施 校园招聘",
      summary: "3、一年及以上管理软件实施经验；或者2年财务审计相关工作经验。",
    }),
    "社招",
  );
  // 社招→校招 只有 2 行，都是语境门在阿拉伯数字侧纠正的：希望学（「26/27年本科」读成 27 年）、阿里云管培生（2 年学习经历）
  assert.strictEqual(
    recruitmentCategory({ title: "石家庄-社群运营SA", job_type: "校招", summary: "岗位要求：1、26/27年本科毕业，有用户运营、社群运营经验优先" }),
    "校招",
  );
  assert.strictEqual(
    recruitmentCategory({ title: "阿里云管培生-商业技术方向", job_type: "校招", summary: "计算机相关专业，具有2年及以上系统学习经历" }),
    "校招",
  );
});
