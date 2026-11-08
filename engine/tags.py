"""Per-account tags and deterministic suggestions learned from monitored titles."""
import re
import unicodedata
from collections import Counter
from typing import Sequence

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from data.models import Monitoring, MonitoringTag, Product, Tag, User
from engine.auth import current_user, get_db

router = APIRouter(prefix="/tags", tags=["tags"])

# Avoid learning from terms that occur in many unrelated product titles.
STOP_WORDS = {
    "com", "para", "por", "sem", "de", "do", "da", "dos", "das", "em",
    "e", "the", "and", "for", "with", "black", "white", "preto", "branco",
    "novo", "nova", "original", "modelo", "produto", "kit", "und", "unidade",
}
MAX_TAGS = 12
MAX_TAG_LENGTH = 40


def fold(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(character for character in decomposed if not unicodedata.combining(character)).casefold()


def normalize_tag(value: str) -> tuple[str, str]:
    if not isinstance(value, str):
        raise ValueError("Tag must be a string")
    name = " ".join(value.split())
    if len(name) < 2 or len(name) > MAX_TAG_LENGTH or not any(char.isalnum() for char in name):
        raise ValueError("Tags must contain 2 to 40 characters and at least one letter or number")
    if any(ord(char) < 32 for char in name):
        raise ValueError("Tag contains unsupported control characters")
    return name, fold(name)


def validate_tag_names(names: Sequence[str]) -> list[tuple[str, str]]:
    if len(names) > MAX_TAGS:
        raise ValueError(f"A product supports up to {MAX_TAGS} tags")
    distinct = {}
    for raw in names:
        name, key = normalize_tag(raw)
        distinct.setdefault(key, (name, key))
    return list(distinct.values())


def set_monitoring_tags(db: Session, user_id: int, monitoring_id: int, names: Sequence[str]):
    requested = validate_tag_names(names)
    # Removing the links must not delete the user's catalog of reusable tags.
    db.query(MonitoringTag).filter(MonitoringTag.monitoring_id == monitoring_id).delete(synchronize_session=False)
    if not requested:
        return
    keys = [key for _, key in requested]
    tags = {tag.normalized_name: tag for tag in db.query(Tag).filter(
        Tag.user_id == user_id, Tag.normalized_name.in_(keys)).all()}
    for name, key in requested:
        if key not in tags:
            tag = Tag(user_id=user_id, name=name, normalized_name=key)
            db.add(tag)
            db.flush()
            tags[key] = tag
        db.add(MonitoringTag(monitoring_id=monitoring_id, tag_id=tags[key].id))


def tags_by_monitoring(db: Session, user_id: int, monitoring_ids: Sequence[int]) -> dict[int, list[str]]:
    if not monitoring_ids:
        return {}
    rows = (db.query(MonitoringTag.monitoring_id, Tag.name)
            .join(Tag, Tag.id == MonitoringTag.tag_id)
            .filter(Tag.user_id == user_id, MonitoringTag.monitoring_id.in_(monitoring_ids))
            .order_by(Tag.name).all())
    result: dict[int, list[str]] = {}
    for monitoring_id, name in rows:
        result.setdefault(monitoring_id, []).append(name)
    return result


def title_tokens(title: str) -> set[str]:
    words = set(re.findall(r"[a-z0-9]+", fold(title)))
    return {word for word in words if len(word) >= 3 and not word.isdigit() and word not in STOP_WORDS}


def suggested_tags(db: Session, user_id: int, name: str) -> list[str]:
    target = title_tokens(name)
    if not target:
        return []
    rows = (db.query(Monitoring.id, Product.name)
            .join(Product, Monitoring.product_id == Product.id)
            .filter(Monitoring.user_id == user_id).all())
    comparable = [(id_, title) for id_, title in rows if target.intersection(title_tokens(title))]
    if len(comparable) < 2:
        return []
    labels = tags_by_monitoring(db, user_id, [id_ for id_, _ in comparable])
    votes = Counter(tag for id_, _ in comparable for tag in labels.get(id_, []))
    threshold = max(2, (len(comparable) + 1) // 2)
    return sorted((tag for tag, count in votes.items() if count >= threshold), key=str.casefold)


@router.get("")
def list_tags(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return [tag.name for tag in db.query(Tag).filter(Tag.user_id == user.id).order_by(Tag.name).all()]


@router.get("/suggest")
def suggest_tags(name: str = Query(..., min_length=2, max_length=255),
                 db: Session = Depends(get_db), user: User = Depends(current_user)):
    return {"tags": list_tags(db, user), "recommended": suggested_tags(db, user.id, name)}


def validated_tags_or_422(names: Sequence[str]) -> list[str]:
    try:
        return [name for name, _ in validate_tag_names(names)]
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
