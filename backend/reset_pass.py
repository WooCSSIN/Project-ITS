import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "app"))

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy.future import select
from core.config import settings_server
from models.chat_message import ChatMessage
from models.user import User

async def reset_pass():
    engine = create_async_engine(settings_server.DATABASE_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == 3))
        user = result.scalar_one_or_none()
        if user:
            # Hash cho "Admin@123"
            user.password = "$2b$12$IQN4BT3zKop0KV89zZME4uv.FzDy9JuYYun2aogQXXD6SzFFtavUK"
            await session.commit()
            print("Reset password success!")
        else:
            print("User not found!")
    
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(reset_pass())
