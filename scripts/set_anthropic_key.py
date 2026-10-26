"""Save your Anthropic API key in .env without showing it: `uv run python -m scripts.set_anthropic_key`.

You paste the key at a hidden prompt (nothing appears as you paste, and it is not saved in your
shell history). The script checks it looks like an Anthropic key, writes it to .env (readable
only by you), and prints nothing of the key itself. It makes no network request, and it does
NOT switch the model on: NEWSLENS_MODEL_PROVIDER stays as it is until you choose to change it.
"""

import getpass
import os
import sys
from pathlib import Path

from scripts.set_typedb_password import with_setting

ENV_FILE = Path(".env")
PREFIX = "sk-ant-api"
MIN_LENGTH = 100        # Anthropic API keys are about 108 characters; shorter usually means cut off


def problem_with(key):
    """Why this doesn't look like an Anthropic API key, or None. Never includes the key."""
    if not key:
        return "nothing was pasted"
    if any(ch.isspace() for ch in key):
        return "it contains spaces or line breaks; copy just the key"
    if key.startswith("sk-ant-admin"):
        return "this is an Admin API key; NewsLens needs an ordinary API key (sk-ant-api...)"
    if not key.startswith(PREFIX):
        return f"Anthropic API keys start with {PREFIX}"
    if len(key) < MIN_LENGTH:
        return (f"it is {len(key)} characters, but Anthropic API keys are about 108; it was "
                "probably copied incompletely. Use the Copy button in the Anthropic Console")
    return None


def save_key(key, env_file=ENV_FILE):
    """Write ANTHROPIC_API_KEY into env_file, replacing any earlier value; mode 600."""
    staged = env_file.with_name(env_file.name + ".new")
    staged.write_text(with_setting(env_file.read_text(), "ANTHROPIC_API_KEY", key))
    os.chmod(staged, 0o600)
    staged.replace(env_file)


def main():
    if not ENV_FILE.exists():
        sys.exit("No .env file here. Run this from the project folder after `cp .env.example .env`.")
    key = getpass.getpass("Paste your Anthropic API key (nothing will appear), then press Enter: ").strip()
    problem = problem_with(key)
    if problem:
        sys.exit(f"Not saved: {problem}. Nothing was changed.")
    save_key(key)
    print("Saved ANTHROPIC_API_KEY in .env (not shown). .env is readable only by you and is "
          "excluded from Git.\nThe model is still off; nothing has been sent to Anthropic.")


if __name__ == "__main__":
    main()
