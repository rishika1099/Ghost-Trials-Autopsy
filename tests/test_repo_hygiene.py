"""Submission rules a grader would check by hand: required files, a valid submission.json, pinned
dependencies, a prompt file per agent shape, no em or en dashes in anything a reader sees, and no secrets."""

import json
import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
READER_FACING = ["README.md", "docs/DESIGN_NOTES.md", "docs/CONTRIBUTIONS.md", "index.html", *sorted(str(p.relative_to(ROOT)) for p in (ROOT / "prompts").glob("*.md"))]


def test_required_files_at_the_root():
    for name in ("app.py", "pyproject.toml", "uv.lock", "README.md", "submission.json", "Dockerfile", "cloudbuild.yaml"):
        assert (ROOT / name).is_file(), name


def test_submission_json():
    data = json.loads((ROOT / "submission.json").read_text())
    assert set(data) == {"deploy_url", "authors", "path"}
    assert data["path"] == "research"
    assert re.fullmatch(r"https://[a-z0-9-]+\.[a-z0-9-]+\.run\.app", data["deploy_url"]), data["deploy_url"]
    assert len(data["authors"]) == 3 and len(set(data["authors"])) == 3
    assert all(re.fullmatch(r"[a-z]{2,4}\d{4}", a) for a in data["authors"]), data["authors"]


def test_every_dependency_is_pinned():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    deps = project["project"]["dependencies"] + project["dependency-groups"]["dev"]
    assert deps and all("==" in d for d in deps), [d for d in deps if "==" not in d]


def test_one_prompt_per_agent_shape():
    for name in ("lead", "researcher", "writer", "checker"):
        text = (ROOT / "prompts" / f"{name}.md").read_text()
        assert len(text) > 200, name


@pytest.mark.parametrize("path", READER_FACING)
def test_no_em_or_en_dashes(path):
    text = (ROOT / path).read_text()
    bad = [n for n, line in enumerate(text.splitlines(), 1) if "—" in line or "–" in line]
    assert not bad, f"{path} lines {bad}"


def test_no_secrets_or_hardcoded_contact_in_code():
    for path in [*ROOT.glob("*.py"), *(ROOT / "ghost").glob("*.py"), *(ROOT / "scripts").glob("*.py")]:
        text = path.read_text()
        assert not re.search(r"AIza[0-9A-Za-z_-]{30,}", text), path  # Google API key
        assert not re.search(r"[\w.]+@(columbia\.edu|gmail\.com)", text), path  # contact belongs in SEC_USER_AGENT
    assert not (ROOT / ".env").exists() or ".env" in (ROOT / ".gitignore").read_text()


def test_readme_test_count_matches_the_suite():
    import subprocess
    import sys
    out = subprocess.run([sys.executable, "-m", "pytest", "--co", "-q", str(ROOT / "tests")], capture_output=True,
                         text=True, cwd=ROOT).stdout
    collected = int(re.search(r"(\d+) tests? collected", out).group(1))
    claimed = int(re.search(r"`uv run pytest`: (\d+) tests", (ROOT / "README.md").read_text()).group(1))
    assert claimed == collected, f"README says {claimed} tests, the suite has {collected}"
