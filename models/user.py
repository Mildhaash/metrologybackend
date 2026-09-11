from pydantic import BaseModel, EmailStr
from typing import Optional

class UserRegister(BaseModel):
    name: str
    email: EmailStr
    password: str
    department: Optional[str] = None

class UserLogin(BaseModel):
    email: EmailStr
    password: str