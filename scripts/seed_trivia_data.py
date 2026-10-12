"""Seed wildlife trivia questions and create gamification tables if needed."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from models import TriviaQuestion, VisitorBadge, db
from app import create_app

CURATED_QUESTIONS = [
    # ── Philippine Wildlife ──
    {
        "category": "Philippine Wildlife",
        "difficulty": "medium",
        "question": "What is the national bird of the Philippines, known for its massive wingspan and brown crested crown?",
        "options": ["Philippine Cockatoo", "Philippine Eagle", "Brahminy Kite", "Rufous Hornbill"],
        "correct_option_index": 1,
        "explanation": "The Philippine Eagle (Pithecophaga jefferyi), also called the Monkey-eating Eagle, is one of the world's rarest and most powerful birds of prey, with a wingspan reaching over 2 meters (7 feet)!",
        "points_reward": 20,
    },
    {
        "category": "Philippine Wildlife",
        "difficulty": "easy",
        "question": "Which tiny Philippine primate found in Bohol has eyes that are each larger than its entire brain?",
        "options": ["Philippine Tarsier", "Slow Loris", "Pygmy Marmoset", "Bushbaby"],
        "correct_option_index": 0,
        "explanation": "The Philippine Tarsier (Carlito syrichta) is one of the smallest primates on Earth. Its enormous eyes are fixed in its skull, but it can rotate its head a full 180 degrees in either direction!",
        "points_reward": 15,
    },
    {
        "category": "Philippine Wildlife",
        "difficulty": "medium",
        "question": "The Tamaraw, a critically endangered dwarf wild water buffalo, is found exclusively on which Philippine island?",
        "options": ["Palawan", "Mindanao", "Mindoro", "Cebu"],
        "correct_option_index": 2,
        "explanation": "The Tamaraw (Bubalus mindorensis) is endemic strictly to the island of Mindoro in the Philippines. It is easily distinguished from the carabao by its V-shaped horns.",
        "points_reward": 20,
    },
    {
        "category": "Philippine Wildlife",
        "difficulty": "hard",
        "question": "Which Philippine reptile is known for its remarkable ability to run across water using specialized toe fringes?",
        "options": ["Sailfin Lizard", "Monitor Lizard", "Flying Gecko", "Flying Dragon"],
        "correct_option_index": 0,
        "explanation": "The Philippine Sailfin Lizard (Hydrosaurus pustulatus) possesses flattened, fringed toes that allow young lizards to sprint across water surfaces to evade predators!",
        "points_reward": 25,
    },

    # ── Big Cats & Predators ──
    {
        "category": "Big Cats & Predators",
        "difficulty": "easy",
        "question": "What is the fastest land animal on Earth, capable of accelerating from 0 to 60 mph in just 3 seconds?",
        "options": ["Lion", "Cheetah", "Pronghorn Antelope", "Greyhound"],
        "correct_option_index": 1,
        "explanation": "Cheetahs can reach top speeds of 110-120 km/h (70-75 mph) in short bursts thanks to their flexible spine, large nasal cavities, and semi-retractable claws that act like athletic cleats.",
        "points_reward": 15,
    },
    {
        "category": "Big Cats & Predators",
        "difficulty": "medium",
        "question": "Unlike most other big cats, which of these species is a passionate swimmer and loves soaking in river water?",
        "options": ["Leopard", "Cheetah", "Tiger", "Snow Leopard"],
        "correct_option_index": 2,
        "explanation": "Tigers love water! In hot climates, they spend hours submerged in streams, pools, and lakes to stay cool, and they are capable of swimming several miles across wide rivers.",
        "points_reward": 15,
    },
    {
        "category": "Big Cats & Predators",
        "difficulty": "medium",
        "question": "A tiger's distinctive striped pattern is not only on its fur. Where else are the stripes found?",
        "options": ["On its claws", "On its skin", "On its tongue", "On the soles of its paws"],
        "correct_option_index": 1,
        "explanation": "Tiger stripes are like human fingerprints — completely unique to each individual — and the pattern is pigmented directly onto their skin!",
        "points_reward": 20,
    },
    {
        "category": "Big Cats & Predators",
        "difficulty": "hard",
        "question": "Which big cat has the strongest bite force relative to its body size, capable of piercing turtle shells and caiman skulls?",
        "options": ["Jaguar", "Lion", "Cougar", "Leopard"],
        "correct_option_index": 0,
        "explanation": "The Jaguar has an extraordinarily compact, muscular jaw that delivers the strongest bite relative to body size among big cats, allowing it to pierce armored reptilian prey.",
        "points_reward": 25,
    },

    # ── Habitats & Gentle Giants ──
    {
        "category": "Gentle Giants",
        "difficulty": "easy",
        "question": "How many neck vertebrae does a tall giraffe have?",
        "options": ["7 vertebrae", "14 vertebrae", "21 vertebrae", "28 vertebrae"],
        "correct_option_index": 0,
        "explanation": "Despite necks that can measure up to 6 feet long, giraffes have exactly 7 neck vertebrae — the same number as humans and nearly all other mammals!",
        "points_reward": 15,
    },
    {
        "category": "Gentle Giants",
        "difficulty": "medium",
        "question": "How do African and Asian elephants primarily communicate over long distances of up to 10 kilometers?",
        "options": ["High-pitched trumpeting", "Low-frequency infrasound", "Scent trails", "Ear flapping signals"],
        "correct_option_index": 1,
        "explanation": "Elephants produce deep infrasound rumbles below 20 Hz (often inaudible to human ears) that travel through the ground and are detected through receptors in other elephants' feet!",
        "points_reward": 20,
    },
    {
        "category": "Gentle Giants",
        "difficulty": "easy",
        "question": "A giant panda's diet in the wild consists of nearly 99% of which plant?",
        "options": ["Eucalyptus leaves", "Bamboo", "Water lilies", "Acorn nuts"],
        "correct_option_index": 1,
        "explanation": "An adult giant panda spends up to 12-16 hours a day eating between 26 to 84 pounds of bamboo to meet its nutritional requirements.",
        "points_reward": 15,
    },
    {
        "category": "Gentle Giants",
        "difficulty": "hard",
        "question": "What is the gestation period of an African elephant, making it the longest pregnancy of any land mammal?",
        "options": ["12 months", "16 months", "22 months", "28 months"],
        "correct_option_index": 2,
        "explanation": "An African elephant calf develops inside its mother for nearly 22 months (almost two full years) before being born!",
        "points_reward": 25,
    },

    # ── Superpowers & Adaptations ──
    {
        "category": "Animal Superpowers",
        "difficulty": "easy",
        "question": "Which nocturnal bird can rotate its head up to 270 degrees without cutting off blood flow to its brain?",
        "options": ["Barn Owl", "Eagle", "Falcon", "Pelican"],
        "correct_option_index": 0,
        "explanation": "Owls have 14 neck vertebrae (twice as many as humans) and a specialized vascular pooling system that prevents blood restriction during extreme head turns.",
        "points_reward": 15,
    },
    {
        "category": "Animal Superpowers",
        "difficulty": "medium",
        "question": "Chameleons change color primarily for which of the following reasons?",
        "options": ["Camouflage matching only", "Temperature regulation and mood communication", "Vision enhancement", "Attracting prey"],
        "correct_option_index": 1,
        "explanation": "While color helps with camouflage, chameleons primarily change coloration through nanocrystal movement to regulate body temperature and signal emotions (like dominance or stress) to other chameleons!",
        "points_reward": 20,
    },
    {
        "category": "Animal Superpowers",
        "difficulty": "hard",
        "question": "Which fascinating amphibian can regenerate lost limbs, heart tissue, spinal cord, and even parts of its brain throughout its entire life?",
        "options": ["Axolotl", "Poison Dart Frog", "Fire Salamander", "Bullfrog"],
        "correct_option_index": 0,
        "explanation": "The Axolotl (Mexican walking fish) possesses extraordinary regenerative abilities, reconstructing perfectly functioning limbs and vital organs without forming scar tissue.",
        "points_reward": 25,
    },
    {
        "category": "Animal Superpowers",
        "difficulty": "medium",
        "question": "How do honeybees communicate the precise direction and distance of nectar flowers to their hive mates?",
        "options": ["By buzzing at different pitches", "Through the 'Waggle Dance'", "By leaving pheromone footprints", "By tapping their antennae"],
        "correct_option_index": 1,
        "explanation": "The famous Waggle Dance uses the angle of the dance relative to the sun to indicate compass direction, while the duration of the waggle conveys distance!",
        "points_reward": 20,
    },

    # ── Conservation & Ecosystems ──
    {
        "category": "Conservation & Ecology",
        "difficulty": "easy",
        "question": "What is the primary role of a 'Keystone Species' within a wildlife ecosystem?",
        "options": ["It is the largest animal in the habitat", "It has a disproportionately large impact on its natural environment", "It is the top carnivore only", "It has the longest lifespan"],
        "correct_option_index": 1,
        "explanation": "A keystone species holds an ecosystem together; if removed, the entire habitat changes dramatically or ceases to exist, much like the keystone of an architectural arch.",
        "points_reward": 15,
    },
    {
        "category": "Conservation & Ecology",
        "difficulty": "medium",
        "question": "Why are sea otters considered a crucial keystone species for underwater ocean forests?",
        "options": ["They plant underwater seagrass", "They eat sea urchins that would otherwise destroy kelp forests", "They filter ocean water", "They frighten away predatory sharks"],
        "correct_option_index": 1,
        "explanation": "Sea otters feast on sea urchins. Without otters, urchin populations explode and clear-cut kelp forests, turning vibrant marine habitats into barren urchin deserts.",
        "points_reward": 20,
    },
    {
        "category": "Conservation & Ecology",
        "difficulty": "easy",
        "question": "Animals that are active primarily during twilight hours (dawn and dusk) are described by which scientific term?",
        "options": ["Diurnal", "Nocturnal", "Crepuscular", "Hibernating"],
        "correct_option_index": 2,
        "explanation": "While diurnal animals are active by day and nocturnal by night, crepuscular animals (such as rabbits, deer, and many wild cats) peak in activity during the cooler dawn and dusk twilights.",
        "points_reward": 15,
    },
    {
        "category": "Conservation & Ecology",
        "difficulty": "medium",
        "question": "What is the primary purpose of 'Environmental Enrichment' for animals living in modern zoos and wildlife sanctuaries?",
        "options": ["To make enclosures look pretty for photos", "To stimulate natural foraging, cognitive thinking, and physical behaviors", "To train animals for human performances", "To keep animals asleep during visiting hours"],
        "correct_option_index": 1,
        "explanation": "Enrichment includes puzzle feeders, novel scents, climbing platforms, and sensory items designed to challenge animals mentally and encourage natural wild behaviors.",
        "points_reward": 20,
    },
]

STARTER_BADGES = [
    {
        "badge_key": "junior_explorer",
        "badge_name": "Junior Explorer",
        "badge_description": "Answered your first wildlife trivia question correctly.",
        "badge_icon": "fa-solid fa-compass",
    },
    {
        "badge_key": "habitat_scholar",
        "badge_name": "Habitat Scholar",
        "badge_description": "Answered 5 trivia questions correctly.",
        "badge_icon": "fa-solid fa-graduation-cap",
    },
    {
        "badge_key": "safari_master",
        "badge_name": "Safari Master",
        "badge_description": "Answered 15 trivia questions correctly.",
        "badge_icon": "fa-solid fa-award",
    },
    {
        "badge_key": "philippine_expert",
        "badge_name": "Archipelago Ranger",
        "badge_description": "Mastered Philippine native wildlife trivia.",
        "badge_icon": "fa-solid fa-mountain-sun",
    },
    {
        "badge_key": "predator_specialist",
        "badge_name": "Apex Predator Specialist",
        "badge_description": "Aced the Big Cats & Predators challenge.",
        "badge_icon": "fa-solid fa-shield-cat",
    },
]


def seed_trivia():
    app = create_app()
    with app.app_context():
        # Ensure tables exist
        db.create_all()

        added_count = 0
        for item in CURATED_QUESTIONS:
            existing = TriviaQuestion.query.filter_by(question=item["question"]).first()
            if not existing:
                q = TriviaQuestion(
                    category=item["category"],
                    difficulty=item["difficulty"],
                    question=item["question"],
                    options=item["options"],
                    correct_option_index=item["correct_option_index"],
                    explanation=item["explanation"],
                    points_reward=item["points_reward"],
                    is_active=True,
                )
                db.session.add(q)
                added_count += 1

        db.session.commit()
        print(f"Successfully seeded {added_count} new trivia questions (Total: {TriviaQuestion.query.count()}).")


if __name__ == "__main__":
    seed_trivia()
