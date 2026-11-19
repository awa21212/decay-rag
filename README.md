# decay-rag — time belongs in the ranking, per chunk

**一个 235 行、零依赖的检索内核，四种形态。** 它只坚持一件事：

> **时间戳必须落在块上，不是落在文件上。**

`score = 0.75 × similarity + 0.25 × decay`，半衰期 30 天。没有向量库、没有 `pip install`、
没有 GPU、没有嵌入服务。只有 Python 3。

---

## 为什么"文件时间"是错的

每个人给检索"加时间"都是取文件的 `mtime`。这在最常见的个人语料上直接失效：

**一本日记、一份周报、一个追加型日志 —— 一个大文件被追加几年，每个块共享同一个 `mtime`，衰减等于没做。**

所以时间戳要按块决定，优先级是：

1. **文件名里的日期** —— `决策记录_2026-11-06.md` → `2026-11-06`（最可靠，起名就有）
2. **块内离 `mtime` 最近的那个日期** —— *不是第一个*
3. `Oct 31` / `10-31` 这类简写（年份按 `mtime` 推断）
4. 都找不到 → 回退 `mtime`

第 2 条是容易踩的点。一份报告常以「审计期间 2019-01-02 至 2025-12-31」开头；取第一个日期，
整块被标成 2019，衰减≈0，它永远排不上来。**写作时间总是靠近 `mtime`，历史日期总是远离它。**

---

## 四种形态（同一套算法）

| 目录 | 是什么 | 什么时候用它 |
|---|---|---|
| [`core/`](core/) | **单文件** `decay_rag.py`（235 行）+ `demo.py` + 测试 | 想读懂算法、或把 `parse_chunk_ts()` 抠出来移植到自己的 RAG |
| [`four_corpus/`](four_corpus/) | 多语料库运行版：`code` / `finance` / `task` / `life` 四套独立索引 + 建库、查询、开工前自查三个 CLI | 笔记按主题分家，不想让「docker 报错」被日记里的句子回答 |
| [`polyglot/`](polyglot/) | 同一份 `SPEC.md` 的 **C / C++ / Go / Java / JS / Python** 六种实现，输出逐字节一致 | 想知道这套打分能不能跨语言复现（能，而且因此抓出一个真 bug） |
| [`plugin/dsh/`](plugin/dsh/) | DeepSeek Harness 插件：每步前自动检索并注入，另给模型一个 `rag_search` 工具 | 想让 agent 每次开工前先读自己的方法库 |

`spec/SPEC.md` 是唯一的实现契约（切块、时间戳、哈希、打分、输出格式），六种语言都按它写。

---

## 数字，照实说

同一语料、同一批题（19 道留出题，作者不参与措辞）：

| 形态 | 命中第一 | 备注 |
|---|---|---|
| `core/` 零依赖字符 n-gram | **14/19（74%）** | 不需要任何模型 |
| `four_corpus/` 混合 + 时间 + 卡片优先 | **17/19（89%）** | 前三 18/19 |
| 纯向量（bge-m3） | 13/19 | 1.2 GB 模型 |
| 纯向量 + RRF 融合 | 13/19 | 融合在这里是**负**优化 |
| bge-m3 混合 + 结构项 | 17/19 | 与第二行同分，代价是模型 |

**多语料库真正解决的是什么**（8 道带标签题，每库 2 道）：

| 口径 | 命中 |
|---|---|
| 只查对的库 | **1.00** |
| 四个库一起查 | **1.00** |
| 用错的库答全部题 | 0.25 |

**它在哪崩**（每道题加 1 个"复述问题原话"的干扰块，最坏情况）：

```
9 块 → 1.00    17 块 → 0.62    25 块 → 0.62    41 块 → 0.50    137 块 → 0.50
```

**加一个近义干扰项就掉到 62%。** 这套方法是**针检索器，不是语义检索器**：
你的笔记各说各的、措辞独特 → 它赢；语料里全是复述同一句话的长段落 → 它输。

**跨语言一致性**（600 块，单次查询）：

| Go | C++ | C | Node.js | Java | Python |
|---|---|---|---|---|---|
| 95 ms | 118 ms | 161 ms | 356 ms | 384 ms | 1326 ms |

六份输出 **md5 相同**。这个对照本身抓到了一个真 bug：C 端口有个 512 块的静态数组，
600 块时溢出——其余五种语言都没事。

---

## 它不适合什么

- **同义词**：「暂停」和「保护性挂起」在字符 n-gram 里没关系。要这个就上嵌入模型。
- **多跳 / 汇总**：「我今年在基础设施上踩了几个坑」需要读完全部块再数，不是排序问题。
- **大语料**：暴力余弦没做 ANN，五万块以上请换方案。
- **当产品用**：没有 UI、没有 PDF/Office 解析、没有数据库、没有对话编排。
  要产品级看 LlamaIndex / LangChain / RAGFlow / Dify；这里给的是**能读懂、能改、能嵌进去的 200 行**。

---

## 目录

```
core/            单文件算法 + 测试 + 基准（最该先读这里）
four_corpus/     多语料库运行版：build.py / ask.py / preflight.py
polyglot/        六语言移植 + verify.sh（输出必须逐字节一致）
plugin/dsh/      DeepSeek Harness 插件（自动注入 + rag_search 工具）
spec/SPEC.md     唯一实现契约
data/sample/     core/demo 用的示例语料（虚构的 NAS 迁移记录）
LICENSE          BUSL 1.1（算法与 Python 实现）
LICENSES/        plugin/ 用 MIT
```

---

## 快速开始

**1. 只看算法（无依赖）**

```bash
cd core && python demo.py
python -m unittest discover -s tests -v
```

**2. 多语料库（需要 bge-m3，走 Ollama）**

```bash
cd four_corpus
cp config.example.json config.json      # 改成你自己的四个目录
python build.py --corpus code           # 每库建一次
python ask.py --corpus code "为什么 apt 拉包 502"
python preflight.py "开工前该看什么"     # 三个库一起查，带来源标注
```

**3. 六语言一致性**

```bash
cd polyglot && ./verify.sh              # 需要本地有 gcc/g++/go/javac/node/python3
```

**4. DSH 插件**

```bash
# 把 plugin/dsh 目录加到 DSH profile 的 plugins 下，然后在 cordis.patch.yml 里
# 指向 four_corpus/preflight.py 和你的 python 解释器
```

---

## 许可

算法与 Python 实现：[BUSL 1.1](LICENSE)（个人 / 研究 / 内部非商业免费；Change Date 2030-11-16，
转 Apache-2.0）。`plugin/` 目录单独用 [MIT](LICENSES/plugin-MIT.txt)。

---

## 这个仓合并自

`decay-rag`（单文件核心）、`decay-rag-lite`（多语料库）、`decay-rag-polyglot`（六语言）、
`dsh-go-local-recall` / `dsh-rag-memory`（插件）。合并原因很简单：**它们是同一件事的四种形态，
分仓库只会让读的人多跳四次。** 旧仓库保留只读存档。
