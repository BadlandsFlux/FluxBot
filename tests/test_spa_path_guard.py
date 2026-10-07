"""Tests for dashboard/app.py's resolve_frontend_path(), the guard behind
the SPA catch-all route. CodeQL flags this pattern (py/path-injection)
even after the resolve+containment check, a documented blind spot for
this exact "resolve, then verify containment" idiom in Python path-
traversal queries; these tests exist to prove by example (not just by
manual reasoning in a comment) that the guard actually holds, including
against a classic pathlib gotcha: joining an absolute path onto a base
with `/` discards the base entirely (`Path("/a") / "/etc/passwd" ==
Path("/etc/passwd")`), so an attacker-controlled full_path that happens
to look absolute needs the same containment check to still catch it.
"""
from __future__ import annotations

import dashboard.app as app_mod


def test_normal_relative_path_passes_through_when_the_file_exists(monkeypatch, tmp_path):
    real_file = tmp_path / "logo.svg"
    real_file.write_text("<svg></svg>")
    monkeypatch.setattr(app_mod, "FRONTEND_DIST", tmp_path)
    assert app_mod.resolve_frontend_path("logo.svg") == real_file


def test_missing_file_falls_back_to_index_html(monkeypatch, tmp_path):
    monkeypatch.setattr(app_mod, "FRONTEND_DIST", tmp_path)
    assert app_mod.resolve_frontend_path("does-not-exist.js") == tmp_path / "index.html"


def test_dot_dot_traversal_is_rejected(monkeypatch, tmp_path):
    outside_secret = tmp_path.parent / "outside-secret.txt"
    outside_secret.write_text("shh")
    try:
        monkeypatch.setattr(app_mod, "FRONTEND_DIST", tmp_path)
        assert app_mod.resolve_frontend_path("../outside-secret.txt") == tmp_path / "index.html"
        assert app_mod.resolve_frontend_path("../../../../../../etc/passwd") == tmp_path / "index.html"
    finally:
        outside_secret.unlink()


def test_absolute_looking_path_is_rejected_despite_the_pathlib_join_gotcha(monkeypatch, tmp_path):
    # Path("/a") / "/etc/passwd" == Path("/etc/passwd"), the base is
    # discarded entirely by the join itself. The containment check runs
    # AFTER that join, on the resolved result, so it still has to catch
    # this rather than being bypassed by it.
    monkeypatch.setattr(app_mod, "FRONTEND_DIST", tmp_path)
    assert app_mod.resolve_frontend_path("/etc/passwd") == tmp_path / "index.html"
    assert app_mod.resolve_frontend_path("//etc/passwd") == tmp_path / "index.html"


def test_empty_path_falls_back_to_index_html(monkeypatch, tmp_path):
    monkeypatch.setattr(app_mod, "FRONTEND_DIST", tmp_path)
    assert app_mod.resolve_frontend_path("") == tmp_path / "index.html"


def test_a_file_that_is_itself_frontend_dist_index_is_not_specialcased_away(monkeypatch, tmp_path):
    (tmp_path / "index.html").write_text("<html></html>")
    monkeypatch.setattr(app_mod, "FRONTEND_DIST", tmp_path)
    # Asking for index.html directly still resolves to it normally.
    assert app_mod.resolve_frontend_path("index.html") == tmp_path / "index.html"
