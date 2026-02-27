"""
Bitespeed Identity Reconciliation Service

Tracks customer identity across multiple purchases by linking contacts
that share an email or phone number.
"""

import sqlite3
import os
from datetime import datetime, timezone
from flask import Flask, request, jsonify

app = Flask(__name__)


def get_db():
    """Get a database connection with row factory."""
    db_path = os.environ.get("DATABASE_PATH", "contacts.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Initialize the database schema."""
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS Contact (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            phoneNumber     TEXT,
            email           TEXT,
            linkedId        INTEGER REFERENCES Contact(id),
            linkPrecedence  TEXT CHECK(linkPrecedence IN ('primary', 'secondary')) NOT NULL,
            createdAt       TEXT NOT NULL,
            updatedAt       TEXT NOT NULL,
            deletedAt       TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_contact_email ON Contact(email) WHERE email IS NOT NULL")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_contact_phone ON Contact(phoneNumber) WHERE phoneNumber IS NOT NULL")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_contact_linked ON Contact(linkedId) WHERE linkedId IS NOT NULL")
    conn.commit()
    conn.close()


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f+00")


def find_contacts_by_email_or_phone(conn, email, phone):
    """Find all contacts matching the given email or phone."""
    conditions = []
    params = []
    if email:
        conditions.append("email = ?")
        params.append(email)
    if phone:
        conditions.append("phoneNumber = ?")
        params.append(phone)
    if not conditions:
        return []
    query = f"SELECT * FROM Contact WHERE deletedAt IS NULL AND ({' OR '.join(conditions)})"
    return conn.execute(query, params).fetchall()


def get_primary_contact(conn, contact):
    """Resolve to the primary contact for a given contact row."""
    if contact["linkPrecedence"] == "primary":
        return contact
    return conn.execute("SELECT * FROM Contact WHERE id = ?", (contact["linkedId"],)).fetchone()


def get_all_linked_contacts(conn, primary_id):
    """Get all secondary contacts linked to a primary contact."""
    return conn.execute(
        "SELECT * FROM Contact WHERE linkedId = ? AND deletedAt IS NULL ORDER BY createdAt",
        (primary_id,)
    ).fetchall()


def build_response(conn, primary_id):
    """Build the consolidated contact response."""
    primary = conn.execute("SELECT * FROM Contact WHERE id = ?", (primary_id,)).fetchone()
    secondaries = get_all_linked_contacts(conn, primary_id)

    emails = []
    phones = []
    secondary_ids = []

    # Primary first
    if primary["email"] and primary["email"] not in emails:
        emails.append(primary["email"])
    if primary["phoneNumber"] and primary["phoneNumber"] not in phones:
        phones.append(primary["phoneNumber"])

    # Then secondaries
    for sec in secondaries:
        if sec["email"] and sec["email"] not in emails:
            emails.append(sec["email"])
        if sec["phoneNumber"] and sec["phoneNumber"] not in phones:
            phones.append(sec["phoneNumber"])
        secondary_ids.append(sec["id"])

    return {
        "contact": {
            "primaryContatctId": primary["id"],
            "emails": emails,
            "phoneNumbers": phones,
            "secondaryContactIds": secondary_ids,
        }
    }


@app.route("/identify", methods=["POST"])
def identify():
    data = request.get_json(force=True)
    email = data.get("email")
    phone = data.get("phoneNumber")

    # Normalize phone to string if provided as number
    if phone is not None:
        phone = str(phone)

    # Both null/empty → bad request
    if not email and not phone:
        return jsonify({"error": "At least one of email or phoneNumber is required"}), 400

    conn = get_db()
    try:
        # Step 1: Find all matching contacts
        matched = find_contacts_by_email_or_phone(conn, email, phone)

        # Step 2: No matches → create new primary contact
        if not matched:
            ts = now_iso()
            cursor = conn.execute(
                "INSERT INTO Contact (phoneNumber, email, linkedId, linkPrecedence, createdAt, updatedAt) VALUES (?, ?, NULL, 'primary', ?, ?)",
                (phone, email, ts, ts),
            )
            conn.commit()
            return jsonify(build_response(conn, cursor.lastrowid)), 200

        # Step 3: Resolve all matched contacts to their primaries
        primary_ids = set()
        primaries = {}
        for c in matched:
            p = get_primary_contact(conn, c)
            primary_ids.add(p["id"])
            primaries[p["id"]] = p

        # Step 4: If two different primary groups are found, merge them
        if len(primary_ids) > 1:
            # The oldest primary wins
            sorted_primaries = sorted(primaries.values(), key=lambda x: x["createdAt"])
            winner = sorted_primaries[0]
            losers = sorted_primaries[1:]

            ts = now_iso()
            for loser in losers:
                # Turn the losing primary into a secondary of the winner
                conn.execute(
                    "UPDATE Contact SET linkedId = ?, linkPrecedence = 'secondary', updatedAt = ? WHERE id = ?",
                    (winner["id"], ts, loser["id"]),
                )
                # Re-link all of loser's secondaries to the winner
                conn.execute(
                    "UPDATE Contact SET linkedId = ?, updatedAt = ? WHERE linkedId = ?",
                    (winner["id"], ts, loser["id"]),
                )

            primary_id = winner["id"]
        else:
            primary_id = primary_ids.pop()

        # Step 5: Check if incoming request has new information → create secondary
        existing_emails = set()
        existing_phones = set()
        primary_row = conn.execute("SELECT * FROM Contact WHERE id = ?", (primary_id,)).fetchone()
        all_contacts = [primary_row] + list(get_all_linked_contacts(conn, primary_id))
        for c in all_contacts:
            if c["email"]:
                existing_emails.add(c["email"])
            if c["phoneNumber"]:
                existing_phones.add(c["phoneNumber"])

        has_new_email = email and email not in existing_emails
        has_new_phone = phone and phone not in existing_phones
        # Only create secondary if there's genuinely new info AND the request has both fields
        # (if only one field is provided and it already matches, no new contact needed)
        if has_new_email or has_new_phone:
            # But only if at least one field matched an existing contact (otherwise it wouldn't be linked)
            email_matched = email and email in existing_emails
            phone_matched = phone and phone in existing_phones
            if email_matched or phone_matched:
                ts = now_iso()
                conn.execute(
                    "INSERT INTO Contact (phoneNumber, email, linkedId, linkPrecedence, createdAt, updatedAt) VALUES (?, ?, ?, 'secondary', ?, ?)",
                    (phone, email, primary_id, ts, ts),
                )

        conn.commit()
        return jsonify(build_response(conn, primary_id)), 200

    finally:
        conn.close()


@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "Bitespeed Identity Reconciliation"})


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 3000))
    app.run(host="0.0.0.0", port=port, debug=False)
