#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 content.json 发布到 Notion：一个以论文命名的根 toggle，里面是分类 toggle，再里面每篇一个 toggle。

用法:
  python3 notion_publish.py --content content.json --page-title "topic论文阅读"
  python3 notion_publish.py --content content.json --page-id 3ff16225-8ab7-80d6-9c8b-e4ed8d78c9db
  python3 notion_publish.py --content content.json --page-id ... --replace   # 先清空该页顶层

Token: ~/.notion-token 或 $NOTION_TOKEN；页面要先 share 给这个 integration。

⚠️ 这个 integration 的 block 追加只吃 PATCH /v1/blocks/{id}/children，
   POST 同一个 URL 会返回 400 invalid_request_url（2026-10 实测）。
"""
import argparse, json, os, sys, time
import urllib.request, urllib.error

API = "https://api.notion.com/v1"
VER = "2025-09-03"


class Notion:
    def __init__(self, token):
        self.token = token

    def req(self, method, path, body=None, tries=5):
        data = json.dumps(body).encode() if body is not None else None
        for i in range(tries):
            r = urllib.request.Request(API + path, data=data, method=method)
            r.add_header("Authorization", "Bearer " + self.token)
            r.add_header("Notion-Version", VER)
            r.add_header("Content-Type", "application/json")
            try:
                with urllib.request.urlopen(r, timeout=60) as resp:
                    return json.loads(resp.read().decode())
            except urllib.error.HTTPError as e:
                msg = e.read().decode()[:300]
                if e.code in (429, 502, 503) and i < tries - 1:
                    time.sleep(3 * (i + 1))
                    continue
                # 刚建好的块马上往里追加，Notion 偶发返回这个 400（最终一致性抖动），
                # 实际写入可能已成功也可能没成功，退避重试即可（2026-10 实测）
                if e.code == 400 and "start_cursor provided is invalid" in msg and i < tries - 1:
                    time.sleep(2 * (i + 1))
                    continue
                raise SystemExit(f"Notion {method} {path} -> {e.code}: {msg}")
            except Exception as e:
                if i < tries - 1:
                    time.sleep(2)
                    continue
                raise SystemExit(f"Notion {method} {path} -> {e}")

    def children(self, block_id):
        return self.req("GET", f"/blocks/{block_id}/children?page_size=100")["results"]

    def append(self, block_id, blocks):
        """PATCH 而不是 POST —— 见文件头说明。"""
        out = []
        for i in range(0, len(blocks), 80):
            out += self.req("PATCH", f"/blocks/{block_id}/children", {"children": blocks[i:i + 80]})["results"]
            time.sleep(0.25)
        return out

    def delete(self, block_id):
        return self.req("DELETE", f"/blocks/{block_id}")

    def find_page(self, title):
        d = self.req("POST", "/search", {"query": title, "filter": {"value": "page", "property": "object"}})
        for p in d.get("results", []):
            props = p.get("properties", {}) or {}
            name = ""
            for v in props.values():
                if v.get("type") == "title":
                    name = "".join(t.get("plain_text", "") for t in v.get("title", []))
            if name.strip() == title.strip():
                return p["id"]
        cands = [p["id"] for p in d.get("results", [])[:5]]
        raise SystemExit(f"没找到标题为「{title}」的页面。搜索候选: {cands}")


def rt(content, bold=False, color="default", link=None):
    o = {"type": "text", "text": {"content": content}, "annotations": {"bold": bold, "color": color}}
    if link:
        o["text"]["link"] = {"url": link}
    return o


def seg(s):
    """单个 rich_text 的 content 上限 2000 字符，超了切成多段（同一个 block 内）。"""
    t, b, out = s["t"], bool(s.get("b")), []
    for i in range(0, len(t), 1900) or [0]:
        out.append({"type": "text", "text": {"content": t[i:i + 1900]},
                    "annotations": {"bold": b}})
    return out or [{"type": "text", "text": {"content": ""}, "annotations": {"bold": b}}]


def to_block(spec):
    rts = [x for s in spec["rt"] for x in seg(s)]
    k = spec["kind"]
    if k == "heading_3":
        return {"object": "block", "type": "heading_3", "heading_3": {"rich_text": rts}}
    if k == "bulleted_list_item":
        return {"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": rts}}
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": rts}}


def paragraph(rts, color="default"):
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": rts, "color": color}}


def toggle(text, children=None):
    return {"object": "block", "type": "toggle",
            "toggle": {"rich_text": [rt(text, bold=True)], "children": children or []}}


def divider():
    return {"object": "block", "type": "divider", "divider": {}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--content", default="content.json")
    ap.add_argument("--page-id")
    ap.add_argument("--page-title")
    ap.add_argument("--token-file", default=os.path.expanduser("~/.notion-token"))
    ap.add_argument("--replace", action="store_true", help="先删掉目标页现有的顶层 block")
    ap.add_argument("--before", action="store_true", help="不建根 toggle，直接把分类挂到页面上")
    args = ap.parse_args()

    token = os.environ.get("NOTION_TOKEN") or (
        open(args.token_file).read().strip() if os.path.exists(args.token_file) else None)
    if not token:
        raise SystemExit("缺少 Notion token（~/.notion-token 或 $NOTION_TOKEN）")

    c = json.load(open(args.content))
    n = Notion(token)
    page = args.page_id or n.find_page(args.page_title)
    print("page:", page)

    if args.replace:
        for b in n.children(page):
            n.delete(b["id"])
            time.sleep(0.2)
        print("已清空页面顶层 block")

    if args.before:
        parent = page
    else:
        root = n.append(page, [toggle(c["root_title"])])[0]["id"]
        n.append(root, [paragraph([rt(c["note"], color="gray")]), divider()])
        parent = root
        print("root toggle:", root)

    cats = n.append(parent, [toggle(f"{cat['name']}（{len(cat['papers'])} 篇）") for cat in c["categories"]])
    print("categories:", [x["id"] for x in cats])

    total = 0
    for cat_blk, cat in zip(cats, c["categories"]):
        for p in cat["papers"]:
            meta = p["meta"] + ("" if p.get("source") == "kimi" else " ⚠️ 非 Kimi 总结")
            body = [paragraph([rt(meta, color="gray", link=p.get("url"))])]
            body += [to_block(b) for b in p["blocks"]]
            n.append(cat_blk["id"], [toggle(p["title"], body)])
            total += 1
            print(f"  + {p['title'][:60]} ({len(body)} blocks)")
            time.sleep(0.3)
    print(f"完成：{len(cats)} 个分类，{total} 篇论文")


if __name__ == "__main__":
    main()
