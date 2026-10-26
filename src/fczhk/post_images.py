"""Private, bounded uploads; bytes are shared by immutable publication snapshots."""

import hashlib
import io
import warnings

from PIL import Image, UnidentifiedImageError
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from .models import PostImage
from .services import DomainError, audit, get_match

MAX_BYTES = 10_000_000


def validate(content: bytes):
    if not content or len(content) > MAX_BYTES:
        raise DomainError("Выберите JPG или PNG размером до 10 МБ", 413)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as image:
                fmt, (width, height) = image.format, image.size
                if fmt not in ("JPEG", "PNG") or getattr(image, "is_animated", False):
                    raise DomainError("Поддерживаются обычные JPG и PNG без анимации")
                if width + height > 10000 or max(width, height) > min(width, height) * 20:
                    raise DomainError(
                        "Картинка слишком большая или вытянутая для Telegram. Выберите другой размер."
                    )
                image.verify()
    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        SyntaxError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise DomainError("Не удалось прочитать картинку. Выберите исправный JPG или PNG.") from exc
    return dict(
        id=hashlib.sha256(content).hexdigest(),
        mime_type="image/jpeg" if fmt == "JPEG" else "image/png",
        size=len(content),
        width=width,
        height=height,
    )


def metadata(db, image_id):
    image = db.get(PostImage, image_id) if image_id else None
    return (
        {key: getattr(image, key) for key in ("id", "mime_type", "size", "width", "height")}
        if image
        else None
    )


def save(factory, actor, match_id, version, content, info):
    with factory() as db, db.begin():
        match = get_match(db, match_id, version, lock=True)
        if match.status != "draft":
            raise DomainError("Картинку можно изменить до открытия сбора", 409)
        old = match.collection_image_id
        if old == info["id"]:
            return metadata(db, old)
        insert = pg_insert if db.bind.dialect.name == "postgresql" else sqlite_insert
        db.execute(
            insert(PostImage)
            .values(**info, content=content, created_by=actor)
            .on_conflict_do_nothing(index_elements=[PostImage.id])
        )
        match.collection_image_id = info["id"]
        match.version += 1
        audit(
            db,
            actor,
            "collection.image_changed",
            match.id,
            old_image_id=old,
            image_id=info["id"],
            size=info["size"],
        )
        db.flush()
        return metadata(db, info["id"])


def remove(db, actor, match_id, version):
    match = get_match(db, match_id, version, lock=True)
    if match.status != "draft":
        raise DomainError("Картинку можно убрать до открытия сбора", 409)
    if match.collection_image_id:
        old = match.collection_image_id
        match.collection_image_id = None
        match.version += 1
        audit(db, actor, "collection.image_removed", match.id, image_id=old)


def content(db, match_id):
    match = get_match(db, match_id)
    if not match.collection_image_id:
        raise DomainError("Картинка не выбрана", 404)
    image = db.get(PostImage, match.collection_image_id)
    return image.content, image.mime_type
