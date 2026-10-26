"""Saving the Anthropic key safely, and where the key may be sent. No network requests."""

import pytest

from newslens.llm import client_options
from scripts import set_anthropic_key
from scripts.set_anthropic_key import clean, problem_with, save_key

FAKE = "sk-ant-api03-" + "x" * 93 + "AA"   # pragma: allowlist secret (not a real key; real length)


def test_the_key_is_written_replacing_the_old_value(tmp_path):
    env = tmp_path / ".env"
    env.write_text("TYPEDB_PASSWORD=password\nANTHROPIC_API_KEY=\nNEWSLENS_MODEL_PROVIDER=none\n")
    save_key(FAKE, env)
    assert env.read_text() == f"TYPEDB_PASSWORD=password\nANTHROPIC_API_KEY={FAKE}\nNEWSLENS_MODEL_PROVIDER=none\n"
    assert oct(env.stat().st_mode)[-3:] == "600"
    assert not (tmp_path / ".env.new").exists()


def test_the_key_is_added_when_missing(tmp_path):
    env = tmp_path / ".env"
    env.write_text("TYPEDB_DATABASE=newslens")
    save_key(FAKE, env)
    assert env.read_text() == f"TYPEDB_DATABASE=newslens\nANTHROPIC_API_KEY={FAKE}\n"


@pytest.mark.parametrize("key, reason", [
    ("", "nothing was pasted"), ("sk-proj-" + "x" * 100, "start with sk-ant-api"),
    ("sk-ant-api03-" + "x" * 60, "copied incompletely"),       # the 73-character case seen for real
    ("sk-ant-admin01-" + "x" * 100, "Admin API key"),
    (FAKE[:20] + " " + FAKE[20:], "spaces"),
])
def test_things_that_are_not_keys_are_refused(key, reason):
    assert reason in problem_with(key)


def test_main_prints_nothing_of_the_key(tmp_path, monkeypatch, capsys):
    env = tmp_path / ".env"
    env.write_text("NEWSLENS_MODEL_PROVIDER=none\n")
    monkeypatch.setattr(set_anthropic_key, "ENV_FILE", env)
    monkeypatch.setattr(set_anthropic_key.getpass, "getpass", lambda prompt: FAKE)
    set_anthropic_key.main()
    out = capsys.readouterr()
    assert FAKE not in out.out + out.err and FAKE[-6:] not in out.out + out.err
    assert "NEWSLENS_MODEL_PROVIDER=none" in env.read_text()        # the model stays off


def test_a_rejected_key_changes_nothing(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("ANTHROPIC_API_KEY=\n")
    monkeypatch.setattr(set_anthropic_key, "ENV_FILE", env)
    monkeypatch.setattr(set_anthropic_key.getpass, "getpass", lambda prompt: "not a key")
    with pytest.raises(SystemExit, match="Nothing was changed"):
        set_anthropic_key.main()
    assert env.read_text() == "ANTHROPIC_API_KEY=\n"


def test_the_key_only_goes_to_anthropics_api(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://somewhere-else.example")
    options = client_options("k", 10)
    assert options["base_url"] == "https://api.anthropic.com" and options["max_retries"] == 0


def test_bracketed_paste_markers_are_removed():
    assert clean("\x1b[200~" + FAKE + "\x1b[201~\n") == FAKE
    assert problem_with(clean("[200~" + FAKE + "[201~")) is None


@pytest.mark.parametrize("pasted, reason", [
    ("\x07" + FAKE, "hidden control characters"),
    ("My NewsLens key", "doesn't start with sk-"),
    ("sk-ant-...AbCd", "not an API key"),
])
def test_unhelpful_pastes_get_a_helpful_reason(pasted, reason):
    message = problem_with(clean(pasted))
    assert reason in message and FAKE not in message
