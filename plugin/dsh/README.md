# dsh-preflight · 方法库记忆

把本地 RAG 接进 DeepSeek Harness：每步开始前自动检索方法库并注入，另给模型一个 `rag_search` 工具。

- 四个语料库：`code` / `finance` / `task` / `life`
- 检索：bge-m3 向量 + 汉字二元组混合，`0.75 × 相似 + 0.25 × 时间衰减`，卡片优先
- 失败安全：任何异常都不会让会话报错，只会「这次没有经验可注入」

## 安装

```powershell
# 本地目录安装：Plugins → Add plugin → 选这个目录
```

行配置在 `cordis.patch.yml`，可调 `python` / `script` / `cwd` / `inject` / `k` / `tool` / `toolK`。

## 结构

```
package.json         # dsh.bundle.patch 指向 cordis.patch.yml
cordis.patch.yml     # 插入 preflight 行
lib/index.js         # 自动注入 + rag_search 工具
locale/{en,zh}.json  # 插件页标题与描述
docs/DETAIL.md       # 功能、配置、已知局限
icon.svg
```

## 维护

索引在 Harness 之外的本地目录，改完卡片要重建对应库，插件才会读到新内容。

详细说明见 [docs/DETAIL.md](docs/DETAIL.md)。
