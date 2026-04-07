"""Encrypt legacy plaintext phone numbers stored in the users table."""
from __future__ import annotations

import logging
from typing import Tuple

from sqlalchemy.orm import Session

from app import models
from app.database import SessionLocal

logger = logging.getLogger(__name__)


def _migrate_plaintext_phones(session: Session) -> Tuple[int, int]:
    """Return (examined_count, updated_count) for rows touched in a session."""
    examined = 0
    updated = 0

    users = session.query(models.User).filter(models.User.phone.isnot(None)).all()
    for user in users:
        plain = user.phone_plain
        if not plain:
            continue
        examined += 1
        if user.phone == plain:
            user.phone_plain = plain
            updated += 1

    return examined, updated


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s %(message)s")
    session = SessionLocal()
    try:
        examined, updated = _migrate_plaintext_phones(session)
        if updated:
            session.commit()
        else:
            session.rollback()
        logger.info("Processed %s phone entries; encrypted %s legacy rows", examined, updated)
    finally:
        session.close()


if __name__ == "__main__":
    main()

