# -*- coding: utf-8 -*-
"""跑一遍示例：建索引 → 问同一个问题，只改半衰期，看排序怎么变。

    python demo.py
"""
import time
from decay_rag import build_index, parse_chunk_ts, search, fmt_ts, ngram_counts

ROOT = "data/sample"


def show(title, rows):
    print("\n" + title)
    for i, (score, sim, decay, ts, d) in enumerate(rows, 1):
        print("  [%d] %-26s %s  综合 %.3f（相似 %.3f × 时间 %.2f）"
              % (i, d["path"], fmt_ts(ts), score, sim, decay))


def main():
    docs = build_index(ROOT)
    print("切出 %d 块，它们的时间戳：\n" % len(docs))
    for d in sorted(docs, key=lambda x: -x["ts"]):
        print("  %s  %-26s %s" % (fmt_ts(d["ts"]), d["path"], d["text"][:24].replace("\n", " ")))

    # 同一个库、同一个问题：关掉时间项时旧方案赢，打开时间项后新方案赢
    q = "ZFS 校验和 快照 要多少内存"
    show("问题：%s｜--no-decay（只看内容，旧方案赢）" % q, search(docs, q, k=3, no_decay=True))
    show("同一问题｜默认（半衰期 30 天，新方案翻上来）", search(docs, q, k=3))
    show("同一问题｜--half-life 1（极端重新鲜度，可能翻过头）", search(docs, q, k=3, half_life=1))

    q3 = "现在用哪个方案"
    show("换个问法：%s｜默认" % q3, search(docs, q3, k=3))

    # 演示「为什么不能取第一个日期」：正文里写着 2019-01-02
    import os
    p = os.path.join(ROOT, "审计档案_2026-11-09.md")
    bad = parse_chunk_ts(open(p, encoding="utf-8").read(), p)
    print("\n正文写着 2019-01-02，但解析出来是 %s（离文件 mtime 最近的那个）" % fmt_ts(bad))


if __name__ == "__main__":
    main()
