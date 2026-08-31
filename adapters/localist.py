"""Localist adapter -- reusable for any Localist calendar.

Localist powers a huge number of university calendars (UNO's
events.unomaha.edu AND Oberlin's calendar.oberlin.edu, among thousands).
They all expose the same public JSON API at /api/2/events, so this one
adapter serves every Localist source -- you just point it at a different
base URL and pass the department/type filters you want.

Modality comes from Localist's `experience` field (inperson / virtual /
hybrid); we also treat a present stream URL as online. That's what lets the
same adapter feed both an in-person source (UNO) and an online-only source
(Oberlin webcasts), with `online_only=True` dropping the in-person ones.

API shape (abridged):
  { "events": [ { "event": {
        "title", "localist_url", "description_text", "experience",
        "stream_url", "location_name",
        "event_instances": [ { "event_instance": {"start","end"} } ]
  } } ] }
"""

from __future__ import annotations

from typing import Any

from dateutil import parser as dtparse

from adapters.base import Adapter
from models import Event


class LocalistAdapter(Adapter):
    def __init__(self, name: str, source_label: str, base_url: str,
                 group_id: int | None = None,
                 type_ids: list[int] | None = None,
                 online_only: bool = False,
                 channel: str = "local"):
        self.name = name
        self.source_label = source_label
        self.base_url = base_url.rstrip("/")
        self.group_id = group_id
        self.type_ids = type_ids or []
        self.online_only = online_only
        self.channel = channel

    def fetch_raw(self) -> Any:
        endpoint = f"{self.base_url}/api/2/events"
        params: dict[str, Any] = {"days": 365, "pp": 100}
        if self.group_id:
            params["group_id"] = self.group_id
        if self.type_ids:
            params["type"] = ",".join(str(t) for t in self.type_ids)
        out: dict[str, Any] = {"events": []}
        page = 1
        while True:
            data = self._get(endpoint, page=page, **params).json()
            out["events"].extend(data.get("events", []))
            if page >= data.get("page", {}).get("total", 1):
                break
            page += 1
        return out

    def parse(self, raw: Any) -> list[Event]:
        events: list[Event] = []
        for wrapper in raw.get("events", []):
            e = wrapper.get("event", wrapper)
            title = e.get("title")
            if not title:
                continue
            online = _is_online(e)
            if self.online_only and not online:
                continue
            venue = "Online / Livestream" if online else (
                e.get("location_name") or e.get("room_number"))
            for inst in e.get("event_instances", []):
                ei = inst.get("event_instance", inst)
                start = ei.get("start")
                if not start:
                    continue
                ev = Event(
                    title=title.strip(),
                    start=dtparse.parse(start),
                    end=dtparse.parse(ei["end"]) if ei.get("end") else None,
                    venue=venue,
                    url=e.get("stream_url") or e.get("localist_url") or e.get("url"),
                    description=(e.get("description_text") or "").strip() or None,
                    category=e.get("event_type") or "Concert/Performance",
                    source=self.source_label,
                )
                events.append(ev)
        return events


def _is_online(e: dict) -> bool:
    experience = (e.get("experience") or "").lower()
    if experience in {"virtual", "hybrid"}:
        return True
    return bool(e.get("stream_url") or e.get("stream_info"))
