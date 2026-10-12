"""Moka 岗位卡上的发布日期 → posted_at（_moka_card_posted_at / MokaAdapter.parse）。

治的病（2026-10-12 香港库实测）：Moka 在招 58,348 行的 posted_at 全是空的，而卡片上本来就写着发布时间。
同日老版门户翻页修复上线，一晚新入库 5,324 个岗，首见时间都是当晚——其中约三成卡片上写的是 2024 年及以前。

夹具 fixtures/moka_cards_posted_at.json 是同日从线上门户抓的卡片 innerText **原文**，每张卡的期望值是对着卡片人工写的。
钉两个方向：① 卡片上写了发布日期的不许丢；② 没写的、认不出的一律留空，不许从别处找一个日期填上。
"""
import json
import os
import unittest
from datetime import date

import normalizer
from adapters.china_ats import MokaAdapter, _moka_card_posted_at

_FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "moka_cards_posted_at.json")


def _load_cards():
    with open(_FIXTURE, encoding="utf-8") as f:
        return {c["id"]: c for c in json.load(f)["cards"]}


CARDS = _load_cards()


def _card(*lines):
    return "\n".join(lines)


class MokaPostedAtFixtureTest(unittest.TestCase):
    def test_every_real_card(self):
        self.assertGreaterEqual(len(CARDS), 14, "夹具被清空了？下面的循环会空转着通过")
        for card in CARDS.values():
            with self.subTest(card=card["id"], why=card["why"]):
                self.assertEqual(_moka_card_posted_at(card["text"]), card["posted_at"])

    def test_fixture_covers_both_directions(self):
        # 只有「写了的都认出来了」或只有「没写的都留空了」都不算数。
        dated = [c for c in CARDS.values() if c["posted_at"]]
        undated = [c for c in CARDS.values() if c["posted_at"] is None]
        self.assertGreaterEqual(len(dated), 8)
        self.assertGreaterEqual(len(undated), 3)


class MokaPostedAtRulesTest(unittest.TestCase):
    """认不出就留空：只认「该在的位置上、整行就是发布日期」的那一行。"""

    def test_the_three_spellings(self):
        for line in ("发布于 2026-10-09", "Posted on 2026-10-09"):
            with self.subTest(line=line):
                self.assertEqual(_moka_card_posted_at(_card("岗位", line, "全职", "全职", "|", "上海市", "上海市")),
                                 "2026-10-09")
        for line in ("发布时间：2026-10-09", "发布时间:2026-10-09"):
            with self.subTest(line=line):
                self.assertEqual(_moka_card_posted_at(_card("岗位", "全职技术类", "上海市", line)), "2026-10-09")

    def test_not_a_calendar_date(self):
        for line in ("发布于 2026-02-30", "发布于 2026-13-01", "发布于 0000-00-00"):
            with self.subTest(line=line):
                self.assertIsNone(_moka_card_posted_at(_card("岗位", line, "全职", "全职")))

    def test_anything_but_a_whole_date_is_left_empty(self):
        # 相对时间、缺日、行里还有别的字：都不去猜是哪一天。
        for line in ("发布于 3天前", "发布于 2026-10", "发布于 10-09", "发布于 2026-10-09 更新", "发布于"):
            with self.subTest(line=line):
                self.assertIsNone(_moka_card_posted_at(_card("岗位", line, "全职", "全职")))

    def test_date_sentence_in_the_body_is_not_the_publish_date(self):
        # 新版卡片没展示发布日期（标题后面直接是字段），正文里出现的日期不是这张卡的发布日。
        card = _card("诉讼律师", "法务 Legal", "法务 Legal", "|", "上海市", "上海市",
                     "发布于 2024-01-01", "本岗位长期有效")
        self.assertIsNone(_moka_card_posted_at(card))

    def test_old_spelling_at_the_end_of_a_long_card_is_body_text(self):
        # 老版卡片标题后面最多「标签行 + 地点行 + 发布时间」；更长的卡片是新版，它的末行是正文。
        card = _card("诉讼律师", "法务 Legal", "法务 Legal", "|", "上海市", "上海市",
                     "职位描述：负责公司诉讼案件。", "发布时间：2024-01-01")
        self.assertIsNone(_moka_card_posted_at(card))

    def test_old_layout_line_budget(self):
        # 边界：标题后面连发布时间在内 3 行认，4 行不认。
        self.assertEqual(_moka_card_posted_at(_card("岗位", "全职技术类", "上海市", "发布时间：2024-01-01")), "2024-01-01")
        self.assertIsNone(_moka_card_posted_at(_card("岗位", "全职技术类", "上海市", "急聘", "发布时间：2024-01-01")))

    def test_old_spelling_must_be_the_last_line(self):
        self.assertIsNone(_moka_card_posted_at(_card("岗位", "发布时间：2024-01-01", "上海市")))

    def test_badge_outside_the_word_list_still_leaves_the_date_on_the_first_line_after_the_title(self):
        # 角标文字租户自己定（这里是词表里没有的「Top」）：标题在第二行，发布日期在第三行。
        card = _card("Top", "品牌创意实习生", "发布于 2026-05-21", "上海市", "上海市")
        self.assertEqual(_moka_card_posted_at(card), "2026-05-21")

    def test_date_in_the_future_is_left_empty(self):
        # 发布日不可能晚于今天。留一天余量：卡片按浏览器所在时区渲染，抓取机的「今天」可能比它晚一天翻页。
        today = date(2026, 10, 12)
        card = lambda line: _card("岗位", line, "全职", "全职")  # noqa: E731
        self.assertEqual(_moka_card_posted_at(card("发布于 2026-10-12"), today=today), "2026-10-12")
        self.assertEqual(_moka_card_posted_at(card("发布于 2026-10-13"), today=today), "2026-10-13")
        self.assertIsNone(_moka_card_posted_at(card("发布于 2026-10-14"), today=today))
        self.assertIsNone(_moka_card_posted_at(card("发布于 2099-01-01")))   # 不传 today 时按当天算

    def test_empty_card(self):
        self.assertIsNone(_moka_card_posted_at(""))
        self.assertIsNone(_moka_card_posted_at(None))


class MokaPostedAtEndToEndTest(unittest.TestCase):
    """卡片 → MokaAdapter.parse → 入库清洗（与 run.py 同一条链）。"""

    BASE = "https://app.mokahr.com/social-recruitment/t/1"

    def _jobs(self, *card_ids):
        payload = {"_base": self.BASE,
                   "cards": [{"href": f"#/job/{i}", "text": CARDS[cid]["text"]} for i, cid in enumerate(card_ids)]}
        return MokaAdapter().parse(json.dumps(payload, ensure_ascii=False))

    def test_parse_fills_posted_at_from_the_card(self):
        jobs = self._jobs("old-layout-tags-place-date", "new-layout-date-after-title",
                          "tenant-hides-the-date-new-layout")
        self.assertEqual([j.posted_at for j in jobs], ["2019-06-12", "2023-06-29", None])

    def test_posted_at_reaches_the_row_written_to_the_database(self):
        job, = self._jobs("old-layout-tags-place-date")
        row = normalizer.normalize(job, source_id="s", company="测试公司", regions={"CN"})
        self.assertEqual(row["posted_at"], "2019-06-12")


if __name__ == "__main__":
    unittest.main()
