#!/usr/bin/env bash
# Pull the latest code, apply new migrations, restart. Run as root on the droplet.
set -euo pipefail
APP=/opt/rx
sudo -u rx git -C "$APP" pull --ff-only
sudo -u rx "$APP/.venv/bin/pip" install -q -r "$APP/requirements.txt"
sudo -u rx bash -c "set -a; . /etc/rx.env; cd $APP && .venv/bin/python migrate.py"
install -m 755 "$APP/deploy/backup.sh" /etc/cron.daily/rx-backup
systemctl restart rx
