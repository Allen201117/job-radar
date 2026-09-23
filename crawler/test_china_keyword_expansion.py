"""中英双语关键词扩展/匹配的纯函数单测（移植自 lib/china-keyword-expansion.test.js 的关注点）。"""
import unittest

import china_keyword_expansion as cke


class NormalizeTest(unittest.TestCase):
    def test_lowercase_and_collapse_whitespace(self):
        self.assertEqual(cke.normalize_for_match("  Machine   Learning  "), "machine learning")
        self.assertEqual(cke.normalize_for_match(None), "")


class ContainsTermBoundaryTest(unittest.TestCase):
    def test_short_latin_uses_word_boundary(self):
        self.assertTrue(cke.contains_term("ai engineer", "ai"))
        self.assertTrue(cke.contains_term("senior ml researcher", "ml"))
        # 误匹配防护：maintain/google 不应被 ai/go 命中
        self.assertFalse(cke.contains_term("maintenance technician", "ai"))
        self.assertFalse(cke.contains_term("google maps lead", "go"))

    def test_long_or_cjk_uses_substring(self):
        self.assertTrue(cke.contains_term("machine learning engineer", "machine learning"))
        self.assertTrue(cke.contains_term("后端工程师", "后端"))
        self.assertFalse(cke.contains_term("财务分析", "算法"))

    def test_cjk_false_friends_are_skipped_but_real_occurrences_still_match(self):
        self.assertFalse(cke.contains_term("系统实施工程师", "施工"))
        self.assertFalse(cke.contains_term("产品管理", "品管"))
        self.assertFalse(cke.contains_term("理化性质检测", "质检"))
        self.assertTrue(cke.contains_term("土建施工与系统实施工程", "施工"))
        self.assertTrue(cke.contains_term("品质检验员", "质检"))


class ExpandTest(unittest.TestCase):
    def test_chinese_expands_to_english_synonyms(self):
        terms = set(cke.expand_china_keyword_terms("算法"))
        for t in ("算法", "machine learning", "ml", "algorithm"):
            self.assertIn(t, terms, t)

    def test_english_expands_to_chinese_synonyms(self):
        terms = set(cke.expand_china_keyword_terms("backend"))
        for t in ("backend", "后端", "服务端"):
            self.assertIn(t, terms, t)

    def test_empty_query_returns_empty(self):
        self.assertEqual(cke.expand_china_keyword_terms(""), [])
        self.assertEqual(cke.expand_china_keyword_terms("   "), [])

    def test_unmatched_term_kept_verbatim(self):
        # 不在任何同义词组里的词应原样保留，仍可做子串匹配
        self.assertIn("blockchain", cke.expand_china_keyword_terms("blockchain"))


class QueryMatchesTest(unittest.TestCase):
    def test_chinese_query_matches_english_job(self):  # 核心 #4 场景
        self.assertTrue(cke.query_matches("Machine Learning Engineer", "算法"))
        self.assertTrue(cke.query_matches("AI Researcher", "算法"))
        self.assertTrue(cke.query_matches("Product Manager", "产品"))

    def test_english_query_matches_chinese_job(self):
        self.assertTrue(cke.query_matches("后端工程师 字节跳动", "backend"))

    def test_no_false_positive_via_short_abbrev(self):
        # 「算法」扩展含 "ai"，但 maintain/maintenance 不应被命中
        self.assertFalse(cke.query_matches("Maintenance Technician — maintain systems", "算法"))

    def test_empty_query_matches_all(self):
        self.assertTrue(cke.query_matches("anything", ""))

    def test_unrelated_query_no_match(self):
        self.assertFalse(cke.query_matches("Finance Analyst report", "前端"))


