#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""memory-recon — 给 agent 会话库做记忆对账。

从历史会话里抽出"用户拍过板 / 说过记住"的话，再去记忆库找落点，
输出一份可人工复核的对账报告。

只读：不改会话库，不写记忆库，不上传任何东西。
零依赖：只用 Python 标准库。

用法：
  python3 recon.py --db ~/.zcode/cli/db/db.sqlite \
      --memory ~/workspace/.dsh/memory --memory ~/workspace/AGENTS.md \
      --out report.md
"""

import argparse
import datetime as dt
import glob
import json
import os
import re
import sqlite3
import sys

# 决策信号。命中任意一条即进入候选池，再由人来判断值不值得长期记。
DECISION_PATTERNS = [
    r"拍板", r"定案", r"就这么定", r"就按这个", r"按这个来", r"决定了",
    r"以后都", r"往后都", r"从现在起", r"统一(用|改|走)", r"约定",
    r"记住", r"记一下", r"记录下来", r"沉淀", r"别忘了",
    r"不要再", r"别再", r"不许", r"禁止", r"千万别", r"不准",
    r"最终方案", r"结论是", r"就这样", r"先这样",
]

ENTITY_RE = re.compile(r"[A-Za-z][A-Za-z0-9_.\-]{2,}")

STOP = {
    "http", "https", "www", "com", "the", "and", "for", "with", "that", "this",
    "you", "not", "use", "all", "can", "file", "path", "data", "code", "test",
    "true", "false", "json", "html", "node", "just", "like", "make", "need",
    "should", "agent", "claude", "github", "workspace", "users", "desktop",
    "project", "python", "shell", "bash", "using", "only", "also", "which",
    "when", "then", "than", "them", "they", "there", "what", "want", "some",
    "more", "most", "into", "over", "such", "been", "being", "from", "have",
    "will", "your", "user", "md", "txt", "read", "write", "new", "old",
}

SKIP_DIRS = ("node_modules", "/.git/", "/out/", "/dist/", "/build/",
             "/.next/", "/venv", "/.venv", "/target/", "/vendor/",
             "__pycache__")


def to_dt(ts):
    """秒 / 毫秒 / 微秒时间戳统一转本地时间。"""
    if ts is None:
        return None
    v = float(ts)
    if v > 1e14:
        v /= 1e6
    elif v > 1e11:
        v /= 1e3
    return dt.datetime.fromtimestamp(v)


def load_zcode(db_path, since=None):
    """读 ZCode 的 sqlite 结构：session / message / part。"""
    con = sqlite3.connect("file:%s?mode=ro" % db_path, uri=True)
    con.text_factory = str
    sql = """
        select s.id, s.title, m.time_created, json_extract(p.data, '$.text')
        from part p
        join message m on p.message_id = m.id
        join session s on m.session_id = s.id
        where json_extract(p.data, '$.type') = 'text'
          and m.data like '%real_user%'
        order by m.time_created
    """
    try:
        rows = con.execute(sql).fetchall()
    finally:
        con.close()
    out = []
    for sid, title, ts, text in rows:
        if not text:
            continue
        when = to_dt(ts)
        if since and when and when < since:
            continue
        out.append({"session": sid, "title": title or "", "when": when,
                    "text": text})
    return out


def load_jsonl(path, since=None):
    """通用格式：每行 {"ts": ..., "text": ...}，ts 可省。"""
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            text = row.get("text") or row.get("content") or ""
            if not text:
                continue
            when = to_dt(row.get("ts")) if row.get("ts") else None
            if since and when and when < since:
                continue
            out.append({"session": row.get("session", ""),
                        "title": row.get("title", ""), "when": when,
                        "text": text})
    return out


def is_decision(text):
    return any(re.search(p, text) for p in DECISION_PATTERNS)


TASK_START = re.compile(
    r"^(你是|你是一名|你是一个|你在|询问|进度询问|背景：|工作目录|研究任务|"
    r"任务：|请对|请检查|请审查|给下列|给一个|给两个|给三个|给六个|"
    r"This session is being continued)")


def entities(text):
    found = set()
    for e in ENTITY_RE.findall(text):
        e = e.lower()
        if len(e) >= 4 and e not in STOP:
            found.add(e)
    return found


def load_memory(paths):
    """把记忆库读成一个大字符串；文件名单独留一份，便于报告指路。"""
    chunks, files = [], []
    for p in paths:
        p = os.path.expanduser(p)
        if os.path.isfile(p):
            cand = [p]
        else:
            cand = []
            for ext in ("md", "txt"):
                cand += glob.glob(os.path.join(p, "**", "*." + ext),
                                  recursive=True)
        for f in cand:
            if any(s in f for s in SKIP_DIRS):
                continue
            try:
                if os.path.getsize(f) > 2_000_000:
                    continue
                chunks.append(open(f, encoding="utf-8", errors="ignore").read())
                files.append(f)
            except OSError:
                continue
    return "\n".join(chunks).lower(), files


def coverage(ents, corpus):
    if not ents:
        return None
    hit = sum(1 for e in ents if e in corpus)
    return hit / len(ents)


def main():
    ap = argparse.ArgumentParser(
        description="给 agent 会话库做记忆对账（只读）")
    ap.add_argument("--db", help="ZCode 的 db.sqlite 路径")
    ap.add_argument("--jsonl", help="通用会话 JSONL（每行 {ts,text}）")
    ap.add_argument("--memory", action="append", default=[],
                    help="记忆目录或文件，可重复")
    ap.add_argument("--out", default="memory-recon-report.md")
    ap.add_argument("--since", help="只看这天之后的，格式 YYYY-MM-DD")
    ap.add_argument("--top", type=int, default=80, help="报告最多列多少条")
    ap.add_argument("--dump-json", help="把候选池另存为 JSON")
    ap.add_argument("--include-tasks", action="store_true",
                    help="把 Agent 任务书也纳入候选（默认跳过）")
    args = ap.parse_args()

    if not args.db and not args.jsonl:
        ap.error("至少要给 --db 或 --jsonl 一个")
    if not args.memory:
        ap.error("至少给一个 --memory")

    since = None
    if args.since:
        since = dt.datetime.strptime(args.since, "%Y-%m-%d")

    rows = []
    if args.db:
        rows += load_zcode(os.path.expanduser(args.db), since)
    if args.jsonl:
        rows += load_jsonl(os.path.expanduser(args.jsonl), since)

    corpus, mem_files = load_memory(args.memory)
    cands, skipped = [], 0
    for r in rows:
        text = r["text"].strip()
        if len(text) < 8 or not is_decision(text):
            continue
        if not args.include_tasks and TASK_START.match(text):
            skipped += 1
            continue
        cands.append(r)

    scored = []
    for r in cands:
        ents = entities(r["text"])
        scored.append({"row": r, "entities": sorted(ents),
                       "coverage": coverage(ents, corpus)})

    # 有实体、覆盖低的排前面（最可能是"聊过但没落盘"的）；
    # 没有英文实体的单独排在后面，避免"记住一下"这类空话占满第一屏。
    scored.sort(key=lambda x: (x["coverage"] is None,
                               x["coverage"] if x["coverage"] is not None else 0.0,
                               -len(x["row"]["text"])))

    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        "# 记忆对账报告",
        "",
        "- 生成时间：%s" % now,
        "- 会话条数：%d" % len(rows),
        "- 决策候选：%d" % len(cands),
        "- 记忆文件：%d（约 %d 字符）" % (len(mem_files), len(corpus)),
        "",
        "> 覆盖度只是线索，不是结论。低分 = 值得人看一眼；",
        "> 高分也可能是同主题不同决定。最终以人工判定为准。",
        "",
        "| 日期 | 会话 | 摘要 | 覆盖 |",
        "|---|---|---|---|",
    ]
    for item in scored[:args.top]:
        r = item["row"]
        when = r["when"].strftime("%Y-%m-%d") if r["when"] else "?"
        title = (r["title"] or "")[:22].replace("|", "/")
        text = re.sub(r"\s+", " ", r["text"])[:90].replace("|", "/")
        cov = item["coverage"]
        cov_s = "—" if cov is None else "%.2f" % cov
        lines.append("| %s | %s | %s | %s |" % (when, title, text, cov_s))

    lines += [
        "",
        "## 怎么用这份表",
        "",
        "1. 从上往下看，先看覆盖低、又带明确结论的。",
        "2. 每条问一句：下次会话还会不会用到？会 → 写进记忆；不会 → 跳过。",
        "3. 重点找带步骤的（流程、判据、验证方法）——这类最容易只在对话里说过。",
        "4. 判定完把结论写回记忆库，别只留在报告里。",
    ]

    with open(args.out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    if args.dump_json:
        payload = [{"date": (i["row"]["when"].strftime("%Y-%m-%d")
                             if i["row"]["when"] else None),
                    "session": i["row"]["session"],
                    "title": i["row"]["title"],
                    "text": i["row"]["text"],
                    "entities": i["entities"],
                    "coverage": i["coverage"]} for i in scored]
        with open(args.dump_json, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)

    print("会话 %d 条，决策候选 %d 条，记忆文件 %d 个" %
          (len(rows), len(cands), len(mem_files)))
    print("报告：%s" % args.out)
    if args.dump_json:
        print("候选池：%s" % args.dump_json)


if __name__ == "__main__":
    sys.exit(main())
