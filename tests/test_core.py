"""Tests for env-doctor core. Run with: python -m pytest -q"""

import json
import subprocess
import sys
from pathlib import Path

from env_doctor.core import audit, find_referenced_vars, is_placeholder, looks_like_real_secret, shannon_entropy


def test_environ_get_form_detected(tmp_path: Path):
    src = tmp_path / "app.py"
    src.write_text(
        'import os\n'
        'DB_HOST = os.environ.get("DB_HOST")\n'
        'API_KEY = os.environ["API_KEY"]\n'
    )
    found = find_referenced_vars(tmp_path)
    assert "DB_HOST" in found  # paren form: os.environ.get("X")
    assert "API_KEY" in found  # bracket form: os.environ["X"]


def test_process_env_bracket_form_detected(tmp_path: Path):
    src = tmp_path / "app.js"
    src.write_text(
        'const key = process.env["API_KEY"];\n'
        "const other = process.env['DB_URL'];\n"
        'const plain = process.env.PORT;\n'
    )
    found = find_referenced_vars(tmp_path)
    assert "API_KEY" in found  # bracket form: process.env["X"]
    assert "DB_URL" in found  # single-quoted bracket form
    assert "PORT" in found  # dot form still works


def test_bracket_ref_not_flagged_unused(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text("API_KEY=abc123\n")
    ex = tmp_path / ".env.example"
    ex.write_text("API_KEY=\n")
    code = tmp_path / "app.js"
    code.write_text('const key = process.env["API_KEY"];\n')
    result = audit(env, ex, scan_root=tmp_path)
    assert "possibly-unused" not in {i["code"] for i in result["issues"]}


def test_bare_dollar_var_detected_and_pid_not(tmp_path: Path):
    src = tmp_path / "deploy.sh"
    src.write_text(
        'curl -H "Authorization: $API_KEY" https://example.com\n'
        'psql "$DB_URL"\n'
        'echo $$ "pid, not a var"\n'
        'echo \\$NOT_A_VAR "escaped literal"\n'
    )
    found = find_referenced_vars(tmp_path)
    assert "API_KEY" in found  # bare $VAR in a double-quoted string
    assert "DB_URL" in found  # bare $VAR as a bare argument
    assert "NOT_A_VAR" not in found  # \$ is a literal dollar, not a reference
    # $$ must not leak a bogus name either: nothing after $$ is a var here.


def test_placeholder_detection():
    assert is_placeholder("changeme")
    assert is_placeholder("your-api-key-here")
    assert is_placeholder("")
    assert not is_placeholder("postgres://localhost:5432/app")


def test_entropy():
    assert shannon_entropy("aaaa") < 1.0
    assert shannon_entropy("aB3$xQ9!zK2#mN7@pL4") > 4.0


def test_real_secret_prefix():
    # Fake prefix only — never a real token shape.
    assert looks_like_real_secret("GH_TOKEN", "ghp_test-value")
    assert not looks_like_real_secret("APP_NAME", "my-app")


def test_duplicate_and_drift(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text("A=1\nA=2\nB=\n")
    ex = tmp_path / ".env.example"
    ex.write_text("A=\nC=\n")
    result = audit(env, ex)
    codes = {i["code"] for i in result["issues"]}
    assert "duplicate-key" in codes
    assert "missing-in-env" in codes  # C in example, not in .env
    assert "missing-in-example" in codes  # B in .env, not in example
    assert "empty-value" in codes
    assert not result["ok"]


def test_clean_file_passes(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text("DATABASE_URL=postgres://localhost:5432/app\n")
    ex = tmp_path / ".env.example"
    ex.write_text("DATABASE_URL=\n")
    result = audit(env, ex)
    assert result["ok"]
    assert result["errors"] == 0


def test_missing_env_file(tmp_path: Path):
    result = audit(tmp_path / ".env", tmp_path / ".env.example")
    assert not result["ok"]
    assert any(i["code"] == "missing-file" for i in result["issues"])


def test_cli_json_output(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text("A=1\n")
    ex = tmp_path / ".env.example"
    ex.write_text("A=\n")
    out = subprocess.run(
        [sys.executable, "-m", "env_doctor", "check", "--env", str(env),
         "--example", str(ex), "--format", "json"],
        capture_output=True, text=True, check=True,
    )
    data = json.loads(out.stdout)
    assert data["ok"] is True
    assert data["keys"] == ["A"]


def test_unused_var_warning(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text("USED=1\nDEAD=1\n")
    ex = tmp_path / ".env.example"
    ex.write_text("USED=\nDEAD=\n")
    code = tmp_path / "app.py"
    code.write_text("import os\nx = os.getenv('USED')\n")
    result = audit(env, ex, scan_root=tmp_path)
    codes = {i["code"] for i in result["issues"]}
    assert "possibly-unused" in codes
    assert any(i["key"] == "DEAD" for i in result["issues"] if i["code"] == "possibly-unused")
