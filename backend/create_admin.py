"""
Script tạo tài khoản admin (role_id = 0) cho Project ITS.

Cách dùng:
    cd d:\Chuyen De He Thong Giao Thong Thong Minh\Project ITS\backend
    python create_admin.py

Hoặc ghi đè thông tin:
    python create_admin.py --username admin --email admin@its.vn --password MyP@ss123 --phone 0900000000
"""
import asyncio
import argparse
import sys
import os

# Đảm bảo import được các module của project
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "app"))

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy.future import select
from core.config import settings_server
from models.user import User
from core.security import hash_password


async def create_admin(username: str, email: str, password: str, phone: str):
    engine = create_async_engine(settings_server.DATABASE_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        # Kiểm tra đã tồn tại chưa
        result = await session.execute(select(User).where(User.email == email))
        existing = result.scalar_one_or_none()

        if existing:
            if existing.role_id == 0:
                print(f"[INFO] Tài khoản '{email}' đã là admin (id={existing.id}). Không cần tạo lại.")
            else:
                # Nâng cấp lên admin
                existing.role_id = 0
                await session.commit()
                print(f"[OK]   Đã nâng tài khoản '{email}' lên ADMIN (role_id=0).")
            await engine.dispose()
            return

        # Tạo mới
        admin_user = User(
            username=username,
            email=email,
            password=hash_password(password),
            phone_number=phone,
            role_id=0,          # 0 = admin
        )
        session.add(admin_user)
        await session.commit()
        await session.refresh(admin_user)
        print(f"[OK]   Đã tạo tài khoản ADMIN thành công!")
        print(f"       ID       : {admin_user.id}")
        print(f"       Username : {admin_user.username}")
        print(f"       Email    : {admin_user.email}")
        print(f"       Role     : ADMIN (role_id=0)")

    await engine.dispose()


def main():
    parser = argparse.ArgumentParser(description="Tạo tài khoản admin cho Project ITS")
    parser.add_argument("--username", default="admin",            help="Tên đăng nhập (default: admin)")
    parser.add_argument("--email",    default="admin@its.local",  help="Email (default: admin@its.local)")
    parser.add_argument("--password", default="Admin@123",        help="Mật khẩu (default: Admin@123)")
    parser.add_argument("--phone",    default="0900000001",       help="Số điện thoại (default: 0900000001)")
    args = parser.parse_args()

    print("=" * 50)
    print("  Project ITS — Tạo tài khoản Admin")
    print("=" * 50)
    print(f"  Username : {args.username}")
    print(f"  Email    : {args.email}")
    print(f"  Phone    : {args.phone}")
    print("=" * 50)

    asyncio.run(create_admin(args.username, args.email, args.password, args.phone))


if __name__ == "__main__":
    main()
