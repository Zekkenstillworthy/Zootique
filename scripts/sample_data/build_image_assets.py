"""Build the local sample image checklist and download licensed Commons assets."""

from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
import re
import sys
import time

import requests
from PIL import Image, UnidentifiedImageError

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.sample_data.fixture import SAMPLE_ZOOS

ASSET_ROOT = ROOT / "static" / "img" / "seed"
CHECKLIST = ROOT / "sample_data_image_checklist.md"
SOURCES = ASSET_ROOT / "image_sources.json"
CACHE_FILE = ASSET_ROOT / "image_query_cache.json"
API = "https://commons.wikimedia.org/w/api.php"
REST_API = "https://commons.wikimedia.org/w/rest.php/v1/search/page"
HEADERS = {"User-Agent": "Zootique sample asset importer/1.0"}


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def image_entry(zoo: dict, record_type: str, filename: str, description: str, query: str) -> dict:
    return {"zoo": zoo["slug"], "type": record_type, "filename": filename, "description": description, "query": query}


def entries() -> list[dict]:
    result = []
    for zoo in SAMPLE_ZOOS:
        if zoo["type"] == "Aquarium":
            theme = "coral reef aquarium"
        elif zoo["type"] == "Farm Attraction":
            theme = "farm visitors"
        elif zoo["type"] == "Safari Park":
            theme = "open range safari wildlife"
        elif zoo["type"] == "Wildlife Rescue Center":
            theme = "wildlife rescue sanctuary"
        else:
            theme = "zoo animals visitors"
        result.append(image_entry(zoo, "cover", "zoo-cover.jpg", f"{zoo['name']} — {theme} visitor view", theme))
        result.append(image_entry(zoo, "map", "map.jpg", f"{zoo['name']} — illustrated zoo or park map", f"{theme} map"))
        for zone in zoo["zones"]:
            query = "zoo entrance" if zone["name"] == "Entrance Plaza" else "zoo education pavilion" if zone["name"] == "Learning Pavilion" else f"{theme} habitat"
            result.append(image_entry(zoo, "zone", f"zone-{slug(zone['name'])}.jpg", f"{zone['name']} — {zone['description']}", query))
        for animal in zoo["animals"]:
            query = "binturong bearcat animal" if animal["species"] == "Bearcat" else f"{animal['species']} animal"
            result.append(image_entry(zoo, "animal", f"animal-{slug(animal['name'])}.jpg", f"{animal['name']} — {animal['species']}", query))
        for service in zoo["services"]:
            text = (service["name"] + " " + service["description"]).lower()
            if any(word in text for word in ("farm", "garden", "harvest", "carabao", "pasture")):
                query = "farm animal visitors"
            elif any(word in text for word in ("reef", "aquarium", "turtle", "sea")):
                query = "aquarium reef visitors"
            elif any(word in text for word in ("safari", "wildlife", "range", "predator", "giraffe", "elephant")):
                query = "wildlife safari visitors"
            elif any(word in text for word in ("feeding", "keeper", "animal care")):
                query = "zookeeper feeding animal"
            else:
                query = "zoo visitors education"
            result.append(image_entry(zoo, "service", f"service-{slug(service['name'])}.jpg", f"{service['name']} — {service['description']}", query))
        for event in zoo["events"]:
            query = "animal feeding keeper" if event["type"] == "Feeding" else "wildlife keeper education talk"
            result.append(image_entry(zoo, "event", f"event-{slug(event['name'])}.jpg", f"{event['name']} — {event['type']} event at {event['zone']}", query))
        for promotion in zoo["promotions"]:
            result.append(image_entry(zoo, "promotion", f"promotion-{slug(promotion['code'])}.jpg", f"{promotion['name']} — {promotion['promo_type']} visitor offer", theme))
    return result


