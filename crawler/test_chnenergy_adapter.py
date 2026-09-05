# -*- coding: utf-8 -*-
import json
import unittest

from adapters.chnenergy import ChnenergyAdapter, _parse_detail, _parse_list_items


# 取自 2026-09-05 线上列表页的真实卡片结构（含那份注释掉的同构 <a>、以及 `title =` 带空格的写法）。
LIST_HTML = """
<ul>
<li class="list-group-item">
  <div class="col-md-4">
    <!-- <h3> <a class="text-red" href="/annc/showgw?id=5a798bfe-a4d4-0be4-e063-98b4d40a088a" title="仪表检维修">仪表检维修</a> </h3> -->
    <h3> <a class="text-red" href="/annc/showgw?id=5a798bfe-a4d4-0be4-e063-98b4d40a088a" title="仪表检维修">仪表检维修</a> </h3>
    <ul class="list-inline">
      <li title="全日制硕士研究生及以上学历">全日制硕士...</li>
      <li>|</li>
      <li title ="机械设计制造及其自动化,自动化">机械设计制...</li>
    </ul>
  </div>
  <div class="col-md-6 row">
    <div class="col-md-12 row"><h5 title="中国神华煤制油化工有限公司鄂尔多斯煤制油分公司本部">中国神华煤制油...</h5></div>
    <div class="col-md-12 row"><ul class="list-inline"><li>内蒙古鄂尔多斯</li><li>招聘人数：12</li></ul></div>
  </div>
  <p class="text-gay">报名截止日期：2026-10-07</p>
</li>
<li class="list-group-item">
  <div class="col-md-4">
    <h3> <a class="text-red" href="/annc/showgw?id=5a798bfe-a4d1-0be4-e063-98b4d40a088a" title="动设备检维修">动设备检维修</a> </h3>
    <ul class="list-inline"><li title="大学本科">大学本科</li></ul>
  </div>
  <div class="col-md-6 row">
    <div class="col-md-12 row"><h5 title="国家能源集团宁夏煤业有限责任公司">国家能源集团宁夏煤业...</h5></div>
    <div class="col-md-12 row"><ul class="list-inline"><li>宁夏银川</li><li>招聘人数：3</li></ul></div>
  </div>
  <p class="text-gay">报名截止日期：2026-10-07</p>
</li>
</ul>
"""

DETAIL_OK = ("<html><body><div>招聘岗位：仪表检维修</div><div>岗位职责 负责生产装置仪表管理。 "
             "岗位要求 学历要求：大学本科</div><footer>国家能源投资集团有限责任公司</footer></body></html>")
DETAIL_GONE = "<html><body><div>× 错误提示 查看岗位信息发生错误，请重试或者联系管理员。 关闭</div></body></html>"


class ChnenergyAdapterTest(unittest.TestCase):
    def test_列表抽出逐岗_id_与全文字段(self):
        rows = _parse_list_items(LIST_HTML)
        self.assertEqual(len(rows), 2)
        first = rows[0]
        self.assertEqual(first["id"], "5a798bfe-a4d4-0be4-e063-98b4d40a088a")
        self.assertEqual(first["title"], "仪表检维修")
        # 列表把学历/专业/单位截断成「…」显示，全文只在 title 属性里——必须取属性。
        self.assertEqual(first["education"], "全日制硕士研究生及以上学历")
        self.assertEqual(first["major"], "机械设计制造及其自动化,自动化")
        self.assertEqual(first["unit"], "中国神华煤制油化工有限公司鄂尔多斯煤制油分公司本部")
        self.assertEqual(first["location"], "内蒙古鄂尔多斯")
        self.assertEqual(first["deadline"], "2026-10-07")

    def test_专业缺失时不会把工作地点错当专业(self):
        # 第二张卡只有「学历」一项、没有专业：两个 ul 必须分开取，拍平会让下标前移。
        second = _parse_list_items(LIST_HTML)[1]
        self.assertEqual(second["education"], "大学本科")
        self.assertEqual(second["major"], "")
        self.assertEqual(second["location"], "宁夏银川")

    def test_注释掉的同构锚点不产生重复行(self):
        self.assertEqual(len({r["id"] for r in _parse_list_items(LIST_HTML)}), 2)

    def test_parse产出可点jd_url且不覆盖company(self):
        payload = json.dumps({"jobs": [dict(r, _job_type="校招") for r in _parse_list_items(LIST_HTML)]})
        jobs = ChnenergyAdapter().parse(payload)
        self.assertEqual(len(jobs), 2)
        self.assertEqual(
            jobs[0].jd_url,
            "https://zhaopin.chnenergy.com.cn/annc/showgw?id=5a798bfe-a4d4-0be4-e063-98b4d40a088a")
        self.assertEqual(jobs[0].job_type, "校招")
        self.assertEqual(jobs[0].education, "全日制硕士研究生及以上学历")
        self.assertEqual(jobs[0].deadline, "2026-10-07")
        # company 必须留空继承 sources.company：招聘单位是子公司，写进去会掉出 %国家能源% 口径。
        self.assertEqual(jobs[0].company, "")
        self.assertIn("中国神华煤制油化工", jobs[0].summary)

    def test_id前8位相同的两个岗不会被当成同一个(self):
        # Oracle GUID 前缀共享；按前 8 位截断去重会把整页岗位压成 1 个。
        rows = _parse_list_items(LIST_HTML)
        self.assertEqual(rows[0]["id"][:8], rows[1]["id"][:8])
        self.assertNotEqual(rows[0]["id"], rows[1]["id"])

    def test_详情正文截掉页脚版权行(self):
        body = _parse_detail(DETAIL_OK)
        self.assertIn("负责生产装置仪表管理", body)
        self.assertNotIn("国家能源投资集团有限责任公司", body)

    def test_不存在的岗位详情返回None(self):
        self.assertIsNone(_parse_detail(DETAIL_GONE))

    def test_半截页面不判死(self):
        # 错误壳文案 + 仍有「招聘岗位」= 半截数据，宁可漏判不可错杀。
        half = DETAIL_GONE.replace("</body>", "<div>招聘岗位：仪表检维修</div><div>岗位职责 X</div></body>")
        self.assertIsNotNone(_parse_detail(half))

    def test_parse_容忍脏输入(self):
        adapter = ChnenergyAdapter()
        self.assertEqual(adapter.parse("not json"), [])
        self.assertEqual(adapter.parse(json.dumps({"jobs": [{"id": "", "title": "x"}]})), [])


if __name__ == "__main__":
    unittest.main()
