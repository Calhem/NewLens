"""The NewsLens HTTP API (FastAPI). The React frontend talks only to this.

All routes live under /api. The database connection is opened on first use and the schema
is brought up to date then, so the API starts (and /api/health can explain the problem) even
while TypeDB is still starting or unreachable.
"""

import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Path
from fastapi.responses import JSONResponse
from typedb.driver import TypeDBDriverException

from newslens import store
from newslens.db import connect
from newslens.migrations import ensure_database, schema_version
from newslens.models import ARTICLE_ID, ArticleDetail, ArticleOut, Health, SubmitArticle, SubmitText
from newslens.settings import load_settings

log = logging.getLogger("newslens.api")

UNAVAILABLE = "The database is not reachable. Check that TypeDB is running (docker compose ps)."
LOGIN_REFUSED = ("TypeDB refused the login. Check TYPEDB_USERNAME and TYPEDB_PASSWORD in .env "
                 "(after `docker compose down -v` the password is back to TypeDB's default).")


def explain(error):
    """A safe, plain explanation of a connection failure (never the raw driver message)."""
    return LOGIN_REFUSED if "CXN16" in str(error) else UNAVAILABLE


class Database:
    """One shared TypeDB connection, opened and prepared on first use."""

    def __init__(self, settings):
        self.settings = settings
        self.name = settings.typedb_database
        self._driver = None
        self._lock = threading.Lock()

    def driver(self):
        with self._lock:
            if self._driver is None:
                driver = connect(self.settings)
                try:
                    applied = ensure_database(driver, self.name)
                    store.ensure_methodology(driver, self.name)
                except Exception:
                    driver.close()
                    raise
                if applied:
                    log.info("database %s: applied %s", self.name, ", ".join(applied))
                self._driver = driver
            return self._driver

    def reset(self):
        """Forget a broken connection so the next request reconnects."""
        with self._lock:
            if self._driver is not None:
                try:
                    self._driver.close()
                except Exception:
                    pass
            self._driver = None

    def close(self):
        self.reset()


def create_app(settings=None):
    settings = settings or load_settings()
    if settings.uses_default_password:
        log.warning("TypeDB is using its default password. Fine on one computer; before sharing "
                    "this installation run: uv run python -m scripts.set_typedb_password")
    database = Database(settings)

    @asynccontextmanager
    async def lifespan(app):
        yield
        database.close()

    app = FastAPI(title="NewsLens API", version="0.0.1", lifespan=lifespan,
                  docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)
    app.state.database = database

    def driver_or_503():
        try:
            return database.driver()
        except Exception as error:
            # The error type only: driver messages can include addresses but never the password.
            log.warning("TypeDB unavailable: %s", explain(error))
            database.reset()
            raise HTTPException(503, explain(error)) from None

    @app.get("/api/health", response_model=Health)
    def health():
        try:
            driver = database.driver()
            version = schema_version(driver, database.name)
        except Exception as error:
            log.warning("health check: %s", explain(error))
            database.reset()
            body = Health(status="unavailable", typedb="unreachable", database=database.name,
                          detail=explain(error))
            return JSONResponse(body.model_dump(), status_code=503)
        return Health(status="ok", typedb="reachable", database=database.name,
                      schema_version=version, model_provider=settings.newslens_model_provider)

    def call(work):
        """Run work(driver, database_name). If the connection has gone stale (for example
        TypeDB restarted), reconnect and try once more; if TypeDB is down, answer 503.

        A retried write can't half-apply (each write is one transaction), and an error that
        isn't about the connection fails the same way on the retry and is raised."""
        try:
            return work(driver_or_503(), database.name)
        except TypeDBDriverException as error:
            log.warning("TypeDB error, reconnecting once: %s", type(error).__name__)
            database.reset()
        return work(driver_or_503(), database.name)

    @app.post("/api/articles", response_model=ArticleOut, status_code=201)
    def submit_article(body: SubmitArticle):
        def work(driver, db):
            return store.get_article(driver, db, store.submit_url(driver, db, body.url))
        return call(work)

    @app.post("/api/articles/manual", response_model=ArticleOut, status_code=201)
    def submit_text(body: SubmitText):
        def work(driver, db):
            return store.get_article(driver, db, store.submit_text(driver, db, body.title, body.text, body.url))
        return call(work)

    @app.get("/api/articles", response_model=list[ArticleOut])
    def list_articles():
        return call(store.list_articles)

    @app.get("/api/articles/{article_id}", response_model=ArticleDetail)
    def get_article(article_id: str = Path(pattern=ARTICLE_ID)):
        article = call(lambda driver, db: store.get_article(driver, db, article_id, detail=True))
        if article is None:
            raise HTTPException(404, "No article with that id.")
        return article

    return app
