import json
import uuid
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, String, TypeDecorator
from sqlalchemy.dialects.postgresql import JSONB, UUID


class GUID(TypeDecorator):
    impl = String(36)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(UUID(as_uuid=False))
        return dialect.type_descriptor(String(36))

    def process_bind_param(self, value: Any, dialect) -> str | None:
        if value is None:
            return None
        return str(value)

    def process_result_value(self, value: Any, dialect) -> str | None:
        if value is None:
            return None
        return str(value)


class JSONField(TypeDecorator):
    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB())
        return dialect.type_descriptor(JSON())


class VectorField(TypeDecorator):
    impl = JSON
    cache_ok = True

    def __init__(self, dimensions: int = 384, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.dimensions = dimensions

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(Vector(self.dimensions))
        return dialect.type_descriptor(JSON())

    def process_bind_param(self, value: Any, dialect):
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value
        if hasattr(value, "tolist"):
            value = value.tolist()
        return [float(v) for v in value]

    def process_result_value(self, value: Any, dialect):
        if value is None:
            return None
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                return None
        return [float(v) for v in value]


def gen_uuid() -> str:
    return str(uuid.uuid4())
