"""Load fake identities from data/seed_identities.json into the database."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bot.db import get_session, init_db
from bot.models import FakeIdentity
from bot.services import fake_identity as fake_svc


def main() -> None:
    init_db()
    with get_session() as session:
        n = fake_svc.seed_from_json(session)
        total = session.query(FakeIdentity).count()
        if n == 0 and total == 0:
            print("No identities loaded. Check data/seed_identities.json")
        elif n:
            print(f"Seeded {n} identities. Total now: {total}")
        else:
            print(f"Pool already has {total} identities (skip seed).")


if __name__ == "__main__":
    main()
