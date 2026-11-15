#!/usr/bin/env python3
"""Personal task agent: SQLite storage + C++ priority scorer + optional LLM chat.

Offline commands (no API key needed):
    python3 agent.py add "Pay electricity bill" -p 4 --due 2026-11-17 --minutes 10
    python3 agent.py list
    python3 agent.py rank
    python3 agent.py done 1

LLM mode (needs ANTHROPIC_API_KEY):
    python3 agent.py chat
"""
import argparse
import json
import os
import sqlite3
import subprocess
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("TASK_DB", HERE / "tasks.db"))
SCORER = HERE / "build" / "scorer"
MODEL = os.environ.get("AGENT_MODEL", "claude-sonnet-5-5")
API_URL = "https://api.anthropic.com/v1/messages"


# ---------------------------------------------------------------- storage
def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute(
        """CREATE TABLE IF NOT EXISTS tasks (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               title TEXT NOT NULL,
               priority INTEGER NOT NULL DEFAULT 3,
               due TEXT,
               minutes INTEGER NOT NULL DEFAULT 30,
               done INTEGER NOT NULL DEFAULT 0,
               created TEXT NOT NULL
           )"""
    )
    return con


def add_task(title, priority=3, due=None, minutes=30):
    priority = max(1, min(5, int(priority)))
    if due:
        datetime.fromisoformat(due)  # validate early
    with db() as con:
        cur = con.execute(
            "INSERT INTO tasks (title, priority, due, minutes, created) VALUES (?,?,?,?,?)",
            (title, priority, due, int(minutes), datetime.now().isoformat(timespec="seconds")),
        )
    return {"id": cur.lastrowid, "title": title}


def list_tasks(include_done=False):
    q = "SELECT * FROM tasks" + ("" if include_done else " WHERE done = 0") + " ORDER BY id"
    with db() as con:
        return [dict(r) for r in con.execute(q)]


def complete_task(task_id):
    with db() as con:
        cur = con.execute("UPDATE tasks SET done = 1 WHERE id = ?", (int(task_id),))
    return {"completed": cur.rowcount == 1, "id": int(task_id)}


# ------------------------------------------------------- C++ scorer bridge
def hours_until(due):
    if not due:
        return "none"
    delta = datetime.fromisoformat(due) - datetime.now()
    return f"{delta.total_seconds() / 3600:.2f}"


def rank_tasks(limit=10):
    tasks = list_tasks()
    if not tasks:
        return []
    if not SCORER.exists():
        raise RuntimeError(f"C++ scorer not built: run `make` first ({SCORER})")
    payload = "\n".join(
        f"{t['id']}\t{t['priority']}\t{hours_until(t['due'])}\t{t['minutes']}" for t in tasks
    )
    res = subprocess.run([str(SCORER)], input=payload, capture_output=True, text=True, check=True)
    by_id = {t["id"]: t for t in tasks}
    ranked = []
    for line in res.stdout.splitlines():
        tid, score = line.split("\t")
        t = by_id[int(tid)]
        ranked.append({**t, "score": round(float(score), 1)})
    return ranked[:limit]


# ------------------------------------------------------------- LLM agent
TOOLS = [
    {
        "name": "add_task",
        "description": "Add a task. Due is an ISO date or datetime like 2026-11-20 or 2026-11-20T17:00.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "priority": {"type": "integer", "minimum": 1, "maximum": 5},
                "due": {"type": "string"},
                "minutes": {"type": "integer"},
            },
            "required": ["title"],
        },
    },
    {
        "name": "list_tasks",
        "description": "List open tasks (set include_done to see finished ones).",
        "input_schema": {"type": "object", "properties": {"include_done": {"type": "boolean"}}},
    },
    {
        "name": "complete_task",
        "description": "Mark a task done by id.",
        "input_schema": {
            "type": "object",
            "properties": {"task_id": {"type": "integer"}},
            "required": ["task_id"],
        },
    },
    {
        "name": "rank_tasks",
        "description": "Rank open tasks by what to do next, using the fast C++ scorer.",
        "input_schema": {"type": "object", "properties": {"limit": {"type": "integer"}}},
    },
]
DISPATCH = {
    "add_task": add_task,
    "list_tasks": list_tasks,
    "complete_task": complete_task,
    "rank_tasks": rank_tasks,
}


def call_api(messages):
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        sys.exit("Set ANTHROPIC_API_KEY to use chat mode (offline commands work without it).")
    body = json.dumps(
        {
            "model": MODEL,
            "max_tokens": 1024,
            "system": f"You are a concise personal task assistant. Now is {datetime.now():%Y-%m-%d %H:%M}. "
            "Use the tools to read or change the task list; never invent task ids.",
            "tools": TOOLS,
            "messages": messages,
        }
    ).encode()
    req = urllib.request.Request(
        API_URL,
        data=body,
        headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def run_turn(messages):
    """Loop until the model stops asking for tools; return its final text."""
    for _ in range(8):  # hard cap so a confused model can't loop forever
        resp = call_api(messages)
        messages.append({"role": "assistant", "content": resp["content"]})
        if resp["stop_reason"] != "tool_use":
            return "".join(b["text"] for b in resp["content"] if b["type"] == "text")
        results = []
        for b in resp["content"]:
            if b["type"] != "tool_use":
                continue
            try:
                out = DISPATCH[b["name"]](**b["input"])
                results.append({"type": "tool_result", "tool_use_id": b["id"], "content": json.dumps(out)})
            except Exception as e:  # report errors to the model so it can recover
                results.append(
                    {"type": "tool_result", "tool_use_id": b["id"], "content": str(e), "is_error": True}
                )
        messages.append({"role": "user", "content": results})
    return "(stopped after too many tool steps)"


def chat():
    print("Task agent ready. Try: 'add buy milk, low priority' or 'what should I do next?'  (Ctrl-C to quit)")
    messages = []
    while True:
        try:
            text = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not text:
            continue
        messages.append({"role": "user", "content": text})
        print("agent>", run_turn(messages))


# -------------------------------------------------------------------- CLI
def show(rows):
    if not rows:
        print("(no open tasks)")
    for r in rows:
        score = f"  score={r['score']}" if "score" in r else ""
        print(f"#{r['id']:<3} P{r['priority']}  due={r['due'] or '-':<16} {r['minutes']:>3}m  {r['title']}{score}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("title")
    a.add_argument("-p", "--priority", type=int, default=3)
    a.add_argument("--due")
    a.add_argument("--minutes", type=int, default=30)
    sub.add_parser("list")
    sub.add_parser("rank")
    d = sub.add_parser("done")
    d.add_argument("task_id", type=int)
    sub.add_parser("chat")
    args = ap.parse_args()

    if args.cmd == "add":
        print("added", add_task(args.title, args.priority, args.due, args.minutes))
    elif args.cmd == "list":
        show(list_tasks())
    elif args.cmd == "rank":
        show(rank_tasks())
    elif args.cmd == "done":
        print(complete_task(args.task_id))
    elif args.cmd == "chat":
        chat()


if __name__ == "__main__":
    main()
