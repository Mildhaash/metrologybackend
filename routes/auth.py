# routes/auth.py

from fastapi import APIRouter, HTTPException, Depends, Header
from datetime import datetime
from bson import ObjectId

from db import require_db
from models.user import UserRegister, UserLogin
from auth_utils import hash_password, verify_password, create_access_token, decode_access_token

router = APIRouter(prefix="/api/auth", tags=["auth"])

def user_to_out(user) -> dict:
    return {
        "id": str(user["_id"]),
        "name": user["name"],
        "email": user["email"],
        "department": user.get("department"),
    }

@router.post("/register")
def register(data: UserRegister):
    db = require_db()
    if db.users.find_one({"email": data.email}):
        raise HTTPException(status_code=400, detail="Email already registered")

    now = datetime.utcnow()
    user_doc = {
        "name": data.name,
        "email": data.email,
        "password_hash": hash_password(data.password),
        "department": data.department,
        "created_at": now,
        "updated_at": now,
    }
    result = db.users.insert_one(user_doc)
    user_doc["_id"] = result.inserted_id

    token = create_access_token(str(user_doc["_id"]), user_doc["email"])
    return {"token": token, "user": user_to_out(user_doc)}

@router.post("/login")
def login(data: UserLogin):
    db = require_db()
    user = db.users.find_one({"email": data.email})
    if not user or not verify_password(data.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = create_access_token(str(user["_id"]), user["email"])
    return {"token": token, "user": user_to_out(user)}

def get_current_user(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authorization header")
    token = authorization.replace("Bearer ", "")
    try:
        payload = decode_access_token(token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    db = require_db()
    user = db.users.find_one({"_id": ObjectId(payload["sub"])})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.get("/me")
def me(current_user = Depends(get_current_user)):
    return {"user": user_to_out(current_user)}