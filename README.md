# decay-rag — time belongs in the ranking, per chunk

**A 235-line, zero-dependency retrieval kernel, shipped in four shapes.** It insists on one thing only:

> **Timestamps belong to chunks, not to files.**

`score = 0.75 × similarity + 0.25 × decay`, 30-day half-life. No vector database, no `pip install`, no GPU, no embedding service. Just Python 3.

---

## Why "file time" is wrong

Almost everyone who adds time to retrieval reaches for the file's `mtime`. On the most common personal corpora that fails immediately:

**A diary, a weekly report, an append-only log — one big file that grows for years. Every chunk shares the same `mtime`, so the decay term does nothing.**

So the timestamp is decided per chunk, in this priority order:

1. **A date in the filename** — `decision_2026-11-06.md` → `2026-11-06` (most reliable; naming it is enough)
2. **The date inside the chunk that is *closest to* `mtime`** — not the first one
3. Shorthand forms like `Oct 31` / `10-31` (year inferred from `mtime`)
4. Nothing found → fall back to `mtime`

Rule 2 is the easy trap. A report often opens with "audit period: 2019-01-02 to 2025-12-31". Take the first date and the whole chunk is stamped 2019, decay ≈ 0, and it never ranks. **When a document was written is always near `mtime`; historical dates are always far from it.**

---

## Four shapes, one algorithm

| Directory | What it is | When to use it |
|---|---|---|
| [`core/`](core/) | **Single file** `decay_rag.py` (235 lines) + `demo.py` + tests | You want to read the algorithm, or lift `parse_chunk_ts()` into your own RAG |
| [`four_corpus/`](four_corpus/) | Multi-corpus runtime: four independent indexes (`code` / `finance` / `task` / `life`) with build / query / pre-work check CLIs | Your notes are split by topic and you do not want a diary line answering "docker build failed" |
| [`polyglot/`](polyglot/) | The same `SPEC.md` implemented six times — **C / C++ / Go / Java / JS / Python** — byte-identical output | You want to know whether this scoring survives a language change (it does, and the exercise found a real bug) |
| [`plugin/dsh/`](plugin/dsh/) | DeepSeek Harness plugin: retrieves and injects before every step, plus a `rag_search` tool for the model | You want an agent to read its own method library before starting work |

`spec/SPEC.md` is the only implementation contract (chunking, timestamps, hashing, scoring, output format). All six languages follow it.

---

## The numbers, as they are

Same corpus, same questions (19 held-out questions; the author did not write the wording):

| Shape | hit@1 | Note |
|---|---|---|
| `core/` zero-dependency character n-gram | **14/19 (74%)** | No model at all |
| `four_corpus/` hybrid + time + card prior | **17/19 (89%)** | 18/19 in the top three |
| Dense only (bge-m3) | 13/19 | 1.2 GB model |
| Dense + RRF fusion | 13/19 | Fusion is a **negative** optimisation here |
| bge-m3 hybrid + structural terms | 17/19 | Ties with row 2, at the cost of a model |

**What the multi-corpus split actually buys you** (8 labelled questions, 2 per corpus):

| Setting | Hits |
|---|---|
| Query the right corpus only | **1.00** |
| Query all four at once | **1.00** |
| Answer everything with the wrong corpus | 0.25 |

**Where it breaks** (one decoy per question that restates the question, worst case):

```
9 chunks -> 1.00    17 -> 0.62    25 -> 0.62    41 -> 0.50    137 -> 0.50
```

**A single near-duplicate decoy drops it to 62%.** This is a **needle retriever, not a semantic retriever**: unique, distinctly worded notes and it wins; a corpus of paragraphs that paraphrase the same sentence and it loses.

**Cross-language consistency** (600 chunks, single query):

| Go | C++ | C | Node.js | Java | Python |
|---|---|---|---|---|---|
| 95 ms | 118 ms | 161 ms | 356 ms | 384 ms | 1326 ms |

All six outputs share the **same md5**. That comparison earned its keep: the C port had a static 512-chunk array that overflowed at 600 chunks. The other five were fine.

---

## What it is not for

- **Synonyms**: "paused" and "protectively suspended" have nothing in common in character n-grams. Use an embedding model for that.
- **Multi-hop / aggregation**: "how many infra mistakes did I make this year" requires reading every chunk and counting, not ranking.
- **Large corpora**: brute-force cosine, no ANN. Above ~50k chunks, use something else.
- **As a product**: no UI, no PDF/Office parsing, no database, no conversation orchestration. For product-grade, look at LlamaIndex / LangChain / RAGFlow / Dify. What you get here is **200 lines you can read, change, and embed**.

---

## Layout

```
core/            single-file algorithm + tests + benchmark (read this first)
four_corpus/     multi-corpus runtime: build.py / ask.py / preflight.py
polyglot/        six ports + verify.sh (output must be byte-identical)
plugin/dsh/      DeepSeek Harness plugin (auto-inject + rag_search tool)
spec/SPEC.md     the only implementation contract
data/sample/     sample corpus for core/demo (fictional NAS migration notes)
LICENSE          BUSL 1.1 (algorithm and Python implementation)
LICENSES/        plugin/ is MIT
```

---

## Quick start

**1. Read the algorithm only (no dependencies)**

```bash
cd core && python demo.py
python -m unittest discover -s tests -v
```

**2. Multi-corpus (needs bge-m3 via Ollama)**

```bash
cd four_corpus
cp config.example.json config.json      # point it at your own four directories
python build.py --corpus code           # build each corpus once
python ask.py --corpus code "why does apt fail with 502"
python preflight.py "what should I read before starting"   # all three corpora, labelled by source
```

**3. Six-language consistency**

```bash
cd polyglot && ./verify.sh              # needs gcc/g++/go/javac/node/python3 locally
```

**4. DSH plugin**

```bash
# add plugin/dsh to your DSH profile's plugins, then point cordis.patch.yml
# at four_corpus/preflight.py and your python interpreter
```

---

## License

Algorithm and Python implementation: [BUSL 1.1](LICENSE) — free for personal, research and internal non-commercial use; Change Date 2030-11-16, converting to Apache-2.0. The `plugin/` directory is [MIT](LICENSES/plugin-MIT.txt) separately.

---

## What this repo merges

`decay-rag` (single-file core), `decay-rag-lite` (multi-corpus), `decay-rag-polyglot` (six languages), and `dsh-go-local-recall` / `dsh-rag-memory` (the plugin). The reason is simple: **they are four shapes of one idea, and splitting them only made readers jump four times.** The old repositories remain as read-only archives.