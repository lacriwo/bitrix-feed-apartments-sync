#!/usr/bin/env python3
"""
По образцу feed-portal: скачивает исходный XML, при необходимости преобразует,
пишет feeds/<slug>.xml и data/state.json. Режим transform=metarealty_2024_12 —
фид для требований Яндекс «Квартиры» / metarealty 2024-12.
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.etree.ElementTree import ParseError

ROOT = Path(__file__).resolve().parents[1]
PROJECTS_FILE = ROOT / "data" / "projects.json"
STATE_FILE = ROOT / "data" / "state.json"
FEEDS_DIR = ROOT / "feeds"
INDEX_FILE = FEEDS_DIR / "index.json"

METAREALTY_NS = "http://webmaster.yandex.ru/schemas/feed/metarealty/2024-12"

RENOVATION_TO_DECORATION: dict[str, str] = {
    "предчистовая отделка": "pre_clean",
    "предчистовая": "pre_clean",
    "черновая": "rough",
    "чистовая": "clean",
    "под ключ": "turnkey",
    "белый короб": "white_box",
    "без отделки": "no_decoration",
}

FEEDS_DIR.mkdir(parents=True, exist_ok=True)


def load_json(path: Path, default):
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def save_json(path: Path, data) -> None:
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def fetch_xml_bytes(url: str, retries: int = 3, timeout: int = 120) -> bytes:
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "bitrix-feed-apartments-sync/1.0"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as response:
                status = getattr(response, "status", 200)
                if status >= 400:
                    raise RuntimeError(f"HTTP status {status}")
                return response.read()
        except (urllib.error.URLError, TimeoutError, RuntimeError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(attempt * 2)
    raise RuntimeError(f"Failed to load source feed: {last_error}")


def local_name(tag: str) -> str:
    if tag.startswith("{") and "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def sanitize_xml(xml_bytes: bytes) -> bytes:
    text = xml_bytes.decode("utf-8", errors="replace")
    text = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F]", "", text)
    text = re.sub(
        r"&(?!amp;|lt;|gt;|quot;|apos;|#\d+;|#x[0-9A-Fa-f]+;)",
        "&amp;",
        text,
    )
    return text.encode("utf-8")


def should_refresh(slug: str, interval_hours: int, state: dict, now: datetime) -> bool:
    entry = state.get(slug)
    if not entry:
        return True
    last = entry.get("last_refresh_utc")
    if not last:
        return True
    try:
        last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
    except ValueError:
        return True
    return now - last_dt >= timedelta(hours=interval_hours)


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


def nested_text(parent: ET.Element | None, *path: str) -> str | None:
    node: ET.Element | None = parent
    for p in path:
        if node is None:
            return None
        node = first_child(node, p)
    return elem_text(node)


def map_currency(c: str | None) -> str:
    u = (c or "RUB").strip().upper()
    if u == "RUR":
        return "RUB"
    return u


def collect_images(offer: ET.Element) -> list[str]:
    items: list[tuple[int, str]] = []
    for img in all_children(offer, "image"):
        url = elem_text(img)
        if not url:
            continue
        tag = (img.attrib.get("tag") or "").strip()
        rank = 2
        if tag == "plan" or "/planers/p/" in url:
            rank = 0
        elif "/planers/floors/" in url:
            rank = 1
        items.append((rank, url))
    items.sort(key=lambda x: (x[0], x[1]))
    return [u for _, u in items]


def decoration_from_renovation(ren: str | None) -> str | None:
    if not ren:
        return None
    low = ren.lower()
    for key, val in RENOVATION_TO_DECORATION.items():
        if key in low:
            return val
    return None


def build_location(
    loc: ET.Element | None,
    def_lat: str,
    def_lon: str,
    canonical_address: str | None = None,
) -> tuple[dict[str, str], bool]:
    if loc is None:
        return {}, False
    apartment = elem_text(first_child(loc, "apartment"))

    if canonical_address:
        address = canonical_address.strip()
    else:
        region = elem_text(first_child(loc, "region"))
        locality = elem_text(first_child(loc, "locality-name"))
        addr = elem_text(first_child(loc, "address"))
        address = addr or ""
        if address and region and region not in address:
            address = f"{region}, {address}"
        if address and locality and locality not in address:
            address = f"{locality}, {address}"

    if not address:
        return {}, False

    # Координаты ЖК с Яндекс Карт; не берём из Битрикса, если задан canonical_address
    if canonical_address:
        lat, lon = def_lat, def_lon
    else:
        lat = elem_text(first_child(loc, "latitude")) or def_lat
        lon = elem_text(first_child(loc, "longitude")) or def_lon

    out: dict[str, str] = {"address": address, "latitude": lat, "longitude": lon}
    if apartment:
        out["apartment"] = apartment
    return out, True


def sub_area(parent: ET.Element, tag: str, src: ET.Element | None) -> bool:
    if src is None:
        return False
    v = nested_text(src, "value")
    unit = nested_text(src, "unit") or "кв. м"
    if not v:
        return False
    a = ET.SubElement(parent, tag)
    ET.SubElement(a, "value").text = v
    ET.SubElement(a, "unit").text = unit
    return True


def transform_offer(
    offer: ET.Element,
    def_lat: str,
    def_lon: str,
    canonical_address: str | None = None,
) -> ET.Element | None:
    oid = offer.attrib.get("internal-id")
    if not oid:
        return None
    typ = elem_text(first_child(offer, "type"))
    cat = elem_text(first_child(offer, "category"))
    if not typ or not cat:
        return None

    loc_el = first_child(offer, "location")
    loc_fields, loc_ok = build_location(loc_el, def_lat, def_lon, canonical_address)
    if not loc_ok:
        return None

    deal = elem_text(first_child(offer, "deal-status"))
    if not deal:
        return None

    price_el = first_child(offer, "price")
    p_val = nested_text(price_el, "value") if price_el is not None else None
    p_cur = map_currency(nested_text(price_el, "currency") if price_el is not None else None)
    if not p_val:
        return None

    images = collect_images(offer)
    if not images:
        return None

    area_el = first_child(offer, "area")
    if area_el is None or nested_text(area_el, "value") is None:
        return None

    yb = elem_text(first_child(offer, "yandex-building-id"))
    yh = elem_text(first_child(offer, "yandex-house-id"))
    if not yb or not yh:
        return None

    neo = ET.Element("offer")
    neo.set("internal-id", oid)

    ET.SubElement(neo, "type").text = typ
    ET.SubElement(neo, "category").text = cat

    loc_out = ET.SubElement(neo, "location")
    for k, v in loc_fields.items():
        ET.SubElement(loc_out, k).text = v

    ET.SubElement(neo, "deal-status").text = deal
    pr = ET.SubElement(neo, "price")
    ET.SubElement(pr, "value").text = p_val
    ET.SubElement(pr, "currency").text = p_cur

    for url in images:
        ET.SubElement(neo, "image").text = url

    sub_area(neo, "area", area_el)
    sub_area(neo, "kitchen-space", first_child(offer, "kitchen-space"))
    sub_area(neo, "living-space", first_child(offer, "living-space"))

    dec = decoration_from_renovation(elem_text(first_child(offer, "renovation")))
    if dec:
        ET.SubElement(neo, "decoration-type").text = dec

    desc = elem_text(first_child(offer, "description"))
    if desc:
        ET.SubElement(neo, "description").text = desc[:10000]

    for tag in (
        "rooms",
        "floor",
        "floors-total",
        "building-name",
        "yandex-building-id",
        "yandex-house-id",
        "building-type",
        "lift",
        "built-year",
        "ready-quarter",
        "building-state",
    ):
        t = elem_text(first_child(offer, tag))
        if t:
            ET.SubElement(neo, tag).text = t

    return neo


def build_metarealty_feed(project: dict) -> bytes:
    xml_data = fetch_xml_bytes(project["source_feed_url"])
    xml_data = sanitize_xml(xml_data)
    root_in = ET.fromstring(xml_data)

    gen: str | None = None
    offers_in: list[ET.Element] = []
    for child in root_in:
        ln = local_name(child.tag)
        if ln == "generation-date":
            gen = elem_text(child)
        elif ln == "offer":
            offers_in.append(child)

    if not gen:
        gen = datetime.now(timezone(timedelta(hours=3))).strftime("%Y-%m-%dT%H:%M:%S+03:00")

    def_lat = str(project.get("default_lat") or "45.034175")
    def_lon = str(project.get("default_lon") or "37.343642")
    canonical_address = project.get("canonical_address")
    if canonical_address:
        canonical_address = str(canonical_address).strip() or None

    root_out = ET.Element("realty-feed")
    root_out.set("xmlns", METAREALTY_NS)
    ET.SubElement(root_out, "generation-date").text = gen

    skipped = 0
    for o in offers_in:
        neo = transform_offer(o, def_lat, def_lon, canonical_address)
        if neo is None:
            skipped += 1
            continue
        root_out.append(neo)

    if skipped:
        print(f"  skipped {skipped} offers (incomplete data)")

    return ET.tostring(root_out, encoding="utf-8", xml_declaration=True)


def build_patched_feed(project: dict) -> bytes:
    import xml.dom.minidom as minidom

    xml_data = fetch_xml_bytes(project["source_feed_url"])
    xml_data = sanitize_xml(xml_data)
    root = ET.fromstring(xml_data)

    ns_uri = ""
    if root.tag.startswith("{") and "}" in root.tag:
        ns_uri = root.tag[1 : root.tag.index("}")]
        ET.register_namespace("", ns_uri)

    target_fields = set(project["fields"])
    replacement = project["replacement_value"]

    for elem in root.iter():
        if local_name(elem.tag) in target_fields:
            elem.text = replacement

    compact = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return minidom.parseString(compact).toprettyxml(indent="  ", encoding="utf-8")


def build_feed_for_project(project: dict) -> bytes:
    if project.get("transform") == "metarealty_2024_12":
        return build_metarealty_feed(project)
    return build_patched_feed(project)


def main() -> None:
    import os

    force_refresh = os.environ.get("FORCE_REFRESH", "").lower() in ("1", "true", "yes")

    projects_payload = load_json(PROJECTS_FILE, {"projects": []})
    projects = projects_payload.get("projects", [])
    state = load_json(STATE_FILE, {})
    now = datetime.now(timezone.utc)
    updated: list[str] = []

    for project in projects:
        slug = project["slug"]
        interval = int(project["interval_hours"])

        try:
            if not force_refresh and not should_refresh(slug, interval, state, now):
                print(f"Skip {slug}: not due yet")
                continue

            print(f"Refreshing {slug}...")
            xml_bytes = build_feed_for_project(project)
            out_file = FEEDS_DIR / f"{slug}.xml"
            with out_file.open("wb") as fh:
                fh.write(xml_bytes)

            state[slug] = {"last_refresh_utc": now.isoformat().replace("+00:00", "Z")}
            updated.append(slug)

        except ParseError as exc:
            print(f"Parse error for {slug}: {exc}")
            continue
        except Exception as exc:
            print(f"Error for {slug}: {exc}")
            continue

    save_json(STATE_FILE, state)

    index_payload = {
        "generated_at_utc": now.isoformat().replace("+00:00", "Z"),
        "projects": [
            {
                "slug": p["slug"],
                "project_name": p["project_name"],
                "interval_hours": p["interval_hours"],
                "feed_path": f"feeds/{p['slug']}.xml",
            }
            for p in projects
        ],
    }
    save_json(INDEX_FILE, index_payload)
    print(f"Updated feeds: {', '.join(updated) if updated else 'none'}")


if __name__ == "__main__":
    main()