class ParityWithFrontendTest(unittest.TestCase):
    def test_group_count_matches_frontend(self):
        # 本次把 JS 已有 25 组同步到 crawler，并在末尾追加金融、教育、医疗、制造、建筑、客服共 20 组。
        # 又追加「学段」修饰组；2026-09-18 学生画像走查再追加投行/并购(46)、编导/内容制作(47) 两组；
        # 2026-09-23 体验走查再追加芯片验证(48)、风控/风险管理(49) 两组。
        # 这个数是两端索引同构的守卫：加组时必须同步 KEYWORD_GROUP_FUNCTIONS 与 lib/china-keyword-expansion.js。
        self.assertEqual(len(cke.CHINA_KEYWORD_GROUPS), 50)

    def test_group_functions_aligned(self):
        self.assertEqual(len(cke.KEYWORD_GROUP_FUNCTIONS), len(cke.CHINA_KEYWORD_GROUPS))

    def test_non_internet_queries_expand_to_real_title_variants(self):
        # 每行是用户会填写的方向词及生产库标题会出现的同义词，防止词表只加名称却无法召回真实岗名。
        cases = [
            ("银行柜员", ("柜员", "teller")),
            ("银行信贷", ("信贷", "personal banker")),
            ("保险理赔", ("理赔", "underwriter")),
            ("投资经理", ("投资经理", "portfolio manager")),
            ("中学数学教师", ("教师", "主讲")),
            ("教研培训", ("教研", "课程研发")),
            ("临床护士", ("护士", "nurse")),
            ("临床医生", ("医生", "physician")),
            ("临床研究", ("临床监查", "cra")),
            ("药师", ("药师", "pharmacist")),
            ("医药代表", ("医药代表", "msl")),
            ("机械工程师", ("机械设计", "mechanical engineer")),
            ("工艺工程师", ("工艺工程", "manufacturing engineer")),
            ("电气自动化", ("电气工程", "plc")),
            ("质量工程师", ("质量工程", "sqe")),
            ("生产管理", ("生产管理", "operator")),
            ("土木工程师", ("土建", "施工")),
            ("工程造价", ("造价", "quantity surveyor")),
            ("客户服务", ("客服", "customer support")),
            ("门店零售", ("店长", "retail")),
        ]
        for query, expected_terms in cases:
            terms = {term.lower() for term in cke.expand_china_keyword_terms(query)}
            for expected in expected_terms:
                self.assertIn(expected, terms, f"{query} 应扩展出 {expected}")


