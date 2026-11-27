"""`deploy/server/keycloak.sh sync-theme` (run by every deploy): Keycloak gets the checkout's sign-in pages, and a changed
stylesheet reaches the browsers that saw the old one.

Found 2026-11-27 (the owner's Safari, after the theme first changed on the server): Keycloak serves its theme files with
Cache-Control: max-age=2592000 and no ETag, at /resources/<Keycloak's version>/login/modeler-one/css/modeler-one.css, the
same address across restarts. A browser that had opened the sign-in page kept the old stylesheet and showed the new
page's words in the old look. The copy Keycloak gets therefore names the stylesheet after its content."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.req("T-06")

REPO = Path(__file__).resolve().parents[3]
THEME = Path("deploy/keycloak/themes/modeler-one")
CSS = "login/resources/css/modeler-one.css"


def _server(tmp_path: Path) -> tuple[Path, Path]:
    """A checkout holding the theme, and an installed Keycloak's themes folder (Keycloak itself not running)."""
    repo = tmp_path / "repo"
    shutil.copytree(REPO / THEME, repo / THEME)
    themes = tmp_path / "kc" / "keycloak-26.7.5" / "themes"
    themes.mkdir(parents=True)
    return repo, themes


def _sync(tmp_path: Path, repo: Path) -> str:
    env = {"HOME": str(tmp_path / "home"), "PATH": "/usr/bin:/bin", "MODELER_REPO": str(repo),
           "MODELER_DATA": str(tmp_path / "data"), "MODELER_LOGS": str(tmp_path / "logs"),
           "MODELER_SECRETS_FILE": str(tmp_path / "none"), "MODELER_KEYCLOAK_HOME": str(tmp_path / "kc")}
    done = subprocess.run(["bash", str(REPO / "deploy/server/keycloak.sh"), "sync-theme"], env=env, capture_output=True,
                          text=True, timeout=60, check=False)
    assert done.returncode == 0, done.stdout + done.stderr
    return done.stdout


def _named(css: bytes) -> str:
    return f"modeler-one-{hashlib.sha256(css).hexdigest()[:12]}.css"


def _files(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_keycloak_gets_the_stylesheet_under_a_name_made_from_its_content(tmp_path):
    repo, themes = _server(tmp_path)
    shutil.copytree(repo / THEME, themes / "modeler-one")      # the server after the first sync: the plain name, cached
    out = _sync(tmp_path, repo)
    assert "copied" in out and "not running" in out
    ours, theirs = _files(repo / THEME), _files(themes / "modeler-one")
    name = _named(ours[CSS])
    moved = {CSS: f"login/resources/css/{name}"}
    assert {moved.get(f, f) for f in ours} == set(theirs)       # the plain name is gone, nothing else added or lost
    for f, content in ours.items():
        if f == "login/theme.properties":
            assert theirs[f] == content.replace(b"css/modeler-one.css", f"css/{name}".encode())
            assert f"styles=css/styles.css css/{name}".encode() in theirs[f]
        else:
            assert theirs[moved.get(f, f)] == content
    assert "are current" in _sync(tmp_path, repo)               # unchanged: no copy, so no restart of Keycloak


def test_a_changed_stylesheet_is_a_new_address_and_the_old_one_goes(tmp_path):
    repo, themes = _server(tmp_path)
    _sync(tmp_path, repo)
    css = repo / THEME / CSS
    before = _named(css.read_bytes())
    css.write_text(css.read_text(encoding="utf-8") + "\n.mo-sub { color: #E4E4E7; }\n", encoding="utf-8")
    assert "copied" in _sync(tmp_path, repo)
    after = _named(css.read_bytes())
    assert after != before
    assert [p.name for p in (themes / "modeler-one" / "login/resources/css").iterdir()] == [after]
    assert not (tmp_path / "kc" / ".theme-staged").exists()
