# agent-skills

给 Claude Code / DeepSeek Harness（DSH）/ Codex 这类编码 agent 用的 **skill 集合**，外加一份通用的编码准则。

skill 就是一段可复用的任务说明书：放进 `~/.claude/skills/`（或 DSH 的 `~/.dsh/skills/`）后，agent 会在任务匹配时自动加载。

## 内容

| 路径 | 说明 |
|---|---|
| [`skills/citation-digest/`](skills/citation-digest/) | 给定一篇论文，抓它的被引列表（Semantic Scholar，含被引数），抓每篇的 papers.cool Kimi 总结（只取「试图解决什么问题」原文），按主题归类，输出 markdown 或发到 Notion |
| [`skills/autoresearch/`](skills/autoresearch/) | 自主研究编排器：主 agent 只负责提假设/读结果/改假设，把环境准备、改代码、跑实验全部交给后台 worker 子 agent，每个 worker 跑在独立 git worktree 里 |
| [`AGENTS.md`](AGENTS.md) / [`CLAUDE.md`](CLAUDE.md) | 同一份编码准则（内容完全相同，只是不同 agent 认不同文件名）：先想后写、简洁至上、外科手术式修改、目标导向、记录管理、环境管理 |

## 安装

```bash
git clone https://github.com/RuijieH/agent-skills.git
cd agent-skills

# Claude Code
cp -r skills/* ~/.claude/skills/

# DeepSeek Harness
cp -r skills/* ~/.dsh/skills/

# 全局编码准则（二选一，内容一样）
cp AGENTS.md ~/.claude/CLAUDE.md
cp AGENTS.md ~/AGENTS.md
```

装好后 `/citation-digest`、`/autoresearch` 即可用（或用自然语言触发）。

## citation-digest

四步流水线，脚本已封装，**不要重新发明**：

```
s2_citations.py  →  citations.json   谁引用了它（含被引数/日期/DOI/arXiv）
kimi_q1.py       →  kimi.json        每篇的 Kimi Q1 原文（结构化块）
（agent 判断）    →  classify.json    分类结果
build_content.py →  content.json + digest.md
notion_publish.py→  Notion 页面
```

```bash
cd skills/citation-digest
python3 scripts/s2_citations.py --title "MP-GUI: Modality Perception with MLLMs for GUI Understanding" --out citations.json
python3 scripts/kimi_q1.py --in citations.json --out kimi.json --sleep 10 --resume
# 写 classify.json 后
python3 scripts/build_content.py --citations citations.json --kimi kimi.json --classify classify.json --out content.json --md digest.md
python3 scripts/notion_publish.py --content content.json --page-title "topic论文阅读"
```

- **依赖**：只要 `python3`（纯标准库，无第三方包）。
- **可选凭证**：Semantic Scholar key（`$SEMANTIC_SCHOLAR_API_KEY`，或 `~/.env/semantic-scholar`，没有也能跑但 429 变多）；Notion token（`$NOTION_TOKEN` 或 `~/.notion-token`），且目标页要先 share 给该 integration。
- **坑**：Notion 的块操作、`papers.cool` 的 venue 兜底、超长 rich_text 切段等实测问题都写在 `SKILL.md` 末尾的表格里。

## autoresearch

把 [karpathy/autoresearch](https://github.com/karpathy/autoresearch) 的「指标优化闭环」泛化成任意项目可用的自主研究编排器。

- **主 agent 是大脑**：提假设、读结果、分析、改假设、决定下一个实验。
- **worker 是手**：环境准备、改代码、跑实验全部交给后台子 agent，各自在独立 worktree，最后回一份 JSON 结果。

两种模式：`grind`（单 worker 贪心压指标）、`research`（假设驱动，串行或并行）。

```bash
# 在任意项目里
/autoresearch init        # 建 .autoresearch/ 目录与 config
/autoresearch grind       # 经典闭环
/autoresearch research    # 假设驱动
/autoresearch status      # 看进度
```

所有管道逻辑都在 `scripts/ar.sh`（`init|prep|status|collect|list|cleanup`），worker 的 prompt 模板在 `templates/`。

- **依赖**：`bash`、`git`（需支持 `git worktree`），以及一个**支持后台子 agent** 的 agent 运行时（Claude Code 的 Agent tool / DSH 的 subagent）。
- **注意**：worker 会执行项目里的任意代码，请只在可信仓库、且 agent 处于自动批准模式下运行。远程 GPU 执行的同步方式由你按项目自己写进 `config.json` 的 `setup_cmd`/`run_cmd`，框架不内置。

## 许可

MIT，见 [LICENSE](LICENSE)。`autoresearch` 的思路来自 [karpathy/autoresearch](https://github.com/karpathy/autoresearch)（MIT）。