class ClassifyJobFunctionTest(unittest.TestCase):
    def test_buckets(self):
        self.assertEqual(cke.classify_job_function("AI 产品经理"), "产品")
        self.assertEqual(cke.classify_job_function("推荐算法工程师"), "研发")
        self.assertEqual(cke.classify_job_function("视觉设计师"), "设计")
        self.assertEqual(cke.classify_job_function("数据分析师"), "数据")
        self.assertEqual(cke.classify_job_function(""), "其他")

    def test_product_precedes_algorithm(self):
        self.assertEqual(cke.classify_job_function("AI 产品经理", "", "了解算法"), "产品")
        self.assertEqual(cke.classify_job_function("产品实习生"), "产品")
        self.assertEqual(cke.classify_job_function("AI产品实习生"), "产品")
        self.assertEqual(cke.classify_job_function("产品助理"), "产品")

    def test_title_classifier_matches_frontend_key_boundaries(self):
        self.assertEqual(cke.classify_job_title_function("2027 届校园招聘 - 后台开发工程师"), "研发")
        self.assertEqual(cke.classify_job_title_function("招聘HR（抖音）"), "职能")
        self.assertEqual(cke.classify_job_title_function("商业化-数据科学家（AI Agent 开发方向）"), "数据")
        self.assertEqual(cke.classify_job_title_function("Engineering Manager, Growth"), "研发")

    def test_product_operations_and_project_management_not_product(self):
        self.assertEqual(cke.classify_job_function("产品运营"), "运营")
        self.assertEqual(cke.classify_job_function("资深AI产品运营（花生AI）"), "运营")
        self.assertEqual(cke.classify_job_function("商业产品运营专家-穿山甲"), "运营")
        self.assertEqual(cke.classify_job_function("Product Operations Manager"), "运营")

        self.assertNotEqual(cke.classify_job_function("Assembler D shift Nights (12-Hours; 6 pm -6 am)"), "产品")
        self.assertNotEqual(
            cke.classify_job_function("Customer Service Agent (Monday-Friday, 9:00 AM-5:00 PM)"), "产品"
        )
        self.assertNotEqual(cke.classify_job_function("CVD PM Machinist"), "产品")
        self.assertEqual(cke.classify_job_function("AI智算项目经理（PM）"), "项目管理")
        self.assertEqual(cke.classify_job_function("Principal Technical Program Manager"), "项目管理")
        self.assertNotEqual(cke.classify_job_function("Senior PM, International Trading"), "产品")

        self.assertEqual(cke.classify_job_function("产品经理"), "产品")
        self.assertEqual(cke.classify_job_function("Senior Product Manager, Autonomous Vehicle Reliability"), "产品")
        self.assertEqual(cke.classify_job_function("海外产品经理"), "产品")
        self.assertNotEqual(cke.classify_job_function("行政专员", "", "需要有项目管理经验"), "项目管理")

    def test_title_first_not_misled_by_job_type(self):
        # 标题优先：job_type/summary 不带偏标题已明确的职能（与 JS 同口径）。
        # 实锤：B站「数据科学家」挂部门 job_type=「产品运营类」下，仍应判数据。
        self.assertEqual(
            cke.classify_job_function("商业化-数据科学家（AI Agent 开发方向）", "产品运营类"), "数据"
        )
        self.assertEqual(
            cke.classify_job_function("算法工程师", "产品技术", "与产品经理协作"), "研发"
        )
        # 「职能」例外：招聘活动标签标题退回看正文真实角色。
        self.assertEqual(
            cke.classify_job_function("2024 届校园招聘", "", "产品经理方向，负责需求管理"), "产品"
        )
        self.assertEqual(cke.classify_job_function("招聘专员", "", "负责候选人寻访"), "职能")

    def test_non_software_engineering_not_rd(self):
        # 口径演进（2026-09-02）：原意仍是「不许塌进软件研发」；旧口径扔进「其他」会让卡片无标签，
        # 且「其他=放行」绕过方向门。生产库「其他」占 27.6%，制造/工业更高；BOSS/智联职位字典将
        # 机械/材料/化工/工艺/电气自动化归一级「生产制造」，故这是从判不出升级为判对，不是回归失败。
        self.assertEqual(cke.classify_job_function("工艺技术开发（机械/自动化）"), "生产制造")
        self.assertEqual(cke.classify_job_function("机械工程师"), "生产制造")
        self.assertEqual(cke.classify_job_function("化工工艺开发"), "生产制造")
        self.assertEqual(cke.classify_job_function("材料研发工程师"), "生产制造")
        self.assertEqual(cke.classify_job_function("焊接技术工程师"), "生产制造")
        self.assertEqual(cke.classify_job_function("产品质量与可靠性工程(BJ)(J20823)"), "生产制造")
        self.assertEqual(cke.classify_job_function("车载电源产品开发工程师(J13826)"), "生产制造")
        # 带软件信号的交叉岗仍判研发（保守降级，不误伤机器人/嵌入式）。
        self.assertEqual(cke.classify_job_function("机械臂算法工程师"), "研发")
        self.assertEqual(cke.classify_job_function("汽车嵌入式软件工程师"), "研发")

    def test_new_cross_industry_function_buckets_from_production_titles(self):
        # 2026-09-02 生产库真实标题：六个新桶仅从标题认领，不能靠正文万能套话误标。
        cases = {
            "生产制造": [
                "工装设备工程师(J10074)", "射频工程师", "钣金工艺工程师", "轮胎成型工艺(J10020)",
                "装配工（云电-西安基地）", "锅炉、空压操作工（众业公司）", "Warehouse Operator",
                "Production Associate", "Production Supervisor", "Manufacturing Technician", "Transmission Mechanic", "检验员QC(J10141)", "品控官", "Site EHS Manager II",
                "Quality Control Analyst I (1st Shift)", "过程质量岗",
            ],
            "建筑工程": [
                "桥梁专业总体(J47269)", "水工结构设计（暑期实习）(J47191)", "施工员", "工程造价岗",
                "莱青高速项目工程部经理", "铁路牵引供变电专业岗位(J47476)",
            ],
            "医疗健康": [
                "肿瘤内科医生(013598)", "儿科门诊护士(013912)", "放射技师(007212)", "营养师",
                "临床协调员/临床研究护士（CRC）-济宁", "CRA Intern-青岛（2027校招）", "药物安全专员-沈阳",
                "Medical Director, USMA Respiratory", "Plasma Center Nurse LVN",
            ],
            "金融业务": [
                "综合柜员岗（呼盟下辖支公司）", "非车险查勘岗", "权益投资经理", "高级风控专员（资管子公司）",
                "Personal Banker Burleson John Jones", "Roving Personal Banker", "Teller Part Time Silver City",
            ],
            "教育培训": [
                "杭州学而思—科学思维教师", "初中语文学习机教师(J55308)", "高中一对一学科教师（教师基地全职）", "进校-渠道培训师",
            ],
            "客服服务": [
                "服务专员(019850)", "全职 | 星级咖啡师", "调茶师（上海八佰伴店）", "运动顾问",
                "Customer Service Representative Small Business", "迪卡侬零售部门经理--天津",
            ],
        }
        for expected, titles in cases.items():
            for title in titles:
                with self.subTest(title=title):
                    self.assertEqual(cke.classify_job_function(title), expected)

    def test_new_buckets_do_not_steal_existing_functions(self):
        for title in ("汽车嵌入式软件工程师", "机械臂算法工程师", "工业自动化测试开发", "Software Architect", "解决方案架构师"):
            with self.subTest(title=title):
                self.assertEqual(cke.classify_job_function(title), "研发")
        for title in ("客户经理", "大客户经理"):
            with self.subTest(title=title):
                self.assertEqual(cke.classify_job_function(title), "销售")
        for title in ("财务经理", "审计专员", "税务助理专员"):
            with self.subTest(title=title):
                self.assertEqual(cke.classify_job_function(title), "职能")
        self.assertEqual(cke.classify_job_function("产品经理"), "产品")
        self.assertEqual(cke.classify_job_function("产品运营"), "运营")
        self.assertEqual(cke.classify_job_function("Product Engineer"), "研发")
        self.assertEqual(cke.classify_job_function("Medical Device Software Engineer"), "研发")
        self.assertEqual(cke.classify_job_function("Trading Systems Engineer"), "研发")
        # Instructional Designer 是设计角色，不是 instructor；教育培训的精确词不能误吃它。
        self.assertEqual(cke.classify_job_function("Instructional Designer"), "设计")
        self.assertNotEqual(cke.classify_job_function("车载电源产品开发工程师"), "产品")
        self.assertEqual(cke.classify_job_function("产品质量与可靠性工程"), "生产制造")

    def test_building_finance_and_manufacturing_words_require_context(self):
        # 2026-09-02 香港生产库对拍：以下均为裸 architect、portfolio、结算、体系等泛词导致的真实误判。
        for title in (
            "Solutions Architect", "Senior Data Architect", "AI Security Architect- ARC, Apple Information Security",
            "Real-Time Computer Vision Architect", "Product Engineer",
        ):
            with self.subTest(title=title):
                self.assertEqual(cke.classify_job_function(title), "研发")
        for title in ("建筑师", "钢结构工程师", "土木工程师", "造价工程师", "2026届校招四公司施工技术岗(J45759)"):
            with self.subTest(title=title):
                self.assertEqual(cke.classify_job_function(title), "建筑工程")
        for title in ("机械结构设计工程师-27届", "强电经理"):
            with self.subTest(title=title):
                self.assertEqual(cke.classify_job_function(title), "生产制造")
        self.assertNotEqual(cke.classify_job_function("研发体系流程管理经理"), "生产制造")
        for title in (
            "Director, Surgical Vision Equipment Portfolio, GSM", "Hematology Portfolio Analytics Manager",
            "伊顺特运中心河南驰枢达电商运营部费用结算员",
        ):
            with self.subTest(title=title):
                self.assertNotEqual(cke.classify_job_function(title), "金融业务")
        for title in ("Teller Part Time Hillcrest", "Personal Banker Farmington", "Actuarial Analyst"):
            with self.subTest(title=title):
                self.assertEqual(cke.classify_job_function(title), "金融业务")
        self.assertEqual(cke.classify_job_function("Production Associate"), "生产制造")
        self.assertEqual(cke.classify_job_function("产品实习生"), "产品")
        self.assertEqual(cke.classify_job_function("产品经理"), "产品")
        self.assertEqual(cke.classify_job_function("产品运营"), "运营")

    def test_traditional_engineering_and_medical_words_do_not_fall_into_software_rd(self):
        # 降级门与生产制造桶不可共用词表：前者尽量全地拦传统工程/医疗，后者才要求归类精确。
        for title in (
            "光学工程师", "声学工程师", "精密仪器工程师", "包装设计工程师", "工业工程师(IE)",
            "生产工艺工程师", "标准化工程师",
        ):
            with self.subTest(title=title):
                self.assertEqual(cke.classify_job_function(title), "生产制造")
        for title in ("医疗器械工程师", "试剂研发工程师", "药物研发工程师", "制药工程师", "临床数据管理"):
            with self.subTest(title=title):
                self.assertEqual(cke.classify_job_function(title), "医疗健康")
        # 结构/管道/技术文档缺少行业语境时可保守留「其他」，但绝不能以泛工程师进入软件研发。
        for title in ("结构工程师", "管道工程师", "技术文档工程师"):
            with self.subTest(title=title):
                self.assertNotEqual(cke.classify_job_function(title), "研发")
        for title in ("土木工程师", "岩土工程师", "暖通工程师", "给排水工程师"):
            with self.subTest(title=title):
                self.assertEqual(cke.classify_job_function(title), "建筑工程")
        for title in ("生物特征识别算法工程师", "汽车嵌入式软件工程师", "机械臂算法工程师", "工业自动化测试开发", "Solutions Architect"):
            with self.subTest(title=title):
                self.assertEqual(cke.classify_job_function(title), "研发")
        self.assertEqual(cke.classify_job_function("机械结构设计工程师-27届"), "生产制造")
        self.assertEqual(cke.classify_job_function("钢结构工程师"), "建筑工程")
        self.assertEqual(cke.classify_job_function("Teller Part Time Hillcrest"), "金融业务")
        self.assertEqual(cke.classify_job_function("产品实习生"), "产品")
        self.assertEqual(cke.classify_job_function("产品运营"), "运营")
        self.assertEqual(cke.classify_job_function("Product Engineer"), "研发")

    def test_cjk_false_friends_do_not_pollute_function_buckets(self):
        for title in (
            "华星-产品管理类（本硕）", "客车-产品管理主任工程师",
            "DMPK-化合物样品管理员(J24376)", "DMPK-早期药物理化性质检测研究员(J24611)",
        ):
            with self.subTest(title=title):
                self.assertNotEqual(cke.classify_job_function(title), "生产制造")
        for title in ("SAP MM系统实施工程师", "高级系统实施工程师", "【AI】云端浏览器基础设施工程师"):
            with self.subTest(title=title):
                self.assertNotEqual(cke.classify_job_function(title), "建筑工程")
        for title in ("品质检验员", "质检员"):
            with self.subTest(title=title):
                self.assertEqual(cke.classify_job_function(title), "生产制造")
        for title in ("施工员", "2026届校招四公司施工技术岗(J45759)", "土建造价工程师"):
            with self.subTest(title=title):
                self.assertEqual(cke.classify_job_function(title), "建筑工程")

    def test_cleaned_cross_industry_terms_keep_real_job_functions(self):
        self.assertNotEqual(cke.classify_job_function("保全电工"), "金融业务")
        self.assertNotEqual(cke.classify_job_function("个人护理产品一号位(J45931)"), "医疗健康")
        self.assertEqual(cke.classify_job_function("护士"), "医疗健康")
        self.assertEqual(cke.classify_job_function("临床协调员/临床研究护士（CRC）-济宁"), "医疗健康")
        self.assertEqual(cke.classify_job_function("餐厅领班"), "客服服务")
        self.assertEqual(cke.classify_job_function("青岛-一对一全科教师(J55621)"), "教育培训")
        self.assertEqual(cke.classify_job_function("全科医学科医师(J20060)"), "医疗健康")
        self.assertEqual(cke.classify_job_function("产品经理"), "产品")
        self.assertEqual(cke.classify_job_function("产品实习生"), "产品")
        self.assertEqual(cke.classify_job_function("产品运营"), "运营")


