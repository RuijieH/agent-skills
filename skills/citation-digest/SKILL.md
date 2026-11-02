---
name: citation-digest
description: 给定一篇论文，抓它的引用列表（Semantic Scholar，含被引数），抓每篇的 papers.cool Kimi 总结（只取「试图解决什么问题」原文），按给定类别归类，输出 markdown 或发布到 Notion（论文命名根 toggle → 分类 toggle → 每篇一个 toggle）。Use when the user asks 引用/被引/citing papers/literature digest 并希望按主题分类或写进 Notion。
---

# 引用文献速览（citation-digest）

输入一篇论文，输出「谁引用了它 + 每篇在解决什么问题 + 按类别分组」，落成 markdown 或 Notion 页面。

流水线四步，脚本已经封装好，**不要**重新发明：

```
s2_citations.py  →  citations.json   谁引用了它（含被引数/日期/DOI/arXiv）
kimi_q1.py       →  kimi.json        每篇的 Kimi Q1 原文（结构化块）
（你来判断）      →  classify.json    分类结果
build_content.py →  content.json + digest.md
notion_publish.py→  Notion 页面
```

## 0. 前置

- S2 key：优先 `$SEMANTIC_SCHOLAR_API_KEY`，其次 `--key`，最后 `~/.env/semantic-scholar`。没 key 也能跑，但 429 会很多，脚本会自动重试（8 次 × 12s）。
- Notion token：`~/.notion-token` 或 `$NOTION_TOKEN`；目标页必须先 share 给这个 integration，否则 search 找不到。

## 1. 抓引用

```bash
python3 scripts/s2_citations.py --title "MP-GUI: Modality Perception with MLLMs for GUI Understanding" --out citations.json
# 也可以 --arxiv 2503.14021 / --paper-id 0e931ba8...
```

脚本内建三条你一定会踩的规则：

1. **去重**：S2 常把同一篇 arXiv 论文返回两条（`A Survey on ...` 和 `A Summary on ...`，一条带 ArXiv、一条只有 DOI `10.48550/arXiv.xxxx`）。按 arXiv id → DOI → 标题去重，保留被引高的那条。
2. **超过 20 篇只留两个 top10**：`--max-total 20 --top 10`，保留「被引数 top10」∪「日期 top10」。默认已开，别自己再筛。
3. **标题匹配**：搜索接口取 token 重合度最高的结果；分数 <0.55 会在 stderr 列出候选，让用户确认是不是同一篇。

先看 `citations.json` 里的 `source.citationCount`，这是要汇报的「被引数」。

## 2. 抓 Kimi 总结

```bash
python3 scripts/kimi_q1.py --in citations.json --out kimi.json --sleep 10 --resume
```

- 走 `POST https://papers.cool/arxiv/kimi?paper=<arxiv_id>`（就是本机 papers-cool MCP 的底层实现），必须带 `User-Agent` / `Origin` / `Referer` 头，否则被挡。
- 返回 HTML FAQ，**只取 Q1「这篇论文试图解决什么问题？」**，按结构转成块：`###` → heading_3、`- ` → bulleted_list_item、`**bold**` → 加粗。原文照搬，不压缩、不改写。
- **papers.cool 不止收 arXiv**，还有 venue 板块：`/venue/<CODE>.<YEAR>`，CODE ∈ AAAI/ACL/COLM/COLT/CoRL/CVPR/ECCV/EMNLP/ICCV/ICLR/ICML/IJCAI/INTERSPEECH/IWSLT/MICCAI/MLSYS/NAACL/NDSS/NeurIPS/OSDI/UAI。脚本对没有 arXiv id 的论文会自动走这条兜底：`/venue/<CODE>.<YEAR>?show=5000` 列表页按 `id="title-<pid>"` 匹配标题拿到 paper id（形如 `49@2026@IJCAI`，IJCAI 的序号就是 DOI 尾号），再 `POST /venue/kimi?paper=<pid>`，返回同样的 FAQ HTML。venue 列表页默认只给 25 条，必须带 `?show=`。
- 两条路都走不通的（IEEE MIPR/AIoTC 这类 papers.cool 没收的会）才进 `missing`，退回摘要或标题，**必须在页面上标注**「非 Kimi 总结」——`build_content.py`/`notion_publish.py` 已对 `source != "kimi"` 自动加 ⚠️ 标记，再在 `classify.json` 的 `notes` 里写清原因。
- `--sleep 10` 比 2 稳；没缓存的论文 Kimi 要现算，单篇可能 60-90s。每篇抓完就写 `--out`，被中断后加 `--resume` 续抓。
- ⚠️ **别用 `pkill -f kimi_q1.py`**：多个 Claude 会话同时跑这个技能时会互相误杀（实测丢过 26 篇已抓好但未落盘的结果）。要在后台跑就先 `cp scripts/kimi_q1.py <scratchpad>/pcfetch_<会话号>.py`，用独立进程名。

