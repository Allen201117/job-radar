// SQL 候选（search_doc 的 bigram tsquery）必须是 JS containsTerm 的超集——职级插词这一类（2026-09-23）。
//
// containsTerm 放行「有机合成高级研究员 / 有机合成（助理）研究员」命中词「合成研究员」之后，/jobs 关键词搜索
// 与 /today 方向层的候选 SQL 仍要求连续 bigram「成研」，真库 52 个这样的在招岗一个都进不了候选。
// 这里复刻 jobs-db/schema.sql 的 search_tokens + to_tsvector('simple') 分词（括号等标点把 bigram 切开，
// 真库 to_tsvector 逐个验过），再求 tsquery 的值——不连库也能钉住「JS 放行的写法 SQL 一定放行」。
const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const { loadTs } = require("./_load-ts");

const {
  keywordMatchTier,
  seniorityInfixSplit,
  SENIORITY_INFIX_WORDS,
  SENIORITY_INFIX_PAREN_WORDS,
} = require("../lib/china-keyword-expansion");
const { buildTsquery } = loadTs(path.join(__dirname, "..", "lib", "job-search.ts"));

/** 复刻 search_tokens：按空白切词，纯拉丁/数字整词，单字原样，其余相邻双字。 */
function searchTokens(text) {
  const out = [];
  for (const tok of String(text || "").toLowerCase().slice(0, 4000).split(/\s+/)) {
    if (!tok) continue;
    if (/^[a-z0-9]+$/.test(tok) || tok.length === 1) { out.push(tok); continue; }
    for (let i = 0; i < tok.length - 1; i++) out.push(tok.slice(i, i + 2));
  }
  return out;
}
/** 复刻 to_tsvector('simple', …) 对 bigram 的切分：标点（（）()-/…）是分隔符，只留字母数字与汉字。 */
function lexemes(text) {
  const set = new Set();
  for (const bg of searchTokens(text)) {
    for (const piece of bg.split(/[^a-z0-9㐀-䶿一-鿿]+/)) if (piece) set.add(piece);
  }
  return set;
}
/** 只认 buildTsquery 会产出的语法：词、&、|、括号。 */
function evalTsquery(query, lex) {
  const toks = query.match(/[()&|]|[^\s()&|]+/g);
  let i = 0;
  const primary = () => {
    if (toks[i] === "(") { i++; const v = orExpr(); assert.equal(toks[i++], ")"); return v; }
    return lex.has(toks[i++]);
  };
  const andExpr = () => { let v = primary(); while (toks[i] === "&") { i++; v = primary() && v; } return v; };
  const orExpr = () => { let v = andExpr(); while (toks[i] === "|") { i++; v = andExpr() || v; } return v; };
  const v = orExpr();
  assert.equal(i, toks.length, `tsquery 没解析完：${query}`);
  return v;
}
const sqlHits = (title, term) => evalTsquery(buildTsquery([term], []), lexemes(title));

/** JS SENIORITY_INFIX 的全部写法（与正则同源：两张词表 × 裸写 / 全角括号 / 半角括号）。 */
const INFIX_FORMS = [
  ...SENIORITY_INFIX_WORDS,
  ...SENIORITY_INFIX_PAREN_WORDS.flatMap((w) => [`（${w}）`, `(${w})`, `（${w})`, `(${w}）`]),
];

test("职级插词的每一种写法：JS 判同一角色的，SQL 候选子句一定命中", () => {
  const terms = ["合成研究员", "有机合成研究员", "产品经理", "客户经理", "化学研究员", "数据分析师", "执业药师"];
  const wraps = [(s) => s, (s) => `2027届-${s}-上海外高桥(J24968)`, (s) => `（实习）${s} (Senior Scientist)`];
  let checked = 0;
  for (const term of terms) {
    const split = seniorityInfixSplit(term);
    assert.ok(split, `${term} 应当可拆成 前缀 + 角色名`);
    for (const form of INFIX_FORMS) {
      for (const wrap of wraps) {
        const title = wrap(`${split.prefix}${form}${split.noun}`);
        assert.equal(sqlHits(title, term), true, `${term} ↛ ${title}`);
        // 写法表确实是 JS 放行的集合（散词「化学研究员」不属任何词组，exact 只可能来自 containsTerm）。
        if (term === "化学研究员") assert.equal(keywordMatchTier({ title }, term), "exact", title);
        checked++;
      }
    }
    // 旧行为不丢：连续写法照旧命中。
    assert.equal(sqlHits(`${term}(J1)`, term), true, term);
  }
  assert.equal(checked, terms.length * INFIX_FORMS.length * wraps.length);
});

test("真实标题端到端：JS 判 exact 的「有机合成高级研究员」进得了 /jobs 候选（城市 AND 也成立）", () => {
  const { ftsCandidateTerms } = require("../lib/china-keyword-expansion");
  const q = buildTsquery(ftsCandidateTerms("有机合成研究员"), [], [["上海"]]);
  for (const title of [
    "有机合成高级研究员",
    "有机合成（助理）研究员",
    "有机合成助理研究员-上海(J21993)",
    "2027届-有机合成高级研究员-上海外高桥(J24968)",
  ]) {
    assert.equal(keywordMatchTier({ title, location: "上海" }, "有机合成研究员"), "exact", title);
    // search_doc = title + company + location + job_type
    assert.equal(evalTsquery(q, lexemes(`${title} 某药企 上海 全职`)), true, title);
  }
});

test("放宽只到职级词：插别的词、缺前缀、只剩角色名都不进候选", () => {
  for (const title of ["合成生物研究员", "合成运营研究员", "药物分析高级研究员", "高级研究员", "合成研究"]) {
    assert.equal(sqlHits(title, "合成研究员"), false, title);
  }
  // 「产品运营经理 ≠ 产品经理」：JS 不放行，SQL 这条子句也不放行（「产品」本身另有子句，与本条无关）。
  assert.equal(sqlHits("产品运营经理", "产品经理"), false);
  // 职级词必须贴着前缀和角色名。只要求「标题某处有高级」的第一版在真库上把这两类捞进来、撞窗口时挤掉真岗。
  assert.equal(sqlHits("客户服务高级经理", "客户经理"), false);
  assert.equal(sqlHits("医学写作高级经理", "医学经理"), false);
  assert.equal(sqlHits("大客户高级经理（甲醇）", "客户经理"), true);
});

test("走不到职级分支的词不改子句：拉丁词、带假朋友的词、前缀不足 2 字、不以角色名结尾", () => {
  for (const term of ["工程师", "药师", "java", "施工", "合成研究", "研究员助理"]) {
    assert.equal(seniorityInfixSplit(term), null, term);
  }
  assert.equal(buildTsquery(["施工"], []), "((施工))");
  assert.equal(buildTsquery(["工程师"], []), "((工程 & 程师))");
});
