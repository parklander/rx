# Generates 004_elements.sql from the PMS 484-1 (Dec 2021) element structure.
import json
E = [
 ("1","Signature Page","agency_admin","Names, qualifications and signatures of the preparer, technical reviewer and agency administrator. The complexity rating and minimum burn boss qualification come from Element 3.",
  [("admin_unit","Administrative unit(s)"),("burn_name","Prescribed fire name"),("ignition_unit","Prescribed fire unit (ignition unit)"),("complexity","Complexity rating"),("min_rxb","Minimum burn boss qualification"),("notes","Notes")]),
 ("2A","Agency Administrator Ignition Authorization","agency_admin","Completed before each ignition period. Discussion items A–H, the FMO/burn boss recommendation and authorized ignition dates.",
  [("changes","A. Changes since approval"),("compliance","B. Compliance"),("conditions","C. Ability to meet plan conditions"),("notifications","D. Notifications"),("briefing","E. Staff briefing"),("circumstances","F. Circumstances that could affect implementation"),("contingency_expect","G. Contingency notification expectations"),("wildfire_expect","H. Wildfire declaration expectations"),("recommendation","FMO / RXB implementation recommendation"),("dates","Authorized ignition dates")]),
 ("2B","Prescribed Fire Go/No-Go Checklist","burn_boss","Answered by the burn boss on each burn day. The answers are recorded on the burn day record; this element holds any unit-specific items.",
  [("preliminary","Preliminary questions (changed conditions, amendments)"),("items","Unit-specific go/no-go items"),("test_fire","Test fire decision")]),
 ("3","Complexity Analysis Summary and Final Complexity","planner","Summary and Final Complexity Worksheet (PMS 424-1), signed.",
  [("summary","Complexity summary"),("final","Final complexity rating and rationale")]),
 ("4","Description of Prescribed Fire Area","planner","Physical description, fuels, values and the maps. Much of this is filled from the database overlay.",
  [("physical","A. Physical description (location, size, topography, project area, ignition units)"),("fuels","B. Vegetation / fuels (on-site, adjacent, % by type, fuel models)"),("values","C. Unique features, natural resources and values"),("maps","D. Maps")]),
 ("5","Objectives","planner","Measurable resource objectives and prescribed fire objectives.",
  [("resource","Resource objectives"),("fire","Prescribed fire objectives")]),
 ("6","Funding","planner","Cost and funding source.",
  [("cost","Cost"),("source","Funding source")]),
 ("7","Prescription","planner","How the fire behaviour will meet the objectives, the environmental and fire behaviour parameters, and the modelling documentation.",
  [("narrative","A. Prescription narrative"),("parameters","B. Prescription parameters (also in the Prescription tab)"),("modeling","Fire behaviour modelling / empirical documentation")]),
 ("8","Scheduling","planner","Ignition time frames or season, projected duration, constraints (MBCA nesting period, training schedule).",
  [("schedule","Implementation schedule"),("duration","Projected duration"),("constraints","Constraints")]),
 ("9","Pre-burn Considerations and Weather","planner","On-site and off-site preparation, how and how often weather and smoke forecasts are obtained, notifications.",
  [("onsite","On-site considerations"),("offsite","Off-site considerations"),("weather","Weather and smoke forecasts: method and frequency"),("notifications","Notifications")]),
 ("10","Briefing","burn_boss","Briefing checklist.",
  [("checklist","Briefing checklist and notes")]),
 ("11","Organization and Equipment","burn_boss","Positions (PMS 310-1 qualifications), equipment and supplies.",
  [("positions","Positions"),("equipment","Equipment"),("supplies","Supplies")]),
 ("12","Communication","burn_boss","Command, tactical and air radio frequencies, telephone numbers.",
  [("radio","Radio frequencies"),("phones","Telephone numbers")]),
 ("13","Public and Personnel Safety, Medical","burn_boss","Hazards and mitigations (including UXO), emergency medical procedures, evacuation, facilities.",
  [("hazards","Safety hazards and mitigation"),("medical","Emergency medical procedures"),("evacuation","Evacuation methods"),("facilities","Emergency facilities")]),
 ("14","Test Fire","burn_boss","Planned location, on-site weather and results (results are recorded on the burn day).",
  [("location","Planned location"),("procedure","Procedure and acceptance criteria")]),
 ("15","Ignition Plan","burn_boss","Firing methods, sequences and patterns, devices, minimum ignition staffing. Variants by wind direction are in the Variants tab.",
  [("methods","Firing methods (techniques, sequence, patterns)"),("devices","Devices"),("staffing","Minimum ignition staffing")]),
 ("16","Holding Plan","burn_boss","General holding procedures, critical holding points and actions, minimum holding organization.",
  [("procedures","General procedures"),("critical_points","Critical holding points and actions"),("minimum","Minimum organization or capabilities")]),
 ("17","Contingency Plan","burn_boss","Management action points (MAPs), actions, minimum contingency resources and maximum response times. Trigger points are drawn on the map.",
  [("maps_points","Management action points"),("actions","Actions needed"),("resources","Minimum contingency resources and maximum response times")]),
 ("18","Wildfire Declaration","burn_boss","Who declares, IC assignment, notifications, extended attack actions.",
  [("who","Who declares"),("ic","IC assignment"),("notifications","Notifications"),("extended","Extended attack actions")]),
 ("19","Smoke Management and Air Quality","planner","Compliance, permits, smoke-sensitive receptors (from the database), impacted areas, mitigation.",
  [("compliance","Compliance and permits"),("receptors","Smoke-sensitive receptors"),("impacts","Potentially impacted areas"),("mitigation","Mitigation strategies")]),
 ("20","Monitoring","planner","Fuels, forecast and observed weather, fire behaviour, objective monitoring and smoke dispersal: how, when and by whom.",
  [("fuels","Fuels information"),("weather","Forecast and observed weather"),("behaviour","Fire behaviour"),("objectives","Monitoring to confirm objectives"),("smoke","Smoke dispersal")]),
 ("21","Post-burn Activities","planner","Post-burn report, rehab, file close-out, database updates (treatment record, new fuels version).",
  [("activities","Post-burn activities, owners and timeframes")]),
 ("A","Appendix A: Maps","planner","Vicinity and project maps required; fuels, values, smoke and fire behaviour maps optional.",[("maps","Map list")]),
 ("B","Appendix B: Technical Reviewer Checklist","planner","",[("checklist","Checklist")]),
 ("C","Appendix C: Complexity Analysis","planner","",[("analysis","Complexity analysis")]),
 ("D","Appendix D: Job Hazard Analysis / Risk Assessment","burn_boss","",[("jha","JHA / risk assessment")]),
 ("E","Appendix E: Fire Behaviour Modelling Documentation","planner","",[("modeling","Model runs and inputs")]),
 ("F","Appendix F: Smoke Management Plan (optional)","planner","",[("smoke","Smoke plan and modelling")]),
]
def q(s): return "'" + s.replace("'","''") + "'"
out=["-- generated by gen_elements.py","insert into plans.element_def (code, ord, title, owner_role, guidance, sections) values"]
rows=[]
for i,(c,t,o,g,s) in enumerate(E):
    secs=json.dumps([{"key":k,"label":l} for k,l in s])
    rows.append(f" ({q(c)}, {i+1}, {q(t)}, {q(o)}, {q(g)}, {q(secs)}::jsonb)")
out.append(",\n".join(rows)+";")
open('/home/claude/rx/db/004_elements.sql','w').write("\n".join(out)+"\n")
