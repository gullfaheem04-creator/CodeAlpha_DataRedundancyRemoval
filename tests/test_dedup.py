"""Run with:  python -m unittest tests/test_dedup.py -v"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import dedup  # noqa: E402


def rec(name="Ali Khan", email="ali@example.com", phone="03001234567", city="Karachi"):
    return {"name": name, "email": email, "phone": phone, "city": city}


class DedupTests(unittest.TestCase):
    def setUp(self):
        self.conn = dedup.connect(":memory:")

    def add(self, **kw):
        return dedup.process_record(self.conn, rec(**kw))

    def count(self):
        return self.conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]

    def test_first_record_is_unique(self):
        self.assertEqual(self.add()["decision"], "unique")
        self.assertEqual(self.count(), 1)

    def test_exact_duplicate_rejected(self):
        self.add()
        self.assertEqual(self.add()["decision"], "redundant")
        self.assertEqual(self.count(), 1)

    def test_formatting_variants_are_duplicates(self):
        self.add()
        r = self.add(name="ALI  KHAN", email="ALI@Example.com", phone="+92 300 1234567", city=" karachi ")
        self.assertEqual(r["decision"], "redundant")

    def test_reordered_name_is_duplicate(self):
        self.add()
        self.assertEqual(self.add(name="Khan Ali")["decision"], "redundant")

    def test_gmail_dots_and_plus_tags(self):
        self.add(email="bilal.raza@gmail.com")
        self.assertEqual(self.add(email="bilalraza+shop@gmail.com")["decision"], "redundant")

    def test_same_phone_similar_name_is_redundant(self):
        self.add()
        self.assertEqual(self.add(name="Ali Khann", email="other@example.com")["decision"], "redundant")

    def test_shared_phone_different_person_is_false_positive(self):
        self.add(name="Hina Malik", email="hina@example.com", phone="03451234567", city="Multan")
        r = self.add(name="Zain Malik", email="zain@example.com", phone="03451234567", city="Multan")
        self.assertEqual(r["decision"], "false_positive")
        self.assertEqual(self.count(), 2)

    def test_similar_name_different_identifiers_is_false_positive(self):
        self.add(name="Ayesha Noor", email="a1@example.com", phone="03007654321")
        r = self.add(name="Ayesha Nur", email="a2@example.com", phone="03337654322")
        self.assertEqual(r["decision"], "false_positive")

    def test_invalid_records_rejected(self):
        for bad in (rec(email="nope"), rec(name=""), rec(phone="12"), rec(name="12345")):
            self.assertEqual(dedup.process_record(self.conn, bad)["decision"], "invalid")
        self.assertEqual(self.count(), 0)

    def test_database_constraint_blocks_duplicates(self):
        self.add()
        with self.assertRaises(Exception):
            self.conn.execute(
                "INSERT INTO records (name,email,phone,city,name_key,email_norm,content_hash,created_at) "
                "VALUES ('x','x','','','x','ali@example.com','h','t')")

    def test_stats_and_audit_log(self):
        self.add()
        self.add()
        self.add(email="bad")
        s = dedup.stats(self.conn)
        self.assertEqual((s["submitted"], s["stored"], s["redundant"], s["invalid"]), (3, 1, 1, 1))
        self.assertEqual(len(dedup.list_audit(self.conn)), 3)


if __name__ == "__main__":
    unittest.main()
