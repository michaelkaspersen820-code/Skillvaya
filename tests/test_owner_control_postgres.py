"""PostgreSQL integration tests for Owner Control account access.

Runs only against the disposable PostgreSQL service provisioned by the CI workflow.
Never point this test module at production data.
"""
import os
import unittest
import uuid

if not os.environ.get("DATABASE_URL"):
    raise RuntimeError("DATABASE_URL is required; run this suite against the isolated PostgreSQL CI service.")

import app


class DummyServer:
    server_address = ("127.0.0.1", 18877)


class OwnerControlPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # CI provisions an empty, disposable PostgreSQL database for this job.
        app.init()

    def setUp(self):
        suffix = uuid.uuid4().hex
        self.emails = {
            "customer": f"owner-control-customer-{suffix}@example.invalid",
            "provider": f"owner-control-provider-{suffix}@example.invalid",
            "admin": f"owner-control-admin-{suffix}@example.invalid",
        }
        self.ids = {}
        with app.conn() as c:
            c.execute(
                "CREATE TABLE IF NOT EXISTS owner_account_access "
                "(user_id BIGINT PRIMARY KEY, original_role TEXT NOT NULL, suspended_at TEXT NOT NULL)"
            )
            for role, email in self.emails.items():
                row = c.execute(
                    "INSERT INTO users(name,email,password_hash,role,created_at) "
                    "VALUES(?,?,?,?,?) RETURNING id",
                    (f"Test {role}", email, "not-a-real-login-hash", role, app.now()),
                ).fetchone()
                self.ids[role] = row["id"]
            c.execute(
                "INSERT INTO payments(user_id,reference,plan,billing,amount,status,created_at) "
                "VALUES(?,?,?,?,?,?,?)",
                (self.ids["customer"], f"OWNER-TEST-{suffix}", "local", "monthly", 105, "verified", app.now()),
            )
            c.execute(
                "INSERT INTO auth_sessions(token,user_id,expires_at,created_at) VALUES(?,?,?,?)",
                (f"owner-test-session-{suffix}", self.ids["customer"], "2999-01-01T00:00:00+00:00", app.now()),
            )
            self.session_token = f"owner-test-session-{suffix}"

    def tearDown(self):
        with app.conn() as c:
            c.execute("DELETE FROM owner_account_access WHERE user_id IN (?,?,?)",
                      (self.ids["customer"], self.ids["provider"], self.ids["admin"]))
            c.execute("DELETE FROM auth_sessions WHERE user_id IN (?,?,?)",
                      (self.ids["customer"], self.ids["provider"], self.ids["admin"]))
            c.execute("DELETE FROM payments WHERE user_id IN (?,?,?)",
                      (self.ids["customer"], self.ids["provider"], self.ids["admin"]))
            c.execute("DELETE FROM users WHERE id IN (?,?,?)",
                      (self.ids["customer"], self.ids["provider"], self.ids["admin"]))

    def post_access(self, user_id, action):
        handler = app.Handler.__new__(app.Handler)
        handler.path = f"/api/admin/accounts/{user_id}/access"
        handler.client_address = ("127.0.0.1", 12345)
        handler.server = DummyServer()
        handler.body = lambda: {"action": action, "reason": "Automated regression test"}
        handler.user = lambda: {"id": self.ids["admin"], "role": "admin"}
        handler.sendj = lambda payload, status=200: (payload, status)
        return handler.do_POST()

    def test_suspend_revokes_sessions_and_restore_returns_original_role(self):
        payload, status = self.post_access(self.ids["customer"], "suspend")
        self.assertEqual(status, 200, payload)
        with app.conn() as c:
            user = c.execute("SELECT role FROM users WHERE id=?", (self.ids["customer"],)).fetchone()
            sessions = c.execute("SELECT count(*) AS n FROM auth_sessions WHERE token=?", (self.session_token,)).fetchone()["n"]
            record = c.execute("SELECT original_role FROM owner_account_access WHERE user_id=?", (self.ids["customer"],)).fetchone()
        self.assertEqual(user["role"], "suspended")
        self.assertEqual(sessions, 0)
        self.assertEqual(record["original_role"], "customer")

        payload, status = self.post_access(self.ids["customer"], "restore")
        self.assertEqual(status, 200, payload)
        with app.conn() as c:
            user = c.execute("SELECT role FROM users WHERE id=?", (self.ids["customer"],)).fetchone()
            record = c.execute("SELECT count(*) AS n FROM owner_account_access WHERE user_id=?", (self.ids["customer"],)).fetchone()["n"]
        self.assertEqual(user["role"], "customer")
        self.assertEqual(record, 0)

    def test_admin_is_protected(self):
        payload, status = self.post_access(self.ids["admin"], "suspend")
        self.assertEqual(status, 403)
        with app.conn() as c:
            role = c.execute("SELECT role FROM users WHERE id=?", (self.ids["admin"],)).fetchone()["role"]
        self.assertEqual(role, "admin")

    def test_unpaid_provider_is_rejected(self):
        payload, status = self.post_access(self.ids["provider"], "suspend")
        self.assertEqual(status, 400)
        with app.conn() as c:
            role = c.execute("SELECT role FROM users WHERE id=?", (self.ids["provider"],)).fetchone()["role"]
        self.assertEqual(role, "provider")

    def test_unknown_account_is_not_found(self):
        payload, status = self.post_access(9223372036854770000, "suspend")
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
