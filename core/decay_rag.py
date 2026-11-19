#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""decay_rag —— 带时间戳衰减的极简检索，只用 Python 标准库。

设计只有三行：

    相似度 = 0.72 × 余弦 + 0.28 × 字面重合
    衰减   = 0.5 ** (块龄 / 半衰期)
    综合分 = 0.75 × 相似度 + 0.25 × 衰减

块龄不是文件修改时间，而是**块自己的日期**（从正文里抽，见 parse_chunk_ts）。
这一条是整个东西的命门：日记、周报这类「一个大文件写到底」的语料，
文件 mtime 全是最后一次保存时间，衰减等于没开。

用法：
    python decay_rag.py build data/sample --index idx.json
    python decay_rag.py query "现在用哪个方案" --index idx.json
    python decay_rag.py query "..." --index idx.json --half-life 3 --no-decay
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
from collections import Counter

# ---------------------------------------------------------------- 可调参数
W_COS, W_LEX = 0.72, 0.28      # 相似度内部：语义/字面怎么分
W_SIM, W_TIME = 0.75, 0.25     # 综合分内部：内容/新鲜怎么分
HALF_LIFE_DAYS = 30.0          # 半衰期：30 天前的资料权重减半
CHUNK_SIZE = 700               # 切块大小（字符）
CHUNK_OVERLAP = 120
DATE_RE = re.compile(r"(20\d{2})-(\d{1,2})-(\d{1,2})")
MD_RE = re.compile(r"(?:^|[^\d])(\d{1,2})-(\d{1,2})(?:\s+|·|$)")
DAY = 86400.0


# ---------------------------------------------------------------- 切块
def split_chunks(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP):
    """按段落切，保留重叠，避免一句话被劈两半。"""
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    out, buf = [], ""
    for p in paras:
        if len(buf) + len(p) + 1 <= size:
            buf = (buf + "\n" + p).strip()
            continue
        if buf:
            out.append(buf)
        while len(p) > size:               # 单段超长，硬切
            out.append(p[:size])
            p = p[size - overlap:]
        buf = p
    if buf:
        out.append(buf)
    return out


# ---------------------------------------------------------------- 时间戳（核心）
def _dates_in(text: str):
    """抽出文本里所有可信日期（YYYY-MM-DD），返回 [(unix_ts, raw)]。"""
    res = []
    for m in DATE_RE.finditer(text):
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            res.append((time.mktime((y, mo, d, 0, 0, 0, 0, 0, -1)), m.group(0)))
        except (ValueError, OverflowError):
            continue
    return res


def parse_chunk_ts(text: str, path: str, mtime: float | None = None, head: int = 400) -> float:
    """块的时间戳。规则按优先级：

    1. 文件名里的日期（`决策记录_2026-11-06.md` → 2026-11-06）
    2. 块内**离文件 mtime 最近**的日期
    3. 正文里的 `10-31` 简写（年份取当前年，未来超过 30 天则退一年）
    4. 文件 mtime

    为什么第 2 条不是「第一个日期」：回测报告正文常写 `2019-01-02`（回测起点），
    取第一个会把整块标成 2019 年，衰减直接算成 0.00。文档的写作时间总是贴近 mtime，
    正文里的历史日期离得远——所以挑最近的，而不是挑第一个。
    """
    if mtime is None:
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            mtime = time.time()

    cands = [t for t, _ in _dates_in(os.path.basename(path))]
    cands += [t for t, _ in _dates_in(text[:head])]

    best, best_gap = None, None
    for t in cands:
        if t > mtime + 2 * DAY:      # 比文件还新的日期不可信（多半是笔误/未来计划）
            continue
        gap = abs(mtime - t)
        if best_gap is None or gap < best_gap:
            best, best_gap = t, gap
    if best is not None:
        return best

    m = MD_RE.search(text[:300])
    if m:
        mo, d = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12 and 1 <= d <= 31:
            now = time.localtime()
            for year in (now.tm_year, now.tm_year - 1):
                try:
                    cand = time.mktime((year, mo, d, 0, 0, 0, 0, 0, -1))
                except (ValueError, OverflowError):
                    continue
                if cand <= time.time() + 30 * DAY:
                    return cand

    return mtime


# ---------------------------------------------------------------- 向量与相似度
def ngram_counts(text: str, ns=(2, 3)) -> Counter:
    t = re.sub(r"\s+", "", text.lower())
    c = Counter()
    for n in ns:
        for i in range(len(t) - n + 1):
            c[t[i:i + n]] += 1
    return c


def cosine(a: Counter, b: Counter) -> float:
    if not a or not b:
        return 0.0
    common = set(a) & set(b)
    dot = sum(a[g] * b[g] for g in common)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb + 1e-12)


def overlap(a: Counter, b: Counter) -> float:
    """命中了查询里多少种二元组（召回向，不惩罚长文档）。"""
    if not a:
        return 0.0
    return len(set(a) & set(b)) / len(a)


