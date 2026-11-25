"""Optional, self-reported reviewer profiles; no automatic schema creation."""
import json
import unicodedata
from datetime import datetime, timezone
from importlib import import_module

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator
from sqlalchemy import Column, Integer, MetaData, Table, Text, select, text
from sqlalchemy.dialects.sqlite import insert

# Separate metadata intentionally keeps create_all() and fresh Demo initialization
# from creating a migration-owned table behind the migration ledger's back.
profiles = Table('reviewer_profiles', MetaData(),
    Column('user_id', Integer, primary_key=True), Column('professional_title', Text),
    Column('institution', Text), Column('department', Text), Column('research_areas', Text),
    Column('expertise', Text), Column('updated_at', Text), Column('provenance', Text))


def _clean(value, maximum):
    if not isinstance(value, str): raise ValueError('Expected text')
    value = value.strip()
    if not value or len(value) > maximum or any(unicodedata.category(c).startswith('C') for c in value):
        raise ValueError('Invalid profile text')
    return value


class ReviewerProfileInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    full_name: str | None = Field(default=None, max_length=100)
    professional_title: str | None = Field(default=None, max_length=100)
    institution: str | None = Field(default=None, max_length=200)
    department: str | None = Field(default=None, max_length=150)
    research_areas: list[str] = Field(default_factory=list, max_length=12)
    expertise: list[str] = Field(default_factory=list, max_length=12)

    @field_validator('full_name')
    @classmethod
    def valid_name(cls, value):
        return _clean(value, 100) if value is not None else None

    @field_validator('professional_title', 'institution', 'department')
    @classmethod
    def optional_text(cls, value, info: ValidationInfo):
        return _clean(value, {'professional_title': 100, 'institution': 200, 'department': 150}[info.field_name]) if value else None

    @field_validator('research_areas', 'expertise')
    @classmethod
    def list_text(cls, value):
        return [_clean(item, 80) for item in value]


def schema_available(db):
    if db.get_bind().dialect.name != 'sqlite':
        raise HTTPException(503, 'Reviewer profiles unavailable')
    schema = db.execute(text("SELECT type, sql FROM sqlite_master WHERE name='reviewer_profiles' AND type IN ('table','view')")).first()
    ledger_table = db.execute(text("SELECT 1 FROM sqlite_master WHERE name='schema_migrations' AND type='table'")).first()
    migration = import_module('migrations.010_reviewer_profiles')
    applied = bool(ledger_table and db.execute(text('SELECT 1 FROM schema_migrations WHERE migration_id=:id'), {'id': migration.MIGRATION_ID}).first())
    if not schema and not applied: return False
    if not schema or schema[0] != 'table' or not schema[1] or not applied or migration.normalize(schema[1]) != migration.normalize(migration.DDL):
        raise HTTPException(503, 'Reviewer profiles unavailable')
    if db.execute(text("SELECT 1 FROM sqlite_master WHERE tbl_name='reviewer_profiles' AND type IN ('trigger','index') AND sql IS NOT NULL")).first():
        raise HTTPException(503, 'Reviewer profiles unavailable')
    return True


def serialize(row):
    if row is None: return None
    return {'professional_title': row.professional_title, 'institution': row.institution,
            'department': row.department, 'research_areas': json.loads(row.research_areas),
            'expertise': json.loads(row.expertise), 'provenance': row.provenance,
            'updated_at': row.updated_at}


def load_profiles(db, user_ids):
    if not schema_available(db) or not user_ids: return {}
    rows = db.execute(select(profiles).where(profiles.c.user_id.in_(user_ids))).all()
    return {row.user_id: serialize(row) for row in rows}


def save_profile(db, user_id, data):
    if not schema_available(db): raise HTTPException(503, 'Reviewer profiles unavailable')
    from app.models import User
    user = db.get(User, user_id)
    if not user or user.role != 'reviewer': raise HTTPException(403, 'Reviewer profile unavailable')
    values = data.model_dump(exclude={'full_name'})
    if data.full_name is not None:
        user.name = data.full_name
    values.update(user_id=user_id, research_areas=json.dumps(data.research_areas, ensure_ascii=False),
                  expertise=json.dumps(data.expertise, ensure_ascii=False),
                  updated_at=datetime.now(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z'),
                  provenance='self_reported')
    stmt = insert(profiles).values(**values)
    db.execute(stmt.on_conflict_do_update(index_elements=['user_id'], set_={key: value for key, value in values.items() if key != 'user_id'}))
    db.commit()
    return serialize(db.execute(select(profiles).where(profiles.c.user_id == user_id)).one())
