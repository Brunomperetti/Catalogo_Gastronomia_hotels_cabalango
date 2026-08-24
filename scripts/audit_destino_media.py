"""Read-only destination-media filesystem audit (run from the repository root)."""

import json

from app.database import SessionLocal
from app.main import audit_destination_media, ensure_destino_media_table


def main() -> None:
    ensure_destino_media_table()
    with SessionLocal() as db:
        print(json.dumps(audit_destination_media(db, "home_hero"), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
