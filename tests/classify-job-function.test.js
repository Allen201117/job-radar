const test = require("node:test");
const assert = require("node:assert/strict");
const { classifyJobFunction } = require("../lib/china-keyword-expansion");

// P1-A 标签精度硬化：职能标签必须与 JD 强相关（角色锚定），研发信号压过"产品"裸词。
// 用户实锤问题：标题含"产品"二字的研发岗被误打成"产品"标签。

test("研发岗含'产品'二字不再被误判为产品（角色锚定，研发优先）", () => {
  assert.equal(classifyJobFunction({ title: "产品研发工程师" }), "研发");
  assert.equal(classifyJobFunction({ title: "产品测试工程师" }), "研发");
  assert.equal(classifyJobFunction({ title: "智能产品开发" }), "研发");
  assert.equal(classifyJobFunction({ title: "硬件产品工程师" }), "研发");
  assert.equal(classifyJobFunction({ title: "产品安全工程师" }), "研发");
});

test("产品设计师归设计（不归产品）", () => {
  assert.equal(classifyJobFunction({ title: "产品设计师" }), "设计");
});

test("真·产品角色仍准确归产品（回归）", () => {
  assert.equal(classifyJobFunction({ title: "产品经理" }), "产品");
  assert.equal(classifyJobFunction({ title: "AI 产品经理" }), "产品");
  assert.equal(classifyJobFunction({ title: "高级产品经理" }), "产品");
  assert.equal(classifyJobFunction({ title: "数据产品经理" }), "产品");
  assert.equal(classifyJobFunction({ title: "产品实习生" }), "产品");
  assert.equal(classifyJobFunction({ title: "AI产品实习生" }), "产品");
  assert.equal(classifyJobFunction({ title: "产品助理" }), "产品");
});

test("产品运营与项目管理不再误判成产品", () => {
  // 这是有意推翻的旧口径：旧规则把「产品运营」当成真·产品角色，生产库 384 个标题含「产品运营」的
  // 在招岗全判「产品」，全被推荐给产品经理用户。产品运营是运营岗，不是产品经理岗；创始人 2026-09-02
  // 明确指出这是误推，所以本断言从「产品」翻成「运营」，不是回归失败。
  assert.equal(classifyJobFunction({ title: "产品运营" }), "运营");
  assert.equal(classifyJobFunction({ title: "资深AI产品运营（花生AI）" }), "运营");
  assert.equal(classifyJobFunction({ title: "商业产品运营专家-穿山甲" }), "运营");
  assert.equal(classifyJobFunction({ title: "Product Operations Manager" }), "运营");

  assert.notEqual(classifyJobFunction({ title: "Assembler D shift Nights (12-Hours; 6 pm -6 am)" }), "产品");
  assert.notEqual(
    classifyJobFunction({ title: "Customer Service Agent (Monday-Friday, 9:00 AM-5:00 PM)" }),
    "产品",
  );
  assert.notEqual(classifyJobFunction({ title: "CVD PM Machinist" }), "产品");
  assert.equal(classifyJobFunction({ title: "AI智算项目经理（PM）" }), "项目管理");
  assert.equal(classifyJobFunction({ title: "Principal Technical Program Manager" }), "项目管理");
  assert.notEqual(classifyJobFunction({ title: "Senior PM, International Trading" }), "产品");

  assert.equal(classifyJobFunction({ title: "产品经理" }), "产品");
  assert.equal(classifyJobFunction({ title: "Senior Product Manager, Autonomous Vehicle Reliability" }), "产品");
  assert.equal(classifyJobFunction({ title: "海外产品经理" }), "产品");
  assert.equal(
    classifyJobFunction({ title: "行政专员", summary: "需要有项目管理经验" }),
    "职能",
  );
});

test("其它职能分类回归不受影响", () => {
  assert.equal(classifyJobFunction({ title: "算法工程师" }), "研发");
  assert.equal(classifyJobFunction({ title: "Product Engineer" }), "研发");
  assert.equal(classifyJobFunction({ title: "数据分析师" }), "数据");
  assert.equal(classifyJobFunction({ title: "视觉设计师" }), "设计");
  assert.equal(classifyJobFunction({ title: "" }), "其他");
});

