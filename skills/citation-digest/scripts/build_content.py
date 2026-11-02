#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 citations.json + kimi.json + classify.json 合成 content.json（并可选导出 markdown）。

classify.json（由你/模型来判断，脚本只负责归类与拼装）:
{
  "categories": [
    {"name": "🧩 场景创新 / 问题创新", "desc": "一句话说明这条分类的判据",
     "papers": ["2503.14021", "10.1109/CVPR52734.2025.02766", "Exact Paper Title"]},
    ...
  ],
  "notes": {"<arxiv id 或标题>": "该篇没有 Kimi 总结时的补充说明（可选）"}
}
papers 里可以用 arXiv id / DOI / 标题（精确或包含匹配）。没被列到的论文会进「未分类」。

用法:
  python3 build_content.py --citations citations.json --kimi kimi.json \
      --classify classify.json --out content.json --md digest.md
"""
import argparse, json, re, sys


def norm(t):
    t = (t or "").lower()
    t = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def keys_of(p):
    ext = p.get("externalIds") or {}
    ks = [p.get("paperId", "")]
    if ext.get("ArXiv"):
        ks.append(ext["ArXiv"])
    if ext.get("DOI"):
        ks.append(ext["DOI"])
    ks.append(p.get("title", ""))
    return [k for k in ks if k]


def match(p, tokens):
    pk = [norm(k) for k in keys_of(p)]
    for t in tokens:
        tn = norm(t)
        if not tn:
            continue
        for k in pk:
            if k == tn or k.startswith(tn) or (len(tn) > 12 and (tn in k or k in tn)):
                return True
    return False


def meta_line(p):
    ext = p.get("externalIds") or {}
    bits = []
    if p.get("venue"):
        bits.append(f"{p['venue']} {p.get('year') or ''}".strip())
    elif p.get("year"):
        bits.append(str(p["year"]))
    if p.get("publicationDate"):
        bits.append(p["publicationDate"])
    bits.append(f"被引 {p.get('citationCount') or 0}")
    if ext.get("ArXiv"):
        bits.append(f"arXiv:{ext['ArXiv']}")
    elif ext.get("DOI"):
        bits.append(f"DOI:{ext['DOI']}")
    return " · ".join(bits)


def link_of(p):
    ext = p.get("externalIds") or {}
    if ext.get("ArXiv"):
        return f"https://arxiv.org/abs/{ext['ArXiv']}"
    if ext.get("DOI"):
        return f"https://doi.org/{ext['DOI']}"
    return f"https://www.semanticscholar.org/paper/{p.get('paperId','')}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--citations", default="citations.json")
    ap.add_argument("--kimi", default="kimi.json")
    ap.add_argument("--classify", default="classify.json")
    ap.add_argument("--out", default="content.json")
    ap.add_argument("--md")
    ap.add_argument("--title", help="覆盖根 toggle 标题（默认用源论文标题）")
    args = ap.parse_args()

    cit = json.load(open(args.citations))
    kimi = json.load(open(args.kimi)) if args.kimi else {"papers": {}, "missing": []}
    cls = json.load(open(args.classify))

    papers = cit.get("kept") or cit.get("by_citations") or []
    used, cats = set(), []

    for c in cls["categories"]:
        entries = []
        for p in papers:
            if p.get("paperId") in used:
                continue
            if match(p, c.get("papers") or []):
                used.add(p.get("paperId"))
                entries.append(p)
        cats.append({"name": c["name"], "desc": c.get("desc", ""), "papers": entries})

    rest = [p for p in papers if p.get("paperId") not in used]
    if rest:
        cats.append({"name": "❓ 未分类", "desc": "classify.json 里没有覆盖到，需要人工归类", "papers": rest})

    out_cats = []
    for c in cats:
        items = []
        for p in c["papers"]:
            ext = p.get("externalIds") or {}
            aid = ext.get("ArXiv")
            k = kimi["papers"].get(aid) if aid else None
            if not k:  # 非 arXiv 的 papers.cool venue 条目，key 是 49@2026@IJCAI 这种，按标题找
                k = next((v for v in kimi["papers"].values()
                          if norm(v.get("title")) == norm(p.get("title"))), None)
            if k:
                blocks, text = k["blocks"], k["text"]
                src = "kimi"
            else:
                notes = cls.get("notes") or {}
                note = next((notes[k] for k in keys_of(p) if k in notes), "")
                text = (p.get("abstract") or "").strip()
                blocks = [{"kind": "paragraph", "rt": [{"t": text, "b": False}]}] if text else []
                if not blocks and not note:
                    blocks = [{"kind": "paragraph",
                               "rt": [{"t": "（非 arXiv，papers.cool 无 Kimi 总结；S2 也没有摘要，需人工补充）", "b": False}]}]
                src = "fallback"
                if note:
                    blocks.append({"kind": "paragraph", "rt": [{"t": note, "b": False}]})
            items.append({
                "title": p["title"], "meta": meta_line(p), "url": link_of(p),
                "arxiv": aid or "", "source": src,
                "blocks": blocks, "text": text,
            })
        out_cats.append({"name": c["name"], "desc": c["desc"], "papers": items})

    src = cit["source"]
    note = (f"源论文：{src['title']}（{src.get('venue') or ''} {src.get('year') or ''}）"
            f"S2 被引 {src.get('citationCount')}；抓取到 {cit['total_records']} 条记录、去重后 "
            f"{cit['unique']} 篇，按规则保留 {len(papers)} 篇。"
            if cit.get("unique", 0) > len(papers) else
            f"源论文：{src['title']}（{src.get('venue') or ''} {src.get('year') or ''}）"
            f"S2 被引 {src.get('citationCount')}，共 {len(papers)} 篇引用。")
    note += " 正文为 papers.cool 的 Kimi 总结 Q1「这篇论文试图解决什么问题」原文。"

    content = {
        "root_title": args.title or src["title"],
        "source": src, "note": note, "categories": out_cats,
    }
    json.dump(content, open(args.out, "w"), ensure_ascii=False, indent=1)
    print(f"写入 {args.out}：" + "，".join(f"{c['name']} {len(c['papers'])} 篇" for c in out_cats))

    if args.md:
        lines = [f"# {content['root_title']}", "", f"> {note}", ""]
        for c in out_cats:
            lines += [f"## {c['name']}（{len(c['papers'])} 篇）", ""]
            if c["desc"]:
                lines += [f"*{c['desc']}*", ""]
            for p in c["papers"]:
                tag = "" if p["source"] == "kimi" else " ⚠️ 非 Kimi 总结"
                lines += ["<details>", f"<summary><b>{p['title']}</b> — {p['meta']}{tag}</summary>", ""]
                lines += [f"[{p['url']}]({p['url']})", ""]
                for b in p["blocks"]:
                    txt = "".join(("**" + s["t"] + "**") if s["b"] else s["t"] for s in b["rt"])
                    if b["kind"] == "heading_3":
                        lines.append(f"### {txt}")
                    elif b["kind"] == "bulleted_list_item":
                        lines.append(f"- {txt}")
                    else:
                        lines.append(txt)
                lines += ["", "</details>", ""]
        open(args.md, "w").write("\n".join(lines))
        print(f"写入 {args.md}")


if __name__ == "__main__":
    main()
