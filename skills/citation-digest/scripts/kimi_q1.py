#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 papers.cool 抓每篇论文的 Kimi 总结，只取 Q1「这篇论文试图解决什么问题？」原文。

papers.cool 除 arXiv 还收录顶会 venue（ICLR/NeurIPS/CVPR/IJCAI/AAAI/ACL...），
没有 arXiv id 的论文会按 venue+year 在 /venue/<CODE>.<YEAR> 列表里按标题找 paper id，
走 /venue/kimi?paper=<id>@<year>@<CODE> 兜底；两条路都走不通才进 "missing"。

用法:
  python3 kimi_q1.py --in citations.json --out kimi.json [--sleep 2] [--only 2503.14021]

输出 kimi.json:
  {"papers": {"2503.14021": {"title": ..., "blocks": [{"kind","rt":[{"t","b"}]}], "text": "..."}},
   "missing": [{"title":..., "reason": "no_arxiv"|"fetch_failed"}]}
"""
import argparse, html, json, os, re, sys, time
import urllib.parse, urllib.request

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
URL = "https://papers.cool/arxiv/kimi?paper={}"
VENUE_URL = "https://papers.cool/venue/kimi?paper={}"
VENUE_LIST = "https://papers.cool/venue/{}.{}?show=5000"

# papers.cool 支持的 venue（/venue/<CODE>.<YEAR>）→ S2 venue 字符串里的特征词
VENUE_CODES = {
    "IJCAI": ["ijcai", "international joint conference on artificial intelligence"],
    "AAAI": ["aaai"],
    "ACL": ["annual meeting of the association for computational linguistics", "acl"],
    "EMNLP": ["empirical methods in natural language processing", "emnlp"],
    "NAACL": ["naacl", "north american chapter"],
    "ICLR": ["international conference on learning representations", "iclr"],
    "ICML": ["international conference on machine learning", "icml"],
    "NeurIPS": ["neural information processing systems", "neurips", "nips"],
    "CVPR": ["computer vision and pattern recognition", "cvpr"],
    "ICCV": ["international conference on computer vision", "iccv"],
    "ECCV": ["european conference on computer vision", "eccv"],
    "COLM": ["conference on language modeling", "colm"],
    "CoRL": ["conference on robot learning", "corl"],
    "MICCAI": ["medical image computing", "miccai"],
    "INTERSPEECH": ["interspeech"],
    "IWSLT": ["iwslt", "spoken language translation"],
    "NDSS": ["network and distributed system security", "ndss"],
    "OSDI": ["operating systems design and implementation", "osdi"],
    "UAI": ["uncertainty in artificial intelligence", "uai"],
    "COLT": ["conference on learning theory", "colt"],
    "MLSYS": ["machine learning and systems", "mlsys"],
}

_venue_cache = {}


def norm_title(t):
    return re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).strip()


def venue_code(venue):
    """S2 的 venue 长名 → papers.cool 的 venue code；认不出返回 None。"""
    v = (venue or "").lower()
    for code, pats in VENUE_CODES.items():
        if any(x in v for x in pats):
            return code
    return None


def venue_paper_id(code, year, title):
    """在 /venue/<CODE>.<YEAR> 列表页按标题找 paper id（如 49@2026@IJCAI）。"""
    ck = (code, year)
    if ck not in _venue_cache:
        req = urllib.request.Request(VENUE_LIST.format(code, year))
        req.add_header("User-Agent", UA)
        with urllib.request.urlopen(req, timeout=120) as r:
            page = r.read().decode("utf-8", "replace")
        # id="title-<pid>" ...>标题</a>
        _venue_cache[ck] = {norm_title(html.unescape(m.group(2))): m.group(1)
                            for m in re.finditer(
                                r'id="title-([^"]+)"[^>]*>([^<]+)</a>', page)}
    idx = _venue_cache[ck]
    want = norm_title(title)
    if want in idx:
        return idx[want]
    for t, pid in idx.items():  # 标题可能有尾注/截断差异
        if want and (want in t or t in want):
            return pid
    return None


def rt_segments(text):
    segs, parts = [], text.split("**")
    for i, p in enumerate(parts):
        if p:
            segs.append({"t": p, "b": (i % 2 == 1)})
    return segs or [{"t": text, "b": False}]


def _block(kind, text):
    text = text.strip()
    if not text:
        return None
    return {"kind": kind, "rt": rt_segments(text)}


def parse_markdown(md):
    out = []
    for raw in md.split("\n"):
        line = raw.strip()
        if not line:
            continue
        m = re.match(r"^#{1,4}\s*(.*)$", line)
        if m:
            b = _block("heading_3", m.group(1))
            b and out.append(b)
            continue
        m = re.match(r"^[-*•]\s+(.*)$", line)
        if m:
            b = _block("bulleted_list_item", m.group(1))
            b and out.append(b)
            continue
        b = _block("paragraph", line)
        b and out.append(b)
    return out


def parse_html(h):
    s = re.sub(r"<h[1-6][^>]*>", "\n### ", h)
    s = re.sub(r"</h[1-6]>", "\n", s)
    s = re.sub(r"<li[^>]*>", "\n- ", s)
    s = re.sub(r"</li>", "\n", s)
    s = re.sub(r"<p[^>]*>", "\n", s)
    s = re.sub(r"</p>", "\n\n", s)
    s = re.sub(r"</?(ul|ol|div|span|strong|em|br|code|table|tr|td)[^>]*>", " ", s)
    s = re.sub(r"<[^>]+>", "", s)
    return parse_markdown(html.unescape(s).replace("<br>", "\n"))


def q1_blocks(page_html):
    """从 papers.cool 的 FAQ HTML 里抠出 Q1 的答案，转成块。"""
    m = re.search(r'<p class="faq-q">\s*<strong>Q1</strong>.*?</p>\s*<div class="faq-a">(.*?)</div>',
                  page_html, re.S)
    if not m:
        return None, None
    body = m.group(1)
    blocks = parse_html(body) if re.search(r"<(h3|ul|li|p)[ >]", body) else parse_markdown(html.unescape(body))
    text = "".join(("**" if s["b"] else "") + s["t"] for b in blocks for s in b["rt"])
    return blocks, text


def fetch(paper_id, tries=3, wait=5, venue=False):
    data = b""
    base, kind = (VENUE_URL, "venue") if venue else (URL, "arxiv")
    for i in range(tries):
        url = base.format(urllib.parse.quote(paper_id, safe=""))
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("User-Agent", UA)
        req.add_header("Accept", "*/*")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        req.add_header("Origin", "https://papers.cool")
        req.add_header("Referer", f"https://papers.cool/{kind}/{paper_id}")
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:
            if i == tries - 1:
                raise
            sys.stderr.write(f"    retry {paper_id}: {e}\n")
            time.sleep(wait)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default="citations.json")
    ap.add_argument("--out", default="kimi.json")
    ap.add_argument("--sleep", type=float, default=2.0)
    ap.add_argument("--only", nargs="*", help="只抓这些 arXiv id")
    ap.add_argument("--resume", action="store_true",
                    help="--out 已存在时跳过里面抓好的（被中断后续抓用）")
    args = ap.parse_args()

    d = json.load(open(args.inp))
    papers = d.get("kept") or d.get("by_citations") or []
    if args.only:
        papers = [p for p in papers if (p.get("externalIds") or {}).get("ArXiv") in args.only]

    out, missing = {}, []
    if args.resume and os.path.exists(args.out):
        prev = json.load(open(args.out))
        out = prev.get("papers", {})
        print(f"续抓：{args.out} 里已有 {len(out)} 篇，跳过")

    def flush():  # 每篇都落盘，中途被杀也不丢
        json.dump({"papers": out, "missing": missing}, open(args.out, "w"),
                  ensure_ascii=False, indent=1)

    for p in papers:
        aid = (p.get("externalIds") or {}).get("ArXiv")
        is_venue = False
        if not aid:  # 非 arXiv：试 papers.cool 的 venue 列表
            code = venue_code(p.get("venue"))
            yr = p.get("year") or (p.get("publicationDate") or "")[:4]
            try:
                aid = venue_paper_id(code, yr, p["title"]) if (code and yr) else None
            except Exception as e:
                sys.stderr.write(f"    venue 列表抓取失败 {code}.{yr}: {e}\n")
                aid = None
            if not aid:
                missing.append({"title": p["title"], "reason": "no_arxiv_no_venue"})
                print(f"  ✗ 非 arXiv 且 papers.cool venue 里没找到: {p['title'][:60]}")
                continue
            is_venue = True
        if aid in out:
            continue
        try:
            page = fetch(aid, venue=is_venue)
            blocks, text = q1_blocks(page)
            if not blocks:
                missing.append({"title": p["title"], "reason": "no_q1"})
                print(f"  ✗ {aid} 没有 Q1")
            else:
                out[aid] = {"title": p["title"], "blocks": blocks, "text": text}
                print(f"  ✓ {aid} {len(blocks)} blocks / {len(text)} chars  {p['title'][:50]}")
            flush()
        except Exception as e:
            missing.append({"title": p["title"], "reason": f"fetch_failed: {e}"})
            print(f"  ✗ {aid} 抓取失败: {e}")
            flush()
        time.sleep(args.sleep)

    flush()
    print(f"写入 {args.out}：{len(out)} 篇有 Kimi 原文，{len(missing)} 篇缺失")


if __name__ == "__main__":
    main()
