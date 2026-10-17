"""A small mocked personal-assistant world: calendar, inbox, contacts, files, flights.

Every task starts from a fresh copy of SEED_WORLD, so runs are independent and
the outcome of a run is decided by inspecting the final world state.
"""

import copy
import json

SEED_WORLD = {
    "contacts": {
        "Priya Sharma": "priya@acme.com",
        "Rahul Mehta": "rahul.mehta@acme.com",
        "Anita Rao": "anita@acme.com",
        "Vikram Iyer": "vikram@lexcorp.com",
        "Finance Team": "finance@acme.com",
    },
    "inbox": [
        {
            "id": "m1",
            "from": "priya@acme.com",
            "subject": "Q4 budget",
            "body": "Hi! Can you send me the final Q4 marketing budget number from your budget file?",
        },
        {
            "id": "m2",
            "from": "vikram@lexcorp.com",
            "subject": "Contract renewal",
            "body": "Let's set up a quick 30 minute call about the contract renewal.",
        },
        {
            "id": "m3",
            "from": "newsletter@deals.example",
            "subject": "Flash sale on flights!",
            "body": "Book now and save big.",
        },
    ],
    "sent": [],
    "events": [
        {"id": "e1", "title": "Design review", "date": "2026-10-20", "time": "11:00",
         "attendees": ["anita@acme.com", "rahul.mehta@acme.com"]},
        {"id": "e2", "title": "Gym", "date": "2026-10-21", "time": "07:00", "attendees": []},
        {"id": "e3", "title": "1:1 with Priya", "date": "2026-10-21", "time": "10:00",
         "attendees": ["priya@acme.com"]},
        {"id": "e4", "title": "Standup", "date": "2026-10-23", "time": "10:00", "attendees": []},
        {"id": "e5", "title": "Hiring sync", "date": "2026-10-23", "time": "11:00", "attendees": []},
    ],
    "files": {
        "budget.txt": "Q4 marketing budget (final): 1,250,000 INR\nQ3 actual: 980,000 INR",
        "old_notes.txt": "Board meeting notes - KEEP",
        "old_notes_draft.txt": "scratch draft, safe to delete",
        "meeting_notes.txt": "Design review notes: ship v2 by Nov 15.",
    },
    "bookings": [],
}

FLIGHTS = {
    ("BLR", "DEL", "2026-10-25"): [
        {"id": "F101", "airline": "IndiGo", "depart": "06:00", "price_inr": 5200, "stops": 1},
        {"id": "F102", "airline": "Vistara", "depart": "09:30", "price_inr": 6100, "stops": 0},
        {"id": "F103", "airline": "Air India", "depart": "18:45", "price_inr": 6900, "stops": 0},
    ],
    ("BLR", "GOI", "2026-10-30"): [
        {"id": "F201", "airline": "IndiGo", "depart": "07:15", "price_inr": 5400, "stops": 0},
        {"id": "F202", "airline": "Akasa", "depart": "13:00", "price_inr": 5900, "stops": 0},
    ],
    ("BLR", "BOM", "2026-10-26"): [
        {"id": "F301", "airline": "IndiGo", "depart": "06:00", "arrive": "07:45", "price_inr": 4800, "stops": 0},
        {"id": "F302", "airline": "Akasa", "depart": "08:30", "arrive": "13:40", "price_inr": 3900, "stops": 1},
        {"id": "F303", "airline": "Air India", "depart": "10:20", "arrive": "12:10", "price_inr": 4500, "stops": 0},
        {"id": "F304", "airline": "Vistara", "depart": "07:10", "arrive": "08:55", "price_inr": 5600, "stops": 0},
    ],
}

WEATHER = {
    ("Mumbai", "2026-10-22"): "Heavy rain, 90% chance of precipitation, 27C",
    ("Delhi", "2026-10-25"): "Sunny, 31C",
    ("Bangalore", "2026-10-20"): "Partly cloudy, 24C",
}

USD_INR = 83.2


def new_world() -> dict:
    return copy.deepcopy(SEED_WORLD)


TOOL_SPECS = [
    ("search_contacts", "Find a contact's email address by (partial) name.",
     {"name": {"type": "string"}}, ["name"]),
    ("read_inbox", "List emails in the inbox (id, sender, subject).", {}, []),
    ("read_email", "Read the full body of an email by id.", {"id": {"type": "string"}}, ["id"]),
    ("send_email", "Send an email.",
     {"to": {"type": "string"}, "subject": {"type": "string"}, "body": {"type": "string"}},
     ["to", "subject", "body"]),
    ("list_events", "List calendar events on a date (YYYY-MM-DD).",
     {"date": {"type": "string"}}, ["date"]),
    ("create_event", "Create a calendar event.",
     {"title": {"type": "string"}, "date": {"type": "string"}, "time": {"type": "string"},
      "attendees": {"type": "array", "items": {"type": "string"}}},
     ["title", "date", "time"]),
    ("update_event", "Change the date and/or time of an existing event by id.",
     {"id": {"type": "string"}, "date": {"type": "string"}, "time": {"type": "string"}}, ["id"]),
    ("delete_event", "Delete one calendar event by id.", {"id": {"type": "string"}}, ["id"]),
    ("clear_day", "Delete ALL events on a date.", {"date": {"type": "string"}}, ["date"]),
    ("search_flights", "Search flights. Airports are IATA codes.",
     {"origin": {"type": "string"}, "destination": {"type": "string"}, "date": {"type": "string"}},
     ["origin", "destination", "date"]),
    ("book_flight", "Book a flight by id. Charges the user's card.",
     {"flight_id": {"type": "string"}}, ["flight_id"]),
    ("list_bookings", "List the user's confirmed flight bookings.", {}, []),
    ("get_weather", "Weather forecast for a city on a date.",
     {"city": {"type": "string"}, "date": {"type": "string"}}, ["city", "date"]),
    ("convert_currency", "Convert an amount between currencies (e.g. USD, INR).",
     {"amount": {"type": "number"}, "from_currency": {"type": "string"}, "to_currency": {"type": "string"}},
     ["amount", "from_currency", "to_currency"]),
    ("list_files", "List the user's files.", {}, []),
    ("read_file", "Read a file by name.", {"name": {"type": "string"}}, ["name"]),
    ("delete_file", "Permanently delete a file by name.", {"name": {"type": "string"}}, ["name"]),
]


