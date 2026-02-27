"""Tests for Bitespeed Identity Reconciliation Service."""

import json
import os
import sys
import tempfile
import unittest

# Use a temp database for each test
os.environ["DATABASE_PATH"] = ":memory:"

from app import app, init_db, get_db


class TestIdentify(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()
        # Reset DB for each test
        os.environ["DATABASE_PATH"] = tempfile.mktemp(suffix=".db")
        init_db()

    def tearDown(self):
        db_path = os.environ["DATABASE_PATH"]
        if os.path.exists(db_path):
            os.unlink(db_path)

    def post_identify(self, data):
        return self.client.post("/identify", json=data)

    # --- Test 1: New customer creates primary contact ---
    def test_new_customer(self):
        resp = self.post_identify({"email": "lorraine@hillvalley.edu", "phoneNumber": "123456"})
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        contact = body["contact"]
        self.assertEqual(contact["emails"], ["lorraine@hillvalley.edu"])
        self.assertEqual(contact["phoneNumbers"], ["123456"])
        self.assertEqual(contact["secondaryContactIds"], [])

    # --- Test 2: Existing email+phone match returns existing contact ---
    def test_exact_match(self):
        self.post_identify({"email": "lorraine@hillvalley.edu", "phoneNumber": "123456"})
        resp = self.post_identify({"email": "lorraine@hillvalley.edu", "phoneNumber": "123456"})
        body = resp.get_json()
        contact = body["contact"]
        self.assertEqual(len(contact["emails"]), 1)
        self.assertEqual(len(contact["phoneNumbers"]), 1)
        self.assertEqual(contact["secondaryContactIds"], [])

    # --- Test 3: Same phone, new email → creates secondary ---
    def test_secondary_creation(self):
        self.post_identify({"email": "lorraine@hillvalley.edu", "phoneNumber": "123456"})
        resp = self.post_identify({"email": "mcfly@hillvalley.edu", "phoneNumber": "123456"})
        body = resp.get_json()
        contact = body["contact"]
        self.assertEqual(contact["primaryContatctId"], 1)
        self.assertEqual(contact["emails"], ["lorraine@hillvalley.edu", "mcfly@hillvalley.edu"])
        self.assertEqual(contact["phoneNumbers"], ["123456"])
        self.assertEqual(len(contact["secondaryContactIds"]), 1)

    # --- Test 4: Query by phone only ---
    def test_query_phone_only(self):
        self.post_identify({"email": "lorraine@hillvalley.edu", "phoneNumber": "123456"})
        self.post_identify({"email": "mcfly@hillvalley.edu", "phoneNumber": "123456"})
        resp = self.post_identify({"phoneNumber": "123456"})
        body = resp.get_json()
        contact = body["contact"]
        self.assertEqual(contact["primaryContatctId"], 1)
        self.assertIn("lorraine@hillvalley.edu", contact["emails"])
        self.assertIn("mcfly@hillvalley.edu", contact["emails"])

    # --- Test 5: Query by email only ---
    def test_query_email_only(self):
        self.post_identify({"email": "lorraine@hillvalley.edu", "phoneNumber": "123456"})
        self.post_identify({"email": "mcfly@hillvalley.edu", "phoneNumber": "123456"})
        resp = self.post_identify({"email": "mcfly@hillvalley.edu"})
        body = resp.get_json()
        contact = body["contact"]
        self.assertEqual(contact["primaryContatctId"], 1)

    # --- Test 6: Two primaries get merged ---
    def test_primary_merge(self):
        # Create two separate primaries
        self.post_identify({"email": "george@hillvalley.edu", "phoneNumber": "919191"})
        self.post_identify({"email": "biffsucks@hillvalley.edu", "phoneNumber": "717171"})

        # Link them
        resp = self.post_identify({"email": "george@hillvalley.edu", "phoneNumber": "717171"})
        body = resp.get_json()
        contact = body["contact"]
        self.assertEqual(contact["primaryContatctId"], 1)
        self.assertIn("george@hillvalley.edu", contact["emails"])
        self.assertIn("biffsucks@hillvalley.edu", contact["emails"])
        self.assertIn("919191", contact["phoneNumbers"])
        self.assertIn("717171", contact["phoneNumbers"])
        self.assertIn(2, contact["secondaryContactIds"])

    # --- Test 7: Phone as number (not string) ---
    def test_phone_as_number(self):
        resp = self.post_identify({"email": "test@test.com", "phoneNumber": 12345})
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["contact"]["phoneNumbers"], ["12345"])

    # --- Test 8: Missing both fields ---
    def test_missing_both(self):
        resp = self.post_identify({})
        self.assertEqual(resp.status_code, 400)

    # --- Test 9: Null fields ---
    def test_null_fields(self):
        resp = self.post_identify({"email": None, "phoneNumber": None})
        self.assertEqual(resp.status_code, 400)

    # --- Test 10: Chain of secondaries after merge ---
    def test_chain_merge(self):
        # A: email=a@test.com, phone=111
        self.post_identify({"email": "a@test.com", "phoneNumber": "111"})
        # B: email=b@test.com, phone=222
        self.post_identify({"email": "b@test.com", "phoneNumber": "222"})
        # C: email=c@test.com, phone=111 → links to A
        self.post_identify({"email": "c@test.com", "phoneNumber": "111"})
        # Now link A and B: email=a@test.com, phone=222
        resp = self.post_identify({"email": "a@test.com", "phoneNumber": "222"})
        body = resp.get_json()
        contact = body["contact"]
        # A (id=1) should be primary
        self.assertEqual(contact["primaryContatctId"], 1)
        # All emails present
        for e in ["a@test.com", "b@test.com", "c@test.com"]:
            self.assertIn(e, contact["emails"])
        for p in ["111", "222"]:
            self.assertIn(p, contact["phoneNumbers"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
