"""Structured content for each PMS 484-1 element (Dec 2021 template).

Field types
  text, textarea, number (unit), select (options), multi (options), date, time, bool
  table      columns: [{key, label, type, options?}], rows?: default rows, fixed: first column is fixed
  checklist  items: [(key, label)], answered yes / no / n/a with a note
  auto       read-only, filled from the plan's map and the database (source: ...)
  component  an editor that lives in its own tables (prescription, variants, signatures)
Elements with map=True show the plan map above the form.
"""

RXB = ["RXB1", "RXB2", "RXB3"]
LMH = ["low", "moderate", "high"]
YN = ["yes", "no"]
POSITIONS = ["RXB1", "RXB2", "RXB3", "FIRB", "IGNITION (FFT1)", "IGNITION (FFT2)", "HOLDING BOSS", "ENGB", "ENGINE CREW", "TFLD",
             "FFT1", "FFT2", "FEMP", "LOOKOUT", "EMT / MEDIC", "WATER TENDER OPERATOR", "HEAVY EQUIPMENT", "UXO ADVISOR", "RANGE CONTROL LIAISON", "OTHER"]
COMPLEXITY_ELEMENTS = ["Off-site values", "On-site values", "Public and political interest", "Safety", "Fire behavior",
                       "Resistance to containment", "Ignition procedures / methods", "Prescribed fire duration", "Smoke management",
                       "Number and dependence of activities", "Management organization", "Treatment / resource objectives",
                       "Constraints", "Project logistics"]

