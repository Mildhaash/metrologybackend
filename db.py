# db.py

from dotenv import load_dotenv
load_dotenv()

from pymongo import MongoClient
import os

MONGODB_URI = os.getenv("MONGODB_URI")

client = None
db = None

if MONGODB_URI:
    client = MongoClient(MONGODB_URI)
    db = client["metrology"]
else:
    print("MONGODB_URI not set yet — database features will not work until you add it to .env")

def get_db():
    if db is None:
        raise RuntimeError("MongoDB is not connected. Add MONGODB_URI to your .env file.")
    return db


def require_db():
    """Get DB or raise a JSON HTTP error instead of an unhandled 500.

    Central helper so no route can crash with a bare RuntimeError traceback
    when MONGODB_URI is missing (no-DB demo mode). Read routes surface a
    clear 503 the frontend can display with a retry hint.
    """
    try:
        return get_db()
    except RuntimeError as e:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=503,
            detail=f"Database not connected: {e}. Add MONGODB_URI to backend/.env and restart the API.",
        )