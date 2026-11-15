# Personal Task Agent (Python + C++)

A small task manager you can talk to in plain English.

- **Python** (`agent.py`): SQLite storage, CLI, and an LLM tool-use loop.
- **C++** (`scorer.cpp`): fast priority scorer. Python pipes tasks to it over stdin and reads the ranking back.

## Setup

    make                      # builds build/scorer
    python3 agent.py add "Pay electricity bill" -p 4 --due 2026-11-17 --minutes 10
    python3 agent.py rank     # what to do next

## Chat mode (uses the Claude API)

    export ANTHROPIC_API_KEY=sk-...
    python3 agent.py chat

Then say things like "add a task to call the bank tomorrow 5pm, high priority" or "what should I do next?".
The model never ranks by itself; it calls the `rank_tasks` tool, which runs the C++ scorer.

## How scoring works

`score = priority*12 + urgency(hours until due) + quick-win bonus (<=15 min) - long-task penalty (>2h)`.
Overdue tasks get the biggest urgency boost. Tweak the numbers in `scorer.cpp` and re-run `make`.

## Ideas to extend

- Replace the subprocess bridge with pybind11 once you can install it (`pip install pybind11`).
- Add Google Calendar or Gmail as extra tools in the `TOOLS` list.
- Run `python3 agent.py rank` from cron every morning and send yourself the result.