class JobMatchesTest(unittest.TestCase):
    """字段感知 + 职能门：发现端（刷新公司库 / 联网发现）精准过滤的核心，与前端看板同口径。"""

    def test_cross_function_precision_pm_not_algo(self):  # 用户原始痛点
        algo = ("推荐算法工程师", "负责推荐产品的算法模型，机器学习")
        data = ("数据分析师", "SQL 业务分析，支撑产品决策")
        self.assertFalse(cke.job_matches(algo[0], algo[1], "pm"), "正文含'产品'的算法岗不应命中 pm")
        self.assertFalse(cke.job_matches(data[0], data[1], "pm"), "正文含'产品'的数据岗不应命中 pm")

    def test_cross_function_precision_reverse(self):
        pm = ("产品经理", "了解算法优先，负责需求管理")
        self.assertFalse(cke.job_matches(pm[0], pm[1], "算法"), "PM 岗正文提'算法'不应命中'算法'")

    def test_body_recall_same_function(self):
        # 这是有意翻转的旧口径：JS 的 jobMatchesChinaKeyword 用 classifyJobTitleFunction 只看标题，
        # 且要求 titleFn 不是「职能」，所以纯「2024 届校园招聘」一直不匹配。Python 旧行为是正文
        # 自证正文的循环论证副产品；两端必须同口径，否则爬虫会抓回前端根本不会推荐的岗。
        # 代价是：真实角色只写在正文的纯活动标签校招会在刷新公司库/官方源发现的后置过滤中漏掉。
        # 这是已知取舍——标题无法判方向时宁可漏，不可把方向不明的岗推给用户。将来若要放宽，应仅对
        # 纯活动标题让正文职能作为弱信号，JS/Python 两端同时改并用真实库对拍误召率，不能只放宽 Python。
        self.assertFalse(cke.job_matches("2024 届校园招聘", "产品经理方向，负责需求管理", "pm"))
        # 标题已有真实技术角色时，正文的同职能具体词仍可召回，不误伤「校招标签 + 具体方向」的岗位。
        self.assertTrue(cke.job_matches("2026年校园招聘-算法工程师", "机器学习方向", "机器学习"))
        self.assertTrue(cke.job_matches("资深工程师", "负责推荐算法与模型训练", "算法"))

    def test_real_jobs_match_via_title(self):
        self.assertTrue(cke.job_matches("策略产品经理", "", "pm"))
        self.assertTrue(cke.job_matches("Senior Product Manager", "", "pm"))

    def test_scattered_company_token_matches_body(self):
        self.assertTrue(cke.job_matches("前端工程师", "字节跳动", "前端 字节"))
        self.assertFalse(cke.job_matches("前端工程师", "字节跳动", "前端 腾讯"))

    def test_empty_query_matches_all(self):
        self.assertTrue(cke.job_matches("任意岗位", "任意正文", ""))

    def test_false_friends_and_school_stage_use_the_real_matcher(self):
        units = cke.keyword_match_units("中学数学教师")
        self.assertEqual(len(units), 3)
        self.assertTrue(any("高中" in unit and "初中" in unit for unit in units))
        self.assertTrue(any(unit == ["数学"] for unit in units))
        self.assertTrue(cke.job_matches("高中数学主讲教师-苏州分校-26校招", "", "中学数学教师"))
        self.assertTrue(cke.job_matches("初中数学教研", "", "中学数学教师"))
        self.assertFalse(cke.job_matches("SAP MM系统实施工程师", "", "土木工程师"))
        self.assertTrue(cke.job_matches("土建造价工程师", "", "土木工程师"))
        self.assertTrue(cke.job_matches("土建施工与系统实施工程", "", "土木"))
        self.assertTrue(cke.job_matches("资深产品经理", "", "产品经理"))
        self.assertTrue(cke.job_matches("推荐算法工程师", "", "算法"))


