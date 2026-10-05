# Sample data images needed

The fixture intentionally contains no remote image URLs. Every image below currently resolves to a placeholder because the matching local file is absent. Add only verified, subject-matching files at the required path before applying the seed.

For each zoo, provide one cover, six animal images, and four service images:

- Cover: `static/img/seed/<zoo-slug>/zoo-cover.<ext>`
- Animal: `static/img/seed/<zoo-slug>/animal-<record-slug>.<ext>`
- Service: `static/img/seed/<zoo-slug>/service-<record-slug>.<ext>`

The exact subjects are the fixture records below. Until supplied, `image_url` remains `NULL`.

- `manila-zoo`: cover Manila Zoo; animals Leo (lion), Mina (giraffe), Bubbles (hippopotamus), Kiko (zebra), Amara (crocodile), Sinta (Philippine eagle); services General Admission, Guided Safari Tour, Animal Feeding Experience, Keeper Talk.
- `lyger-zoo`: cover Lyger Zoo; animals Kibo (elephant), Naya (giraffe), Rafi (zebra), Tala (lion), Mako (crocodile), Luna (owl); services General Admission, Wildlife Tram Tour, Elephant Care Talk, Family Discovery Walk.
- `burol-zoo`: cover Burol Zoo; animals Clover (goat), Datu (crocodile), Pia (capybara), Liko (macaw), Nami (otter), Berto (tortoise); services General Admission, Wetlands Walk, Junior Keeper Hour, School Nature Trail.
- `graco-farms`: cover Graco Farms; animals Bessie (cow), Tomas (carabao), Poppy (goat), Mila (sheep), Nico (chicken), Daisy (rabbit); services Farm Learning Tour, Animal Feeding Round, Garden Workshop, Harvest Picnic Pass.
- `hiraya-farms`: cover Hiraya Farms; animals Coco (goat), Lala (horse), Mango (carabao), Pip (rabbit), Sage (chicken), Momo (sheep); services Petting Yard Pass, Hillside Farm Tour, Carabao Care Session, Family Garden Class.
- `coral-triangle`: cover Coral Triangle Marine Discovery Center; animals Milo (clownfish), Luna (green sea turtle), Coral (seahorse), Azure (blue tang), Tide (stingray), Bituin (whale shark); services Reef Guided Walk, Behind the Reef Session, Sea Turtle Recovery Talk, Sunset Aquarium Visit.
- `palawan-rescue`: cover Palawan Wildlife Rescue Sanctuary; animals Amihan (Philippine eagle), Kaya (bearcat), Lakan (Philippine crocodile), Sinta (owl), Tala (hornbill), Bughaw (flying fox); services Rescue Forest Walk, Raptor Care Briefing, Wetland Conservation Tour, Keeper for a Morning.
- `taal-countryside`: cover Taal Countryside Animal Farm; animals Pipin (goat), Dahlia (horse), Mabini (carabao), Tala (rabbit), Basil (chicken), Honey (sheep); services Morning Farm Rounds, Carabao Care Experience, Garden-to-Table Workshop, Young Farmers Trail.
- `davao-highlands`: cover Davao Highlands Wildlife Park; animals Kibo (Asian elephant), Sari (Malayan tiger), Mara (giraffe), Jengo (lion), Nala (red panda), Bongo (zebra); services Highlands Wildlife Tour, Elephant Keeper Talk, Twilight Predator Walk, Wildlife Portrait Session.
- `northern-plains`: cover Northern Plains Safari Reserve; animals Zuri (giraffe), Kito (zebra), Oko (rhinoceros), Ayo (ostrich), Jabari (lion), Mosi (wildebeest); services Open Range Safari Drive, Giraffe Browse Encounter, Grassland Keeper Briefing, Sunrise Wildlife Drive.
