"""Seed a DEMO plan and DEMO landscape layers (notional geometry, not real Shilo data),
plus the Red-headed Woodpecker critical habitat grid (from the ECCC list).

    python seed_demo.py
"""
import json
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import LineString, Point, Polygon, mapping

import db

ROOT = Path(__file__).resolve().parent
# Notional placement: map pixels at 2 m each, top-left corner at this UTM 14N point.
E0, N0 = 458000, 5509000
to_ll = Transformer.from_crs(32614, 4326, always_xy=True).transform


def ll(x, y):
    return to_ll(E0 + 2 * x, N0 - 2 * y)


def poly(pts):
    return mapping(Polygon([ll(*p) for p in pts]))


def line(pts):
    return mapping(LineString([ll(*p) for p in pts]))


def pt(x, y):
    return mapping(Point(ll(x, y)))


def ellipse(cx, cy, rx, ry, n=32):
    import math
    return poly([(cx + rx * math.cos(2 * math.pi * i / n), cy + ry * math.sin(2 * math.pi * i / n)) for i in range(n)])


UNIT = [(220, 170), (860, 140), (930, 560), (820, 760), (260, 740), (180, 420)]
NOTE = "DEMO data: notional geometry"


def vwrite(c, table, data, release=None, valid_from="2025-01-01"):
    c.execute("select meta.vwrite(%s::regclass, null, %s, %s::timestamptz, %s, 'seed', %s)",
              (table, db.jsonb(data), valid_from, NOTE, release))


def release(c, layer, name, notes):
    return c.execute("insert into meta.release (layer, name, notes, created_by, published_at) values (%s,%s,%s,'seed',now()) returning id",
                     (layer, name, notes)).fetchone()["id"]


