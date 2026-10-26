import io
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramRetryAfter
from PIL import Image
from sqlalchemy import select

from fczhk.models import PostImage, Publication
from fczhk.worker import deliver_one, mark_stale, publication_parts
from tests.test_prepared_collections import clock as clock
from tests.test_prepared_collections import prepare


def picture(color="red", format="PNG", size=(40, 30)):
    stream = io.BytesIO()
    Image.new("RGB", size, color).save(stream, format=format)
    return stream.getvalue()


def upload(env, m, data, role="admin", expected=200, version=None):
    response = env[2].put(
        f"/api/matches/{m['id']}/collection-image?version={version or m['version']}",
        content=data,
        headers={"Authorization": f"Bearer {env[3][role]}", "Content-Type": "image/png"},
    )
    assert response.status_code == expected, response.text
    return response


def test_upload_replace_remove_are_private_and_publication_keeps_original(env, call, clock):
    m = prepare(call)
    first = picture()
    info = upload(env, m, first).json()["image"]
    assert (info["mime_type"], info["width"], info["height"]) == ("image/png", 40, 30)
    m = call("GET", f"/matches/{m['id']}")
    assert m["collection_image"]["id"] == info["id"]
    image_url = f"/matches/{m['id']}/collection-image"
    response = env[2].get(
        "/api" + image_url, headers={"Authorization": f"Bearer {env[3]['admin']}"}
    )
    assert response.content == first and response.headers["content-type"] == "image/png"
    assert response.headers["cache-control"] == "no-store"
    call("GET", image_url, role="player", expected=403)
    upload(env, m, first, role="player", expected=403)
    upload(env, m, b"<svg/>", expected=400)
    upload(env, m, picture("blue"), version=m["version"] - 1, expected=409)
    # An identical upload is idempotent and consumes no additional media row.
    upload(env, m, first)
    assert call("GET", f"/matches/{m['id']}")["version"] == m["version"]
    with env[1]() as db:
        assert len(list(db.scalars(select(PostImage)))) == 1
        assert not list(db.scalars(select(Publication)))
    m = call("POST", f"/matches/{m['id']}/actions/open", {"version": m["version"]})
    with env[1]() as db:
        pub = db.scalar(
            select(Publication).where(
                Publication.match_id == m["id"], Publication.kind == "collection"
            )
        )
        assert pub.image_id == info["id"]
        pub_id = pub.id
    upload(env, m, picture("blue"), expected=409)
    call("DELETE", image_url, {"version": m["version"]}, expected=409)
    m = call(
        "POST",
        f"/matches/{m['id']}/cancel",
        {"version": m["version"], "reason": "Закрыть ранний сбор", "advance_schedule": False},
    )
    upload(env, m, picture("blue"))
    m = call("GET", f"/matches/{m['id']}")
    assert m["collection_image"]["id"] != info["id"]
    with env[1]() as db:
        assert db.get(Publication, pub_id).image_id == info["id"]
        assert db.get(PostImage, info["id"]).content == first
    call("DELETE", image_url, {"version": m["version"]})
    assert call("GET", f"/matches/{m['id']}")["collection_image"] is None
    call("GET", image_url, expected=404)


@pytest.mark.parametrize(
    "content", [b"", b"not an image", picture(format="GIF"), picture(size=(200, 1))]
)
def test_invalid_images_do_not_modify_game(env, call, clock, content):
    m = prepare(call)
    upload(env, m, content, expected=413 if not content else 400)
    assert call("GET", f"/matches/{m['id']}")["version"] == m["version"]
    with env[1]() as db:
        assert not list(db.scalars(select(PostImage)))


def test_oversized_image_is_rejected_before_body_is_read(env, call, clock):
    m = prepare(call)
    response = env[2].put(
        f"/api/matches/{m['id']}/collection-image?version={m['version']}",
        content=b"x",
        headers={"Authorization": f"Bearer {env[3]['admin']}", "Content-Length": "10000001"},
    )
    assert response.status_code == 413
    assert call("GET", f"/matches/{m['id']}")["collection_image"] is None