test("中文假朋友不污染分类，真岗位词仍保留", () => {
  for (const title of [
    "华星-产品管理类（本硕）",
    "客车-产品管理主任工程师",
    "DMPK-化合物样品管理员(J24376)",
    "DMPK-早期药物理化性质检测研究员(J24611)",
  ]) assert.notEqual(classifyJobFunction({ title }), "生产制造", title);

  for (const title of ["SAP MM系统实施工程师", "高级系统实施工程师", "【AI】云端浏览器基础设施工程师"]) {
    assert.notEqual(classifyJobFunction({ title }), "建筑工程", title);
  }

  for (const title of ["品质检验员", "质检员"]) assert.equal(classifyJobFunction({ title }), "生产制造", title);
  for (const title of ["施工员", "2026届校招四公司施工技术岗(J45759)", "土建造价工程师"]) {
    assert.equal(classifyJobFunction({ title }), "建筑工程", title);
  }
});

test("清理跨行业裸词后仍按真实岗位职能分类", () => {
  assert.notEqual(classifyJobFunction({ title: "保全电工" }), "金融业务");
  assert.notEqual(classifyJobFunction({ title: "个人护理产品一号位(J45931)" }), "医疗健康");
  assert.equal(classifyJobFunction({ title: "护士" }), "医疗健康");
  assert.equal(classifyJobFunction({ title: "临床协调员/临床研究护士（CRC）-济宁" }), "医疗健康");
  assert.equal(classifyJobFunction({ title: "餐厅领班" }), "客服服务");
  assert.equal(classifyJobFunction({ title: "青岛-一对一全科教师(J55621)" }), "教育培训");
  assert.equal(classifyJobFunction({ title: "全科医学科医师(J20060)" }), "医疗健康");
  assert.equal(classifyJobFunction({ title: "产品经理" }), "产品");
  assert.equal(classifyJobFunction({ title: "产品实习生" }), "产品");
  assert.equal(classifyJobFunction({ title: "产品运营" }), "运营");
});

// 2026-09-02 生产库 5 万条在招岗对拍：全行业岗位有 27.6% 落入「其他」，其中教育/医疗/建筑/制造更高。
// 以下标题均为生产库真实样本；新增桶只从标题判，防止 JD 正文的行业套话批量误标。
test("全行业新增职能桶覆盖生产库真实标题", () => {
  for (const title of [
    "工装设备工程师(J10074)", "射频工程师", "钣金工艺工程师", "轮胎成型工艺(J10020)",
    "装配工（云电-西安基地）", "锅炉、空压操作工（众业公司）", "Warehouse Operator",
    "Production Associate", "Production Supervisor", "Manufacturing Technician", "Transmission Mechanic", "检验员QC(J10141)", "品控官", "Site EHS Manager II",
    "Quality Control Analyst I (1st Shift)", "过程质量岗",
  ]) assert.equal(classifyJobFunction({ title }), "生产制造", title);

  for (const title of [
    "桥梁专业总体(J47269)", "水工结构设计（暑期实习）(J47191)", "施工员", "工程造价岗",
    "莱青高速项目工程部经理", "铁路牵引供变电专业岗位(J47476)",
  ]) assert.equal(classifyJobFunction({ title }), "建筑工程", title);

  for (const title of [
    "肿瘤内科医生(013598)", "儿科门诊护士(013912)", "放射技师(007212)", "营养师",
    "临床协调员/临床研究护士（CRC）-济宁", "CRA Intern-青岛（2027校招）", "药物安全专员-沈阳",
    "Medical Director, USMA Respiratory", "Plasma Center Nurse LVN",
  ]) assert.equal(classifyJobFunction({ title }), "医疗健康", title);

  for (const title of [
    "综合柜员岗（呼盟下辖支公司）", "非车险查勘岗", "权益投资经理", "高级风控专员（资管子公司）",
    "Personal Banker Burleson John Jones", "Roving Personal Banker", "Teller Part Time Silver City",
  ]) assert.equal(classifyJobFunction({ title }), "金融业务", title);

  for (const title of [
    "杭州学而思—科学思维教师", "初中语文学习机教师(J55308)", "高中一对一学科教师（教师基地全职）", "进校-渠道培训师",
  ]) assert.equal(classifyJobFunction({ title }), "教育培训", title);

  for (const title of [
    "服务专员(019850)", "全职 | 星级咖啡师", "调茶师（上海八佰伴店）", "运动顾问",
    "Customer Service Representative Small Business", "迪卡侬零售部门经理--天津",
  ]) assert.equal(classifyJobFunction({ title }), "客服服务", title);
});

