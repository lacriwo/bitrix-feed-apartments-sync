#!/usr/bin/env python3
"""
Downloads Bitrix Yandex.Realty XML feed and writes data/apartments.json
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any


FEED_URL = os.environ.get(
    "FEED_URL",
    "https://bx.sskuban.ru/local/integrat/feed/jcat/9019077",
)
OUT_JSON = os.environ.get("OUT_JSON", os.path.join(os.path.dirname(__file__), "..", "data", "apartments.json"))
OUT_META = os.environ.get("OUT_META", os.path.join(os.path.dirname(__file__), "..", "data", "sync_meta.json"))


def local_name(tag: str) -> str:
    return tag.split("}", 1)[-1] if tag.startswith("{") else tag


def first_child(parent: ET.Element, name: str) -> ET.Element | None:
    for c in parent:
        if local_name(c.tag) == name:
            return c
    return None


def all_children(parent: ET.Element, name: str) -> list[ET.Element]:
    return [c for c in parent if local_name(c.tag) == name]


def elem_text(el: ET.Element | None) -> str | None:
    if el is None:
        return None
    t = (el.text or "").strip()
    return t if t else None


def nested_text(parent: ET.Element, path: list[str]) -> str | None:
    node: ET.Element | None = parent
    for p in path:
        if node is None:
            return None
        node = first_child(node, p)
    return elem_text(node)


def parse_offer(offer: ET.Element) -> dict[str, Any]:
    oid = offer.attrib.get("internal-id") or offer.attrib.get("internal_id")
    loc = first_child(offer, "location")
    price_el = first_child(offer, "price")

    images: list[str] = []
    plan_first: str | None = None
    for img in all_children(offer, "image"):
        url = elem_text(img)
        if not url:
            continue
        tag = img.attrib.get("tag", "")
        if tag == "plan" and plan_first is None:
            plan_first = url
        images.append(url)
    if plan_first and images and images[0] != plan_first:
        images = [plan_first] + [u for u in images if u != plan_first]

    row: dict[str, Any] = {
        "internal_id": oid,
        "type": elem_text(first_child(offer, "type")),
        "category": elem_text(first_child(offer, "category")),
        "deal_status": elem_text(first_child(offer, "deal-status")),
        "price_value": nested_text(price_el, ["value"]) if price_el is not None else None,
        "price_currency": nested_text(price_el, ["currency"]) if price_el is not None else None,
        "address": nested_text(loc, ["address"]) if loc is not None else None,
        "apartment": nested_text(loc, ["apartment"]) if loc is not None else None,
        "region": nested_text(loc, ["region"]) if loc is not None else None,
        "locality": nested_text(loc, ["locality-name"]) if loc is not None else None,
        "rooms": elem_text(first_child(offer, "rooms")),
        "floor": elem_text(first_child(offer, "floor")),
        "floors_total": elem_text(first_child(offer, "floors-total")),
        "area_value": nested_text(first_child(offer, "area"), ["value"]),
        "area_unit": nested_text(first_child(offer, "area"), ["unit"]),
        "building_name": elem_text(first_child(offer, "building-name")),
        "yandex_building_id": elem_text(first_child(offer, "yandex-building-id")),
        "yandex_house_id": elem_text(first_child(offer, "yandex-house-id")),
        "building_section": elem_text(first_child(offer, "building-section")),
        "built_year": elem_text(first_child(offer, "built-year")),
        "ready_quarter": elem_text(first_child(offer, "ready-quarter")),
        "images": images[:30],
    }
    desc = elem_text(first_child(offer, "description"))
    if desc:
        row["description"] = desc[:5000]
    return row


def main() -> int:
    print(f"Fetching {FEED_URL!r} …", file=sys.stderr)
    req = urllib.request.Request(
        FEED_URL,
        headers={"User-Agent": "bitrix-feed-apartments-sync/1.0"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        raw = resp.read()

    root = ET.fromstring(raw)
    gen_el = first_child(root, "generation-date")
    generation_date = elem_text(gen_el)

    offers: list[ET.Element] = []
    for child in root:
        if local_name(child.tag) == "offer":
            offers.append(child)

    apartments = [parse_offer(o) for o in offers]
    apartments.sort(key=lambda r: str(r.get("internal_id") or ""))

    payload = {
        "feed_url": FEED_URL,
        "generation_date": generation_date,
        "synced_at": datetime.now(timezone.utc).isoformat(),
        "count": len(apartments),
        "apartments": apartments,
    }

    os.makedirs(os.path.dirname(os.path.abspath(OUT_JSON)), exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    meta = {
        "feed_url": FEED_URL,
        "generation_date": generation_date,
        "synced_at": payload["synced_at"],
        "count": len(apartments),
    }
    with open(OUT_META, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print(f"Wrote {len(apartments)} apartments → {OUT_JSON}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
