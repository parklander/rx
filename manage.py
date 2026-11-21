"""Admin commands.

    python manage.py create-user <username> <role> "<Display Name>"   (prompts for the password)
    python manage.py migrate
    python manage.py seed-demo
    python manage.py sync-habitat [--force] [--file CriticalHabitat.zip] [--dry-run]
    python manage.py sync-dem [--force] [--dry-run]
"""
import getpass
import sys

import auth
import db


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd = sys.argv[1]
    if cmd == "migrate":
        import migrate
        migrate.migrate()
    elif cmd == "seed-demo":
        import seed_demo
        seed_demo.seed()
    elif cmd == "sync-habitat":
        import habitat_sync
        habitat_sync.main(sys.argv[2:])
    elif cmd == "sync-dem":
        import dem_sync
        dem_sync.main(sys.argv[2:])
    elif cmd == "create-user":
        username, role, name = sys.argv[2], sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else sys.argv[2]
        pw = getpass.getpass("Password: ") if sys.stdin.isatty() else sys.stdin.readline().strip()
        db.open_pool()
        auth.create_user(username, name, role, pw)
        db.pool.close()
        print("user", username, "saved with role", role)
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
