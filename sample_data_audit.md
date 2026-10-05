# Zootique Sample-Data Audit

Audit date: 2026-09-24

## Animals

| Zoo | Name/group | Rule | Current value | Corrected value | Depicts |
|---|---|---|---|---|---|
| Manila Zoo | Leo, Mina | Habitat names must be existing zones; images are external/unverified | `Savannah Zone`, `Grassland Dome`; Unsplash URLs | Habitat normalized to real zones; image cleared when unverified | Unverified external URLs |
| Legacy farms | Bessie, Clover and other legacy animals | Habitat names did not consistently match zone records; images external/unverified | Legacy fixture habitats and external URLs | Habitat normalized to same-zoo zones; unsupported images cleared | Unverified external URLs |
| Tagged demo zoos | 30 seeded animals | OK after normalization | Species and habitats mapped cyclically to seeded zones | Same-zoo zone names | External storage images not locally verified |

## Services

| Zoo | Name/group | Rule | Current value | Corrected value | Depicts |
|---|---|---|---|---|---|
| Manila Zoo | General Admission | External image failed in browser | Unsplash URL | Empty image; placeholder fallback | Unverified/broken |
| Manila Zoo | Guided Safari Tour, Animal Feeding Experience | External URLs load in some browsers but are not verified subject assets | Unsplash URLs | Empty image when not verifiably subject-specific | Unverified external URLs |
| Legacy and tagged zoos | All services | Shared cover images or external URLs cannot prove subject accuracy | External/Supabase image URLs | Placeholder until a verified local subject photo exists | Unverified |

## Events

| Zoo | Name/group | Rule | Current value | Corrected value | Depicts |
|---|---|---|---|---|---|
| Manila, Lyger, Burol, Graco, Hiraya | Legacy events | Locations such as `Main Habitat`/`Learning Pavilion` were not consistently zone-backed; dates were not seed-relative | Legacy time/location strings | Zoo-linked events normalized to real zones and future relative date/time | Images cleared when unverified |
| Tagged demo zoos | All events | Shared zoo-cover images did not prove event subject | Supabase zoo-cover URL | Empty image placeholder | Unverified |
| Zoo-less legacy events | Five global events | No zoo relationship, so zone rule cannot be evaluated | Lion Feeding Show, Dolphin Performance, Bird of Prey Demonstration, Elephant Feeding, Night Safari Walk | Unresolved; do not assign automatically | Unverified |

## Promotions

| Zoo | Name/group | Rule | Current value | Corrected value | Depicts |
|---|---|---|---|---|---|
| Legacy zoos | Existing two promotions per zoo | Expired dates such as 2026-07-14 | Past expiry | First two promotions moved to relative future dates; expired examples retained where deliberate | No verified banner |
| Tagged demo zoos | DEMO-* promotions | Intentional active, soon, expired and no-image cases | Relative DEMO dates and local demo banners | Preserved and made idempotent | Local demo banners viewed; generic elephant/wildlife assets, not species-specific |
| All zoos | External promotion images | Subject could not be verified locally | External/Supabase URLs | Cleared unless a local verified banner exists | Unverified |

## Zones

| Zoo | Name/group | Rule | Current value | Corrected value | Depicts |
|---|---|---|---|---|---|
| Tagged demo zoos | Entrance Plaza, Discovery Trail, Learning Pavilion | Positions and same-zoo relationships | 3 zones with percentage positions | Retained; Learning Pavilion deliberately has no image | Local generic assets only for two zone photos |
| Legacy zoos | Existing zones | Most lack map images and pin coordinates | Null map image/positions | Left as placeholder; no zone-photo fallback reused as map | None |
| Live Pipeline Test Sanctuary | No zones | No sample content | Empty | Unresolved test record | None |

## Bookings

| Zoo | Name/group | Rule | Current value | Corrected value |
|---|---|---|---|---|
| Sample zoos | Confirmed/Pending bookings | Must be today/future | Some legacy dates were past | Dates normalized relative to seed time |
| Sample zoos | Completed bookings | Must be past | Existing mixed dates | Dates normalized relative to seed time |
| Zoo-less booking | `BK-1002` | No zoo relationship; cannot be scoped to a park | Pending booking with no `zoo_id` | Unresolved; do not assign automatically |

## Needs Photo

Required local files under `static/img/seed/<zoo-slug>/`:

- `manila-zoo/animal-leo-lion.jpg`
- `manila-zoo/animal-mina-giraffe.jpg`
- `manila-zoo/service-guided-safari-tour.jpg`
- `manila-zoo/service-animal-feeding-experience.jpg`
- `manila-zoo/service-general-admission.jpg`
- `lyger-zoo/animal-*.jpg`
- `graco-farms/service-farm-learning-tour.jpg`
- `hiraya-farms/service-petting-yard-pass.jpg`
- Subject-specific event photos for every zoo-linked event
- Subject-specific promotion banners for promotions that should display imagery

External URLs were not treated as verified subject images when the browser or local inspection could not establish the subject.

## Orphans Requiring User Decision

- Five zoo-less events: assign each to a specific zoo and existing zone, or delete them.
- `BK-1002`: assign it to a zoo/service/visitor context, or delete it.

No orphan records were assigned or deleted automatically.
