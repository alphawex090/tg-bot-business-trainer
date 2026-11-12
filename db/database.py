from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy import select, func
from db.models import Base, User, Application
from datetime import datetime, timezone

engine = create_async_engine("sqlite+aiosqlite:///bot.db", echo=False)
Session = async_sessionmaker(engine, expire_on_commit=False)


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def add_user(user_id: int, username: str | None):
    async with Session() as session:
        user = await session.get(User, user_id)
        if not user:
            session.add(User(id=user_id, username=username))
            await session.commit()


async def save_application(user_id: int, name: str, phone: str, request_text: str) -> int:
    async with Session() as session:
        app = Application(
            user_id=user_id,
            name=name,
            phone=phone,
            request_text=request_text,
        )
        session.add(app)
        await session.commit()
        return app.id


async def get_last_applications(limit: int = 5) -> list[Application]:
    async with Session() as session:
        result = await session.execute(
            select(Application).order_by(Application.created_at.desc()).limit(limit)
        )
        return list(result.scalars().all())


async def get_stats() -> dict:
    async with Session() as session:
        total = (await session.execute(select(func.count(Application.id)))).scalar_one()
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        today_count = (
            await session.execute(
                select(func.count(Application.id)).where(Application.created_at >= today)
            )
        ).scalar_one()
        return {"total": total, "today": today_count}


async def get_all_user_ids() -> list[int]:
    async with Session() as session:
        result = await session.execute(select(User.id))
        return list(result.scalars().all())


async def remove_user(user_id: int):
    async with Session() as session:
        user = await session.get(User, user_id)
        if user:
            await session.delete(user)
            await session.commit()


async def get_all_applications() -> list[Application]:
    """Достает абсолютно все заявки из базы для экспорта."""
    async with Session() as session:
        result = await session.execute(
            select(Application).order_by(Application.created_at.desc())
        )
        return list(result.scalars().all())