## 3. 分类（你来做，脚本不做）

写 `classify.json`：

```json
{
  "categories": [
    {"name": "🧩 场景创新 / 问题创新", "desc": "新任务、新基准、新评测维度，或重新定义了要解决的问题",
     "papers": ["2503.14021", "10.1109/CVPR52734.2025.02766", "Exact Title"]},
    {"name": "🔧 技术改进", "desc": "问题已知，贡献在方法/训练流程/系统/架构",
     "papers": ["..."]},
    {"name": "📚 仅综述", "desc": "不提出新方法或新任务，价值在脉络与开放问题",
     "papers": ["..."]}
  ],
  "notes": {"2504.20464": "该篇 S2 有两条重复记录，已合并"}
}
```

`papers` 里写 arXiv id / DOI / 标题都行（精确或包含匹配）。没覆盖到的会自动进「❓ 未分类」，**不会静默丢**。

判据（用户没另说时用这三条）：

- **场景创新 / 问题创新**：提出新任务、新 benchmark、新的评测维度（如「只看终态不够，要看过程」）、或把某现象重新定义成一个问题（如「工具挂了却不用」）。
- **技术改进**：问题已被公认，贡献是方法、训练流程、系统实现、架构。
- **仅综述**：Survey / Review / 立场文章，不提出可实验的新方法。
- 边界情况（benchmark 到底算问题创新还是单独一类、分析型论文归哪）——先按上面判，然后在回复里把判断理由说一句，别默默归类。

正文标签：普通论文用「试图解决的问题」，综述用「核心洞见」——但既然 Q1 原文照搬，通常**不加标签**，让原文自己说话。

## 4. 拼装 + 落盘

```bash
python3 scripts/build_content.py --citations citations.json --kimi kimi.json \
    --classify classify.json --out content.json --md digest.md
```

## 5. 发 Notion

```bash
python3 scripts/notion_publish.py --content content.json --page-title "topic论文阅读"
# 或 --page-id xxx；要覆盖已有内容加 --replace
```

结构固定为：**一个以论文命名的根 toggle** → 说明段落 + 三个分类 toggle → 每篇论文一个 toggle（第一行灰色元信息：`发表处 · 日期 · 被引 N · arXiv:xxx`，可点；下面是 Q1 原文块）。

## 坑（都是实测踩过的）

| 症状 | 原因 / 解法 |
|---|---|
| `POST /v1/blocks/{id}/children` → `400 invalid_request_url` | 这个 integration 只吃 **PATCH** 追加；`notion_publish.py` 已经用 PATCH |
| 想「移动」已有 block | Notion 没有 move API，只能重建：读旧 block → 在新父级重建 → 删旧 block |
| 删 block 报 `Can't edit block that is archived` | 用 `DELETE /v1/blocks/{id}`（`PATCH {archived:true}` 之后就不能再改它） |
| 单个 rich_text 超长 | 每段 ≤2000 字符；`seg()` 已自动按 1900 切成多段（退回摘要的长英文 abstract 必踩，实测 2063 字符）|
| `PATCH /blocks/{id}/children` → `400 ... start_cursor provided is invalid` | Notion 最终一致性抖动：刚建好的块马上往里追加就可能报这个，**写入其实常常已经成功**，紧接着 GET children 还可能读到 0 子块。`req()` 已对这个 400 退避重试；排查时别急着重发整页，先按根 toggle 遍历看实际结构 |
| 重发整页前 | 脚本不幂等，直接重跑会多出一个根 toggle。先 `DELETE /v1/blocks/<上次的 root toggle id>`（日志里的 `root toggle:` 行），再重跑 |
| 一次 append 太多 | 每个请求 ≤100 blocks（脚本按 80 切） |
| 嵌套建不出来 | 单次请求最多两层：toggle 的 children 里再套 toggle 可以，三层以上要分次 append |
| S2 一直 429 | 正常，退避重试；并行请求会更容易挂，串行 + sleep |

## 收工前自检

- [ ] `citations.json.source.citationCount` 和实际列出的篇数对得上（<=20 全列；>20 是两榜并集）
- [ ] 每篇都有元信息行（被引数必填），有 arXiv 的有可点链接
- [ ] 没有 Kimi 原文的篇目都标了原因（⚠️ 标记 + `notes`）
- [ ] Notion 顶层只有一个根 toggle（没有重发留下的重复）
- [ ] 分类条数 + 未分类 = 总篇数
- [ ] Notion 上抽查一个 toggle：标题 → 元信息 → Q1 原文（小标题/列表/粗体都在）
