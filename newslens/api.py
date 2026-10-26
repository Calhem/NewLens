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

from newslens import store
from newslens.db import connect
from newslens.migrations import ensure_database, schema_version
from newslens.models import ARTICLE_ID, ArticleOut, Health, SubmitArticle
from newslens.settings import load_settings

log = logging.getLogger("newslens.api")

UNAVAILABLE = "The database is not reachable. Check that TypeDB is running (docker compose ps)."


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
            log.warning("TypeDB unavailable: %s", type(error).__name__)
            database.reset()
            raise HTTPException(503, UNAVAILABLE) from None

    @app.get("/api/health", response_model=Health)
    def health():
        try:
            driver = database.driver()
            version = schema_version(driver, database.name)
        except Exception as error:
            log.warning("health check: TypeDB unavailable: %s", type(error).__name__)
            database.reset()
            body = Health(status="unavailable", typedb="unreachable", database=database.name,
                          detail=UNAVAILABLE)
            return JSONResponse(body.model_dump(), status_code=503)
        return Health(status="ok", typedb="reachable", database=database.name,
                      schema_version=version)

    @app.post("/api/articles", response_model=ArticleOut, status_code=201)
    def submit_article(body: SubmitArticle):
        driver = driver_or_503()
        article_id = store.submit_url(driver, database.name, body.url)
        return store.get_article(driver, database.name, article_id)

    @app.get("/api/articles", response_model=list[ArticleOut])
    def list_articles():
        return store.list_articles(driver_or_503(), database.name)

    @app.get("/api/articles/{article_id}", response_model=ArticleOut)
    def get_article(article_id: str = Path(pattern=ARTICLE_ID)):
        article = store.get_article(driver_or_503(), database.name, article_id)
        if article is None:
            raise HTTPException(404, "No article with that id.")
        return article

    return app
