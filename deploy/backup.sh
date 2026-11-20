#!/usr/bin/env bash
# Nightly pg_dump of the rx database; keeps 14 days in /var/backups/rx.
set -euo pipefail
mkdir -p /var/backups/rx
sudo -u postgres pg_dump -Fc rx > /var/backups/rx/rx-$(date +%F).dump
find /var/backups/rx -name 'rx-*.dump' -mtime +14 -delete
