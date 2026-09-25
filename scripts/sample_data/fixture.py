"""Single declarative source for the resettable Zootique sample dataset."""

from __future__ import annotations

SAMPLE_MARKER = "[zootique-sample-v2]"


def _zones(habitat_name: str, habitat_description: str) -> list[dict]:
    return [
        {"name": "Entrance Plaza", "kind": "facility", "description": "Main entry, guest services, and accessible routes.", "position_x": 16.0, "position_y": 24.0},
        {"name": habitat_name, "kind": "habitat", "description": habitat_description, "position_x": 50.0, "position_y": 50.0},
        {"name": "Learning Pavilion", "kind": "facility", "description": "Keeper talks, education sessions, and visitor orientation.", "position_x": 84.0, "position_y": 76.0},
    ]


def _promotions(prefix: str) -> list[dict]:
    return [
        {"name": "Discovery Pass", "code": f"{prefix}-ACTIVE", "promo_type": "Seasonal", "discount": "15% off", "days": 30, "image": None},
        {"name": "Family Explorer Offer", "code": f"{prefix}-FAMILY", "promo_type": "Family", "discount": "10% off", "days": 14, "image": None},
        {"name": "Conservation Weekend", "code": f"{prefix}-SOON", "promo_type": "Group Tour", "discount": "10% off", "days": 2, "image": None},
        {"name": "Final-Day Offer", "code": f"{prefix}-TODAY", "promo_type": "Seasonal", "discount": "5% off", "days": 0, "image": None},
        {"name": "Founders Day Offer", "code": f"{prefix}-EXPIRED", "promo_type": "Student", "discount": "25% off", "days": -1, "image": None},
    ]


def _bookings(prefix: str) -> list[dict]:
    rows = []
    prefix = prefix[:3]
    statuses = ["Completed", "Confirmed", "Pending", "Cancelled", "Completed", "Confirmed", "Pending", "Completed", "Confirmed", "Cancelled"]
    offsets = [-12, 2, 4, -3, -8, 7, 9, -18, 12, -5]
    for index, (status, day_offset) in enumerate(zip(statuses, offsets), start=1):
        rows.append({
            "code": f"{prefix}-BK-{index:02d}",
            "service_index": (index - 1) % 4,
            "day_offset": day_offset,
            "status": status,
            "guests": 2 + (index % 3),
            "visitor_index": (index - 1) % 4,
        })
    return rows


def _zoo(slug: str, name: str, zoo_type: str, location: str, description: str, habitat: str, habitat_description: str, animals: list[tuple[str, str]], services: list[tuple[str, float, str]], events: list[tuple[str, str, str]]) -> dict:
    return {
        "slug": slug,
        "name": name,
        "type": zoo_type,
        "location": location,
        "description": f"{description} {SAMPLE_MARKER}",
        "zones": _zones(habitat, habitat_description),
        "animals": [{"name": name_, "species": species, "zone": habitat, "status": "Healthy", "image": None} for name_, species in animals],
        "services": [{"name": name_, "price": price, "description": description_, "image": None} for name_, price, description_ in services],
        "events": [{"name": name_, "type": type_, "zone": zone_, "day_offset": 14 + index * 7, "time": "10:00 AM" if index == 0 else "03:00 PM"} for index, (name_, type_, zone_) in enumerate(events)],
        "promotions": _promotions(slug.upper()),
        "bookings": _bookings(slug.upper()),
    }