test("新增职能桶不抢软件研发、销售和公司职能岗位", () => {
  for (const title of ["汽车嵌入式软件工程师", "机械臂算法工程师", "工业自动化测试开发", "Software Architect", "解决方案架构师"]) {
    assert.equal(classifyJobFunction({ title }), "研发", title);
  }
  for (const title of ["客户经理", "大客户经理"]) assert.equal(classifyJobFunction({ title }), "销售", title);
  for (const title of ["财务经理", "审计专员", "税务助理专员"]) assert.equal(classifyJobFunction({ title }), "职能", title);
  assert.equal(classifyJobFunction({ title: "产品经理" }), "产品");
  assert.equal(classifyJobFunction({ title: "产品运营" }), "运营");
  assert.equal(classifyJobFunction({ title: "Product Engineer" }), "研发");
  assert.equal(classifyJobFunction({ title: "Medical Device Software Engineer" }), "研发");
  assert.equal(classifyJobFunction({ title: "Trading Systems Engineer" }), "研发");
  // Instructional Designer 中 designer 是明确设计角色；它不是 instructor，不能被教育培训的精确词误吃。
  assert.equal(classifyJobFunction({ title: "Instructional Designer" }), "设计");
  assert.notEqual(classifyJobFunction({ title: "车载电源产品开发工程师" }), "产品");
  assert.equal(classifyJobFunction({ title: "产品质量与可靠性工程" }), "生产制造");
});

// 2026-09-02 香港生产库对拍：建筑/金融/制造中的泛词会把大量非本职能岗位错分，以下均为真实标题。
test("建筑、金融与制造的行业词必须有明确语境", () => {
  for (const title of [
    "Solutions Architect", "Senior Data Architect", "AI Security Architect- ARC, Apple Information Security",
    "Real-Time Computer Vision Architect", "Product Engineer",
  ]) assert.equal(classifyJobFunction({ title }), "研发", title);

  for (const title of ["建筑师", "钢结构工程师", "土木工程师", "造价工程师", "2026届校招四公司施工技术岗(J45759)"]) {
    assert.equal(classifyJobFunction({ title }), "建筑工程", title);
  }
  for (const title of ["机械结构设计工程师-27届", "强电经理"]) assert.equal(classifyJobFunction({ title }), "生产制造", title);
  assert.notEqual(classifyJobFunction({ title: "研发体系流程管理经理" }), "生产制造");

  for (const title of [
    "Director, Surgical Vision Equipment Portfolio, GSM", "Hematology Portfolio Analytics Manager",
    "伊顺特运中心河南驰枢达电商运营部费用结算员",
  ]) assert.notEqual(classifyJobFunction({ title }), "金融业务", title);
  for (const title of ["Teller Part Time Hillcrest", "Personal Banker Farmington", "Actuarial Analyst"]) {
    assert.equal(classifyJobFunction({ title }), "金融业务", title);
  }
  assert.equal(classifyJobFunction({ title: "Production Associate" }), "生产制造");
  assert.equal(classifyJobFunction({ title: "产品实习生" }), "产品");
  assert.equal(classifyJobFunction({ title: "产品经理" }), "产品");
  assert.equal(classifyJobFunction({ title: "产品运营" }), "运营");
});