def test_jpeg_is_recognized_by_content_even_with_generic_content_type(env, call, clock):
    m = prepare(call)
    data = picture(format="JPEG")
    response = env[2].put(
        f"/api/matches/{m['id']}/collection-image?version={m['version']}",
        content=data,
        headers={
            "Authorization": f"Bearer {env[3]['admin']}",
            "Content-Type": "application/octet-stream",
        },
    )
    assert response.status_code == 200
    assert response.json()["image"]["mime_type"] == "image/jpeg"


async def test_worker_sends_photo_with_caption_and_marks_caption_stale(env, call, clock):
    m = prepare(call)
    photo = picture()
    upload(env, m, photo)
    m = call("GET", f"/matches/{m['id']}")
    m = call("POST", f"/matches/{m['id']}/actions/open", {"version": m["version"]})
    with env[1]() as db, db.begin():
        pub = db.scalar(select(Publication).where(Publication.match_id == m["id"]))
        pub.chat_id = "123"
        pid = pub.id
    bot = SimpleNamespace(
        send_photo=AsyncMock(return_value=SimpleNamespace(message_id=77)),
        send_message=AsyncMock(),
        edit_message_caption=AsyncMock(),
        edit_message_text=AsyncMock(),
    )
    assert await deliver_one(env[0], env[1], bot)
    assert not await deliver_one(env[0], env[1], bot)
    bot.send_photo.assert_awaited_once()
    bot.send_message.assert_not_awaited()
    args = bot.send_photo.await_args
    assert args.args[1].data == photo and "Открыта запись" in args.kwargs["caption"]
    assert args.kwargs["reply_markup"].inline_keyboard[0][0].text == "Открыть игру"
    with env[1]() as db, db.begin():
        pub = db.get(Publication, pid)
        pub.stale = True
        assert pub.message_ids == [77]
    await mark_stale(env[0], env[1], bot)
    bot.edit_message_caption.assert_awaited_once()
    bot.edit_message_text.assert_not_awaited()
    assert "НЕАКТУАЛЬНО" in bot.edit_message_caption.await_args.kwargs["caption"]
    assert (
        len(bot.edit_message_caption.await_args.kwargs["caption"].encode("utf-16-le")) // 2 <= 1024
    )


async def test_photo_acknowledgement_survives_retry_of_long_text_continuation(env, call, clock):
    m = prepare(call)
    upload(env, m, picture())
    m = call("GET", f"/matches/{m['id']}")
    m = call("POST", f"/matches/{m['id']}/actions/open", {"version": m["version"]})
    with env[1]() as db, db.begin():
        pub = db.scalar(select(Publication).where(Publication.match_id == m["id"]))
        pub.chat_id = "123"
        pub.text = "⚽" * 2000 + "\nВесь текст должен сохраниться"
        pid = pub.id
    retry = TelegramRetryAfter(method=SimpleNamespace(), message="retry", retry_after=0)
    bot = SimpleNamespace(
        send_photo=AsyncMock(return_value=SimpleNamespace(message_id=10)),
        send_message=AsyncMock(side_effect=retry),
    )
    assert await deliver_one(env[0], env[1], bot)
    with env[1]() as db, db.begin():
        pub = db.get(Publication, pid)
        assert pub.status == "pending" and pub.message_ids == [10]
        pub.next_attempt_at = clock[0]
    # Worker uses its real clock; make the retained retry immediately due.
    from fczhk.db import now

    with env[1]() as db, db.begin():
        db.get(Publication, pid).next_attempt_at = now()
    bot.send_message = AsyncMock(return_value=SimpleNamespace(message_id=11))
    assert await deliver_one(env[0], env[1], bot)
    bot.send_photo.assert_awaited_once()
    with env[1]() as db:
        pub = db.get(Publication, pid)
        assert pub.status == "sent" and len(pub.message_ids) == len(
            publication_parts(pub.kind, pub.text, photo=True)
        )
