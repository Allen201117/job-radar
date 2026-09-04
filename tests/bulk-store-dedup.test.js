const { test } = require("node:test");
const assert = require("node:assert");
const path = require("node:path");
const { loadTs } = require("./_load-ts");

const {
  BULK_STORE_COMPANIES,
  MIN_BODY_CHARS,
  bulkStoreCompanyOf,
  bulkStoreGroupKey,
  collapseBulkStoreJobs,
  dedupeBulkStoreJobs,
} = loadTs(path.join(__dirname, "..", "lib", "bulk-store-dedup.ts"));

const BODY =
  "岗位职责： 1.负责上门客户接待、咨询工作，为客户提供专业的房地产相关咨询服务； 2.根据公司现行渠道开发客户与房源； " +
  "3.了解客户需求，为客户有效匹配房源，促成一手楼盘销售、二手房买卖、房屋租赁，并负责业务跟进和房屋过户手续办理等后续服务工作。";
assert.ok(BODY.replace(/\s+/g, "").length >= MIN_BODY_CHARS, "测试样例正文得够长，否则测的不是折叠");

const store = (id, title, location = "杭州", summary = BODY) => ({
  id,
  company: "我爱我家",
  title,
  location,
  summary,
});

test("同城 + 同正文的门店副本折叠成一条，并记下这一组有多少家", () => {
  const jobs = collapseBulkStoreJobs([
    store("a", "杭州-赵乐怡-奥特莱斯店3组(J711263)"),
    store("b", "杭州-门店自招-枫华府第店2组(J654279)"),
    store("c", "杭州-谢英英-御观邸店组(J690895)"),
  ]);
  assert.equal(jobs.length, 1);
  assert.equal(jobs[0].id, "a", "留下的必须是排在最前面（打分最高）的那条");
  assert.equal(jobs[0].__storeCount, 3);
});

// ⚠️ 这条是本文件最重要的断言：判据用错会一次性抹掉几百个真岗。
// 2026-09-04 live 实测：美光 1,255 行共用**同一段公司简介样板**，底下是 727 个真正不同的岗
// （SAP ERP Analyst / Electrical Failure Analysis Engineer / Lean Manufacturing Engineer…）。
// Visa 1,534 行 / 647 个岗、Salesforce、强生、Applied Materials 全是同一种形态。
// 所以「同公司+同城+同正文」这个判据**只能对显式点名的公司生效**，绝不能自动推广。
test("名单外的公司即使同城同正文也一条都不许合并（美光/Visa 那种公司简介样板）", () => {
  const boiler = "Our vision is to transform how the world uses information to enrich life for all. ".repeat(2);
  const micron = (id, title) => ({ id, company: "美光 Micron", title, location: "上海", summary: boiler });
  const jobs = collapseBulkStoreJobs([
    micron("m1", "SAP ERP Principal Business Process Analyst"),
    micron("m2", "Electrical Failure Analysis Engineer"),
    micron("m3", "Lean Manufacturing Engineer"),
  ]);
  assert.equal(jobs.length, 3, "名单外公司被折叠 = 抹掉真实机会");
  assert.ok(jobs.every((j) => j.__storeCount === undefined));
});

test("正文太短不折叠——短正文不是可靠的角色载体", () => {
  const jobs = collapseBulkStoreJobs([
    store("a", "杭州-A店", "杭州", "招人"),
    store("b", "杭州-B店", "杭州", "招人"),
  ]);
  assert.equal(jobs.length, 2);
  assert.equal(bulkStoreGroupKey(store("a", "x", "杭州", "招人")), null);
});

test("不同 location 各留一条——同一角色在两个城市是两个不同的机会", () => {
  const jobs = collapseBulkStoreJobs([
    store("a", "杭州-A店", "杭州"),
    store("b", "北京-B店", "北京"),
    store("c", "北京-C店", "北京"),
  ]);
  assert.equal(jobs.length, 2);
  assert.deepEqual(
    jobs.map((j) => [j.location, j.__storeCount ?? 1]),
    [["杭州", 1], ["北京", 2]],
  );
});

// 用完整 location 而不是解析出的城市：门店岗按区分布，解析成「杭州」会把余杭和滨江并成一个。
test("location 精确到区时不跨区合并", () => {
  const jobs = collapseBulkStoreJobs([
    store("a", "A店", "杭州·余杭区"),
    store("b", "B店", "杭州·滨江区"),
  ]);
  assert.equal(jobs.length, 2);
});

test("公司名带后缀也能命中名单（库里 company 常是实体全称）", () => {
  assert.equal(bulkStoreCompanyOf("我爱我家控股集团股份有限公司"), "我爱我家");
  assert.equal(bulkStoreCompanyOf("美光 Micron"), null);
  assert.equal(bulkStoreCompanyOf(null), null);
  assert.equal(bulkStoreCompanyOf(""), null);
});

test("名单公司与普通公司混在一起时，只折叠名单里的那家", () => {
  const { jobs, groupSizeById } = dedupeBulkStoreJobs([
    store("s1", "杭州-A店"),
    { id: "n1", company: "字节跳动", title: "后端工程师", location: "杭州", summary: BODY },
    store("s2", "杭州-B店"),
    { id: "n2", company: "字节跳动", title: "前端工程师", location: "杭州", summary: BODY },
  ]);
  assert.deepEqual(jobs.map((j) => j.id), ["s1", "n1", "n2"]);
  assert.equal(groupSizeById.get("s1"), 2);
});

test("名单是显式的——新增公司必须是一次人工决定，不是自动识别", () => {
  assert.ok(Array.isArray(BULK_STORE_COMPANIES) && BULK_STORE_COMPANIES.length > 0);
  assert.ok(BULK_STORE_COMPANIES.includes("我爱我家"));
});

test("空输入与缺字段不炸", () => {
  assert.deepEqual(collapseBulkStoreJobs([]), []);
  assert.equal(collapseBulkStoreJobs([{ id: "x" }]).length, 1);
  assert.equal(bulkStoreGroupKey({}), null);
});
