# -*- coding: utf-8 -*-
"""unittest：三件事必须成立。

1. 块时间不是文件 mtime，也不是正文里第一个日期
2. 衰减能把「更像但太旧」压给「稍弱但新鲜」
3. 关掉时间项时，排序只由内容决定
"""
import os
import tempfile
import time
import unittest

from decay_rag import build_index, parse_chunk_ts, search, split_chunks, ngram_counts

DAY = 86400.0


def _touch(path, text, age_days=0.0):
    open(path, "w", encoding="utf-8").write(text)
    t = time.time() - age_days * DAY
    os.utime(path, (t, t))
    return path


class TestChunkTs(unittest.TestCase):
    def test_nearest_to_mtime_not_first_date(self):
        """正文第一篇写 2019-01-02（审计区间起点），文件名是 2026-11-09 → 取 2026-11-09。"""
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "审计档案_2026-11-09.md")
            _touch(p, "审计区间 2019-01-02 至 2025-12-31，结论：单盘更省事。", age_days=0.5)
            ts = parse_chunk_ts(open(p, encoding="utf-8").read(), p)
            self.assertEqual(time.strftime("%Y-%m-%d", time.localtime(ts)), "2026-11-09")

    def test_falls_back_to_mtime(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "no_date.md")
            _touch(p, "这里面一个日期都没有。", age_days=10)
            ts = parse_chunk_ts(open(p, encoding="utf-8").read(), p)
            self.assertAlmostEqual(ts, os.path.getmtime(p), delta=2)

    def test_body_date_when_no_filename_date(self):
        """文件名没日期，正文写 10-31，mtime 也是那天附近 → 认 10-31。"""
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "日记.md")
            _touch(p, "今天的三件事（10-31 22:10）：把动量池改回 20 只。", age_days=1)
            ts = parse_chunk_ts(open(p, encoding="utf-8").read(), p)
            self.assertEqual(time.strftime("%m-%d", time.localtime(ts)), "10-31")


class TestDecayRanking(unittest.TestCase):
    def setUp(self):
        self.docs = [
            {"path": "old.md", "chunk": 0, "ts": time.time() - 60 * DAY,
             "text": "双盘 镜像 改 单盘", "vec": ngram_counts("双盘 镜像 改 单盘")},
            {"path": "new.md", "chunk": 0, "ts": time.time() - 0.2 * DAY,
             "text": "防守池 换成国债黄金", "vec": ngram_counts("防守池 换成国债黄金")},
        ]

    def test_equal_content_newer_wins(self):
        """内容一模一样时，新的必须排在前面——这是时间项最低限度的承诺。"""
        same = "这一段内容完全相同，用来验证时间项。"
        docs = [
            {"path": "old.md", "chunk": 0, "ts": time.time() - 90 * DAY, "text": same, "vec": ngram_counts(same)},
            {"path": "new.md", "chunk": 0, "ts": time.time() - 1 * DAY, "text": same, "vec": ngram_counts(same)},
        ]
        rows = search(docs, "验证时间项", k=2)
        self.assertEqual(rows[0][4]["path"], "new.md")
        self.assertAlmostEqual(rows[0][1], rows[1][1], delta=0.01)   # 相似度相同
        self.assertGreater(rows[0][2], rows[1][2])                   # 差距全在时间

    def test_no_decay_makes_same_content_tie(self):
        same = "内容相同就没有排序依据。"
        docs = [
            {"path": "a.md", "chunk": 0, "ts": time.time() - 90 * DAY, "text": same, "vec": ngram_counts(same)},
            {"path": "b.md", "chunk": 0, "ts": time.time() - 1 * DAY, "text": same, "vec": ngram_counts(same)},
        ]
        rows = search(docs, "排序依据", k=2, no_decay=True)
        self.assertAlmostEqual(rows[0][0], rows[1][0], delta=1e-9)

    def test_decay_weight_is_half_at_half_life(self):
        d = {"path": "x.md", "chunk": 0, "ts": time.time() - 30 * DAY,
             "text": "abc", "vec": ngram_counts("abc")}
        rows = search([d], "abc", k=1, half_life=30.0)
        self.assertAlmostEqual(rows[0][2], 0.5, delta=0.01)

    def test_runaway_scores_stay_in_range(self):
        d = {"path": "x.md", "chunk": 0, "ts": time.time(), "text": "abc", "vec": ngram_counts("abc")}
        rows = search([d], "abc", k=1)
        self.assertLessEqual(rows[0][0], 1.0)
        self.assertGreaterEqual(rows[0][0], 0.0)


class TestChunking(unittest.TestCase):
    def test_chunks_respect_size(self):
        text = "\n\n".join("段落%d：" % i + "字" * 50 for i in range(40))
        chunks = split_chunks(text, size=200, overlap=20)
        self.assertTrue(all(len(c) <= 200 for c in chunks))
        self.assertGreater(len(chunks), 5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