def seed():
    db.open_pool()
    with db.tx() as c:
        if c.execute("select 1 from plans.plan where demo").fetchone():
            print("demo already seeded")
            return

        # --- landscape layers -------------------------------------------------
        r = release(c, "fuels.fuel_class", "DEMO fuels 2026.1", "Notional fuel classes for the demo unit")
        vwrite(c, "fuels.fuel_class", {"fuel_class": "mixed_grass", "load_kg_m2": 0.3, "fbp_equiv": "O-1b", "geom": poly([(150, 72), (998, 68), (1003, 805), (150, 795)])}, r)
        for g, k, load in [(ellipse(620, 380, 140, 110), "grass_juniper", 0.6), (ellipse(630, 445, 70, 45), "juniper", 1.2),
                           (ellipse(895, 360, 50, 110), "juniper", 1.2), (ellipse(340, 650, 110, 90), "grass_juniper", 0.6),
                           (ellipse(720, 690, 75, 70), "aspen", None), (ellipse(340, 240, 45, 45), "shrub", None),
                           (ellipse(960, 320, 30, 60), "aspen", None), (ellipse(940, 650, 45, 55), "juniper", 1.2)]:
            g = dict(g)
            vwrite(c, "fuels.fuel_class", {"fuel_class": k, "load_kg_m2": load, "geom": g}, r)
        c.execute("select set_config('rx.versioning','on',true)")
        c.execute("""insert into fuels.treatment (kind, occurred_on, completeness_pct, note, recorded_by, geom)
                     values ('prescribed_burn','2023-04-28',80,%s,'seed',ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(%s),4326)))""",
                  (NOTE, json.dumps(poly([(500, 540), (820, 600), (840, 700), (700, 780), (300, 760), (300, 600)]))))
        for i, (x, y, k) in enumerate([(360, 380, "mixed_grass"), (620, 440, "juniper"), (890, 360, "juniper"),
                                       (350, 640, "grass_juniper"), (720, 690, "aspen"), (560, 240, "mixed_grass")], 1):
            c.execute("""insert into fuels.plot (plot_code, sampled_on, fuel_class, load_kg_m2, curing_pct, note, recorded_by, geom)
                         values (%s,'2026-10-01',%s,%s,%s,%s,'seed',ST_SetSRID(ST_GeomFromGeoJSON(%s),4326))""",
                      (f"P{i}", k, {"mixed_grass": 0.3, "juniper": 1.2, "grass_juniper": 0.6}.get(k), 95, NOTE, json.dumps(pt(x, y))))
        c.execute("select set_config('rx.versioning','off',true)")

        r = release(c, "ops.fireguard", "DEMO fireguards 2026.1", "")
        vwrite(c, "ops.fireguard", {"name": "N / E fireguard", "guard_type": "disced", "width_m": 10, "condition": "good",
                                    "last_maintained": "2026-09-15", "dac_cleared": True, "geom": line([(180, 420), (220, 170), (860, 140), (930, 560), (820, 760)])}, r)
        vwrite(c, "ops.fireguard", {"name": "Fireguard 22", "guard_type": "disced", "width_m": 15, "condition": "fair",
                                    "last_maintained": "2025-10-01", "dac_cleared": True, "geom": line([(160, 78), (1005, 68)])}, r)
        r = release(c, "ops.road", "DEMO roads 2026.1", "")
        vwrite(c, "ops.road", {"name": "Range Rd A", "road_class": "range_road", "engine_access": True, "tender_access": True, "geom": line([(40, 778), (600, 782), (1040, 800)])}, r)
        vwrite(c, "ops.road", {"name": "Range Rd B", "road_class": "range_road", "engine_access": True, "tender_access": True, "geom": line([(1005, 20), (1004, 450), (1008, 900)])}, r)
        vwrite(c, "ops.road", {"name": "Trail 14", "road_class": "trail", "engine_access": True, "tender_access": False, "geom": line([(160, 20), (155, 400), (165, 900)])}, r)
        vwrite(c, "ops.water_source", {"name": "Dugout W1", "kind": "dugout", "capacity_m3": 400, "tender_access": True, "seasonal_note": "Low by August", "geom": pt(95, 540)}, None)
        vwrite(c, "ops.restricted_area", {"name": "DEMO impact area", "kind": "no_ground_access", "geom": poly([(1040, 0), (1300, 0), (1300, 920), (1040, 920)])}, None)
        vwrite(c, "ops.bivouac", {"name": "DEMO bivouac 3", "designated": True, "treatment_note": "Mow before use", "geom": ellipse(300, 860, 60, 30)}, None)
        for name, typ, mat, vul, g in [("Range latrine", "latrine", "plastic", "high", pt(930, 814)),
                                       ("Wooden range structure", "structure", "wood", "high", pt(880, 640)),
                                       ("Target frame", "target", "steel", "low", pt(980, 560)),
                                       ("Bunker", "bunker", "concrete", "low", pt(1000, 300)),
                                       ("Observation tower", "tower", "steel", "low", pt(980, 140)),
                                       ("Distribution line", "power_line", None, "moderate", line([(40, 835), (1040, 850)]))]:
            vwrite(c, "infra.asset", {"name": name, "asset_type": typ, "material": mat, "vulnerability": vul, "geom": g}, None)
        vwrite(c, "habitat.sensitive_feature", {"kind": "rare_plant", "name": "Habitat exclusion (demo)", "restricted": True, "fire_effect": "harmed",
                                                "measure": "Wet line exclusion", "geom": poly([(320, 600), (440, 590), (470, 680), (350, 705)])}, None)
        vwrite(c, "habitat.sensitive_feature", {"kind": "cultural", "name": "Cultural site (generalized, demo)", "restricted": True,
                                                "fire_effect": "mixed", "measure": "No line building in buffer", "geom": ellipse(700, 300, 70, 70)}, None)
        for name, kind, sens, (x, y) in [("DEMO community", "community", "high", (3200, -4500)), ("DEMO housing area", "housing", "moderate", (-1500, -800)),
                                          ("DEMO highway", "highway", "moderate", (600, -1700))]:
            vwrite(c, "smoke.receptor", {"name": name, "kind": kind, "sensitivity": sens, "geom": pt(x, y)}, None)

        # --- Red-headed Woodpecker grid (real list from ECCC) ---------------------
        r = release(c, "habitat.critical_habitat", "ECCC Red-headed Woodpecker grid (MB)", "10 km UTM squares from the recovery strategy list, loaded 2026-11-20")
        gj = json.loads((ROOT / "data" / "rhwo_critical_habitat_grid_mb.geojson").read_text())
        for f in gj["features"]:
            p = f["properties"]
            c.execute("select meta.vwrite('habitat.critical_habitat'::regclass, null, %s, '2021-01-01', 'ECCC list', 'seed', %s)",
                      (db.jsonb({"species": "Red-headed Woodpecker", "sci_name": "Melanerpes erythrocephalus", "status": "final",
                                 "grid_id": p["grid_id"], "tenure": p["tenure"],
                                 "source_doc": "Recovery Strategy for the Red-headed Woodpecker in Canada (2021)",
                                 "geom": f["geometry"]}), r))

        # --- the plan ----------------------------------------------------------
        pid = c.execute("""insert into plans.plan (name, unit_name, status, complexity, min_burn_boss, planned_window, demo, created_by)
                           values ('DEMO Burn Unit 7', 'Ignition units A, B, C', 'draft', 'moderate', 'RXB2',
                                   'Apr 15 – May 14, or Aug 16 – Oct 31', true, 'seed') returning id""").fetchone()["id"]
        feats = [
            ("burn_unit", "Burn Unit 7", poly(UNIT)),
            ("ignition_unit", "A", poly([(220, 170), (860, 140), (930, 560), (880, 650), (865, 560), (800, 215), (209, 240)])),
            ("ignition_unit", "B", poly([(209, 240), (800, 215), (865, 560), (205, 520), (180, 420)])),
            ("ignition_unit", "C", poly([(205, 520), (865, 560), (880, 650), (820, 760), (260, 740)])),
            ("contingency_area", "Contingency area", poly([(150, 72), (998, 68), (1003, 805), (150, 795)])),
            ("holding_line", "N / E disced fireguard", line([(180, 420), (220, 170), (860, 140), (930, 560), (820, 760)])),
            ("holding_line", "W wet line on Trail 14", line([(260, 740), (180, 420)])),
            ("holding_line", "S Range Rd A", line([(260, 745), (820, 765)])),
            ("contingency_line", "Fireguard 22", line([(160, 78), (1005, 68)])),
            ("contingency_line", "Range Rd B", line([(995, 68), (1000, 800)])),
            ("trigger_point", "TP1", pt(900, 100)), ("trigger_point", "TP2", pt(972, 302)),
            ("anchor_point", "AP", pt(860, 140)), ("test_fire_site", "TF", pt(815, 180)),
            ("safety_zone", "SZ1", pt(958, 876)), ("safety_zone", "SZ2", pt(104, 840)),
            ("escape_route", "ER1", line([(874, 130), (995, 86), (1000, 780), (972, 852)])),
            ("escape_route", "ER2", line([(205, 248), (160, 330), (165, 770), (124, 812)])),
            ("drop_point", "DP / ICP", pt(1024, 799)), ("lookout", "Lookout", pt(90, 300)),
        ]
        for kind, label, g in feats:
            c.execute("insert into plans.feature (plan_id, kind, label, geom, updated_by) values (%s,%s,%s,ST_SetSRID(ST_GeomFromGeoJSON(%s),4326),'seed')",
                      (pid, kind, label, json.dumps(g)))
        for param, lo, hi in [("temp_c", 10, 24), ("rh_pct", 20, 45), ("wind_kmh", 5, 22), ("ffmc", 77, 90), ("isi", 4, 7),
                              ("fwi", None, 12), ("dmc", None, 25), ("dc", None, 210), ("bui", None, 30), ("curing_pct", 80, None)]:
            c.execute("insert into plans.prescription_param (plan_id, param, low, high) values (%s,%s,%s,%s)", (pid, param, lo, hi))
        c.execute("""insert into plans.ignition_variant (plan_id, name, wind_dir_min, wind_dir_max, description, firing_sequence) values
            (%s,'SW wind',200,250,'Downwind edge NE. Anchor at the NE corner.',%s),
            (%s,'NW wind',290,340,'Downwind edge SE. Anchor at the SE corner on Range Rd A.',%s)""",
                  (pid, db.jsonb([{"step": "Test fire at TF"}, {"step": "Unit A: back fire W along N guard and S along E guard; black ≥ 60 m"},
                                  {"step": "Unit B: strip head fire, NW–SE strips, NE to SW, 30–50 m spacing"},
                                  {"step": "Unit C: wet line the exclusion, then flank/head fire from Rd A"}]),
                   pid, db.jsonb([{"step": "Test fire near the SE corner"}, {"step": "Back fire W along Range Rd A and N along the E guard"},
                                  {"step": "Strip head fire SW–NE strips, working SE to NW"}])))
        text = {
            "4": {"range_area": "DEMO range", "slope": "0–8", "aspect": ["flat", "S", "SW"],
                  "topography": "Notional sandy rolling terrain.", "fuel_models": ["FBP O-1b", "Local (juniper)"],
                  "fuels_notes": "Creeping juniper patches carry fire only in dry conditions."},
            "5": {"objectives": [
                {"type": "resource", "objective": "Reduce fine fuel load before the spring exercise", "measure": "Fuel plots", "target": "< 0.15 kg/m² over 80% of the unit", "when": "Within 2 weeks"},
                {"type": "fire", "objective": "Keep fire out of the habitat exclusion", "measure": "Post-burn site visit", "target": "No fire in the exclusion", "when": "Day of burn"}]},
            "8": {"windows": [{"from": "2027-04-15", "to": "2027-05-14", "note": "Spring"}, {"from": "2027-08-16", "to": "2027-10-31", "note": "Fall"}],
                  "ignition_start": "11:00", "ignition_end": "17:00", "duration": 1,
                  "constraints": ["No ignition May 15 – Aug 15 (MBCA)", "Range Control booking"]},
            "14": {"procedure": "Test fire at TF near the anchor point (SW wind variant). Observe 10–15 minutes."},
            "15": {"techniques": ["backing", "strip head", "flanking"], "devices": ["drip torch"],
                   "staffing": [{"position": "FIRB", "qty": 1}, {"position": "IGNITION (FFT2)", "qty": 2}]},
            "17": {"maps_table": [{"map": "TP1", "condition": "Slopover north of the N fireguard", "intent": "Stop spread at Fireguard 22",
                                   "actions": "Stop firing; E1 to Fireguard 22", "resources": "E1, tender", "timeframe": "< 10 min", "who": "Holding boss"},
                                  {"map": "TP2", "condition": "Slopover east of the E guard", "intent": "Hold at Range Rd B",
                                   "actions": "Stop firing; E2 to Rd B", "resources": "E2", "timeframe": "< 10 min", "who": "Holding boss"}],
                   "resources": [{"resource": "Type 6 engine", "source": "Base Fire Department", "response_min": 10}]},
            "19": {"transport": "From 200–250° (SW) or 290–340° (NW)", "mitigation": ["Highway signage", "Advance public notification"]},
        }
        for code, content in text.items():
            c.execute("insert into plans.element (plan_id, code, content, status, updated_by) values (%s,%s,%s,'draft','seed')",
                      (pid, code, db.jsonb(content)))
    print("seeded demo plan", pid)
    db.pool.close()


if __name__ == "__main__":
    seed()