def find_source(query: str, cache: dict[str, dict | None]) -> dict | None:
    if query in cache:
        return cache[query]
    params = {
        "action": "query", "generator": "search", "gsrsearch": query,
        "gsrnamespace": 6, "gsrlimit": 20, "prop": "imageinfo",
        "iiprop": "url|mime|extmetadata", "iiurlwidth": 1000, "format": "json",
    }
    for attempt in range(4):
        response = requests.get(API, params=params, headers=HEADERS, timeout=30)
        if response.status_code != 429:
            response.raise_for_status()
            break
        time.sleep(2 ** attempt)
    if response.status_code == 429:
        response = requests.get(REST_API, params={"q": query, "limit": 20}, headers=HEADERS, timeout=30)
        response.raise_for_status()
        for page in response.json().get("pages", []):
            excerpt = page.get("excerpt", "")
            thumbnail = (page.get("thumbnail") or {}).get("url", "")
            if thumbnail and any(marker in excerpt.lower() for marker in ("cc by", "cc0", "public domain", "pdm")):
                source = {
                    "title": page.get("title"),
                    "url": re.sub(r"/\d+px-", "/1000px-", thumbnail),
                    "original_url": re.sub(r"/\d+px-", "/1000px-", thumbnail),
                    "license": excerpt,
                    "author": "Wikimedia Commons contributor",
                }
                cache[query] = source
                return source
        cache[query] = None
        return None
    for page in response.json().get("query", {}).get("pages", {}).values():
        info = (page.get("imageinfo") or [{}])[0]
        metadata = info.get("extmetadata") or {}
        license_name = (metadata.get("LicenseShortName") or {}).get("value", "")
        if (info.get("mime") or "").startswith("image/") and any(
            marker in license_name.lower() for marker in ("cc by", "cc by-sa", "cc0", "public domain", "pdm")
        ):
            source = {
                "title": page.get("title"), "url": info.get("thumburl") or info.get("url"),
                "original_url": info.get("url"), "license": license_name,
                "author": (metadata.get("Artist") or {}).get("value", ""),
            }
            cache[query] = source
            return source
    cache[query] = None
    return None


def download(entry: dict, source: dict) -> bool:
    target = ASSET_ROOT / entry["zoo"] / entry["filename"]
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file() and target.stat().st_size > 10_000:
        return True
    urls = [source["url"], source["original_url"]]
    clean_url = re.sub(
        r"https://thumb\.wikimedia\.org/wikipedia/commons/thumb/(.*?)/\d+px-[^/]+(?:\?.*)?$",
        r"https://upload.wikimedia.org/wikipedia/commons/\1",
        source["url"],
    )
    clean_url = clean_url.split("?")[0]
    urls.append(clean_url)
    for url in dict.fromkeys(urls):
        try:
            response = None
            for attempt in range(4):
                response = requests.get(url, headers=HEADERS, timeout=30)
                if response.status_code != 429:
                    break
                time.sleep(2 ** attempt)
            response.raise_for_status()
            response.raise_for_status()
            image = Image.open(BytesIO(response.content)).convert("RGB")
            image.thumbnail((1400, 1000), Image.Resampling.LANCZOS)
            for quality in (84, 78, 72, 66):
                buffer = BytesIO()
                image.save(buffer, "JPEG", quality=quality, optimize=True, progressive=True)
                if len(buffer.getvalue()) <= 260_000 or quality == 66:
                    target.write_bytes(buffer.getvalue())
                    return True
        except (requests.RequestException, UnidentifiedImageError, OSError):
            continue
    return False


def write_checklist(rows: list[dict]) -> None:
    lines = ["# Sample image checklist", "", "Generated from `scripts/sample_data/fixture.py`; every path is rendered by a sample page.", ""]
    for zoo in SAMPLE_ZOOS:
        lines += [f"## {zoo['name']} (`{zoo['slug']}`)", "", "| File path | Subject |", "| --- | --- |"]
        for row in (row for row in rows if row["zoo"] == zoo["slug"]):
            lines.append(f"| `static/img/seed/{row['zoo']}/{row['filename']}` | {row['description']} |")
        lines.append("")
    CHECKLIST.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    rows = entries()
    write_checklist(rows)
    cache = json.loads(CACHE_FILE.read_text(encoding="utf-8")) if CACHE_FILE.is_file() else {}
    sources = json.loads(SOURCES.read_text(encoding="utf-8")) if SOURCES.is_file() else {}
    failures = []
    for index, row in enumerate(rows, start=1):
        source = find_source(row["query"], cache)
        if source is None:
            failures.append((row["filename"], row["query"]))
            continue
        if not download(row, source):
            failures.append((row["filename"], row["query"]))
            continue
        sources[f"{row['zoo']}/{row['filename']}"] = source
        CACHE_FILE.write_text(json.dumps(cache, indent=2), encoding="utf-8")
        print(f"[{index}/{len(rows)}] OK {row['zoo']}/{row['filename']}")
        time.sleep(0.03)
    SOURCES.parent.mkdir(parents=True, exist_ok=True)
    SOURCES.write_text(json.dumps(sources, indent=2), encoding="utf-8")
    print(f"ASSETS={len(sources)} EXPECTED={len(rows)} FAILED={len(failures)}")
    for failure in failures:
        print("FAILED=", failure)
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())