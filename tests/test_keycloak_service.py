import unittest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app import models
from app.config import settings
from app.services.keycloak_service import KeycloakSyncService


class _DummyAdmin:
    def __init__(self, users, groups=None):
        self._users = users
        self._groups = groups or {}

    def get_users(self, _params):
        return self._users

    def get_user_groups(self, user_id):
        return self._groups.get(user_id, [])


class KeycloakSyncServiceTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.session = self.Session()
        self.prev_enabled = settings.KEYCLOAK_ENABLED
        settings.KEYCLOAK_ENABLED = True

    def tearDown(self):
        self.session.close()
        Base.metadata.drop_all(self.engine)
        settings.KEYCLOAK_ENABLED = self.prev_enabled

    def test_sync_creates_and_updates_users(self):
        dummy_admin = _DummyAdmin(
            users=[
                {
                    "id": "kc-1",
                    "username": "alice",
                    "email": "alice@example.com",
                    "firstName": "Alice",
                    "lastName": "Doe",
                    "enabled": True,
                    "attributes": {"team": ["SRE"], "phoneNumber": ["13800000000"]},
                },
                {
                    "id": "kc-2",
                    "username": "bob",
                    "email": "bob@example.com",
                    "firstName": "Bob",
                    "lastName": "Lee",
                    "enabled": False,
                    "attributes": {},
                },
            ],
            groups={
                "kc-1": [{"name": "oncall-admins"}],
                "kc-2": [{"name": "operators"}],
            },
        )

        service = KeycloakSyncService(self.session, admin_client=dummy_admin)
        stats = service.sync_users()

        self.assertEqual(stats["created"], 2)
        alice = self.session.query(models.User).filter_by(username="alice").first()
        self.assertEqual(alice.role, "admin")
        self.assertEqual(alice.keycloak_groups, ["oncall-admins"])
        self.assertTrue(alice.is_active)
        self.assertEqual(alice.phone_plain, "13800000000")

        bob = self.session.query(models.User).filter_by(username="bob").first()
        self.assertFalse(bob.is_active)

        # run again to ensure updates don't duplicate
        stats = service.sync_users()
        self.assertEqual(stats["updated"], 2)

    def test_missing_users_can_be_disabled(self):
        existing = models.User(
            username="ghost",
            email="ghost@example.com",
            full_name="Ghost",
            hashed_password="test",
            keycloak_id="old-id",
            is_active=True,
        )
        self.session.add(existing)
        self.session.commit()

        dummy_admin = _DummyAdmin(users=[])
        service = KeycloakSyncService(self.session, admin_client=dummy_admin)
        stats = service.sync_users()

        self.assertEqual(stats["deactivated"], 1)
        refreshed = self.session.query(models.User).filter_by(username="ghost").first()
        self.assertFalse(refreshed.is_active)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

