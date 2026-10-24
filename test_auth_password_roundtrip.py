"""Regression tests for Skillvaya's password hashing and verification.

Run with: python -m unittest test_auth_password_roundtrip.py
These tests use no production database and create no customer accounts.
"""
import hashlib
import unittest

import app as skillvaya


class PasswordRoundTripTests(unittest.TestCase):
    def test_new_password_hash_verifies_exact_password(self):
        password = "Ski11vaya-Test! 2026"
        stored = skillvaya.hashpw(password)
        self.assertTrue(stored.startswith("pbkdf2_sha256$"))
        self.assertTrue(skillvaya.verify_password(stored, password))

    def test_wrong_password_is_rejected(self):
        stored = skillvaya.hashpw("Correct-Horse-2026!")
        self.assertFalse(skillvaya.verify_password(stored, "Correct-Horse-2026?"))

    def test_case_and_spaces_are_preserved(self):
        password = " CaseSensitive Password "
        stored = skillvaya.hashpw(password)
        self.assertTrue(skillvaya.verify_password(stored, password))
        self.assertFalse(skillvaya.verify_password(stored, password.strip()))
        self.assertFalse(skillvaya.verify_password(stored, password.lower()))

    def test_legacy_sha256_password_hash_remains_compatible(self):
        password = "Legacy-Account-2026!"
        legacy_hash = hashlib.sha256(password.encode()).hexdigest()
        self.assertTrue(skillvaya.verify_password(legacy_hash, password))
        self.assertFalse(skillvaya.verify_password(legacy_hash, "not-the-password"))


if __name__ == "__main__":
    unittest.main()