SAMPLE_ZOOS = [
    _zoo("manila-zoo", "Manila Zoo", "Zoo Park", "Manila, NCR", "A family zoo focused on Philippine wildlife education and ethical care.", "Savannah Wetlands Habitat", "A managed grassland and wetland habitat for hoofstock, big cats, and aquatic wildlife.", [("Leo", "Lion"), ("Mina", "Giraffe"), ("Bubbles", "Hippopotamus"), ("Kiko", "Zebra"), ("Amara", "Crocodile"), ("Sinta", "Philippine eagle")], [("General Admission", 500, "Standard entry to all public habitats."), ("Guided Safari Tour", 1200, "A two-hour guided route through the savannah habitat."), ("Animal Feeding Experience", 800, "A supervised feeding session with resident animals."), ("Keeper Talk", 350, "A keeper-led animal welfare and conservation talk.")], [("Savannah Feeding Show", "Feeding", "Savannah Wetlands Habitat"), ("Keeper Conservation Talk", "Talk", "Learning Pavilion")]),
    _zoo("lyger-zoo", "Lyger Zoo", "Zoo Park", "Laguna, PH", "A curated wildlife park with family trails and conservation learning.", "Grassland Habitat", "Mixed grassland for giraffes, zebras, and managed grazing.", [("Kibo", "Elephant"), ("Naya", "Giraffe"), ("Rafi", "Zebra"), ("Tala", "Lion"), ("Mako", "Crocodile"), ("Luna", "Owl")], [("General Admission", 500, "Entry to the park and public exhibits."), ("Wildlife Tram Tour", 900, "A guided tram ride through grassland exhibits."), ("Elephant Care Talk", 700, "Learn about elephant welfare from the care team."), ("Family Discovery Walk", 400, "A guided family route with habitat interpretation.")], [("Grassland Feeding Hour", "Feeding", "Grassland Habitat"), ("Wildlife Keeper Talk", "Talk", "Learning Pavilion")]),
    _zoo("burol-zoo", "Burol Zoo", "Zoo Park", "Cavite, PH", "A compact community zoo pairing animal care with school programs.", "River Wetlands", "Freshwater habitat with pools, banks, and shaded refuge areas.", [("Clover", "Goat"), ("Datu", "Crocodile"), ("Pia", "Capybara"), ("Liko", "Macaw"), ("Nami", "Otter"), ("Berto", "Tortoise")], [("General Admission", 400, "Entry to the community zoo."), ("Wetlands Walk", 650, "A guided look at freshwater habitats and wildlife."), ("Junior Keeper Hour", 500, "A supervised animal-care learning activity."), ("School Nature Trail", 300, "A teacher-friendly guided education route.")], [("Wetlands Feeding", "Feeding", "River Wetlands"), ("Junior Keeper Talk", "Talk", "Learning Pavilion")]),
    _zoo("graco-farms", "Graco Farms", "Farm Attraction", "Tagaytay, PH", "A working family farm teaching animal welfare and sustainable food production.", "Farm Pasture", "Rotational pasture for gentle livestock and supervised farm encounters.", [("Bessie", "Cow"), ("Tomas", "Carabao"), ("Poppy", "Goat"), ("Mila", "Sheep"), ("Nico", "Chicken"), ("Daisy", "Rabbit")], [("Farm Learning Tour", 350, "A guided walk through livestock and garden areas."), ("Animal Feeding Round", 300, "Supervised feeding for family groups."), ("Garden Workshop", 450, "A practical lesson in seasonal planting and composting."), ("Harvest Picnic Pass", 550, "Farm access with a seasonal tasting plate.")], [("Pasture Feeding Round", "Feeding", "Farm Pasture"), ("Farmer Skills Talk", "Talk", "Learning Pavilion")]),
    _zoo("hiraya-farms", "Hiraya Farms", "Farm Attraction", "Batangas, PH", "A hillside farm retreat with a petting yard and weekend learning stations.", "Petting Pasture", "Low-stress pasture for small livestock and supervised interactions.", [("Coco", "Goat"), ("Lala", "Horse"), ("Mango", "Carabao"), ("Pip", "Rabbit"), ("Sage", "Chicken"), ("Momo", "Sheep")], [("Petting Yard Pass", 250, "Supervised access to the small-animal pasture."), ("Hillside Farm Tour", 400, "A guided tour of crops, livestock, and water care."), ("Carabao Care Session", 500, "Learn traditional and modern carabao care."), ("Family Garden Class", 350, "A hands-on planting activity for families.")], [("Petting Pasture Feeding", "Feeding", "Petting Pasture"), ("Farm Stewardship Talk", "Talk", "Learning Pavilion")]),
    _zoo("coral-triangle", "Coral Triangle Marine Discovery Center", "Aquarium", "Mactan Island, Cebu", "A marine education center focused on reefs, mangroves, and responsible coastal tourism.", "Coral Reef Habitat", "Aquatic reef habitat with coral structures and species-appropriate water flow.", [("Milo", "Clownfish"), ("Luna", "Green sea turtle"), ("Coral", "Seahorse"), ("Azure", "Blue tang"), ("Tide", "Stingray"), ("Bituin", "Whale shark")], [("Reef Guided Walk", 650, "A naturalist-led tour through reef and seagrass galleries."), ("Behind the Reef Session", 900, "See aquarists prepare diets and monitor water quality."), ("Sea Turtle Recovery Talk", 350, "A conservation briefing beside the recovery lagoon."), ("Sunset Aquarium Visit", 500, "A quiet guided visit to the evening reef galleries.")], [("Reef Feeding Demonstration", "Feeding", "Coral Reef Habitat"), ("Blue Planet Talk", "Talk", "Learning Pavilion")]),
    _zoo("palawan-rescue", "Palawan Wildlife Rescue Sanctuary", "Wildlife Rescue Center", "Puerto Princesa, Palawan", "A quiet sanctuary rehabilitating native wildlife and teaching forest stewardship.", "Rainforest Canopy", "Layered forest habitat for climbing, flying, and canopy species.", [("Amihan", "Philippine eagle"), ("Kaya", "Bearcat"), ("Lakan", "Philippine crocodile"), ("Sinta", "Owl"), ("Tala", "Hornbill"), ("Bughaw", "Flying fox")], [("Rescue Forest Walk", 550, "A ranger-led trail about rehabilitation and release."), ("Raptor Care Briefing", 750, "Learn how rescued raptors are conditioned for care."), ("Wetland Conservation Tour", 450, "A guided look at native freshwater habitats."), ("Keeper for a Morning", 1200, "A supervised enrichment session for adult guests.")], [("Wetland Feeding Session", "Feeding", "Rainforest Canopy"), ("Rescue Keeper Talk", "Talk", "Learning Pavilion")]),
    _zoo("taal-countryside", "Taal Countryside Animal Farm", "Farm Attraction", "Laurel, Batangas", "A countryside farm connecting livestock care, composting, and food education.", "Countryside Pasture", "A mixed pasture for heritage livestock and low-impact visitor activities.", [("Pipin", "Goat"), ("Dahlia", "Horse"), ("Mabini", "Carabao"), ("Tala", "Rabbit"), ("Basil", "Chicken"), ("Honey", "Sheep")], [("Morning Farm Rounds", 300, "A supervised feeding and welfare check."), ("Carabao Care Experience", 450, "A lesson in water buffalo care and heritage farming."), ("Garden-to-Table Workshop", 500, "Harvest produce and prepare a simple farm snack."), ("Young Farmers Trail", 250, "A self-guided route with animal-care stations.")], [("Pasture Feeding Show", "Feeding", "Countryside Pasture"), ("Heritage Farm Talk", "Talk", "Learning Pavilion")]),
    _zoo("davao-highlands", "Davao Highlands Wildlife Park", "Zoo Park", "Toril District, Davao City", "An upland wildlife park pairing spacious habitats with Mindanao conservation education.", "Highland Grassland", "Open highland habitat for grazing species and predator enrichment.", [("Kibo", "Asian elephant"), ("Sari", "Malayan tiger"), ("Mara", "Giraffe"), ("Jengo", "Lion"), ("Nala", "Red panda"), ("Bongo", "Zebra")], [("Highlands Wildlife Tour", 700, "A guided circuit through flagship habitats."), ("Elephant Keeper Talk", 850, "Observe protected elephant care routines."), ("Twilight Predator Walk", 600, "A ranger walk focused on predator behavior."), ("Wildlife Portrait Session", 950, "A safe-distance wildlife photography lesson.")], [("Highland Feeding Hour", "Feeding", "Highland Grassland"), ("Mindanao Conservation Talk", "Talk", "Learning Pavilion")]),
    _zoo("northern-plains", "Northern Plains Safari Reserve", "Safari Park", "Clark Freeport Zone, Pampanga", "An open-range reserve focused on grassland restoration and responsible wildlife viewing.", "Open Savanna", "Open-range grassland for herd species and carefully managed predator habitats.", [("Zuri", "Giraffe"), ("Kito", "Zebra"), ("Oko", "Rhinoceros"), ("Ayo", "Ostrich"), ("Jabari", "Lion"), ("Mosi", "Wildebeest")], [("Open Range Safari Drive", 1100, "A guided vehicle route through grazing habitats."), ("Giraffe Browse Encounter", 850, "A keeper-led feeding talk from a protected platform."), ("Grassland Keeper Briefing", 600, "Learn how pasture, water, and herd welfare are managed."), ("Sunrise Wildlife Drive", 1300, "An early drive for cooler conditions and active animals.")], [("Savanna Feeding Demonstration", "Feeding", "Open Savanna"), ("Reserve Stewardship Talk", "Talk", "Learning Pavilion")]),
]

