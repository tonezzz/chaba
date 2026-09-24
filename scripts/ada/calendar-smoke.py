#!/usr/bin/env python3
"""Read-only smoke test for Ada's calendar backend against live providers.

Loads the rendered registry (~/.config/ada/calendar.json) exactly the way a
running ada service does, then lists calendars, today's events, open tasks,
and freebusy. No writes unless --write-test is passed (creates then deletes
a clearly-marked test event).

Run on any host that has the registry + token file:

  python3 scripts/ada/calendar-smoke.py               # read-only smoke
  python3 scripts/ada/calendar-smoke.py --write-test  # create+delete a test event
  python3 scripts/ada/calendar-smoke.py --day tomorrow --days 3

Env: ADA_INSTANCE_ID (defaults to 'tony' for the smoke run),
     ADA_CALENDAR_FILE, ADA_GOOGLE_TOKEN_FILE as usual.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

# repo checkout of ada-pi on this host — registry/env decide everything else
ADA_PI = os.environ.get("ADA_PI_DIR", os.path.expanduser("~/CascadeProjects/ada-pi"))
sys.path.insert(0, ADA_PI)


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--day", default="today")
    ap.add_argument("--days", type=int, default=1)
    ap.add_argument("--write-test", action="store_true", help="create then delete a '[ada smoke]' event")
    args = ap.parse_args()

    os.environ.setdefault("ADA_INSTANCE_ID", "tony")

    from backend.calendar_providers import CalendarService

    svc = CalendarService.load(instance=os.environ["ADA_INSTANCE_ID"])
    if svc is None:
        print("FAIL: calendar not configured (no registry providers for this instance)")
        return 1

    print(f"== providers: {list(svc.providers)}  read={svc.read}  write={svc.write}  tz={svc.tz}\n")

    cals = await svc.list_calendars()
    print(f"calendars ({len(cals['calendars'])}):")
    for c in cals["calendars"]:
        print(f"  {c['qualified']:40} {c['title']}{'  [primary]' if c.get('primary') else ''}")
    for e in cals["errors"]:
        print(f"  ERROR {e}")

    events = await svc.list_events(day=args.day, days=args.days)
    print(f"\nevents {args.day} +{args.days}d ({len(events['events'])}):")
    for ev in events["events"]:
        print(f"  {ev['start'][:16]:18} {ev['title']}  [{ev['id']}]")
    for e in events["errors"]:
        print(f"  ERROR {e}")

    tasks = await svc.list_tasks()
    print(f"\nopen tasks ({len(tasks['tasks'])}):")
    for t in tasks["tasks"][:15]:
        print(f"  {t['title']}  due={t.get('due') or '-'}  [{t['id']}]")
    for e in tasks["errors"]:
        print(f"  ERROR {e}")

    busy = await svc.freebusy(day=args.day)
    print(f"\nbusy slots {args.day}: {len(busy['busy'])}")
    for e in busy["errors"]:
        print(f"  ERROR {e}")

    if args.write_test:
        print("\n-- write test: creating '[ada smoke] test event' --")
        from datetime import datetime, timedelta
        start = (datetime.now(svc.tz) + timedelta(hours=2)).replace(minute=0, second=0, microsecond=0)
        ev = await svc.create_event("[ada smoke] test event", start.isoformat(), (start + timedelta(minutes=30)).isoformat())
        print(f"created {ev['id']}")
        await svc.delete_event(ev["id"])
        print("deleted — write path OK")

    print("\nSMOKE OK" if not (cals["errors"] or events["errors"] or tasks["errors"]) else "\nSMOKE PARTIAL — see errors above")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
