#!/usr/bin/env bash
# Nightly backup: pg_dump of the rx database (14 days kept) and a copy of the field photos.
set -euo pipefail
mkdir -p /var/backups/rx
sudo -u postgres pg_dump -Fc rx > /var/backups/rx/rx-$(date +%F).dump
find /var/backups/rx -name 'rx-*.dump' -mtime +14 -delete
[ -d /opt/rx/media ] && rsync -a /opt/rx/media/ /var/backups/rx/media/ || true
