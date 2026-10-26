"""The shapes of data going in and out of the API, checked by Pydantic.

Anything a user sends is untrusted: it is validated here before any other code sees it.
"""

from pydantic import BaseModel, Field, field_validator

from newslens.ingest.extract import MAX_TEXT_CHARS
from newslens.ingest.http import MAX_URL_LENGTH, check_url

ARTICLE_ID = r"^[0-9a-f]{32}$"


def _valid_url(value):
    value = value.strip()
    problem = check_url(value)
    if problem:
        # The same checks the fetcher applies, so a URL accepted here can be fetched. Where the
        # name really points (no private networks, no metadata endpoints) is checked again
        # when connecting.
        raise ValueError(problem[0].upper() + problem[1:] + ".")
    return value


class SubmitArticle(BaseModel):
    url: str = Field(max_length=MAX_URL_LENGTH + 100)

    @field_validator("url")
    @classmethod
    def _check_url(cls, value):
        return _valid_url(value)


class SubmitText(BaseModel):
    """Article text a user pastes in, for example when a page can't be retrieved."""
    title: str = Field(min_length=1, max_length=500)
    text: str = Field(min_length=20, max_length=MAX_TEXT_CHARS)
    url: str | None = Field(default=None, max_length=MAX_URL_LENGTH + 100)

    @field_validator("title")
    @classmethod
    def _title(cls, value):
        value = " ".join(value.split())
        if not value:
            raise ValueError("The title can't be empty.")
        return value

    @field_validator("text")
    @classmethod
    def _text(cls, value):
        value = value.replace("\r\n", "\n").strip()
        if len(value) < 20:
            raise ValueError("Paste the article's text (at least 20 characters).")
        return value

    @field_validator("url")
    @classmethod
    def _url(cls, value):
        return _valid_url(value) if value and value.strip() else None


class Stage(BaseModel):
    name: str
    status: str
    started_at: str
    finished_at: str | None
    details: list[str]


class ModelCall(BaseModel):
    model: str
    prompt_version: str
    status: str
    input_tokens: int | None
    output_tokens: int | None


class RunOut(BaseModel):
    id: str
    status: str
    stage: str | None
    created_at: str
    finished_at: str | None
    failure_reason: str | None
    methodology_version: str
    stages: list[Stage]
    model_calls: list[ModelCall]


class ArticleOut(BaseModel):
    id: str
    url: str | None
    title: str | None
    retrieval_status: str
    input_method: str
    created_at: str
    runs: list[RunOut]


class Publisher(BaseModel):
    name: str
    domain: str


class Speaker(BaseModel):
    name: str
    confidence: str


class Quotation(BaseModel):
    id: str
    start: int
    end: int
    text: str
    speakers: list[Speaker]


class Link(BaseModel):
    url: str
    anchor_text: str | None


class Claim(BaseModel):
    id: str
    text: str
    kind: str
    basis: str
    missing_information: list[str]
    quote: str
    start: int
    end: int
    run_id: str


class ArticleDetail(ArticleOut):
    subheading: str | None
    canonical_url: str | None
    final_url: str | None
    http_status: int | None
    published_at: str | None
    modified_at: str | None
    retrieved_at: str | None
    language: str | None
    text: str | None
    content_hash: str | None
    bylines: list[str]
    metadata_sources: list[str]
    retrieval_notes: list[str]
    publishers: list[Publisher]
    quotations: list[Quotation]
    links: list[Link]
    claims: list[Claim]


class Health(BaseModel):
    status: str                 # "ok" or "unavailable"
    typedb: str                 # "reachable" or "unreachable"
    database: str
    schema_version: str | None = None
    model_provider: str | None = None
    detail: str | None = None