// 降级门与生产制造桶不能共用词表：前者要尽量全地阻止传统工程/医疗岗落入软件研发，后者才要求归类精确。
test("传统工程和医疗词不再因泛工程师落入研发", () => {
  for (const title of [
    "光学工程师", "声学工程师", "精密仪器工程师", "包装设计工程师", "工业工程师(IE)",
    "生产工艺工程师", "标准化工程师",
  ]) assert.equal(classifyJobFunction({ title }), "生产制造", title);
  for (const title of ["医疗器械工程师", "试剂研发工程师", "药物研发工程师", "制药工程师", "临床数据管理"]) {
    assert.equal(classifyJobFunction({ title }), "医疗健康", title);
  }
  // 结构/管道/技术文档缺少行业语境时可保守留「其他」，但绝不能以泛工程师进入软件研发。
  for (const title of ["结构工程师", "管道工程师", "技术文档工程师"]) {
    assert.notEqual(classifyJobFunction({ title }), "研发", title);
  }
  for (const title of ["土木工程师", "岩土工程师", "暖通工程师", "给排水工程师"]) {
    assert.equal(classifyJobFunction({ title }), "建筑工程", title);
  }
  for (const title of ["生物特征识别算法工程师", "汽车嵌入式软件工程师", "机械臂算法工程师", "工业自动化测试开发", "Solutions Architect"]) {
    assert.equal(classifyJobFunction({ title }), "研发", title);
  }
  assert.equal(classifyJobFunction({ title: "机械结构设计工程师-27届" }), "生产制造");
  assert.equal(classifyJobFunction({ title: "钢结构工程师" }), "建筑工程");
  assert.equal(classifyJobFunction({ title: "Teller Part Time Hillcrest" }), "金融业务");
  assert.equal(classifyJobFunction({ title: "产品实习生" }), "产品");
  assert.equal(classifyJobFunction({ title: "产品运营" }), "运营");
  assert.equal(classifyJobFunction({ title: "Product Engineer" }), "研发");
});

test("正文兜底不再把非研发标题误判为研发，标题研发不受影响", () => {
  assert.equal(
    classifyJobFunction({ title: "公共关系岗", summary: "需要理解 AI、技术和算法发展" }),
    "其他",
  );
  // 「招聘HR（抖音）」是**真 HR 岗**——它招的是产品经理和算法工程师，正文里那些岗位名是它的
  // 招聘对象、不是它自己的职能。旧实现判「产品」会把这个 HR 岗推给产品经理用户，是个真 bug；
  // classifyJobFunction 的注释本来就写着「真 HR 岗正文不会翻盘、仍判职能」，旧实现没做到自己
  // 声明的意图。2026-09-01 改「最靠后命中优先」后一并修正。
  assert.equal(
    classifyJobFunction({ title: "招聘HR（抖音）", summary: "支持产品经理与算法工程师招聘" }),
    "职能",
    "真 HR 岗不该被正文里的招聘对象翻盘成产品岗",
  );
  // 「职能」例外分支仍然有效：这类标题命中的「招聘」是招聘活动标签、不是 HR 岗，
  // 仍要退回看正文里的真实角色。
  assert.equal(
    classifyJobFunction({
      title: "2027 校园招聘",
      summary: "面向应届生的产品经理岗位，负责需求分析与产品方案设计",
    }),
    "产品",
  );
  assert.equal(classifyJobFunction({ title: "算法工程师", summary: "负责 AI 平台" }), "研发");
});

// 招聘活动标签盖住真实角色：标题里的「校园招聘 / 社会招聘」命中「招聘」被判成 HR 岗，
// 但标签后面白纸黑字写着真实岗位名。2026-09-02 香港库实测（1.15 万在招岗对拍）：这类误判
// 让「2026年校园招聘-信息技术类岗位」「安全工程师——2027届校园招聘」「团险销售岗-社会招聘」
// 都挂着「职能」标签展示给用户。剥掉活动标签重判即可，改动只动 0.09% 的岗、全部是纠正。
test("招聘活动标签不掩盖标题里的真实角色", () => {
  assert.equal(classifyJobFunction({ title: "2027 届校园招聘 - 后台开发工程师" }), "研发");
  assert.equal(classifyJobFunction({ title: "安全工程师——2027届校园招聘" }), "研发");
  assert.equal(classifyJobFunction({ title: "2027校园招聘: 研发类-自动驾驶方向" }), "研发");
  assert.equal(
    classifyJobFunction({ title: "人保健康-辽宁分公司-保险类条线-团险销售岗-社会招聘" }),
    "销售",
  );
  // 剥完仍是职能的真·职能岗不受影响（中交系校招大量是这种）。
  assert.equal(classifyJobFunction({ title: "2026届校招中交二航局一公司财务管理岗" }), "职能");
  assert.equal(classifyJobFunction({ title: "【27届校招】法务专员（IPR方向）" }), "职能");
});

