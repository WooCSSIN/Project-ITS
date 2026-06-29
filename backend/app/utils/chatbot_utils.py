from langchain_core.messages.utils import (
    trim_messages,
    count_tokens_approximately
)
from models.chat_message import ChatMessage
from sqlalchemy.ext.asyncio import AsyncSession

MAX_PRIVATE_IMAGES_PER_THREAD = 8
_chat_private_images: dict[str, list[str]] = {}

def _normalize_thread_id(thread_id: str | int | None) -> str:
    if thread_id is None:
        return "anonymous"
    return str(thread_id)


def clear_private_images(thread_id: str | int | None) -> None:
    key = _normalize_thread_id(thread_id)
    _chat_private_images.pop(key, None)

def append_private_image(thread_id: str | int | None, image_url: str) -> None:
    key = _normalize_thread_id(thread_id)
    images = _chat_private_images.setdefault(key, [])
    images.append(image_url)
    if len(images) > MAX_PRIVATE_IMAGES_PER_THREAD:
        del images[:-MAX_PRIVATE_IMAGES_PER_THREAD]


def pop_private_images(thread_id: str | int | None) -> list[str]:
    key = _normalize_thread_id(thread_id)
    return _chat_private_images.pop(key, [])


async def save_user_message(
    db: AsyncSession,
    user_id: int,
    message: str,
    channel: str,
):
    """Lưu tin nhắn user ngay khi nhận được, TRƯỚC khi gọi AI."""
    db.add(
        ChatMessage(
            user_id=user_id,
            message=message,
            is_user=True,
            images=None,
            extra_data={"channel": channel},
        )
    )
    await db.commit()


async def save_ai_response(
    db: AsyncSession,
    user_id: int,
    message: str,
    images: list[str] | None,
    channel: str,
):
    """Lưu tin nhắn AI response sau khi AI trả lời xong."""
    extra_data = {"channel": channel}
    if images:
        extra_data["image_source"] = "minio-url"

    db.add(
        ChatMessage(
            user_id=user_id,
            message=message,
            is_user=False,
            images=images or None,
            extra_data=extra_data,
        )
    )
    await db.commit()
