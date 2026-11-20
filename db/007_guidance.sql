-- rx: element guidance now that parameters and variants are edited inside their elements.
update plans.element_def set guidance = 'How the fire behaviour will meet the objectives, the prescription parameters checked on burn days, and the expected fire behaviour from modelling or test fires.' where code = '7';
update plans.element_def set guidance = 'Firing techniques, the firing sequence for each wind direction (ignition variants), devices and minimum ignition staffing.' where code = '15';
update plans.element_def set guidance = 'Management action points tied to the trigger points on the map, the actions they set off, and the minimum contingency resources with their response times.' where code = '17';