// 口径演进（2026-09-02）：这组原意始终是「不许塌进软件研发」，该保护仍成立；旧口径只能扔进「其他」，
// 代价是卡片无类型标签，且「其他=放行」让它们绕过方向门推给互联网用户。生产库「其他」占 27.6%，制造/工业更高。
// BOSS直聘、智联官方职位字典均将机械/材料/化工/工艺/电气自动化放在一级「生产制造」：这不是回归失败，
// 而是从判不出升级为判对；用户实锤「工艺技术开发（机械/自动化）」曾被研发误召。
test("非软件工程岗归生产制造而非软件研发", () => {
  assert.equal(classifyJobFunction({ title: "工艺技术开发（机械/自动化）" }), "生产制造");
  assert.equal(classifyJobFunction({ title: "机械工程师" }), "生产制造");
  assert.equal(classifyJobFunction({ title: "化工工艺开发" }), "生产制造");
  assert.equal(classifyJobFunction({ title: "材料研发工程师" }), "生产制造");
  assert.equal(classifyJobFunction({ title: "焊接技术工程师" }), "生产制造");
  assert.equal(classifyJobFunction({ title: "产品质量与可靠性工程(BJ)(J20823)" }), "生产制造");
  assert.equal(classifyJobFunction({ title: "车载电源产品开发工程师(J13826)" }), "生产制造");
});

test("带软件信号的交叉岗仍判研发（保守降级，不误伤机器人/嵌入式等）", () => {
  // 机械臂/自动驾驶/嵌入式等：有工业标记但带软件/算法信号 → 仍是软件研发。
  assert.equal(classifyJobFunction({ title: "机械臂算法工程师" }), "研发");
  assert.equal(classifyJobFunction({ title: "工业自动化测试开发" }), "研发");
  assert.equal(classifyJobFunction({ title: "汽车嵌入式软件工程师" }), "研发");
});

// 标题权威优先：job_type / summary 不得把标题已说清的职能带偏。
// 用户实锤：B站「数据科学家」挂在部门 job_type=「产品运营类」下，旧实现拼全文 → 误判「产品」→
// 匹配上「AI 数据产品经理」推给产品经理用户。标题「数据科学家」应判「数据」。
test("标题优先：job_type/summary 不带偏标题已明确的职能", () => {
  assert.equal(
    classifyJobFunction({ title: "商业化-数据科学家（AI Agent 开发方向）", job_type: "产品运营类" }),
    "数据",
    "数据科学家挂在产品运营部门下，仍应判数据（不被 job_type 带偏成产品）",
  );
  assert.equal(
    classifyJobFunction({ title: "算法工程师", job_type: "产品技术", summary: "与产品经理协作" }),
    "研发",
    "算法工程师标题清晰，不被 job_type/summary 的产品字样带偏",
  );
  // 「职能」例外：招聘活动标签标题（命中「招聘」）退回看正文真实角色 → 产品经理仍可召回。
  assert.equal(
    classifyJobFunction({ title: "2024 届校园招聘", summary: "产品经理方向，负责需求管理" }),
    "产品",
    "招聘标签标题退回正文，summary 的产品经理仍可召回",
  );
  // 真 HR 岗：标题就是招聘角色，正文不翻盘 → 仍判职能（不被例外误伤）。
  assert.equal(classifyJobFunction({ title: "招聘专员", summary: "负责候选人寻访" }), "职能");
});
