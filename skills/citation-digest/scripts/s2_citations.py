#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按标题（或 paperId）抓一篇论文的引用列表，带被引数与元信息。

用法:
  python3 s2_citations.py --title "MP-GUI: Modality Perception with MLLMs for GUI Understanding" \
      --out citations.json
  python3 s2_citations.py --arxiv 2503.14021 --out citations.json
  python3 s2_citations.py --paper-id 0e931ba8... --out citations.json

API key: --key / $SEMANTIC_SCHOLAR_API_KEY / ~/.env/semantic-scholar。
不加 key 也能跑，但限流更严（会疯狂 429）。
"""
import argparse, json, os, re, sys, time
import urllib.request, urllib.parse, urllib.error

BASE = "https://api.semanticscholar.org/graph/v1"
FIELDS = ("title,year,venue,publicationDate,citationCount,influentialCitationCount,"
          "authors,externalIds,abstract")

def api_key(args):
    if args.key:
        return args.key.strip()
    if os.environ.get("SEMANTIC_SCHOLAR_API_KEY"):
        return os.environ["SEMANTIC_SCHOLAR_API_KEY"].strip()
    p = os.path.expanduser("~/.env/semantic-scholar")
    if os.path.exists(p):
        return open(p).read().strip()
    return None

def get(url, key, tries=8, wait=12):
    for i in range(tries):
        req = urllib.request.Request(url, headers={"User-Agent": "citation-digest/1.0"})
        if key:
            req.add_header("x-api-key", key)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429 or e.code >= 500:
                sys.stderr.write(f"  [{i+1}/{tries}] HTTP {e.code}, retry in {wait}s\n")
                time.sleep(wait)
                continue
            raise
        except Exception as e:  # 网络抖动
            sys.stderr.write(f"  [{i+1}/{tries}] {e}, retry in {wait}s\n")
            time.sleep(wait)
    raise SystemExit("S2 请求连续失败（限流），稍后再试或换 key。")

def norm(t):
    t = (t or "").lower()
    t = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()

def resolve_paper(args, key):
    if args.paper_id:
        return get(f"{BASE}/paper/{args.paper_id}?fields={FIELDS},citationCount", key)
    if args.arxiv:
        return get(f"{BASE}/paper/arXiv:{args.arxiv}?fields={FIELDS},citationCount", key)
    q = urllib.parse.quote(args.title)
    data = get(f"{BASE}/paper/search?query={q}&limit=10&fields={FIELDS}", key)
    best, best_score = None, -1
    want = norm(args.title)
    for p in data.get("data", []):
        got = norm(p.get("title"))
        if got == want:
            score = 1000
        else:
            # 简单的 token 重合度
            a, b = set(want.split()), set(got.split())
            score = len(a & b) / max(1, len(a | b))
        if score > best_score:
            best, best_score = p, score
    if not best:
        raise SystemExit(f"没搜到：{args.title}")
    if best_score < 0.55:
        cands = "\n".join(f"  - {p['title']} ({p.get('year')}) {p['paperId']}" for p in data.get("data", []))
        sys.stderr.write(f"⚠️  标题匹配度低（{best_score:.2f}），选了「{best['title']}」。候选：\n{cands}\n")
    return best

def dedupe(papers):
    """S2 常把同一篇 arXiv 论文返回两条（arXiv 版 + DOI 版），按 arXiv/DOI/标题去重。"""
    seen, out = {}, []
    for p in papers:
        ext = p.get("externalIds") or {}
        doi = (ext.get("DOI") or "").lower()
        m = re.search(r"arxiv[./](\d{4}\.\d{4,5})", doi)
        # arXiv 优先：一条可能只在 DOI 里带 10.48550/arXiv.xxxx，另一条只在 externalIds.ArXiv 里带
        aid = ext.get("ArXiv") or (m.group(1) if m else None)
        key = ("arxiv:" + aid) if aid else ("doi:" + doi if doi else "title:" + norm(p.get("title")))
        if key in seen:
            # 保留信息更全 / 被引更高的那条
            old = seen[key]
            if (p.get("citationCount") or 0) > (old.get("citationCount") or 0):
                out[out.index(old)] = p
                seen[key] = p
            continue
        seen[key] = p
        out.append(p)
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--title")
    ap.add_argument("--arxiv")
    ap.add_argument("--paper-id")
    ap.add_argument("--key")
    ap.add_argument("--out", default="citations.json")
    ap.add_argument("--max-total", type=int, default=20,
                    help="引用数超过这个值时，只保留「被引 top10 + 日期 top10」(默认 20)")
    ap.add_argument("--top", type=int, default=10)
    args = ap.parse_args()
    if not (args.title or args.arxiv or args.paper_id):
        ap.error("需要 --title / --arxiv / --paper-id 之一")

    key = api_key(args)
    if not key:
        sys.stderr.write("⚠️  没有 S2 key，限流会很严重\n")

    src = resolve_paper(args, key)
    pid = src["paperId"]
    total = src.get("citationCount") or 0
    print(f"源论文: {src['title']} ({src.get('year')}) 被引 {total}  paperId={pid}")

    rows, offset = [], 0
    while True:
        url = f"{BASE}/paper/{pid}/citations?fields={FIELDS}&limit=1000&offset={offset}"
        d = get(url, key)
        batch = [e["citingPaper"] for e in d.get("data", [])]
        rows += [p for p in batch if p.get("title")]
        if not d.get("next") or not batch:
            break
        offset = d["next"]
        time.sleep(1)

    uniq = dedupe(rows)
    by_c = sorted(uniq, key=lambda p: (-(p.get("citationCount") or 0), -(p.get("year") or 0)))
    by_d = sorted(uniq, key=lambda p: (p.get("publicationDate") or "0000"), reverse=True)

    if len(uniq) > args.max_total:
        keep = by_c[:args.top] + [p for p in by_d[:args.top] if p not in by_c[:args.top]]
        print(f"引用 {len(uniq)} 篇 > {args.max_total}，保留被引 top{args.top} + 日期 top{args.top}（去重后 {len(keep)} 篇）")
    else:
        keep = by_c

    out = {
        "source": {
            "title": src["title"], "paperId": pid, "citationCount": total,
            "year": src.get("year"), "venue": src.get("venue"),
            "doi": (src.get("externalIds") or {}).get("DOI"),
            "arxiv": (src.get("externalIds") or {}).get("ArXiv"),
        },
        "total_records": len(rows), "unique": len(uniq),
        "by_citations": by_c, "by_date": by_d,
        "kept": keep,
    }
    json.dump(out, open(args.out, "w"), ensure_ascii=False, indent=1)
    print(f"写入 {args.out}：{len(keep)} 篇")

if __name__ == "__main__":
    main()
