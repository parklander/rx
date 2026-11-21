#!/usr/bin/env bash
# One-time setup of rx on an Ubuntu 24.04 droplet. Safe to run on the droplet that already serves fwx:
# it adds its own service, database and Caddy site and leaves fwx alone. Run as root:
#   bash setup.sh <git-repo-url> rx.rtams.ca
set -euo pipefail
REPO=${1:?usage: bash setup.sh <git-repo-url> <domain>}
DOMAIN=${2:?usage: bash setup.sh <git-repo-url> <domain>}
APP=/opt/rx

apt-get update
apt-get install -y python3-venv git rsync postgresql postgis postgresql-16-postgis-3 debian-keyring debian-archive-keyring apt-transport-https curl gnupg
if ! command -v caddy >/dev/null; then
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/gpg.key | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update && apt-get install -y caddy
fi
command -v ufw >/dev/null && { ufw allow OpenSSH; ufw allow 80,443/tcp; ufw --force enable; } || true

# Database: local only, password kept in /etc/rx.env (not in git)
if [ ! -f /etc/rx.env ]; then
  PW=$(openssl rand -hex 24)
  sudo -u postgres psql -v ON_ERROR_STOP=1 -c "create role rx login password '$PW'" -c "create database rx owner rx"
  sudo -u postgres psql -d rx -c "create extension if not exists postgis; create extension if not exists pgcrypto;"
  printf 'RX_DATABASE_URL=postgresql://rx:%s@localhost/rx\nRX_TZ=America/Winnipeg\n' "$PW" > /etc/rx.env
  chmod 600 /etc/rx.env
fi

id -u rx >/dev/null 2>&1 || useradd --system --create-home --home-dir /var/lib/rx --shell /usr/sbin/nologin rx
[ -d "$APP/.git" ] || git clone "$REPO" "$APP"
chown -R rx:rx "$APP"
sudo -u rx python3 -m venv "$APP/.venv"
sudo -u rx "$APP/.venv/bin/pip" install -q -r "$APP/requirements.txt"
chown root:rx /etc/rx.env && chmod 640 /etc/rx.env
sudo -u rx bash -c "set -a; . /etc/rx.env; cd $APP && .venv/bin/python migrate.py"

install -m 644 "$APP/deploy/rx.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now rx

# Caddy: add a site block for this domain if it isn't there yet (keeps fwx's block)
touch /etc/caddy/Caddyfile
if ! grep -q "^$DOMAIN " /etc/caddy/Caddyfile; then
  printf '\n%s {\n\tencode zstd gzip\n\treverse_proxy 127.0.0.1:8100\n}\n' "$DOMAIN" >> /etc/caddy/Caddyfile
fi
systemctl reload caddy || systemctl restart caddy

# Nightly database backup, 14 days kept
install -m 755 "$APP/deploy/backup.sh" /etc/cron.daily/rx-backup

# Weekly check of ECCC critical habitat (loads only when ECCC has published a new version)
install -d -o rx -g rx /var/lib/rx/sources
install -m 644 "$APP/deploy/rx-habitat-sync.service" "$APP/deploy/rx-habitat-sync.timer" "$APP/deploy/rx-dem-sync.service" "$APP/deploy/rx-dem-sync.timer" /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now rx-habitat-sync.timer rx-dem-sync.timer

echo
echo "Done: https://$DOMAIN"
echo "Next: create your first user:"
echo "  sudo -u rx bash -c 'set -a; . /etc/rx.env; cd $APP && .venv/bin/python manage.py create-user <username> admin \"Your Name\"'"
echo "Optional demo data: same command with 'manage.py seed-demo'"
