# rx: Prescribed Fire Planning

A web app for writing NWCG-style prescribed fire plans (PMS 484 / 484-1, Dec 2021 template) on top of a
versioned PostGIS database of the landscape: fuels, fireguards, roads, water, restricted areas,
infrastructure, critical habitat, sensitive features and smoke receptors. Companion to
[fwx](https://github.com/parklander/fwx) (fire weather); meant for `rx.rtams.ca`.

- **Burn program** (`/`): every burn block on one map, coloured by plan status, with area, window,
  last fire on record, site visits and plan progress. **Add burn block** draws a new block and opens
  its fire plan.
- **Fire plan view** (`/#plan/<id>`): the elements listed down the left with their status, the selected
  element on the right as a structured form (tables, checklists, pick lists; fields filled from the
  map and database are shown read-only), with the plan map above spatial elements. Also: plan map, the 21 elements plus appendices A–F, map features,
  values and fuels, prescription, ignition variants, burn days, versions and signatures, Word export.
- **Mobile** (`/m`): the burn program map (tap a block to open it), then the plan for the field. GPS position, layers, ignition steps,
  values, every element. The last plan opened is kept on the device and works offline; map tiles you
  have viewed are cached.

## Site visits (mobile)

The **Site visit** tab on `/m` records what is found on the ground: pre-burn recce, burn day, post-burn,
monitoring or fuel surveys.

- **Recce checklist**: holding and contingency lines, anchor point, access, water, safety zones,
  escape routes, hazards, values, fuels, smoke, radio coverage. OK in one tap; *Issue* asks for a note
  and photos.
- **Photo points, notes, hazards** (UXO, snags, structures, power lines…).
- **Fuel plots**: clip-and-weigh (frame area, wet weight, moisture or oven-dry weight) or a visual
  estimate; curing, height, cover, juniper %, litter depth, continuity. The load is worked out on the
  phone and again on the server, and each plot with a position is added to `fuels.plot`.
- Every record carries the GPS position and accuracy. Photos are shrunk on the phone (2560 px).
- **Photo direction**: the compass heading of the back camera is recorded with each photo (from the
  phone's orientation sensors; set by hand with a slider when there is no reading). Maps show a
  field-of-view wedge per photo (about 66° landscape, 50° portrait); clicking it opens the photo.
- **Works offline**: visits, records and photos are kept on the phone (IndexedDB) with ids made on the
  phone, and are sent when there is a signal (also every 30 s). Resending is harmless.
- On the desktop, **Site visits** lists each visit with its issues, fuel plot table, photos and map
  markers, and can copy the issues into Element 9.

Photos are stored under `RX_MEDIA_DIR` (default `media/` in the app folder) and copied nightly to
`/var/backups/rx/media`.

## Pre-burn work

Jobs that lower a burn's complexity (mulch or mow along control lines, disc, grade, wet line, black
line, brush/juniper removal, snag felling, protect an asset, water supply, signage) are drawn where
they go: a line with its width (shown as a band), an area or a point. Each carries the standard to
meet, depth, whether DAC clearance is needed, which PMS 424 complexity elements it lowers, when it is
needed (before approval or ignition), a due date and who does it.

- Status: planned → assigned → done → verified (or not needed), with every change kept (who, when,
  note, measured width).
- **Verified on site** from the mobile view: Prep work tab → *Check on site* during a site visit; the
  check carries GPS, photos with direction, measured width and notes.
- **GO is blocked** on a burn day while work needed before ignition is unverified, unless the burn
  boss records a reason (kept with the burn day).
- Element 9 lists the work; Element 3 shows what the post-plan risk ratings depend on; the Word
  export includes both. A work order (.csv) and GeoJSON (for GPS units) can be downloaded.
- The specification is locked with the plan at approval; status updates continue.

## Burn program: operation order, meetings, people

The program view has four tabs: **Map**, **Op order**, **Meetings** and **People**.

- **Op order.** Each season (year) has an operation order in the CFB Shilo OPORD layout: heading
  (title, file number, references, distribution), situation, mission, execution (intent, phases with
  dates, main effort, end state, groupings and tasks, coordinating instructions), service support,
  command and signals, authorization and annexes. Three parts fill themselves in: the season's burn
  blocks (Annex B), the resources the burn plans need (largest need of any one burn, from Element 11)
  and the points of contact (from People). *New season* copies last year's order with dates cleared.
  Export to Word, route it for signature, then **record the signature**: that locks the order, and
  changes after that start a new revision. Every save is kept.
- **People.** Name, rank, appointment, organization, phone, email and qualifications (RXB2, FIRB,
  ICT4, FFT1, EMR, EOD, ...), reused on every burn; names are offered in Element 11, 12, 2A and the
  signatures. Paste the points of contact from an existing order to add them in one go.
- **Usual roles.** Who normally fills each role (burn boss, firing boss, holding boss, lookout, medic,
  UXO advisor, Range Control liaison, agency administrator...). New burn plans start with these names
  in Element 11. Element 11 checks each name against the qualification the position needs
  (a higher burn boss qualification covers a lower one).
- **Meetings.** Planning, coordination, briefings and after action reviews, for the program or one
  burn block: attendees from People, agenda, notes, decisions and actions (owner, due, done). Open
  actions across meetings are listed on the Meetings tab.
- **Program file.** Names and phone numbers are not kept in this repository. A season's order, people
  and usual roles can be loaded from a JSON file (Op order → *Load a program file*, burn boss or admin):

  ```json
  {"season": {"year": 2025, "op_name": "Op ...", "opord": {"situation": "...", "...": "..."},
              "signed_name": "LCol ..., BComd", "signed_at": "2025-03-26"},
   "people": [{"name": "...", "rank": "Maj", "appointment": "G3", "phone": "CSN ...", "poc": true}],
   "role_defaults": {"burn_boss": "..."}}
  ```

## Element forms

Each element's fields are defined in `schema.py` (field types: text, textarea, number, date, time,
select, multi, bool, table, checklist, auto, component; text fields and table columns can offer
the People list). Element 3 follows the 14 PMS 424 complexity
elements; 7 holds the prescription parameters; 15 the ignition variants; 1 the signatures. Content
is stored as JSON per element; text saved under the old free-text layout is kept and shown under
the form. The Word export follows the same schema.

