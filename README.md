# Bitespeed Identity Reconciliation Service

A web service that identifies and consolidates customer contact information across multiple purchases.

## Live Endpoint

> **Base URL:** `https://<your-render-url>.onrender.com`
>
> **Identify endpoint:** `POST /identify`

*(Replace with your actual Render URL after deployment)*

## How It Works

Customers may use different email/phone combinations across orders. This service links contacts that share an email or phone number, maintaining a single primary identity with any number of secondary contacts.

**Key behaviors:**
- New contact info with no matches → creates a **primary** contact
- Incoming request shares email or phone with existing contact but has new info → creates a **secondary** contact linked to the primary
- Request links two previously separate primary contacts → the older one stays primary, the newer becomes secondary (along with all its secondaries)

## API

### `POST /identify`

**Request body (JSON):**
```json
{
  "email": "mcfly@hillvalley.edu",
  "phoneNumber": "123456"
}
```

Either field can be `null`, but at least one must be provided.

**Response:**
```json
{
  "contact": {
    "primaryContatctId": 1,
    "emails": ["lorraine@hillvalley.edu", "mcfly@hillvalley.edu"],
    "phoneNumbers": ["123456"],
    "secondaryContactIds": [23]
  }
}
```

## Tech Stack

- **Language:** Python 3.12
- **Framework:** Flask
- **Database:** SQLite
- **Server:** Gunicorn

## Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run the server (port 3000)
python3 app.py

# Run tests
python3 test_app.py
```

## Deployment (Render)

1. Push to GitHub
2. Create a new **Web Service** on [render.com](https://render.com)
3. Connect your repo
4. Render will auto-detect the `render.yaml` config
5. Set environment variable `DATABASE_PATH=/tmp/contacts.db`

Alternatively, use the Dockerfile for any container-based deployment.