# ---------------------------------------------------------------- 索引
def build_index(root: str, exts=(".md", ".txt"), index: str | None = None):
    docs = []
    for dirpath, _, files in os.walk(root):
        for f in sorted(files):
            if not f.lower().endswith(exts) or f.startswith(("_", ".")):
                continue
            p = os.path.join(dirpath, f)
            try:
                text = open(p, encoding="utf-8", errors="ignore").read()
            except OSError:
                continue
            try:
                mtime = os.path.getmtime(p)
            except OSError:
                mtime = time.time()
            for i, c in enumerate(split_chunks(text)):
                docs.append({
                    "path": os.path.relpath(p, root),
                    "chunk": i,
                    "ts": parse_chunk_ts(c, p, mtime),
                    "text": c,
                })
    for d in docs:
        d["vec"] = dict(ngram_counts(d["text"]))

    if index:
        json.dump(docs, open(index, "w", encoding="utf-8"), ensure_ascii=False)
    return docs


def load_index(index: str):
    docs = json.load(open(index, encoding="utf-8"))
    for d in docs:
        d["vec"] = Counter(d.pop("vec"))
    return docs


# ---------------------------------------------------------------- 检索
def search(docs, query: str, k: int = 5, half_life: float = HALF_LIFE_DAYS,
           no_decay: bool = False, hours: float = 0.0, newest: bool = False,
           current_only: bool = False, now: float | None = None):
    now = time.time() if now is None else now
    q = ngram_counts(query)

    scored = []
    for d in docs:
        ts = d["ts"]
        if hours and ts < now - hours * 3600:
            continue
        cos = cosine(q, d["vec"])
        lex = overlap(q, d["vec"])
        sim = W_COS * cos + W_LEX * lex
        age = max(0.0, (now - ts) / DAY)
        decay = 0.5 ** (age / max(half_life, 1e-9))
        score = sim if no_decay else W_SIM * sim + W_TIME * decay
        scored.append((score, sim, decay, ts, d))

    if newest:
        scored.sort(key=lambda x: -x[3])
    else:
        scored.sort(key=lambda x: -x[0])

    if current_only:
        seen, uniq = set(), []
        for row in scored:
            if row[4]["path"] in seen:
                continue
            seen.add(row[4]["path"])
            uniq.append(row)
        scored = uniq
    return scored[:k]


def fmt_ts(ts: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(ts))


# ---------------------------------------------------------------- CLI
def cmd_build(a):
    docs = build_index(a.root)
    if a.index:
        json.dump([{kk: (dict(vv) if kk == "vec" else vv) for kk, vv in d.items()} for d in docs],
                  open(a.index, "w", encoding="utf-8"), ensure_ascii=False)
    fresh = sum(1 for d in docs if (time.time() - d["ts"]) / DAY <= 3)
    print("[ok] %d 块 -> %s（其中 %d 块在 3 天内，%d 块更旧）"
          % (len(docs), a.index or "(仅内存)", fresh, len(docs) - fresh))


def cmd_query(a):
    docs = load_index(a.index) if a.index else build_index(a.root)
    rows = search(docs, a.q, k=a.k, half_life=a.half_life, no_decay=a.no_decay,
                  hours=a.hours, newest=a.newest, current_only=a.current_only)
    if not rows:
        print("没有命中（放宽 --hours）")
        return
    newest_in = max(r[3] for r in rows)
    print("\n== %s ==" % a.q)
    print("   命中 %d 块 · 结果里最新 %s" % (len(rows), fmt_ts(newest_in)))
    for i, (score, sim, decay, ts, d) in enumerate(rows, 1):
        head = "[%d] %s#%d" % (i, d["path"], d["chunk"])
        detail = "" if a.newest else "  综合 %.3f（相似 %.3f × 时间 %.2f）" % (score, sim, decay)
        print("\n%s  %s%s" % (head, fmt_ts(ts), detail))
        print("    " + d["text"][:200].replace("\n", " "))


def main(argv=None):
    ap = argparse.ArgumentParser(description="时间衰减检索（纯标准库）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="建索引")
    b.add_argument("root", nargs="?", default="data/sample")
    b.add_argument("--index", default="idx.json")
    b.set_defaults(func=cmd_build)

    q = sub.add_parser("query", help="检索")
    q.add_argument("q")
    q.add_argument("--index", default="idx.json")
    q.add_argument("--root", default="data/sample")
    q.add_argument("-k", type=int, default=5)
    q.add_argument("--half-life", type=float, default=HALF_LIFE_DAYS)
    q.add_argument("--no-decay", action="store_true")
    q.add_argument("--hours", type=float, default=0.0)
    q.add_argument("--newest", action="store_true")
    q.add_argument("--current-only", action="store_true")
    q.set_defaults(func=cmd_query)

    a = ap.parse_args(argv)
    a.func(a)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