## Data model

One PostGIS database, one schema per domain:

| Schema | Holds |
|---|---|
| `plans` | plans, the 21+6 elements, plan geometry (burn unit, ignition units, contingency area, holding and contingency lines, trigger points, safety zones, escape routes…), prescription, ignition variants, signatures, burn days |
| `fuels` | `fuel_class` (versioned); `treatment`, `plot`, `test_fire` (records) |
| `ops` | `fireguard`, `road`, `water_source`, `restricted_area`, `bivouac` (versioned) |
| `infra` | `asset` with material and vulnerability class (versioned) |
| `habitat` | `critical_habitat`, `sensitive_feature` (versioned); `observation` (records) |
| `smoke` | `receptor` (versioned) |
| `weather` | `forecast_snapshot`: forecasts frozen at decision points |
| `field` | site visits, their records (checks, notes, hazards, fuel plots) and photos |
| `meta` | users, sessions, layer catalogue, releases, the versioning functions |

### Versioning

**State layers** (what the landscape is like) are never overwritten. Every row carries:

- `feature_id`: the feature's identity across versions;
- `valid`: when the row is true on the ground;
- `recorded`: when the database held it as current knowledge;
- `release_id`, `change_note`, `changed_by`, `source_event`.

`meta.vwrite(table, feature_id, data, valid_from, note, who, release)` writes a new version (or a new
feature when `feature_id` is null); `meta.vretire(...)` ends one. A trigger blocks plain UPDATE and
DELETE. Any past state can be rebuilt: *what was true on date G, as we knew it on date K*:

```sql
select * from ops.fireguard where recorded @> K and valid @> G;
```

**Event layers** (burns, mowing, plots, test fires, observations) are append-only records.

**Releases** (`meta.release`) name reviewed versions of a layer, e.g. "Fuels 2026.2".

### Plans

- Elements are saved as structured sections; every save is kept (`plans.element_rev`), as is every
  change to plan geometry (`plans.feature_rev`).
- Status: draft → review → approved → implemented → closed (or cancelled). Approval needs the
  `burn_boss` role, **locks the plan** and records `as_of` (the knowledge time) and the published
  releases in force. The overlay, maps and export of an approved plan always show the data as it was
  at approval.
- **Amend** copies an approved plan into a new draft version (`parent_plan_id`, `version_no + 1`).
- **Ignition variants** are pre-approved firing plans by wind direction.
- **Burn days** freeze the burn-morning forecast (Open-Meteo `gem_seamless`, as in fwx) at the unit,
  check every hour 06–21 against the prescription and the variants, require one variant to hold for
  the whole ignition period, and record the 2B checklist and the burn boss's GO / NO-GO.

### Roles

`viewer` (read; no sensitive layers) · `planner` (edit drafts and layers) · `burn_boss` (approve,
publish releases, go / no-go) · `admin`.

## Run locally

```bash
sudo apt install postgresql postgis
sudo -u postgres psql -c "create role rx login password 'rx' superuser" -c "create database rx owner rx"
pip install -r requirements.txt
python migrate.py
python seed_demo.py                                   # optional: DEMO plan + notional layers + RHWO grid
python manage.py create-user admin admin "Your Name"  # prompts for a password
RX_INSECURE_COOKIE=1 uvicorn app:app --port 8100      # cookie without HTTPS, local only
```

`RX_DATABASE_URL` (default `postgresql://rx:rx@localhost/rx`), `RX_TZ` (default `America/Winnipeg`).

## Deploy (alongside fwx)

1. DNS: an `A` record for `rx.rtams.ca` pointing at the droplet.
2. On the droplet, as root: `bash deploy/setup.sh <repo-url> rx.rtams.ca`
   It installs PostgreSQL/PostGIS, creates the database with a random password in `/etc/rx.env`,
   runs the migrations, adds an `rx` systemd service on port 8100, **appends** a Caddy site block
   (fwx's stays), and installs a nightly `pg_dump` (14 days in `/var/backups/rx`).
3. Create a user (the command is printed at the end).
4. Updates: `bash /opt/rx/deploy/update.sh`.

**Before loading real CFB Shilo data:** the droplet is outside DND networks. Species locations,
cultural sites, UXO areas and infrastructure need sign-off for that hosting. Sensitive layers are
already restricted to planner and above, but that is not a substitute for the approval.

## Demo data

`seed_demo.py` loads a **notional** 161 ha burn unit and notional layers (marked DEMO) so the app can
be tried, plus the real Red-headed Woodpecker critical habitat grid (176 × 10 km squares, Manitoba).

## Next

- Map products: the six PMS 484-1 map templates generated from a plan (vicinity, project, fuels,
  values, smoke, fire behaviour), one project and smoke map per ignition variant.
- Fireline runs attached to Element 7 / Appendix E; hourly FFMC/ISI on burn days (from fwx's `wxpoint`).
- Layer editing in the UI (today: API) and import tools (shapefile / GeoPackage → a release).
- Post-burn: write the burn perimeter to `fuels.treatment` and a new fuels version.
