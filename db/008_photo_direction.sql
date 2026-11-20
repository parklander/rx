-- rx: which way each photo was taken (compass heading of the camera) and its field of view.
alter table field.media add column if not exists heading_deg numeric;     -- true/magnetic per device, 0 = north, clockwise
alter table field.media add column if not exists fov_deg numeric;         -- horizontal field of view
alter table field.media add column if not exists heading_source text;     -- compass | manual
