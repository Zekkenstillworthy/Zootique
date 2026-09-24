"""Seed a complete, manually triggered Zootique demo dataset.

Usage:
    python scripts/seed_full_demo.py
    python scripts/seed_full_demo.py --force

This script is intentionally separate from app startup and services.demo_seed.
It creates one tagged dataset, refuses to duplicate it, and uses one database
transaction for all row inserts. Images are downloaded from Unsplash and
Random User and passed through the existing StorageService.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
import urllib.request
import uuid
from urllib.error import HTTPError
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

from flask import Flask
from werkzeug.datastructures import FileStorage

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app import create_app  # noqa: E402
from models import (  # noqa: E402
    Animal,
    Booking,
    BookingPayment,
    Event,
    Feedback,
    Notification,
    Promotion,
    Service,
    StaffTask,
    User,
    Zoo,
    ZooAdminFeedback,
    ZooAdminFeedbackReply,
    ZooLayoutConfig,
    ZooSubscription,
    ZooZone,
    db,
)
from services.storage import _get_supabase_client, save_uploaded_image  # noqa: E402

SEED_VERSION = "zootique-full-demo-v1"
SEED_MARKER = f"[{SEED_VERSION}]"
VISITOR_PASSWORD = "DemoVisitor2026!"
STAFF_PASSWORD = "DemoStaff2026!"
ADMIN_PASSWORD = "DemoZooAdmin2026!"
DEMO_MAP_IMAGE = "/static/img/zoo_manila.png"
DEMO_PROMOTION_BANNER = "/static/img/dashboard_elephant.png"
DEMO_PROMOTION_BANNER_ALT = "/static/img/hero_elephant_bg.png"
DEMO_ZONE_DEFINITIONS = (
    {"name": "Entrance Plaza", "description": "Main entry point, guest services, and accessible routes.", "position_x": 20.0, "position_y": 28.0, "zone_image_url": "/static/img/dashboard_elephant.png"},
    {"name": "Discovery Trail", "description": "A shaded route connecting the most popular habitats and viewing decks.", "position_x": 50.0, "position_y": 52.0, "zone_image_url": "/static/img/hero_elephant_bg.png"},
    {"name": "Learning Pavilion", "description": "Education talks and keeper-led activities happen here.", "position_x": 80.0, "position_y": 76.0, "zone_image_url": None},
)
SPECIES_FALLBACKS = {
    "Blue tang": ("Paracanthurus hepatus", "Surgeonfish"),
    "Blue-spotted ribbontail ray": ("Bluespotted ribbontail ray", "Ribbontail ray"),
    "Lined seahorse": ("Long-snouted seahorse", "Seahorse"),
    "Masai giraffe": ("Giraffe",),
    "Native chicken": ("Chicken",),
    "Nubian goat": ("Goat",),
    "Palawan bearcat": ("Binturong", "Bearcat"),
    "Philippine native horse": ("Horse",),
    "Southern white rhinoceros": ("White rhinoceros", "Rhinoceros"),
    "Whale shark": ("Whale shark", "Shark"),
}
IMAGE_URLS = {
    "elephant": "https://images.unsplash.com/photo-1557050543-4d5f4e07ef46?auto=format&fit=crop&w=1200&q=82",
    "tiger": "https://images.unsplash.com/photo-1561731216-c3a4d99437d5?auto=format&fit=crop&w=1200&q=82",
    "lion": "https://images.unsplash.com/photo-1546182990-dffeafbe841d?auto=format&fit=crop&w=1200&q=82",
    "giraffe": "https://images.unsplash.com/photo-1547721064-da6cfb341d50?auto=format&fit=crop&w=1200&q=82",
    "zebra": "https://images.unsplash.com/photo-1526095179574-86e545346ae6?auto=format&fit=crop&w=1200&q=82",
    "rhino": "https://images.unsplash.com/photo-1557050543-4d5f4e07ef46?auto=format&fit=crop&w=1200&q=82",
    "red_panda": "https://images.unsplash.com/photo-1535338454770-8be927b5a00b?auto=format&fit=crop&w=1200&q=82",
    "eagle": "https://images.unsplash.com/photo-1529516548873-9ce57c8f155e?auto=format&fit=crop&w=1200&q=82",
    "crocodile": "https://images.unsplash.com/photo-1544551763-46a013bb70d5?auto=format&fit=crop&w=1200&q=82",
    "turtle": "https://images.unsplash.com/photo-1507525428034-b723cf961d3e?auto=format&fit=crop&w=1200&q=82",
    "hornbill": "https://images.unsplash.com/photo-1444464666168-49d633b86797?auto=format&fit=crop&w=1200&q=82",
    "clownfish": "https://images.unsplash.com/photo-1544551763-77ef2d0cfc6c?auto=format&fit=crop&w=1200&q=82",
    "seahorse": "https://images.unsplash.com/photo-1546026423-cc4642628d2b?auto=format&fit=crop&w=1200&q=82",
    "stingray": "https://images.unsplash.com/photo-1544550285-f813152fb2fd?auto=format&fit=crop&w=1200&q=82",
    "goat": "https://images.unsplash.com/photo-1524024973431-2ad916746881?auto=format&fit=crop&w=1200&q=82",
    "horse": "https://images.unsplash.com/photo-1553284965-83fd3e82fa5a?auto=format&fit=crop&w=1200&q=82",
    "rabbit": "https://images.unsplash.com/photo-1585110396000-c9ffd4e4b308?auto=format&fit=crop&w=1200&q=82",
    "buffalo": "https://upload.wikimedia.org/wikipedia/commons/9/90/Guiguinto_Municipality_in_Bulacan_08.jpg",
    "blue_tang": "https://upload.wikimedia.org/wikipedia/commons/1/13/Paletten-Doktorfisch_M%C3%BCnster.JPG",
    "wildebeest": "https://upload.wikimedia.org/wikipedia/commons/f/fb/Blue_Wildebeest%2C_Ngorongoro.jpg",
    "whale_shark": "https://upload.wikimedia.org/wikipedia/commons/f/f6/Similan_Dive_Center_-_great_whale_shark.jpg",
    "chicken": "https://upload.wikimedia.org/wikipedia/commons/8/84/Male_and_female_chicken_sitting_together.jpg",
    "owl": "https://upload.wikimedia.org/wikipedia/commons/b/b7/Palawan_Scops_Owl.jpg",
    "flying_fox": "https://upload.wikimedia.org/wikipedia/commons/7/73/Polynesian_flying_fox_%28Pteropus_tonganus%29_in_flight_Taveuni.jpg",
    "binturong": "https://upload.wikimedia.org/wikipedia/commons/a/a7/Binturong_in_Overloon.jpg",
    "ostrich": "https://upload.wikimedia.org/wikipedia/commons/c/c9/Struthio_Diversity.jpg",
    "sheep": "https://upload.wikimedia.org/wikipedia/commons/8/85/Ostfriesische_milchschafe.jpg",
    "masai_giraffe": "https://upload.wikimedia.org/wikipedia/commons/6/64/Masai_giraffes_%28Giraffa_tippelskirchi%29_Arusha.jpg",
    "reticulated_giraffe": "https://upload.wikimedia.org/wikipedia/commons/6/67/Two_Giraffes.PNG",
    "philippine_eagle": "https://upload.wikimedia.org/wikipedia/commons/1/1f/Pamarayeg_IIIx2_%28cropped%29.jpg",
}
SPECIES_IMAGE_KEYS = {
    "African lion": "lion", "Angora rabbit": "rabbit", "Asian elephant": "elephant", "Blue tang": "blue_tang",
    "Blue wildebeest": "wildebeest", "Blue-spotted ribbontail ray": "stingray", "Carabao": "buffalo", "Common ostrich": "ostrich",
    "East Friesian sheep": "sheep", "Green sea turtle": "turtle", "Lined seahorse": "seahorse", "Malayan tiger": "tiger",
    "Masai giraffe": "masai_giraffe", "Native chicken": "chicken", "Nubian goat": "goat", "Ocellaris clownfish": "clownfish",
    "Palawan bearcat": "binturong", "Palawan flying fox": "flying_fox", "Palawan hornbill": "hornbill", "Palawan scops owl": "owl",
    "Philippine crocodile": "crocodile", "Philippine eagle": "philippine_eagle", "Philippine native horse": "horse", "Plains zebra": "zebra",
    "Red panda": "red_panda", "Reticulated giraffe": "reticulated_giraffe", "Southern white rhinoceros": "rhino", "Whale shark": "whale_shark",
}

PEOPLE = [
    ("Alicia Santos", "alicia.santos@example.com", "women", 11),
    ("Mateo Rivera", "mateo.rivera@example.com", "men", 12),
    ("Clara Mendoza", "clara.mendoza@example.com", "women", 13),
    ("Julian Cruz", "julian.cruz@example.com", "men", 14),
    ("Nina Villanueva", "nina.villanueva@example.com", "women", 15),
    ("Rafael Navarro", "rafael.navarro@example.com", "men", 16),
    ("Beatriz Flores", "beatriz.flores@example.com", "women", 17),
    ("Andre Lim", "andre.lim@example.com", "men", 18),
    ("Sofia Mercado", "sofia.mercado@example.com", "women", 19),
    ("Marco Dela Cruz", "marco.delacruz@example.com", "men", 20),
    ("Elena Garcia", "elena.garcia@example.com", "women", 21),
    ("Paolo Reyes", "paolo.reyes@example.com", "men", 22),
    ("Maya Castillo", "maya.castillo@example.com", "women", 23),
    ("Diego Aquino", "diego.aquino@example.com", "men", 24),
    ("Isabel Torres", "isabel.torres@example.com", "women", 25),
    ("Enzo Bautista", "enzo.bautista@example.com", "men", 26),
    ("Lara Dominguez", "lara.dominguez@example.com", "women", 27),
    ("Gabriel Ong", "gabriel.ong@example.com", "men", 28),
]

ESTABLISHMENTS = [
    {
        "name": "Coral Triangle Marine Discovery Center",
        "type": "Aquarium",
        "location": "Mactan Island, Cebu",
        "description": "Founded by Cebuano marine biologists in 2014, the center combines reef research with public education on the Coral Triangle. Its galleries spotlight local seagrass meadows, mangrove nurseries, and responsible coastal tourism.",
        "image": "clownfish",
        "animals": [
            ("Milo", "Ocellaris clownfish", "A planted Indo-Pacific reef tank with anemone colonies and gentle circulating water."),
            ("Luna", "Green sea turtle", "A shallow rehabilitation lagoon with sandy shelves and a quiet recovery pool."),
            ("Coral", "Lined seahorse", "A seagrass nursery habitat with holdfast branches and low-current water."),
            ("Azure", "Blue tang", "A broad coral reef exhibit with live rock, caves, and open swimming space."),
            ("Tide", "Blue-spotted ribbontail ray", "A sandy-bottom touch-free viewing habitat modeled on a sheltered lagoon."),
            ("Bituin", "Whale shark", "A deep pelagic viewing tank designed for a rescued juvenile whale shark."),
        ],
        "services": [
            ("Coral Triangle Guided Walk", 650, "A naturalist-led tour through reef, mangrove, and seagrass galleries."),
            ("Behind the Reef Care Session", 900, "Watch aquarists prepare diets and explain water-quality monitoring."),
            ("Sunset Aquarium Photography", 500, "A quiet after-hours photo session focused on reef exhibits and silhouettes."),
            ("Sea Turtle Recovery Talk", 350, "A family-friendly conservation briefing beside the rehabilitation lagoon."),
        ],
        "events": [("Reef Guardians Weekend", "Workshop", "October 12, 2026", "Education Hall"), ("Blue Planet Night", "Evening Program", "November 7, 2026", "Main Gallery")],
        "promotions": [("Reef Explorer Family Pass", "CTM-FAMILY26", "Family", "December 31, 2026", "15% family discount"), ("Student Tidepool Tuesday", "CTM-STUDENT26", "Student", "November 30, 2026", "Student orientation")],
    },
    {
        "name": "Palawan Wildlife Rescue Sanctuary",
        "type": "Wildlife Rescue Center",
        "location": "Puerto Princesa, Palawan",
        "description": "Opened by a coalition of Palawan conservation groups in 2009, the sanctuary rehabilitates native wildlife confiscated from the illegal trade. Visitors follow quiet forest trails while learning how rescued animals are prepared for release or lifelong care.",
        "image": "eagle",
        "animals": [
            ("Amihan", "Philippine eagle", "A tall forest aviary with native dipterocarp branches and secluded flight lanes."),
            ("Kaya", "Palawan bearcat", "A shaded canopy habitat with climbing poles, fruit feeders, and dense foliage."),
            ("Lakan", "Philippine crocodile", "A freshwater wetland enclosure with basking banks and a deep refuge pool."),
            ("Sinta", "Palawan scops owl", "A nocturnal forest room with hollow logs and low red-spectrum lighting."),
            ("Tala", "Palawan hornbill", "A planted rainforest aviary with nest boxes and broad flight perches."),
            ("Bughaw", "Palawan flying fox", "A high-roofed dusk habitat with hanging roosts and native flowering trees."),
        ],
        "services": [
            ("Rescue Forest Walk", 550, "A ranger-led trail explaining rehabilitation, release, and habitat protection."),
            ("Raptor Care Briefing", 750, "Meet the care team and learn how rescued Philippine eagles are conditioned."),
            ("Wetland Conservation Tour", 450, "A guided visit to the crocodile and native freshwater habitats."),
            ("Keeper for a Morning", 1200, "A supervised enrichment session for guests aged 16 and over."),
        ],
        "events": [("Palawan Wildlife Week", "Conservation Fair", "October 4, 2026", "Rescue Education Hall"), ("Night Forest Soundwalk", "Guided Walk", "November 21, 2026", "Forest Trail Entrance")],
        "promotions": [("Conservation Supporter Pass", "PWR-SUPPORT26", "Seasonal", "December 15, 2026", "Wildlife meal funded"), ("Ranger Family Saturday", "PWR-RANGER26", "Family", "November 28, 2026", "Free trail booklet")],
    },
    {
        "name": "Taal Countryside Animal Farm",
        "type": "Farm Attraction",
        "location": "Laurel, Batangas",
        "description": "Established by a Batangas farming family in 2017, this working farm turns everyday livestock care into hands-on environmental education. School groups learn about animal welfare, composting, and small-scale food production against the Taal highlands.",
        "image": "goat",
        "animals": [
            ("Pipin", "Nubian goat", "A breezy hillside paddock with climbing platforms, shade trees, and mineral blocks."),
            ("Dahlia", "Philippine native horse", "A grassy exercise yard with a sheltered stable and gentle grooming stations."),
            ("Mabini", "Carabao", "A wallowing pond and shaded pasture used for supervised heritage breed care."),
            ("Tala", "Angora rabbit", "A cool, well-ventilated small-stock house with raised resting platforms."),
            ("Basil", "Native chicken", "A free-range orchard run with nesting boxes and dust-bathing areas."),
            ("Honey", "East Friesian sheep", "A grassy rotational paddock with low fencing and a covered feeding lane."),
        ],
        "services": [
            ("Morning Farm Rounds", 300, "Help the farm team with a supervised feeding and welfare check."),
            ("Carabao Care Experience", 450, "Learn how water buffalo support Philippine farming traditions."),
            ("Garden-to-Table Workshop", 500, "Harvest seasonal produce and prepare a simple farm snack."),
            ("Young Farmers Trail", 250, "A self-guided activity route for children with animal-care stations."),
        ],
        "events": [("Harvest Lantern Market", "Farm Market", "October 24, 2026", "Orchard Pavilion"), ("Carabao Heritage Day", "Heritage Program", "November 15, 2026", "Lower Pasture")],
        "promotions": [("Family Farm Morning", "TCF-FAMILY26", "Family", "December 20, 2026", "Family snack bundle"), ("School Field Day", "TCF-SCHOOL26", "Student", "November 30, 2026", "Teacher briefing")],
    },
    {
        "name": "Davao Highlands Wildlife Park",
        "type": "Zoo Park",
        "location": "Toril District, Davao City",
        "description": "Built in 2006 on former upland pasture, the park pairs spacious animal habitats with a regional breeding and education program. Its collection gives Mindanao families a close, carefully managed introduction to global wildlife and local conservation.",
        "image": "elephant",
        "animals": [
            ("Kibo", "Asian elephant", "A large forested habitat with a mud wallow, browse stands, and a deep bathing pool."),
            ("Sari", "Malayan tiger", "A planted territory with rock ledges, water, and hidden feeding lanes."),
            ("Mara", "Masai giraffe", "An open savanna paddock with acacia-style browse poles and high feeders."),
            ("Jengo", "African lion", "A warm grassland enclosure with elevated shade decks and retreat dens."),
            ("Nala", "Red panda", "A cool bamboo forest habitat with high climbing branches and nest boxes."),
            ("Bongo", "Plains zebra", "A mixed-grass paddock with dust-bathing space and visual barriers."),
        ],
        "services": [
            ("Highlands Wildlife Tour", 700, "A two-hour guided circuit through the park's flagship habitats."),
            ("Elephant Keeper Talk", 850, "Observe a protected care routine and discuss Asian elephant welfare."),
            ("Twilight Predator Walk", 600, "A late-day ranger walk focused on tiger and lion behavior."),
            ("Wildlife Portrait Session", 950, "A photography lesson using safe distances and natural habitat views."),
        ],
        "events": [("Mindanao Conservation Expo", "Education Fair", "October 18, 2026", "Visitor Center"), ("Twilight at the Park", "After-hours Tour", "December 5, 2026", "Main Gate")],
        "promotions": [("Highlands Family Safari", "DHW-FAMILY26", "Family", "December 31, 2026", "Map and guide"), ("Wildlife Photographer Pass", "DHW-PHOTO26", "Seasonal", "November 30, 2026", "Photo briefing")],
    },
    {
        "name": "Northern Plains Safari Reserve",
        "type": "Safari Park",
        "location": "Clark Freeport Zone, Pampanga",
        "description": "Founded in 2012 on restored grassland north of Manila, the reserve uses open-range habitats to support wildlife learning and native grassland restoration. Guided drives emphasize animal behavior, habitat stewardship, and responsible viewing rather than staged encounters.",
        "image": "giraffe",
        "animals": [
            ("Zuri", "Reticulated giraffe", "An open acacia-style savanna with tall browse poles and a shaded night yard."),
            ("Kito", "Plains zebra", "A rolling grassland paddock with dust wallows and a freshwater trough."),
            ("Oko", "Southern white rhinoceros", "A broad grazer habitat with a mud wallow, shade trees, and keeper lanes."),
            ("Ayo", "Common ostrich", "A dry grassland enclosure with long running lanes and nesting ground."),
            ("Jabari", "African lion", "A secure reserve edge habitat with elevated viewing berms and retreat cover."),
            ("Mosi", "Blue wildebeest", "A mixed-herd grassland with mineral sites and seasonal grazing zones."),
        ],
        "services": [
            ("Open Range Safari Drive", 1100, "A guided vehicle route through the reserve's grazing habitats."),
            ("Giraffe Browse Encounter", 850, "A keeper-led feeding talk from a protected raised platform."),
            ("Grassland Keeper Briefing", 600, "Learn how the reserve manages pasture, water, and herd welfare."),
            ("Sunrise Wildlife Drive", 1300, "An early access drive for cooler temperatures and active animals."),
        ],
        "events": [("Grassland Restoration Day", "Volunteer Program", "October 10, 2026", "North Range"), ("Safari Lights Festival", "Evening Program", "December 12, 2026", "Visitor Village")],
        "promotions": [("Sunrise Safari Season", "NPS-SUNRISE26", "Seasonal", "November 30, 2026", "Coffee included"), ("Family Range Pass", "NPS-FAMILY26", "Family", "December 31, 2026", "Reserved departure")],
    },
]


def download_image(url: str, filename: str) -> FileStorage:
    request = urllib.request.Request(url, headers={"User-Agent": "Zootique full demo seed/1.0"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = response.read()
            break
        except HTTPError as exc:
            if exc.code != 429 or attempt == 3:
                raise
            time.sleep(2 ** attempt)
    if not payload:
        raise RuntimeError(f"Downloaded image was empty: {url}")
    return FileStorage(
        stream=io.BytesIO(payload),
        filename=filename,
        content_type="image/jpeg",
    )


def find_wikipedia_image(title: str, *fallback_titles: str) -> str:
    for page_title in (title, *fallback_titles):
        time.sleep(0.35)
        api_url = "https://en.wikipedia.org/api/rest_v1/page/summary/" + quote(page_title.replace(" ", "_"))
        request = urllib.request.Request(api_url, headers={"User-Agent": "Zootique full demo seed/1.0"})
        for attempt in range(4):
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    payload = json.load(response)
                break
            except HTTPError as exc:
                if exc.code != 429 or attempt == 3:
                    raise
                time.sleep(2 ** attempt)
        image_url = payload.get("thumbnail", {}).get("source")
        if image_url:
            parts = urlsplit(image_url)
            path = parts.path.replace("/wikipedia/commons/thumb/", "/wikipedia/commons/", 1)
            path_parts = path.split("/")
            if len(path_parts) >= 2 and "px-" in path_parts[-1]:
                path_parts.pop()
                path = "/".join(path_parts)
            return urlunsplit((parts.scheme, "upload.wikimedia.org", path, parts.query, ""))
    raise RuntimeError(f"Wikipedia returned no image for: {title}")


def upload_image(app: Flask, url: str, filename: str, folder: str) -> str:
    with app.app_context():
        file_storage = download_image(url, filename)
        stored_url = save_uploaded_image(file_storage, folder)
    if not stored_url:
        raise RuntimeError(f"StorageService could not save image: {url}")
    expected_prefix = supabase_public_prefix()
    if not stored_url.startswith(expected_prefix):
        raise RuntimeError(
            "StorageService returned a non-Supabase image URL; local fallback is forbidden for this script"
        )
    return stored_url


def upload_remote_image(app: Flask, url: str, filename: str, folder: str) -> str:
    return upload_image(app, url, filename, folder)


def cached_direct_image(app: Flask, namespace: str, key: str, filename: str, folder: str, cache: dict[str, str]) -> str:
    cache_key = f"{namespace}:{key}"
    if cache_key not in cache:
        cache[cache_key] = upload_remote_image(app, IMAGE_URLS[key], filename, folder)
    return cache[cache_key]


def image_url(app: Flask, key: str, filename: str, folder: str, cache: dict[str, str]) -> str:
    if key not in cache:
        cache[key] = upload_image(app, IMAGE_URLS[key], filename, folder)
    return cache[key]


def people_image(app: Flask, gender: str, number: int, cache: dict[str, str]) -> str:
    key = f"profile:person-{gender}-{number}"
    if key not in cache:
        url = f"https://randomuser.me/api/portraits/{gender}/{number}.jpg"
        cache[key] = upload_image(app, url, f"{key}.jpg", "profile_pictures")
    return cache[key]


def add_count(counts: dict[str, int], model, amount: int = 1) -> None:
    counts[model.__tablename__] = counts.get(model.__tablename__, 0) + amount


def supabase_public_prefix() -> str:
    base_url = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    bucket = os.environ.get("SUPABASE_STORAGE_BUCKET", "zootique-images").strip()
    return f"{base_url}/storage/v1/object/public/{bucket}/"


def preflight_supabase() -> str:
    base_url = os.environ.get("SUPABASE_URL", "").strip()
    key = os.environ.get("SUPABASE_KEY", "").strip()
    bucket = os.environ.get("SUPABASE_STORAGE_BUCKET", "zootique-images").strip()
    if not base_url or not key or not bucket:
        raise RuntimeError(
            "Supabase credentials missing/invalid - this script requires real Supabase storage, no local fallback is allowed"
        )
    client = _get_supabase_client()
    if client is None:
        raise RuntimeError(
            "Supabase credentials missing/invalid - this script requires real Supabase storage, no local fallback is allowed"
        )
    try:
        client.storage.from_(bucket).list(path="", options={"limit": 1})
        probe_path = f"__zootique_seed_preflight__/{uuid.uuid4().hex}.txt"
        client.storage.from_(bucket).upload(
            path=probe_path,
            file=b"zootique supabase storage preflight",
            file_options={"content-type": "text/plain"},
        )
        client.storage.from_(bucket).remove([probe_path])
    except Exception as exc:
        raise RuntimeError(
            f"Supabase credentials invalid or bucket upload/delete is not permitted ({bucket}); no local fallback is allowed: {exc}"
        ) from exc
    prefix = supabase_public_prefix()
    print(f"Supabase connectivity check passed: bucket={bucket}")
    return prefix


def verify_seed_images(prefix: str) -> None:
    marker_zoos = Zoo.query.filter(Zoo.description.like(f"%{SEED_MARKER}%")).all()
    zoo_ids = [z.id for z in marker_zoos]
    image_values = [z.image_url for z in marker_zoos]
    image_values.extend(a.image_url for a in Animal.query.filter(Animal.zoo_id.in_(zoo_ids)).all())
    image_values.extend(s.image_url for s in Service.query.filter(Service.zoo_id.in_(zoo_ids)).all())
    image_values.extend(
        u.profile_image
        for u in User.query.filter(User.email.like("demo.%"), User.profile_image.isnot(None)).all()
    )
    invalid = [value for value in image_values if not value or not value.startswith(prefix)]
    if invalid:
        raise RuntimeError(f"Seed image verification found {len(invalid)} non-Supabase URL(s)")
    print(f"Supabase image URL verification passed: {len(image_values)} URLs checked; zero local fallback uploads")


def validate_subject_image_collisions(zoos: list[Zoo]) -> None:
    zoo_ids = [z.id for z in zoos]
    animals = Animal.query.filter(Animal.zoo_id.in_(zoo_ids)).all()
    subjects: dict[str, str] = {}
    for zoo in zoos:
        if zoo.image_url:
            subject = f"zoo cover: {zoo.name}"
            previous = subjects.setdefault(zoo.image_url, subject)
            if previous != subject:
                raise RuntimeError(f"Image collision: {subject} shares URL with {previous}")
    for animal in animals:
        if not animal.image_url:
            raise RuntimeError(f"Animal image missing: {animal.name} ({animal.species})")
        subject = f"animal species: {animal.species}"
        previous = subjects.setdefault(animal.image_url, subject)
        if previous != subject:
            raise RuntimeError(f"Image collision: {subject} shares URL with {previous}")
    print(f"Subject image collision validation passed: {len(animals)} animals and {len(zoos)} Zoo covers checked")


def print_animal_image_table() -> None:
    zoos = Zoo.query.filter(Zoo.description.like(f"%{SEED_MARKER}%")).all()
    zoo_ids = [z.id for z in zoos]
    print("Animal image URLs:")
    for animal in Animal.query.filter(Animal.zoo_id.in_(zoo_ids)).order_by(Animal.id).all():
        print(f"- {animal.name} | {animal.species} | {animal.image_url}")


def upsert_visitor_demo_content(zoos: list[Zoo], now: datetime, counts: dict[str, int]) -> None:
    for zoo_index, zoo in enumerate(zoos):
        zoo.landing_map_image_url = DEMO_MAP_IMAGE
        zoo.landing_map_title = f"{zoo.name} Visitor Map"
        zoo.landing_map_description = "Use the pins to explore each zone before planning your visit."
        for zone_data in DEMO_ZONE_DEFINITIONS:
            zone = ZooZone.query.filter_by(zoo_id=zoo.id, name=zone_data["name"]).first()
            if zone is None:
                zone = ZooZone(zoo_id=zoo.id, name=zone_data["name"])
                db.session.add(zone)
                add_count(counts, ZooZone)
            zone.description = zone_data["description"]
            zone.position_x = zone_data["position_x"]
            zone.position_y = zone_data["position_y"]
            zone.map_image_url = zone_data.get("zone_image_url")
            zone.panorama_360_url = None

        promotion_definitions = (
            {
                "name": "Demo Active Wildlife Discovery Pass",
                "code": f"DEMO-{zoo_index + 1}-ACTIVE",
                "promo_type": "Seasonal",
                "discount": "20% off",
                "valid_until": (now + timedelta(days=30)).date().isoformat(),
                "image_url": DEMO_PROMOTION_BANNER,
            },
            {
                "name": "Demo Active Flexible Explorer Offer",
                "code": f"DEMO-{zoo_index + 1}-FLEX",
                "promo_type": "Family",
                "discount": "15% off",
                "valid_until": (now + timedelta(days=30)).date().isoformat(),
                "image_url": None,
            },
            {
                "name": "Demo Ending Soon Conservation Weekend Experience",
                "code": f"DEMO-{zoo_index + 1}-SOON",
                "promo_type": "Group Tour",
                "discount": "10% off",
                "valid_until": (now + timedelta(days=2)).date().isoformat(),
                "image_url": DEMO_PROMOTION_BANNER_ALT,
            },
            {
                "name": "Demo Expired Founders Day Offer",
                "code": f"DEMO-{zoo_index + 1}-EXPIRED",
                "promo_type": "Student",
                "discount": "25% off",
                "valid_until": (now - timedelta(days=1)).date().isoformat(),
                "image_url": None,
            },
        )
        for promo_data in promotion_definitions:
            promotion = Promotion.query.filter_by(code=promo_data["code"]).first()
            if promotion is None:
                promotion = Promotion(zoo_id=zoo.id, code=promo_data["code"], name=promo_data["name"])
                db.session.add(promotion)
                add_count(counts, Promotion)
            promotion.zoo_id = zoo.id
            promotion.name = promo_data["name"]
            promotion.promo_type = promo_data["promo_type"]
            promotion.country = "Philippines"
            promotion.discount = promo_data["discount"]
            promotion.valid_until = promo_data["valid_until"]
            promotion.image_url = promo_data["image_url"]


def reset_seeded_data() -> None:
    marker_zoos = Zoo.query.filter(Zoo.description.like(f"%{SEED_MARKER}%")).all()
    if not marker_zoos:
        return
    zoo_ids = [z.id for z in marker_zoos]
    seed_users = User.query.filter(
        (User.email.like("demo.visitor.%@example.com"))
        | (User.email.like("demo.staff.%@example.com"))
        | (User.email.like("demo.admin.%@example.com"))
    ).all()
    user_ids = [u.id for u in seed_users]
    booking_ids = [b.id for b in Booking.query.filter(Booking.zoo_id.in_(zoo_ids)).all()]
    if booking_ids:
        db.session.query(Notification).filter(Notification.booking_id.in_(booking_ids)).delete(synchronize_session=False)
        db.session.query(BookingPayment).filter(BookingPayment.booking_id.in_(booking_ids)).delete(synchronize_session=False)
    db.session.query(Booking).filter(Booking.zoo_id.in_(zoo_ids)).delete(synchronize_session=False)
    db.session.query(Feedback).filter(Feedback.zoo_id.in_(zoo_ids)).delete(synchronize_session=False)
    db.session.query(Event).filter(Event.zoo_id.in_(zoo_ids)).delete(synchronize_session=False)
    db.session.query(Promotion).filter(Promotion.zoo_id.in_(zoo_ids)).delete(synchronize_session=False)
    db.session.query(ZooZone).filter(ZooZone.zoo_id.in_(zoo_ids)).delete(synchronize_session=False)
    db.session.query(Service).filter(Service.zoo_id.in_(zoo_ids)).delete(synchronize_session=False)
    db.session.query(Animal).filter(Animal.zoo_id.in_(zoo_ids)).delete(synchronize_session=False)
    db.session.query(StaffTask).filter(StaffTask.zoo_id.in_(zoo_ids)).delete(synchronize_session=False)
    db.session.query(ZooAdminFeedbackReply).filter(ZooAdminFeedbackReply.feedback_id.in_(db.session.query(ZooAdminFeedback.id).filter(ZooAdminFeedback.zoo_id.in_(zoo_ids)))).delete(synchronize_session=False)
    db.session.query(ZooAdminFeedback).filter(ZooAdminFeedback.zoo_id.in_(zoo_ids)).delete(synchronize_session=False)
    db.session.query(ZooLayoutConfig).filter(ZooLayoutConfig.zoo_id.in_(zoo_ids)).delete(synchronize_session=False)
    db.session.query(ZooSubscription).filter(ZooSubscription.zoo_id.in_(zoo_ids)).delete(synchronize_session=False)
    if user_ids:
        db.session.query(Notification).filter(Notification.user_id.in_(user_ids)).delete(synchronize_session=False)
        db.session.query(User).filter(User.id.in_(user_ids)).delete(synchronize_session=False)
    db.session.query(Zoo).filter(Zoo.id.in_(zoo_ids)).delete(synchronize_session=False)


def seed(app: Flask, force: bool = False) -> dict[str, int]:
    counts: dict[str, int] = {}
    marker_exists = Zoo.query.filter(Zoo.description.like(f"%{SEED_MARKER}%")).first() is not None
    # End the marker lookup's implicit read transaction before any reset or seed work.
    db.session.rollback()
    if marker_exists and not force:
        marker_zoos = Zoo.query.filter(Zoo.description.like(f"%{SEED_MARKER}%")).order_by(Zoo.id.asc()).all()
        db.session.rollback()
        with db.session.begin():
            upsert_visitor_demo_content(marker_zoos, datetime.utcnow(), counts)
        print(f"Seed marker {SEED_VERSION} exists; visitor demo content was updated idempotently.")
        return counts
    if marker_exists and force:
        confirmation = input(f"Type RESET to remove the {SEED_VERSION} dataset and reseed it: ").strip()
        if confirmation != "RESET":
            print("Reset cancelled; nothing was changed.")
            return counts
        reset_seeded_data()
        db.session.commit()

    now = datetime.utcnow()
    image_cache: dict[str, str] = {}
    # Download all image assets before opening the database transaction so a
    # network failure leaves database rows untouched.
    cover_searches = ["clownfish", "eagle", "goat", "elephant", "giraffe"]
    cover_urls = [
        cached_direct_image(app, "zoo", query, f"cover-{index + 1}.jpg", "zoo_images", image_cache)
        for index, query in enumerate(cover_searches)
    ]
    animal_urls = {
        species: cached_direct_image(app, "animal", SPECIES_IMAGE_KEYS[species], f"animal-{index + 1}.jpg", "animal_images", image_cache)
        for index, species in enumerate({animal[1] for details in ESTABLISHMENTS for animal in details["animals"]})
    }
    profile_urls = [people_image(app, gender, number, image_cache) for _, _, gender, number in PEOPLE]

    visitors: list[User] = []
    zoos: list[Zoo] = []
    services: list[Service] = []
    with db.session.begin():
        for index, details in enumerate(ESTABLISHMENTS):
            zoo = Zoo(
                name=details["name"],
                type=details["type"],
                location=details["location"],
                description=f"{details['description']} {SEED_MARKER}",
                image_url=cover_urls[index],
                created_at=now - timedelta(days=180 + index * 17),
            )
            db.session.add(zoo)
            zoos.append(zoo)
            add_count(counts, Zoo)
        db.session.flush()

        for index, (full_name, email, gender, number) in enumerate(PEOPLE):
            visitor = User(
                email=f"demo.visitor.{email}",
                full_name=full_name,
                role="visitor",
                status="active",
                profile_image=profile_urls[index],
                created_at=now - timedelta(days=120 - (index * 3)),
            )
            visitor.set_password(VISITOR_PASSWORD)
            db.session.add(visitor)
            visitors.append(visitor)
            add_count(counts, User)
        db.session.flush()

        for zoo_index, (zoo, details) in enumerate(zip(zoos, ESTABLISHMENTS)):
            admin = User(
                email=f"demo.admin.{zoo_index + 1}@example.com",
                full_name=f"{details['name']} Administrator",
                role="zoo_admin",
                zoo_id=zoo.id,
                status="active",
                profile_image=profile_urls[(zoo_index + 5) % len(profile_urls)],
                created_at=zoo.created_at + timedelta(days=2),
            )
            admin.set_password(ADMIN_PASSWORD)
            db.session.add(admin)
            add_count(counts, User)
            for staff_index, role_name in enumerate(("Feeding Specialist", "Visitor Guide", "Admissions Coordinator")):
                staff_number = zoo_index * 3 + staff_index + 1
                staff = User(
                    email=f"demo.staff.{zoo_index + 1}.{staff_index + 1}@example.com",
                    full_name=f"{details['name']} {role_name}",
                    role="zoo_staff",
                    zoo_id=zoo.id,
                    status="active",
                    profile_image=profile_urls[(zoo_index * 3 + staff_index + 10) % len(profile_urls)],
                    created_at=zoo.created_at + timedelta(days=5 + staff_index),
                )
                staff.set_password(STAFF_PASSWORD)
                db.session.add(staff)
                add_count(counts, User)
            db.session.flush()

            for animal_index, (name, species, habitat) in enumerate(details["animals"]):
                animal_image = animal_urls[species]
                db.session.add(Animal(zoo_id=zoo.id, name=name, species=species, habitat=habitat, status="Healthy", description=f"Care team notes for {name}: monitored daily with species-appropriate enrichment.", image_url=animal_image))
                add_count(counts, Animal)

            for service_index, (name, price, description) in enumerate(details["services"]):
                service = Service(zoo_id=zoo.id, name=name, price=price, description=description, image_url=cover_urls[zoo_index])
                db.session.add(service)
                services.append(service)
                add_count(counts, Service)
            db.session.flush()

            for event_name, event_type, event_time, location in details["events"]:
                db.session.add(Event(zoo_id=zoo.id, name=event_name, type=event_type, time=event_time, location=location, image_url=cover_urls[zoo_index]))
                add_count(counts, Event)
            for promo_name, code, promo_type, valid_until, description in details["promotions"]:
                db.session.add(Promotion(zoo_id=zoo.id, name=promo_name, code=code, promo_type=promo_type, country="Philippines", discount=description, valid_until=valid_until, image_url=DEMO_PROMOTION_BANNER))
                add_count(counts, Promotion)

        db.session.flush()
        validate_subject_image_collisions(zoos)
        for booking_index, (zoo_index, visitor_index, service_index, days_offset, status, payment_status, guests) in enumerate([
            (0, 0, 0, -42, "Completed", "paid", 2), (0, 3, 1, 9, "Confirmed", "paid", 3),
            (1, 1, 4, -18, "Completed", "paid", 1), (1, 4, 5, 21, "Confirmed", "unpaid", 4),
            (2, 2, 8, -31, "Completed", "paid", 2), (2, 5, 9, 14, "Cancelled", "refunded", 5),
            (3, 6, 12, -12, "Completed", "paid", 2), (3, 7, 13, 28, "Confirmed", "unpaid", 3),
            (4, 8, 16, -7, "Completed", "paid", 4), (4, 9, 17, 35, "Cancelled", "refunded", 2),
        ]):
            service = services[service_index]
            booking_date = (now + timedelta(days=days_offset)).date().isoformat()
            booking_id = f"DEMO-BK-{booking_index + 1:02d}"
            booking = Booking(id=booking_id, zoo_id=zoos[zoo_index].id, service_id=service.id, user_id=visitors[visitor_index].id, visitor_name=visitors[visitor_index].full_name, service_name=service.name, date=booking_date, time="10:00 AM" if booking_index % 2 == 0 else "2:00 PM", guests=guests, status=status, amount=service.price * guests, payment_status=payment_status, created_at=now - timedelta(days=max(1, 50 - booking_index * 3)))
            db.session.add(booking)
            add_count(counts, Booking)
            if payment_status in {"paid", "refunded"}:
                db.session.add(BookingPayment(booking_id=booking_id, payer_user_id=visitors[visitor_index].id, amount=service.price * guests, method="card", status=payment_status, reference=f"DEMO-PAY-{booking_index + 1:02d}", provider="demo_gateway", paid_at=now - timedelta(days=max(1, 40 - booking_index))))
                add_count(counts, BookingPayment)

        for zoo_index, zoo in enumerate(zoos):
            for feedback_index, (rating, comment) in enumerate([
                (5, "The staff explained the animals thoughtfully and the habitat signage was easy to follow."),
                (4, "A memorable visit with well-kept grounds. The afternoon queue could move a little faster."),
                (3, "Good educational content, although a few viewing areas were busy during our visit."),
            ]):
                visitor = visitors[(zoo_index * 3 + feedback_index) % len(visitors)]
                db.session.add(Feedback(zoo_id=zoo.id, user_id=visitor.id, visitor_name=visitor.full_name, rating=rating, comment=comment, date=(now - timedelta(days=10 + feedback_index * 4)).date().isoformat(), created_at=now - timedelta(days=10 + feedback_index * 4)))
                add_count(counts, Feedback)

            upsert_visitor_demo_content(zoos, now, counts)

    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed a complete Zootique demo dataset once.")
    parser.add_argument("--force", action="store_true", help="Confirm and replace the tagged demo dataset.")
    args = parser.parse_args()
    app = create_app()
    with app.app_context():
        try:
            marker_exists = Zoo.query.filter(Zoo.description.like(f"%{SEED_MARKER}%")).first() is not None
            prefix = preflight_supabase() if args.force or not marker_exists else ""
            counts = seed(app, force=args.force)
            if counts and prefix:
                verify_seed_images(prefix)
                print_animal_image_table()
        except Exception as exc:
            db.session.rollback()
            print(f"Seed failed before completion; transaction rolled back: {exc}", file=sys.stderr)
            return 1
    if counts:
        print("Full demo seed completed with zero errors.")
        for table, count in sorted(counts.items()):
            print(f"{table}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
