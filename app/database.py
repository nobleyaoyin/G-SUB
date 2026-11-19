"""SQLite configuration confined to the isolated collaboration workspace."""
import os
from pathlib import Path
import sqlite3
import stat

from app.config import DATA_ROOT, PROJECT_ROOT
from sqlalchemy import create_engine, event
from sqlalchemy.engine import URL
from sqlalchemy.orm import DeclarativeBase, sessionmaker

BASE_DIR = DATA_ROOT  # Existing document paths remain relative to this workspace.


def _validated_database_path() -> Path:
    configured = os.environ.get('COLLABORATION_DATABASE')
    if not configured:
        raise RuntimeError('COLLABORATION_DATABASE must name an existing isolated database')
    path = Path(configured)
    root = PROJECT_ROOT / '.test-data'
    if not path.is_absolute() or root.is_symlink() or not root.is_dir():
        raise RuntimeError('Collaboration database path is unavailable')
    resolved_root = root.resolve(strict=True)
    if resolved_root != root or resolved_root.parent != PROJECT_ROOT:
        raise RuntimeError('Collaboration database directory is unsafe')
    root_info = resolved_root.stat()
    if root_info.st_uid != os.geteuid() or stat.S_IMODE(root_info.st_mode) & 0o022:
        raise RuntimeError('Collaboration database directory must be owner-controlled')
    if path.is_symlink() or path.parent != resolved_root or path.resolve(strict=True) != path:
        raise RuntimeError('Collaboration database path is outside the isolated directory')
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid():
        raise RuntimeError('Collaboration database must be a private regular file')
    if stat.S_IMODE(info.st_mode) & 0o077:
        raise RuntimeError('Collaboration database permissions must be private')
    return path


DATABASE_PATH = _validated_database_path()
DATABASE_URL = URL.create('sqlite', database=str(DATABASE_PATH))


def _open_database():
    if _validated_database_path() != DATABASE_PATH:
        raise RuntimeError('Collaboration database configuration changed')
    return sqlite3.connect(DATABASE_PATH.as_uri() + '?mode=rw', uri=True, check_same_thread=False)


engine = create_engine(DATABASE_URL, creator=_open_database)


@event.listens_for(engine, 'connect')
def enable_sqlite_foreign_keys(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute('PRAGMA foreign_keys=ON')
    finally:
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
