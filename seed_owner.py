"""
Seed default owner user for the Owner App.
Creates a default user with known credentials for easy access.
"""
import os
import sys
import asyncio
from datetime import datetime, timezone

# Add agent-engine to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "agent-engine")))

from auth import create_user, Role
from db import init_db, async_session
from onboarding import OwnerCreate
from sqlalchemy import select

DEFAULT_EMAIL = "owner@whatsappagent.com"
DEFAULT_PASSWORD = "owner123"
DEFAULT_NAME = "Platform Owner"


async def seed_owner():
    """Create default owner user if not exists."""
    await init_db()
    
    # Check if user already exists
    from auth import User
    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.email == DEFAULT_EMAIL)
        )
        existing = result.scalar_one_or_none()
        
        if existing:
            print(f"[i] Owner user already exists: {DEFAULT_EMAIL}")
            print(f"    Email: {DEFAULT_EMAIL}")
            print(f"    Password: {DEFAULT_PASSWORD}")
            return
    
    # Create user
    try:
        user = await create_user(
            email=DEFAULT_EMAIL,
            password=DEFAULT_PASSWORD,
            full_name=DEFAULT_NAME,
            role=Role.CLIENT.value,
            client_id=1,
        )
        print(f"[v] Owner user created successfully!")
        print(f"    Email: {DEFAULT_EMAIL}")
        print(f"    Password: {DEFAULT_PASSWORD}")
        print(f"    Role: {user.role}")
        print(f"    User ID: {user.id}")
    except Exception as e:
        print(f"[ERROR] Failed to create owner user: {e}")
        return


if __name__ == "__main__":
    asyncio.run(seed_owner())
