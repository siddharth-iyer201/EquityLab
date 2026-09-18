#!/usr/bin/env python3
"""Verify Home page HTML structure and rendered layout checks."""

from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import (  # noqa: E402
    _home_credibility_html,
    _home_feature_cards_html,
    _home_hero_section_html,
    _home_lower_sections_html,
)


def check_static_html() -> list[str]:
    errors: list[str] = []
    hero = _home_hero_section_html()
    lower = _home_lower_sections_html()
    features = _home_feature_cards_html()
    cred = _home_credibility_html()

    if hero.count("<div") != hero.count("</div"):
        errors.append("hero section: unbalanced div tags")
    if lower.count("<div") != lower.count("</div"):
        errors.append("lower sections: unbalanced div tags")
    if "el-home-container" not in hero or "el-home-container" not in lower:
        errors.append("missing el-home-container")
    if "el-home-hero" not in hero:
        errors.append("missing el-home-hero grid")
    if "grid-template-columns" not in hero and "el-home-hero" not in hero:
        errors.append("hero grid wrapper missing")
    if "viewBox=\"0 0 520 400\"" not in hero:
        errors.append("hero SVG missing viewBox/dimensions")
    if "65.3%" not in hero or "+1.27" not in hero:
        errors.append("hero SVG missing equity/EV metrics")
    if hero.count("<rect") < 169:
        errors.append(f"hero heatmap rects too few: {hero.count('<rect')}")
    if "Make better" not in hero or "poker decisions" not in hero:
        errors.append("headline copy missing")
    if features.count("<svg") < 4:
        errors.append("feature cards missing inline SVG icons")
    if cred.count("<svg") < 4:
        errors.append("credibility section missing inline SVG icons")
    if "el-home-card-grid" not in lower:
        errors.append("product preview grid missing")
    if lower.count("<article") != 4:
        errors.append("expected 4 product preview cards")
    return errors


def check_rendered() -> list[str]:
    errors: list[str] = []
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return ["playwright not installed — skip rendered checks"]

    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(ROOT / "app.py"),
            "--server.headless",
            "true",
            "--server.port",
            "8766",
            "--browser.gatherUsageStats",
            "false",
        ],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        time.sleep(5)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.goto("http://127.0.0.1:8766/", wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(2000)

            checks = {
                "el-home-container": page.locator(".el-home-container").first,
                "el-home-hero": page.locator(".el-home-hero").first,
                "hero svg": page.locator(".el-home-hero-art").first,
                "headline line 1": page.get_by_text("Make better", exact=True),
                "gradient text": page.locator(".el-home-gradient-text").first,
                "product grid": page.locator(".el-home-card-grid").first,
                "feature svgs": page.locator(".el-home-card-icon svg"),
                "cred svgs": page.locator(".el-home-cred-icon svg"),
                "cta analyze": page.get_by_role("button", name=re.compile(r"Start Analyzing")),
                "cta ranges": page.get_by_role("button", name=re.compile(r"Build a Range")),
            }
            for name, loc in checks.items():
                if loc.count() == 0:
                    errors.append(f"rendered: missing {name}")

            container = page.locator(".el-home-container").first
            if container.count():
                box = container.bounding_box()
                if box and box["width"] < 1200:
                    errors.append(f"container too narrow: {box['width']:.0f}px")

            hero = page.locator(".el-home-hero").first
            if hero.count():
                styles = hero.evaluate(
                    "el => getComputedStyle(el).gridTemplateColumns"
                )
                if "px" not in styles and "fr" not in styles:
                    errors.append(f"hero not using grid columns: {styles}")

            headline = page.locator(".el-home-headline").first
            if headline.count():
                line_count = headline.evaluate(
                    """el => {
                        const range = document.createRange();
                        const lines = [];
                        const text = el.innerText;
                        const rects = [];
                        el.querySelectorAll('.el-home-headline-line').forEach(node => {
                            rects.push(node.getBoundingClientRect().top);
                        });
                        return new Set(rects.map(v => Math.round(v))).size;
                    }"""
                )
                if line_count > 3:
                    errors.append(f"headline wraps into too many lines: {line_count}")

            card_grid = page.locator(".el-home-card-grid").first
            if card_grid.count():
                cols = card_grid.evaluate(
                    "el => getComputedStyle(el).gridTemplateColumns.split(' ').length"
                )
                if cols < 2:
                    errors.append(f"product grid not 2 columns at desktop: {cols}")

            raw_html = page.content()
            if re.search(r"<\s*div[^>]*>\s*<\s*div", raw_html) and "&lt;div" in raw_html:
                errors.append("escaped/raw HTML visible in page")

            browser.close()
    finally:
        proc.terminate()
        proc.wait(timeout=10)
    return errors


def main() -> int:
    errors = check_static_html()
    errors.extend(check_rendered())
    if errors:
        print("Home verification FAILED:")
        for err in errors:
            print(f"  - {err}")
        return 1
    print("Home verification passed (static + rendered).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