SCHEMA = {
  "1": [
    {"key": "admin_unit", "label": "Administrative unit(s)", "type": "text", "default": "CFB Shilo"},
    {"key": "burn_name", "label": "Prescribed fire name", "type": "auto", "source": "plan_name"},
    {"key": "ignition_unit", "label": "Prescribed fire unit (ignition units)", "type": "auto", "source": "ignition_units"},
    {"key": "complexity", "label": "Complexity rating (from Element 3)", "type": "select", "options": LMH},
    {"key": "min_rxb", "label": "Minimum burn boss qualification", "type": "select", "options": RXB},
    {"key": "signatures", "label": "Preparer, technical reviewer and agency administrator", "type": "component", "component": "signatures"},
  ],
  "2A": [
    {"key": "discussion", "label": "Discussion items", "type": "checklist", "items": [
        ("changes", "A. Changes since approval have been considered (conditions, staffing, plan amendments)"),
        ("compliance", "B. Compliance requirements are complete (permits, environmental review, range booking)"),
        ("conditions", "C. All elements and conditions in the plan can be met"),
        ("notifications", "D. Notifications are complete or will be made"),
        ("briefing", "E. Staff have been briefed on the burn and its risks"),
        ("circumstances", "F. No circumstances (fire activity, resource shortage, training) affect implementation"),
        ("contingency", "G. Expectations for notification if contingency actions are taken are clear"),
        ("wildfire", "H. Expectations for wildfire declaration are clear")]},
    {"key": "recommendation", "label": "FMO / burn boss recommendation", "type": "select", "options": ["implement", "do not implement"]},
    {"key": "authorized_from", "label": "Ignition authorized from", "type": "date"},
    {"key": "authorized_to", "label": "Ignition authorized to", "type": "date"},
    {"key": "administrator", "label": "Agency administrator", "type": "text", "list": "people"},
    {"key": "signed_on", "label": "Signed", "type": "date"},
  ],
  "2B": [
    {"key": "preliminary", "label": "Preliminary questions", "type": "checklist", "items": [
        ("conditions_changed", "Have conditions in the project area changed since the plan was approved?"),
        ("amendments", "Have all amendments been approved?"),
        ("authorization", "Is the ignition authorization (2A) current?")]},
    {"key": "unit_items", "label": "Unit-specific go / no-go items", "type": "table", "columns": [
        {"key": "item", "label": "Item", "type": "text"}, {"key": "requirement", "label": "Requirement", "type": "text"}]},
    {"key": "note", "label": "", "type": "info", "text": "The standard checklist is answered on each burn day (Burn days)."},
  ],
  "3": [
    {"key": "elements", "label": "Complexity elements (PMS 424)", "type": "table", "fixed": True,
     "rows": [{"element": e} for e in COMPLEXITY_ELEMENTS], "columns": [
        {"key": "element", "label": "Element", "type": "fixed"},
        {"key": "pre_risk", "label": "Pre-plan risk", "type": "select", "options": LMH},
        {"key": "post_risk", "label": "Post-plan risk", "type": "select", "options": LMH},
        {"key": "difficulty", "label": "Technical difficulty", "type": "select", "options": LMH},
        {"key": "rationale", "label": "Rationale / mitigation", "type": "text"}]},
    {"key": "mitigation", "label": "Pre-burn work that lowers complexity", "type": "auto", "source": "mitigation"},
    {"key": "summary", "label": "Summary rating", "type": "auto", "source": "complexity_summary"},
    {"key": "final", "label": "Final complexity (agency administrator)", "type": "select", "options": LMH},
    {"key": "rationale", "label": "Rationale for the final rating", "type": "textarea"},
  ],
  "4": {"map": True, "fields": [
    {"key": "location", "label": "Location", "type": "auto", "source": "location"},
    {"key": "size", "label": "Size", "type": "auto", "source": "size"},
    {"key": "range_area", "label": "Range / training area", "type": "text"},
    {"key": "elev_min", "label": "Elevation low (m)", "type": "number"},
    {"key": "elev_max", "label": "Elevation high (m)", "type": "number"},
    {"key": "slope", "label": "Slope (%)", "type": "text"},
    {"key": "aspect", "label": "Aspects", "type": "multi", "options": ["flat", "N", "NE", "E", "SE", "S", "SW", "W", "NW"]},
    {"key": "topography", "label": "Topography notes", "type": "textarea"},
    {"key": "boundary", "label": "Project boundary description", "type": "textarea"},
    {"key": "fuels_table", "label": "On-site and adjacent fuels (from the fuels layer)", "type": "auto", "source": "fuels"},
    {"key": "fuel_models", "label": "Fuel models used", "type": "multi", "options": ["FBP O-1a", "FBP O-1b", "FBP M-1/M-2", "FBP D-1", "FBP S-1", "Rothermel GR1–GR9", "Rothermel GS1–GS4", "Local (juniper)"]},
    {"key": "fuels_notes", "label": "Fuels notes", "type": "textarea"},
    {"key": "values_table", "label": "Values in the unit and contingency area (from the database)", "type": "auto", "source": "values"},
    {"key": "values_notes", "label": "Unique features, natural resources and values: notes", "type": "textarea"},
  ]},
  "5": [
    {"key": "objectives", "label": "Objectives", "type": "table", "columns": [
        {"key": "type", "label": "Type", "type": "select", "options": ["resource", "fire"]},
        {"key": "objective", "label": "Objective", "type": "text"},
        {"key": "measure", "label": "Measured by", "type": "text"},
        {"key": "target", "label": "Target", "type": "text"},
        {"key": "when", "label": "When", "type": "text"}],
     "rows": [{"type": "resource", "objective": "Reduce fine fuel load before training", "measure": "Fuel plots (kg/m²)", "target": "", "when": "Post-burn"},
              {"type": "fire", "objective": "Consume cured grass across the unit", "measure": "% of unit blackened", "target": "", "when": "Day of burn"}]},
  ],
  "6": [
    {"key": "costs", "label": "Costs", "type": "table", "columns": [
        {"key": "item", "label": "Item", "type": "text"}, {"key": "amount", "label": "Amount ($)", "type": "number"},
        {"key": "source", "label": "Funding source", "type": "text"}]},
    {"key": "total", "label": "Total", "type": "auto", "source": "cost_total"},
  ],
  "7": [
    {"key": "narrative", "label": "A. Prescription narrative: how the fire behaviour meets the objectives", "type": "textarea"},
    {"key": "parameters", "label": "B. Prescription parameters", "type": "component", "component": "prescription"},
    {"key": "model", "label": "Fire behaviour modelling", "type": "select", "options": ["Fireline", "FBP (CFFDRS)", "Rothermel / BehavePlus", "Empirical / test fires"]},
    {"key": "behaviour", "label": "Expected fire behaviour", "type": "table", "columns": [
        {"key": "fire_type", "label": "Fire", "type": "select", "options": ["backing", "flanking", "strip head", "head"]},
        {"key": "fuel", "label": "Fuel", "type": "text"},
        {"key": "ros", "label": "ROS m/min (low–high)", "type": "text"}, {"key": "fl", "label": "Flame length m", "type": "text"},
        {"key": "hfi", "label": "Intensity kW/m", "type": "text"}]},
    {"key": "run_ref", "label": "Model run references (Appendix E)", "type": "text"},
  ],
  "8": [
    {"key": "windows", "label": "Burn windows", "type": "table", "columns": [
        {"key": "from", "label": "From", "type": "date"}, {"key": "to", "label": "To", "type": "date"}, {"key": "note", "label": "Note", "type": "text"}]},
    {"key": "mbca", "label": "Migratory birds check", "type": "auto", "source": "mbca"},
    {"key": "ignition_start", "label": "Ignition period from", "type": "time", "default": "11:00"},
    {"key": "ignition_end", "label": "Ignition period to", "type": "time", "default": "17:00"},
    {"key": "duration", "label": "Projected duration (days)", "type": "number"},
    {"key": "constraints", "label": "Constraints", "type": "multi", "options": ["No ignition May 15 – Aug 15 (MBCA)", "Range Control booking", "Training schedule", "Smoke on highways", "Fire ban / provincial restrictions", "Weekend / holiday staffing"]},
    {"key": "constraints_notes", "label": "Constraint notes", "type": "textarea"},
  ],
  "9": [
    {"key": "prep", "label": "Pre-burn work on the map (lowers complexity; verified before ignition)", "type": "component", "component": "prep_tasks"},
    {"key": "onsite", "label": "Other preparation (no map location)", "type": "table", "columns": [
        {"key": "task", "label": "Task", "type": "text"}, {"key": "who", "label": "Who", "type": "text"},
        {"key": "due", "label": "Due", "type": "date"}, {"key": "done", "label": "Done", "type": "bool"}],
     "rows": [{"task": "Pre-burn recce (site visit)"}, {"task": "Book range with Range Control"}]},
    {"key": "offsite", "label": "Off-site considerations", "type": "textarea"},
    {"key": "forecast_sources", "label": "Weather and smoke forecasts", "type": "multi", "options": ["Burn-morning forecast (rx)", "fwx.rtams.ca", "ECCC spot / public forecast", "CWFIS", "On-site belt weather", "Base weather station"]},
    {"key": "forecast_frequency", "label": "How often", "type": "text", "default": "Daily from 3 days out; burn morning; hourly on site"},
    {"key": "notifications", "label": "Notifications", "type": "table", "columns": [
        {"key": "party", "label": "Who", "type": "text"}, {"key": "method", "label": "How", "type": "text"},
        {"key": "when", "label": "When", "type": "text"}, {"key": "done", "label": "Done", "type": "bool"}],
     "rows": [{"party": "Range Control", "when": "24 h before"}, {"party": "Base Fire Department"}, {"party": "Base Public Affairs"}, {"party": "Neighbouring RM / landowners"}, {"party": "Utility (power line)"}]},
  ],
  "10": [
    {"key": "checklist", "label": "Briefing checklist", "type": "checklist", "items": [
        ("organization", "Burn organization"), ("objectives", "Burn objectives and prescription"), ("area", "Description of the project area"),
        ("weather", "Expected weather and fire behaviour"), ("comms", "Communications"), ("ignition", "Ignition plan"),
        ("holding", "Holding plan"), ("contingency", "Contingency plan and trigger points"), ("wildfire", "Wildfire declaration"),
        ("safety", "Safety hazards (UXO), medical plan"), ("aerial", "Aerial ignition (if used)")]},
    {"key": "notes", "label": "Briefing notes", "type": "textarea"},
  ],
  "11": [
    {"key": "positions", "label": "Positions", "type": "table", "columns": [
        {"key": "position", "label": "Position", "type": "select", "options": POSITIONS}, {"key": "qty", "label": "Qty", "type": "number"},
        {"key": "name", "label": "Name(s)", "type": "text", "list": "people"}, {"key": "qualified", "label": "Qual. checked", "type": "bool"}]},
    {"key": "quals_check", "label": "Qualification check (from People)", "type": "auto", "source": "quals_check", "tag": "checked against People"},
    {"key": "equipment", "label": "Equipment", "type": "table", "columns": [
        {"key": "type", "label": "Equipment", "type": "text"}, {"key": "qty", "label": "Qty", "type": "number"}, {"key": "note", "label": "Note", "type": "text"}],
     "rows": [{"type": "Type 6 engine"}, {"type": "Water tender"}, {"type": "UTV with slip-on"}, {"type": "Drip torches"}]},
    {"key": "supplies", "label": "Supplies", "type": "textarea"},
  ],
  "12": [
    {"key": "radio", "label": "Radio", "type": "table", "columns": [
        {"key": "function", "label": "Function", "type": "select", "options": ["command", "tactical", "air", "range control", "medical"]},
        {"key": "channel", "label": "Channel / name", "type": "text"}, {"key": "rx", "label": "RX", "type": "text"},
        {"key": "tx", "label": "TX", "type": "text"}, {"key": "tone", "label": "Tone", "type": "text"}]},
    {"key": "phones", "label": "Telephone", "type": "table", "columns": [
        {"key": "who", "label": "Who", "type": "text", "list": "people"}, {"key": "number", "label": "Number", "type": "text"}],
     "rows": [{"who": "Range Control"}, {"who": "Base Fire Department"}, {"who": "Burn boss"}, {"who": "Agency administrator"}, {"who": "Hospital"}]},
  ],
  "13": {"map": True, "fields": [
    {"key": "hazards", "label": "Safety hazards and mitigation", "type": "table", "columns": [
        {"key": "hazard", "label": "Hazard", "type": "text"}, {"key": "mitigation", "label": "Mitigation", "type": "text"}],
     "rows": [{"hazard": "UXO / dud-producing areas", "mitigation": "No ground entry in impact areas; stay on cleared routes"},
              {"hazard": "Smoke on roads", "mitigation": "Signage and patrol"}, {"hazard": "Snags / burning aspen"}, {"hazard": "Heat stress / long shifts"}]},
    {"key": "ems", "label": "Emergency medical procedures", "type": "textarea"},
    {"key": "hospital", "label": "Nearest hospital", "type": "text"},
    {"key": "hospital_km", "label": "Distance (km)", "type": "number"},
    {"key": "evacuation", "label": "Evacuation", "type": "multi", "options": ["Ground ambulance", "Air ambulance", "Crew vehicle to rendezvous"]},
    {"key": "lz", "label": "Medevac landing zone (location)", "type": "text"},
    {"key": "facilities", "label": "Emergency facilities", "type": "textarea"},
  ]},
  "14": {"map": True, "fields": [
    {"key": "site", "label": "Test fire location", "type": "auto", "source": "test_fire_site"},
    {"key": "procedure", "label": "Procedure", "type": "textarea", "default": "Light a small test fire at the planned site, observe for 10–15 minutes, record weather and fire behaviour."},
    {"key": "criteria", "label": "Acceptance criteria", "type": "table", "columns": [
        {"key": "what", "label": "What", "type": "text"}, {"key": "acceptable", "label": "Acceptable range", "type": "text"}],
     "rows": [{"what": "Rate of spread"}, {"what": "Flame length"}, {"what": "Spotting"}, {"what": "Smoke column / direction"}]},
  ]},
  "15": {"map": True, "fields": [
    {"key": "techniques", "label": "Firing techniques", "type": "multi", "options": ["backing", "flanking", "strip head", "ring", "spot / grid", "head (controlled)"]},
    {"key": "variants", "label": "Firing sequence by wind direction (ignition variants)", "type": "component", "component": "variants"},
    {"key": "devices", "label": "Ignition devices", "type": "multi", "options": ["drip torch", "terra torch", "fusees", "propane torch", "aerial (PSD / drone)"]},
    {"key": "staffing", "label": "Minimum ignition staffing", "type": "table", "columns": [
        {"key": "position", "label": "Position", "type": "select", "options": POSITIONS}, {"key": "qty", "label": "Qty", "type": "number"}],
     "rows": [{"position": "FIRB", "qty": 1}, {"position": "IGNITION (FFT2)", "qty": 2}]},
    {"key": "notes", "label": "Ignition notes", "type": "textarea"},
  ]},
  "16": {"map": True, "fields": [
    {"key": "lines", "label": "Holding lines (from the map)", "type": "auto", "source": "holding_lines"},
    {"key": "procedures", "label": "General holding procedures", "type": "textarea"},
    {"key": "critical", "label": "Critical holding points", "type": "table", "columns": [
        {"key": "where", "label": "Where", "type": "text"}, {"key": "concern", "label": "Concern", "type": "text"}, {"key": "action", "label": "Action", "type": "text"}]},
    {"key": "minimum", "label": "Minimum holding organization", "type": "table", "columns": [
        {"key": "resource", "label": "Resource", "type": "text"}, {"key": "qty", "label": "Qty", "type": "number"}, {"key": "where", "label": "Position", "type": "text"}]},
  ]},
  "17": {"map": True, "fields": [
    {"key": "triggers", "label": "Trigger points (from the map)", "type": "auto", "source": "trigger_points"},
    {"key": "maps_table", "label": "Management action points", "type": "table", "columns": [
        {"key": "map", "label": "MAP", "type": "text"}, {"key": "condition", "label": "Condition", "type": "text"},
        {"key": "intent", "label": "Intent", "type": "text"}, {"key": "actions", "label": "Actions", "type": "text"},
        {"key": "resources", "label": "Resources", "type": "text"}, {"key": "timeframe", "label": "Time frame", "type": "text"},
        {"key": "who", "label": "Responsible", "type": "text"}]},
    {"key": "resources", "label": "Minimum contingency resources", "type": "table", "columns": [
        {"key": "resource", "label": "Resource", "type": "text"}, {"key": "source", "label": "Where from", "type": "text"},
        {"key": "response_min", "label": "Max response (min)", "type": "number"}]},
    {"key": "actions", "label": "Actions needed", "type": "textarea"},
  ]},
  "18": [
    {"key": "who", "label": "Who declares a wildfire", "type": "text", "default": "Burn boss"},
    {"key": "when", "label": "When it is declared", "type": "textarea", "default": "When contingency actions fail to contain the fire within the contingency area, or the fire cannot be returned to prescription by the end of the next burn period."},
    {"key": "ic", "label": "Incident commander", "type": "text", "list": "people"},
    {"key": "notifications", "label": "Notifications", "type": "table", "columns": [
        {"key": "party", "label": "Who", "type": "text"}, {"key": "how", "label": "How", "type": "text"}],
     "rows": [{"party": "Agency administrator"}, {"party": "Range Control"}, {"party": "Base Fire Department / dispatch"}, {"party": "Manitoba Wildfire Service"}]},
    {"key": "extended", "label": "Extended attack actions", "type": "textarea"},
  ],
  "19": {"map": True, "fields": [
    {"key": "permits", "label": "Compliance and permits", "type": "table", "columns": [
        {"key": "permit", "label": "Permit / requirement", "type": "text"}, {"key": "issuer", "label": "Issued by", "type": "text"},
        {"key": "status", "label": "Status", "type": "select", "options": ["not needed", "to apply", "applied", "received"]}]},
    {"key": "receptors", "label": "Smoke-sensitive receptors (from the database)", "type": "auto", "source": "receptors"},
    {"key": "transport", "label": "Acceptable transport wind directions", "type": "text"},
    {"key": "impacts", "label": "Potentially impacted areas", "type": "textarea"},
    {"key": "mitigation", "label": "Mitigation", "type": "multi", "options": ["Burn only with transport winds away from receptors", "Minimum mixing height / ventilation index", "Highway signage", "Advance public notification", "Mop-up near roads before evening"]},
    {"key": "mitigation_notes", "label": "Mitigation notes", "type": "textarea"},
  ]},
  "20": [
    {"key": "monitoring", "label": "Monitoring", "type": "table", "columns": [
        {"key": "what", "label": "What", "type": "select", "options": ["fuels", "forecast weather", "observed weather", "fire behaviour", "objectives", "smoke"]},
        {"key": "method", "label": "Method", "type": "text"}, {"key": "when", "label": "When / how often", "type": "text"}, {"key": "who", "label": "Who", "type": "text"}],
     "rows": [{"what": "fuels", "method": "Fuel plots (site visit)", "when": "Pre-burn"}, {"what": "observed weather", "method": "Belt weather kit", "when": "Hourly"},
              {"what": "fire behaviour", "method": "ROS / flame length observations", "when": "Each ignition phase"}, {"what": "objectives", "method": "Post-burn plots and perimeter", "when": "Within 2 weeks"}]},
  ],
  "21": [
    {"key": "tasks", "label": "Post-burn activities", "type": "table", "columns": [
        {"key": "task", "label": "Task", "type": "text"}, {"key": "who", "label": "Who", "type": "text"},
        {"key": "due", "label": "Due", "type": "text"}, {"key": "done", "label": "Done", "type": "bool"}],
     "rows": [{"task": "Map the burn perimeter and record it as a fuel treatment"}, {"task": "Post-burn site visit and plots"},
              {"task": "Rehab of holding lines"}, {"task": "Post-burn report"}, {"task": "Update the fuels layer (new version)"}]},
  ],
  "A": [{"key": "maps", "label": "Maps", "type": "checklist", "items": [
      ("vicinity", "Vicinity map (required)"), ("project", "Project / ignition units map (required)"), ("fuels", "Fuels map"),
      ("values", "Sensitive features / values map"), ("smoke", "Smoke impact areas map"), ("behaviour", "Expected fire behaviour map")]}],
  "B": [{"key": "review", "label": "Technical reviewer checklist", "type": "checklist", "items": [
      (f"e{i}", f"Element {i} is complete and adequate") for i in ["1", "2", "3", "4", "5", "7", "8", "9", "11", "12", "13", "15", "16", "17", "18", "19", "20", "21"]]},
      {"key": "comments", "label": "Reviewer comments", "type": "textarea"}],
  "C": [{"key": "note", "label": "", "type": "info", "text": "The complexity analysis is in Element 3."}, {"key": "notes", "label": "Notes", "type": "textarea"}],
  "D": [{"key": "jha", "label": "Job hazard analysis", "type": "table", "columns": [
      {"key": "task", "label": "Task", "type": "text"}, {"key": "hazard", "label": "Hazard", "type": "text"},
      {"key": "control", "label": "Control", "type": "text"}, {"key": "risk", "label": "Residual risk", "type": "select", "options": LMH}]}],
  "E": [{"key": "runs", "label": "Model runs", "type": "table", "columns": [
      {"key": "model", "label": "Model", "type": "text"}, {"key": "inputs", "label": "Inputs", "type": "text"},
      {"key": "outputs", "label": "Outputs", "type": "text"}, {"key": "ref", "label": "File / run id", "type": "text"}]}],
  "F": [{"key": "plan", "label": "Smoke management plan", "type": "textarea"}],
}


