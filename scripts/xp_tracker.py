#!/usr/bin/env python3
"""Quant Odyssey XP tracker: derives XP from git commit messages.

Put tags in square brackets in any commit message that contains "Day N":

    git commit -m "Day 2: python basics [main side]"

  main      +40   main quest done (micro-steps are folded into this)
  side[=K]  +20   each side quest (max 5 per day)
  retro     +30   weekly retro
  ship      +100  shipped something public
  boss=N    +500 / 1000 / 1500 / 2000 for boss N (1-4)

Rules
  * Each tag counts once per day number, so extra commits can't farm XP.
  * A day that falls inside a 7+ day streak earns x1.2.
  * Level n needs 20 * n^2 total XP.
  * xp-adjustments.json holds flat manual XP (e.g. backfilling Day 1).
"""
import json
import math
import re
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "xp.json"
ADJ = ROOT / "xp-adjustments.json"

DAY_RE = re.compile(r"\bday\s*(\d+)\b", re.I)
TAG_RE = re.compile(r"\[([^\]]*)\]")
FLAT = {"main": 40, "side": 20, "retro": 30, "ship": 100}
BOSS = {1: 500, 2: 1000, 3: 1500, 4: 2000}
TITLES = [(26, "Founder-Quant"), (18, "Quant"), (11, "Analyst"), (0, "Apprentice")]


def git_log():
    out = subprocess.run(
        ["git", "log", "--reverse", "--format=%aI%x1f%s"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout
    for line in out.splitlines():
        if "\x1f" in line:
            iso, subject = line.split("\x1f", 1)
            yield datetime.fromisoformat(iso).astimezone(IST).date(), subject


def parse(subject):
    m = DAY_RE.search(subject)
    if not m:
        return None
    parts = {}
    for group in TAG_RE.findall(subject):
        for tok in re.split(r"[\s,]+", group.strip().lower()):
            if not tok:
                continue
            key, _, val = tok.partition("=")
            n = int(val) if val.isdigit() else 1
            if key in ("main", "retro", "ship"):
                parts[key] = 1
            elif key == "side":
                parts["side"] = min(n, 5)
            elif key == "boss" and n in BOSS:
                parts["boss"] = n
    return int(m.group(1)), parts


def base_xp(parts):
    xp = sum(FLAT[k] * v for k, v in parts.items() if k in FLAT)
    if "boss" in parts:
        xp += BOSS[parts["boss"]]
    return xp


def tag_labels(parts):
    labels = []
    for k, v in sorted(parts.items()):
        labels.append(f"{k}={v}" if k == "boss" or (k == "side" and v > 1) else k)
    return labels


def load_adjustments():
    if not ADJ.exists():
        return {}
    by_day = {}
    for a in json.loads(ADJ.read_text()):
        by_day.setdefault(int(a["day"]), []).append(a)
    return by_day


def main():
    days = {}
    for d, subject in git_log():
        parsed = parse(subject)
        if not parsed:
            continue
        n, parts = parsed
        rec = days.setdefault(n, {"date": d, "parts": {}})
        for k, v in parts.items():
            rec["parts"][k] = max(rec["parts"].get(k, 0), v)

    # streaks over calendar days (IST) that have at least one "Day N" commit
    active = sorted({r["date"] for r in days.values()})
    streak_at, run, prev = {}, 0, None
    for d in active:
        run = run + 1 if prev and (d - prev).days == 1 else 1
        streak_at[d], prev = run, d
    longest = max(streak_at.values(), default=0)
    today = datetime.now(IST).date()
    current = streak_at[active[-1]] if active and (today - active[-1]).days <= 1 else 0

    adjustments = load_adjustments()
    rows, total = [], 0
    for n in sorted(set(days) | set(adjustments)):
        rec = days.get(n)
        xp, bonus = 0, False
        if rec:
            bonus = streak_at[rec["date"]] >= 7
            xp = round(base_xp(rec["parts"]) * (1.2 if bonus else 1.0))
        for a in adjustments.get(n, []):
            xp += int(a["xp"])
        total += xp
        rows.append({
            "day": n,
            "date": rec["date"].isoformat() if rec else None,
            "xp": xp,
            "tags": tag_labels(rec["parts"]) if rec else [],
            "streak_bonus": bonus,
            "adjusted": n in adjustments,
        })

    level = int(math.sqrt(total / 20))
    summary = {
        "total_xp": total,
        "level": level,
        "title": next(t for lv, t in TITLES if level >= lv),
        "level_floor_xp": 20 * level ** 2,
        "next_level_xp": 20 * (level + 1) ** 2,
        "xp_to_next": 20 * (level + 1) ** 2 - total,
        "streak_current": current,
        "streak_longest": longest,
        "days_logged": len(rows),
        "updated_at": datetime.now(IST).isoformat(timespec="seconds"),
        "days": rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(summary, indent=2) + "\n")
    print(f"Level {level} ({summary['title']}) | {total} XP | "
          f"{summary['xp_to_next']} to next | streak {current} (best {longest})")


if __name__ == "__main__":
    main()