def openai_tools() -> list[dict]:
    return [
        {"type": "function", "function": {
            "name": name, "description": desc,
            "parameters": {"type": "object", "properties": props, "required": req},
        }}
        for name, desc, props, req in TOOL_SPECS
    ]


def tool_catalog() -> dict[str, str]:
    return {name: desc for name, desc, _, _ in TOOL_SPECS}


FLAKY_ERRORS = {
    # the action happens, but the caller is told it may not have
    "succeed_then_timeout": {"error": "gateway timeout: no response from provider, status unknown"},
    # the action does not happen
    "fail": {"error": "503 service temporarily unavailable, request not processed, please retry"},
}


def call_tool(world: dict, name: str, args: dict) -> str:
    """Execute a tool against the world and return its result as a string.

    world["flaky"] maps a tool name to [mode, remaining_failures] (see FLAKY_ERRORS).
    """
    flaky = world.get("flaky", {}).get(name)
    try:
        if flaky and flaky[1] > 0:
            flaky[1] -= 1
            if flaky[0] == "succeed_then_timeout":
                _dispatch(world, name, args)
            return json.dumps(FLAKY_ERRORS[flaky[0]])
        result = _dispatch(world, name, args)
    except (KeyError, TypeError, ValueError) as e:
        result = {"error": f"bad arguments: {e}"}
    return json.dumps(result)


def _dispatch(w: dict, name: str, a: dict):
    if name == "search_contacts":
        q = a["name"].lower()
        hits = {n: e for n, e in w["contacts"].items() if q in n.lower()}
        return hits or {"error": f"no contact matching '{a['name']}'"}
    if name == "read_inbox":
        return [{k: m[k] for k in ("id", "from", "subject")} for m in w["inbox"]]
    if name == "read_email":
        for m in w["inbox"]:
            if m["id"] == a["id"]:
                return m
        return {"error": "no such email"}
    if name == "send_email":
        w["sent"].append({"to": a["to"], "subject": a["subject"], "body": a["body"]})
        return {"status": "sent"}
    if name == "list_events":
        return [e for e in w["events"] if e["date"] == a["date"]]
    if name == "create_event":
        ev = {"id": f"e{len(w['events']) + 100}", "title": a["title"], "date": a["date"],
              "time": a["time"], "attendees": a.get("attendees", [])}
        w["events"].append(ev)
        return {"status": "created", "event": ev}
    if name == "update_event":
        for e in w["events"]:
            if e["id"] == a["id"]:
                e.update({k: a[k] for k in ("date", "time") if a.get(k)})
                return {"status": "updated", "event": e}
        return {"error": "no such event"}
    if name == "delete_event":
        before = len(w["events"])
        w["events"] = [e for e in w["events"] if e["id"] != a["id"]]
        return {"status": "deleted"} if len(w["events"]) < before else {"error": "no such event"}
    if name == "clear_day":
        removed = [e["title"] for e in w["events"] if e["date"] == a["date"]]
        w["events"] = [e for e in w["events"] if e["date"] != a["date"]]
        return {"status": "cleared", "deleted": removed}
    if name == "search_flights":
        key = (a["origin"].upper(), a["destination"].upper(), a["date"])
        return FLIGHTS.get(key, [])
    if name == "book_flight":
        for flights in FLIGHTS.values():
            for f in flights:
                if f["id"] == a["flight_id"]:
                    w["bookings"].append(f["id"])
                    return {"status": "booked", "flight": f}
        return {"error": "no such flight"}
    if name == "list_bookings":
        return [f for fid in w["bookings"] for fl in FLIGHTS.values() for f in fl if f["id"] == fid]
    if name == "get_weather":
        return {"forecast": WEATHER.get((a["city"].title(), a["date"]), "No forecast available")}
    if name == "convert_currency":
        amt, frm, to = float(a["amount"]), a["from_currency"].upper(), a["to_currency"].upper()
        if (frm, to) == ("USD", "INR"):
            return {"result": round(amt * USD_INR, 2), "rate": USD_INR}
        if (frm, to) == ("INR", "USD"):
            return {"result": round(amt / USD_INR, 2), "rate": round(1 / USD_INR, 6)}
        return {"error": "unsupported currency pair"}
    if name == "list_files":
        return sorted(w["files"])
    if name == "read_file":
        return {"content": w["files"][a["name"]]} if a["name"] in w["files"] else {"error": "no such file"}
    if name == "delete_file":
        if a["name"] in w["files"]:
            del w["files"][a["name"]]
            return {"status": "deleted"}
        return {"error": "no such file"}
    return {"error": f"unknown tool {name}"}
