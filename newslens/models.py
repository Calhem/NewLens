"""The shapes of data going in and out of the API, checked by Pydantic.

Anything a user sends is untrusted: it is validated here before any other code sees it.
"""

import re
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator

MAX_URL_LENGTH = 2048
ARTICLE_ID = r"^[0-9a-f]{32}$"
_CONTROL = re.compile(r"[\x00-\x20\x7f]")


class SubmitArticle(BaseModel):
    url: str = Field(max_length=MAX_URL_LENGTH)

    @field_validator("url")
    @classmethod
    def _check_url(cls, value):
        value = value.strip()
        if _CONTROL.search(value):
            raise ValueError("The address contains spaces or control characters.")
        parts = urlsplit(value)
        if parts.scheme not in ("http", "https"):
            raise ValueError("The address must start with http:// or https://.")
        if not parts.hostname or "." not in parts.hostname.strip("."):
            raise ValueError("The address needs a full website name, such as example.com.")
        if parts.username or parts.password:
            raise ValueError("Addresses with a user name or password in them are not accepted.")
        # Which hosts may actually be fetched (no private networks, no metadata endpoints) is
        # checked at fetch time, on the resolved address, when fetching is added (Milestone 2).
        return value


class RunOut(BaseModel):
    id: str
    status: str
    created_at: str
    methodology_version: str


class ArticleOut(BaseModel):
    id: str
    url: str | None
    title: str | None
    retrieval_status: str
    input_method: str
    created_at: str
    runs: list[RunOut]


class Health(BaseModel):
    status: str                 # "ok" or "unavailable"
    typedb: str                 # "reachable" or "unreachable"
    database: str
    schema_version: str | None = None
    detail: str | None = None