def fields(code):
    s = SCHEMA.get(code, [])
    return s["fields"] if isinstance(s, dict) else s


def has_map(code):
    s = SCHEMA.get(code)
    return isinstance(s, dict) and s.get("map", False)


# --- Operation order for a burn season (program level) ------------------------------------------
# Sections follow the CFB Shilo OPORD layout: heading, situation, mission, execution, service support,
# command and signals, authorization. Defaults are starting wording to edit.
OPORD = [
  {"section": "Heading", "fields": [
    {"key": "title", "label": "Title", "type": "text", "default": "Op [NAME] (RTA prescribed fire)"},
    {"key": "file_number", "label": "File number", "type": "text", "default": "3000-1 (G3)"},
    {"key": "drafted_by", "label": "Drafted by", "type": "text"},
    {"key": "references", "label": "References", "type": "table", "columns": [
        {"key": "ref", "label": "Ref", "type": "text", "w": "70px"}, {"key": "title", "label": "Document", "type": "text"}],
     "rows": [{"ref": "A", "title": "Range Standing Orders"}, {"ref": "B", "title": "Wildland Fire Hazard Reduction Plan"},
              {"ref": "C", "title": "PMS 484 – NWCG Standards for Prescribed Fire Planning and Implementation (2022)"}]},
    {"key": "dist_action", "label": "Distribution: action", "type": "textarea"},
    {"key": "dist_info", "label": "Distribution: info", "type": "textarea"},
  ]},
  {"section": "Situation", "fields": [
    {"key": "situation", "label": "Situation", "type": "textarea",
     "default": "The CFB Shilo Range and Training Area (RTA) covers about 40,000 ha of native mixed-grass prairie, forest, wetland and sand dunes, with species at risk and a network of firebreaks. Fine fuels build up between burns and raise the risk of wildfires that disrupt training and threaten sensitive sites. This season's prescribed fire operation reduces that risk while supporting prairie health and training."},
  ]},
  {"section": "Mission", "fields": [
    {"key": "mission", "label": "Mission", "type": "textarea",
     "default": "CFB Shilo will conduct prescribed fires in the RTA to reduce wildfire risk, improve native prairie health, and keep conditions that support military training and conservation."},
  ]},
  {"section": "Execution", "fields": [
    {"key": "intent", "label": "Intent", "type": "textarea",
     "default": "Conduct prescribed fire operations that limit wildfire impacts on training, protect sensitive sites and infrastructure, and keep nearby communities safe. This order sets out the resources, support and processes needed, and is updated each year."},
    {"key": "phases", "label": "Scheme of manoeuvre", "type": "table", "columns": [
        {"key": "phase", "label": "Phase", "type": "text", "w": "190px"}, {"key": "description", "label": "Description", "type": "textarea"},
        {"key": "from", "label": "From", "type": "date", "w": "150px"}, {"key": "to", "label": "To", "type": "date", "w": "150px"}],
     "rows": [{"phase": "1 – Planning", "description": "Prepare equipment and burn plans; notify the RTA user community, stakeholders and the public; environmental review and permits; contracts."},
              {"phase": "2 – Conduct", "description": "Begins when the weather is within the burn prescriptions (Annex B). Burns in priority order (Annex C), booked through Range Control. Each fire is monitored until it is out."},
              {"phase": "3 – Consolidation", "description": "Operations cease; demobilize; post-operation report and after action review; lessons learned into next season's plan."}]},
    {"key": "main_effort", "label": "Main effort", "type": "textarea", "default": "Reduce the fine fuel load in the RTA."},
    {"key": "end_state", "label": "End state", "type": "textarea", "default": "Fine fuel load reduced safely and responsibly, and all administrative tasks completed."},
    {"key": "blocks", "label": "Planned burn blocks (Annex B)", "type": "auto", "source": "season_blocks", "tag": "from this season's burn plans"},
    {"key": "groupings", "label": "Groupings and tasks", "type": "table", "columns": [
        {"key": "group", "label": "Organization", "type": "text", "w": "200px"}, {"key": "tasks", "label": "Tasks", "type": "textarea"}],
     "rows": [{"group": "SES", "tasks": "Overall OPI; planning and implementing; post-operation report"},
              {"group": "Range Control", "tasks": "Bookings; fire monitoring; safety traces; airspace; UXO threat briefing"},
              {"group": "G3 Ops", "tasks": "Coordinate additional resources; finance (O&M, SWE)"},
              {"group": "RTAMS", "tasks": "Assist plan preparation; fire history; burn priorities; hazard assessment; fire effects monitoring; burn plans and maps (rx)"},
              {"group": "PAO", "tasks": "Public, lodger units, media"},
              {"group": "G4", "tasks": "Equipment support (dozers, discs, graders); fireguard maintenance; EOD support"},
              {"group": "RPOU", "tasks": "Mowing burn perimeters; fire-suppression well maintenance"},
              {"group": "MET / RTAMS", "tasks": "Daily met package; daily FWI and DSR"}]},
    {"key": "resources", "label": "Resources required (from the burn plans, Element 11)", "type": "auto", "source": "season_resources", "tag": "largest need of any one burn"},
    {"key": "timings", "label": "Timings", "type": "table", "columns": [
        {"key": "when", "label": "When", "type": "text", "w": "220px"}, {"key": "what", "label": "What", "type": "text"}],
     "rows": [{"what": "Planning complete"}, {"what": "Ignition operations"}, {"what": "Cease operations"}, {"what": "After action review complete"}]},
    {"key": "locations", "label": "Locations", "type": "textarea", "default": "Range Control: [building]\nPlanned burn locations: Annex B"},
    {"key": "uxo", "label": "UXO hazards", "type": "textarea", "default": "A qualified EOD operator sweeps travel corridors and escape routes used for each burn. All personnel receive a UXO threat briefing from Range Control."},
    {"key": "environmental", "label": "Environmental", "type": "textarea", "default": "Best management practices are followed. No prescribed ignition May 15 – Aug 15 (Migratory Birds Convention Act)."},
    {"key": "aar", "label": "After action report", "type": "textarea", "default": "On completion, a report shows completed burns, burns planned for next season and areas for improvement (Annex E)."},
    {"key": "daily_plan", "label": "Daily activity plan", "type": "textarea", "default": "The daily plan for each burn block, with its risk assessment, is in its burn plan (Annex D)."},
    {"key": "notification", "label": "RTA disruption notification", "type": "textarea", "default": "Range Control and PAO notify the user community, stakeholders and the public (Annex C)."},
    {"key": "bookings", "label": "RTA bookings", "type": "textarea", "default": "Prescribed fire is prioritized for RTA bookings (Annex B). Range Control manages daily conflicts."},
  ]},
  {"section": "Service support", "fields": [
    {"key": "dress", "label": "Dress", "type": "text", "default": "Wildland firefighting PPE"},
    {"key": "transport", "label": "Transport", "type": "text", "default": "By each organization; recovery requests to Range Control"},
    {"key": "rations", "label": "Rations", "type": "text", "default": "Field ration requests to Base Ops"},
    {"key": "financial", "label": "Financial", "type": "text", "default": "Overtime coordinated by Base Ops"},
    {"key": "medical", "label": "Medical", "type": "text", "default": "Treated on site; evacuation coordinated through Range Control"},
  ]},
  {"section": "Command and signals", "fields": [
    {"key": "pocs", "label": "Points of contact (from People)", "type": "auto", "source": "season_pocs", "tag": "people marked as a point of contact"},
    {"key": "comms", "label": "Communications plan", "type": "textarea"},
  ]},
  {"section": "Authorization", "fields": [
    {"key": "auth_name", "label": "Name", "type": "text"},
    {"key": "auth_rank", "label": "Rank", "type": "text"},
    {"key": "auth_appointment", "label": "Appointment", "type": "text", "default": "Base Commander"},
  ]},
  {"section": "Annexes", "fields": [
    {"key": "annexes", "label": "Annexes", "type": "table", "columns": [
        {"key": "annex", "label": "Annex", "type": "text", "w": "70px"}, {"key": "title", "label": "Title", "type": "text"}],
     "rows": [{"annex": "A", "title": "Map of the RTA and burn blocks"}, {"annex": "B", "title": "Burn parameters and planned burn locations"},
              {"annex": "C", "title": "Priorities and notifications"}, {"annex": "D", "title": "Burn plans / daily activity plans"}, {"annex": "E", "title": "After action report"}]},
  ]},
]

ROLES = [("burn_boss", "Burn boss", "RXB2"), ("firing_boss", "Firing boss", "FIRB"), ("holding_boss", "Holding boss", "HOLDING BOSS"),
         ("lookout", "Lookout", "LOOKOUT"), ("medic", "Medic / EMR", "EMT / MEDIC"), ("uxo_advisor", "UXO advisor (EOD)", "UXO ADVISOR"),
         ("range_control", "Range Control liaison", "RANGE CONTROL LIAISON"), ("agency_administrator", "Agency administrator", None),
         ("technical_reviewer", "Technical reviewer", None), ("preparer", "Plan preparer", None)]