SPECIES_HABITAT_TYPES = {
    "Hippopotamus": {"savanna", "wetland", "river"},
    "Lion": {"savanna", "grassland"}, "Giraffe": {"savanna", "grassland"}, "Zebra": {"savanna", "grassland"}, "Wildebeest": {"savanna", "grassland"}, "Ostrich": {"savanna", "grassland"}, "Rhinoceros": {"savanna", "grassland"},
    "Elephant": {"grassland", "forest"}, "Malayan tiger": {"forest", "grassland"}, "Red panda": {"forest"}, "Philippine eagle": {"forest"}, "Bearcat": {"forest"}, "Owl": {"forest"}, "Hornbill": {"forest"}, "Flying fox": {"forest"},
    "Crocodile": {"wetland", "river", "aquatic"}, "Capybara": {"wetland", "river"}, "Otter": {"wetland", "river"}, "Tortoise": {"wetland", "farm"},
    "Clownfish": {"aquatic", "reef"}, "Green sea turtle": {"aquatic", "reef"}, "Seahorse": {"aquatic", "reef"}, "Blue tang": {"aquatic", "reef"}, "Stingray": {"aquatic", "reef"}, "Whale shark": {"aquatic", "reef"},
    "Goat": {"farm", "pasture"}, "Cow": {"farm", "pasture"}, "Carabao": {"farm", "pasture", "wetland"}, "Sheep": {"farm", "pasture"}, "Chicken": {"farm", "pasture"}, "Rabbit": {"farm", "pasture"}, "Horse": {"farm", "pasture"}, "Macaw": {"forest"},
}