class StudentPersonaWalkthroughDirectionsTest(unittest.TestCase):
    """2026-09-18 学生画像走查补词表：9 个几乎搜不到的方向，与 lib/china-keyword-expansion.js
    的 tests/china-keyword-expansion.test.js 同批断言同步，两边必须保持一致。"""

    def test_investment_banking_direction(self):
        for title in [
            "投行业务岗（先进制造方向）",
            "承做业务岗（并购组）",
            "债券承做岗(009759)",
            "投资银行部",
            "Investment Banking Analyst",
        ]:
            self.assertTrue(cke.job_matches(title, "", "投行分析师"), title)
        self.assertFalse(cke.job_matches("证券研究员", "", "投行分析师"))

    def test_pharma_rd_direction_not_blocked_by_generic_engineering_group(self):
        for title in [
            "2026届-博士-有机合成研究员-北京总部",
            "制剂分析研究员-北京",
            "药理毒理总监级",
            "原料药合成实验员(J11081)",
            "药物化学研究员(J16619)",
            "CMC Director",
        ]:
            self.assertTrue(cke.job_matches(title, "", "药物研发"), title)

    def test_clinical_research_direction(self):
        self.assertTrue(cke.job_matches("医学经理(J22026)", "", "临床研究"))
        self.assertTrue(cke.job_matches("临床运营部：临床项目总监", "", "临床研究"))

    def test_cost_engineering_direction(self):
        self.assertTrue(cke.job_matches("2027届校招一公司预算员", "", "造价"))

    def test_warehouse_operations_direction_and_data_warehouse_false_friend(self):
        self.assertTrue(cke.job_matches("仓库管理员", "", "仓储"))
        self.assertTrue(cke.job_matches("仓储主管", "", "仓储"))
        # 「数据仓库」是数据工程概念，不该被供应链组的「仓库」抢成"已被认领"，否则会把它从
        # 「数据分析」这类查询里挤掉。
        self.assertTrue(cke.job_matches("Data Warehouse Engineer", "", "数据分析"))
        self.assertTrue(cke.job_matches("数据仓库开发工程师-国际化业务", "", "数据分析"))

    def test_after_sales_and_store_trainee_suffix_fix(self):
        self.assertTrue(cke.job_matches("2027-国内售后工程师（惠州）", "", "售后服务"))
        self.assertTrue(cke.job_matches("售后运营培训生-东南亚", "", "售后服务"))
        self.assertTrue(cke.job_matches("特步-储备店长（云南）", "", "门店管培"))

    def test_content_production_direction(self):
        for title in ["米哈游 视频编导", "阿里巴巴 动漫制片", "游戏动画导演（2027届）", "视频剪辑专员(J25948)"]:
            self.assertTrue(cke.job_matches(title, "", "编导"), title)
        self.assertFalse(cke.job_matches("客户端开发工程师（PC端基础剪辑）", "", "编导"))

    def test_chip_verification_and_risk_directions(self):
        # 2026-09-23：与 JS 同步（tests/china-keyword-expansion.test.js 同名用例），爬虫侧的发现过滤走这里。
        for title in ["芯片验证工程师（上海）", "数字验证工程师-2027届校招", "Design Verification Engineer"]:
            self.assertTrue(cke.job_matches(title, "", "ic验证"), title)
        self.assertFalse(cke.job_matches("芯片设计工程师", "", "ic验证"))
        for title in ["信用风险实习生", "市场风险管理岗", "风险管理实习生"]:
            self.assertTrue(cke.job_matches(title, "", "风控"), title)
        self.assertFalse(cke.job_matches("阿里云智能-IDC风险运营专家-杭州", "", "风控"))
        self.assertEqual(cke.classify_job_function("市场风险实习生"), "金融业务")

    def test_generic_engineering_group_still_required_when_no_overlap(self):
        # 「硬件工程师」的"硬件"耗不尽查询、仍剩"工程师"三个实字 → 21 组必须保留，
        # 否则「硬件产品经理」「硬件采购专员」这类无关角色会被放行（2026-09-18 全量对拍实测过的红线）。
        self.assertFalse(cke.job_matches("硬件产品经理", "", "硬件工程师"))
        self.assertFalse(cke.job_matches("硬件采购专员", "", "硬件工程师"))
        self.assertTrue(cke.job_matches("嵌入式硬件工程师", "", "硬件工程师"))
        # 「机械工程师」的"工程"与"机械工程"重叠、可以压掉 21 组，纯英文标题也应召回。
        self.assertTrue(cke.job_matches("Principal Mechanical Engineer, Industrial Robotics Group", "", "机械工程师"))


if __name__ == "__main__":
    unittest.main()
