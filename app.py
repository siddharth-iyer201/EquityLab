from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from html import escape
import base64
import importlib

from pathlib import Path

import streamlit as st

import poker_engine
import hand_history_store
import equity_heatmap
import decision_analysis

APP_DIR = Path(__file__).resolve().parent
FAVICON_PATH = APP_DIR / "assets" / "equitylab_favicon.png"

# Streamlit keeps imported modules alive across reruns; reload when they change.
if getattr(poker_engine, "ENGINE_VERSION", 0) < 11:
    poker_engine = importlib.reload(poker_engine)
if getattr(hand_history_store, "STORE_VERSION", 0) < 5:
    hand_history_store = importlib.reload(hand_history_store)
if getattr(equity_heatmap, "HEATMAP_MODULE_VERSION", 0) < 2:
    equity_heatmap = importlib.reload(equity_heatmap)
if getattr(decision_analysis, "DECISION_ANALYSIS_VERSION", 0) < 3:
    decision_analysis = importlib.reload(decision_analysis)

from poker_engine import (
    HAND_CATEGORIES,
    analyze_board_texture,
    analyze_hero_situation,
    calculate_equity,
    classify_completed_hand,
    describe_hand,
    evaluate_best_hand,
    evaluate_call_decision,
    expand_weighted_range,
    parse_cards,
    parse_opponent_range,
)
from equity_heatmap import (
    HEATMAP_RANKS,
    build_heatmap_cache_key,
    equity_to_heatmap_color,
    get_or_compute_equity_heatmap,
    heatmap_exact_max_matchups,
    heatmap_simulation_budget,
    last_heatmap_cache_hit,
    pick_display_combo,
)
from decision_analysis import (
    build_decision_explanation as _pure_build_decision_explanation,
    build_decision_sensitivity as _pure_build_decision_sensitivity,
    confidence_level as _pure_confidence_level,
    decision_stability as _pure_decision_stability,
    equity_margin as _pure_equity_margin,
    format_monte_carlo_equity_ci as _pure_format_monte_carlo_equity_ci,
)
from hand_history_store import (
    DuplicateRangeNameError,
    delete_hand_history_entry_by_id,
    delete_saved_range_by_id,
    get_hand_history_entry,
    get_saved_range_by_id,
    initialize_hand_history_db,
    insert_hand_history_entry,
    insert_saved_range,
    load_hand_history_entries,
    load_saved_ranges,
    normalize_hand_weights,
    update_saved_range_by_id,
)

MAX_MONTE_CARLO_TRIALS = 250_000
MIN_MONTE_CARLO_TRIALS = 10_000
DEFAULT_MONTE_CARLO_TRIALS = 25_000
MONTE_CARLO_PRESETS = (10_000, 25_000, 50_000, 100_000, 250_000)
# Pot 100 / call 25 → required equity = 25 / 125 = 20%.
DEFAULT_POT_SIZE = 100.0
DEFAULT_CALL_AMOUNT = 25.0

RANGE_PRESETS = {
    "Random": "",
    "Top 50%": "22+, A2s+, K2s+, Q7s+, J8s+, T8s+, 98s, A2o+, K8o+, Q9o+, JTo, T9o",
    "Top 25%": "44+, A2s+, K8s+, Q9s+, J9s+, T9s, A8o+, KTo+, QJo",
    "Top 10%": "88+, ATs+, KTs+, QJs, AQo+, KQo",
    "Custom": "",
}

# Grid hand-class presets for the Range Builder (not stored in SQLite).
BUILTIN_RANGE_PRESETS = {
    "Tight (TAG)": "77+, A9s+, KTs+, QJs, JTs, T9s, ATo+, KQo",
    "Loose": "22+, A2s+, K5s+, Q8s+, J8s+, T8s+, 97s+, 87s, 76s, 65s, A2o+, K9o+, QTo+, JTo, T9o",
    "Nit": "TT+, AJs+, KQs, AQo+",
    "3-Bet Value": "QQ+, AKs, AKo",
    "Button Open": (
        "22+, A2s+, K4s+, Q8s+, J8s+, T7s+, 97s+, 86s+, 76s, 65s, 54s, "
        "A2o+, K9o+, QTo+, J9o+, T9o, 98o"
    ),
    "Small Blind Defense": "22+, A2s+, K8s+, Q9s+, J9s+, T8s+, 98s, 87s, 76s, A8o+, KTo+, QJo, JTo",
}

QUICK_EXAMPLES = (
    {
        "label": "AKs Preflop",
        "description": "Premium broadway vs a random range",
        "icon": "aks",
        "hero": ["As", "Ks"],
        "flop": [None, None, None],
        "turn": None,
        "river": None,
        "opponent": "Random",
        "pot": 100.0,
        "call": 25.0,
    },
    {
        "label": "Pocket Aces",
        "description": "AA under pressure vs a tight range",
        "icon": "aa",
        "hero": ["Ah", "As"],
        "flop": [None, None, None],
        "turn": None,
        "river": None,
        "opponent": "Top 25%",
        "pot": 100.0,
        "call": 50.0,
    },
    {
        "label": "Flush Draw",
        "description": "Nut flush draw on a wet flop",
        "icon": "flush",
        "hero": ["5d", "6d"],
        "flop": ["Qd", "7d", "2h"],
        "turn": None,
        "river": None,
        "opponent": "Random",
        "pot": 150.0,
        "call": 50.0,
    },
    {
        "label": "Straight Draw",
        "description": "Open-ended straight draw mid-stakes",
        "icon": "straight",
        "hero": ["9h", "Tc"],
        "flop": ["8c", "Jd", "2s"],
        "turn": None,
        "river": None,
        "opponent": "Random",
        "pot": 120.0,
        "call": 40.0,
    },
)

# Primary navigation (display labels). Internal session state uses these strings.
TAB_HOME = "Home"
TAB_ANALYZE = "Analyze"
TAB_RANGES = "Ranges"
TAB_HISTORY = "History"
TAB_TOOLS = "Tools"
TAB_ABOUT = "About"
APP_TABS = (TAB_HOME, TAB_ANALYZE, TAB_RANGES, TAB_HISTORY, TAB_ABOUT)
_LEGACY_TAB_MAP = {
    "Equity Calculator": TAB_ANALYZE,
    "Range Builder": TAB_RANGES,
    "Hand History": TAB_HISTORY,
    "Hand Eval (Dev)": TAB_TOOLS,
    "Tools": TAB_TOOLS,
}

RANGE_RANKS = ("A", "K", "Q", "J", "T", "9", "8", "7", "6", "5", "4", "3", "2")
RANGE_NS_OPPONENT = "opponent"
RANGE_NS_HERO = "hero"
HERO_MODE_SINGLE = "Single Hand"
HERO_MODE_RANGE = "Hero Range"
SUIT_NAMES = {"h": "Hearts", "d": "Diamonds", "c": "Clubs", "s": "Spades"}
SUIT_SYMBOLS = {"h": "♥", "d": "♦", "c": "♣", "s": "♠"}
SUIT_STYLES = {
    "h": {
        "background": "#dc2626",
        "gradient": "linear-gradient(180deg, #ef4444 0%, #dc2626 48%, #b91c1c 100%)",
        "border": "#b91c1c",
        "selected_border": "rgba(254, 202, 202, 0.9)",
        "text": "#fecaca",
        "selected_glow": "0 0 0 1.5px rgba(254, 202, 202, 0.42), 0 0 16px rgba(248, 113, 113, 0.42)",
    },
    "d": {
        "background": "#0284c7",
        "gradient": "linear-gradient(180deg, #38bdf8 0%, #0ea5e9 42%, #0284c7 100%)",
        "border": "#0369a1",
        "selected_border": "rgba(186, 230, 253, 0.95)",
        "text": "#bae6fd",
        "selected_glow": "0 0 0 1.5px rgba(125, 211, 252, 0.42), 0 0 16px rgba(14, 165, 233, 0.4)",
    },
    "c": {
        "background": "#16a34a",
        "gradient": "linear-gradient(180deg, #22c55e 0%, #16a34a 48%, #15803d 100%)",
        "border": "#15803d",
        "selected_border": "rgba(187, 247, 208, 0.9)",
        "text": "#bbf7d0",
        "selected_glow": "0 0 0 1.5px rgba(187, 247, 208, 0.4), 0 0 16px rgba(34, 197, 94, 0.38)",
    },
    "s": {
        "background": "#64748b",
        "gradient": "linear-gradient(180deg, #94a3b8 0%, #64748b 48%, #475569 100%)",
        "border": "#94a3b8",
        "selected_border": "rgba(241, 245, 249, 0.95)",
        "text": "#f8fafc",
        "selected_glow": "0 0 0 1.5px rgba(241, 245, 249, 0.4), 0 0 16px rgba(148, 163, 184, 0.48)",
    },
}

BOARD_CARD_WIDTH = 98
BOARD_CARD_HEIGHT = 128
HERO_CARD_WIDTH = 119
HERO_CARD_HEIGHT = 156
BOARD_STREET_GAP = 0.42
BOARD_ROW_MAX_WIDTH_REM = 36
BOARD_LABEL_FONT_REM = 0.72
CARD_RADIUS_PX = 12
_POCKET_PAIR_NAMES = {
    "A": "Aces",
    "K": "Kings",
    "Q": "Queens",
    "J": "Jacks",
    "T": "Tens",
    "9": "Nines",
    "8": "Eights",
    "7": "Sevens",
    "6": "Sixes",
    "5": "Fives",
    "4": "Fours",
    "3": "Threes",
    "2": "Twos",
}


def main() -> None:
    favicon = _ensure_equitylab_favicon()
    st.set_page_config(
        page_title="EquityLab",
        page_icon=str(favicon),
        layout="wide",
        initial_sidebar_state="collapsed",
        menu_items={
            "Get Help": None,
            "Report a Bug": None,
            "About": None,
        },
    )
    _initialize_state()
    _inject_styles()
    _render_tab_navigation()

    if st.session_state.active_tab == TAB_HOME:
        _render_home_page()
    elif st.session_state.active_tab == TAB_ANALYZE:
        _render_equity_calculator_tab()
    elif st.session_state.active_tab == TAB_RANGES:
        _render_range_builder_tab()
    elif st.session_state.active_tab == TAB_HISTORY:
        _render_hand_history_tab()
    elif st.session_state.active_tab == TAB_TOOLS:
        _render_hand_eval_dev_tab()
    else:
        _render_about_tab()


def _svg_data_uri_img(
    svg: str,
    *,
    css_class: str,
    width: int,
    height: int,
    alt: str = "",
) -> str:
    """Embed SVG via data-URI <img> so Streamlit st.html (DOMPurify) does not strip it."""
    b64 = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return (
        f'<img class="{css_class}" width="{width}" height="{height}" alt="{escape(alt)}" '
        f'src="data:image/svg+xml;base64,{b64}"/>'
    )


def _equitylab_logo_svg(*, size: int = 36) -> str:
    """Rounded tile mark: coral rising bars + white equity line."""
    svg = (
        '<svg class="el-logo-mark" viewBox="0 0 32 32" width="32" height="32" '
        'fill="none" aria-hidden="true" xmlns="http://www.w3.org/2000/svg">'
        '<rect x="1.5" y="1.5" width="29" height="29" rx="7.5" fill="#111827" '
        'stroke="#1f2937" stroke-width="1"/>'
        '<rect x="7" y="18.5" width="4.2" height="7" rx="1" fill="#fb7185"/>'
        '<rect x="13.9" y="13.5" width="4.2" height="12" rx="1" fill="#f43f5e"/>'
        '<rect x="20.8" y="8.5" width="4.2" height="17" rx="1" fill="#e11d48"/>'
        '<path d="M8.2 20.2 L12.6 16.4 L17.4 17.8 L25.2 9.2" '
        'stroke="#f8fafc" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/>'
        '<circle cx="25.2" cy="9.2" r="1.45" fill="#ffffff"/>'
        "</svg>"
    )
    return _svg_data_uri_img(svg, css_class="el-logo-mark", width=size, height=size, alt="")


def _equitylab_wordmark_html() -> str:
    """Brand wordmark: Equity in white, Lab in coral (#fb7185)."""
    return (
        '<span class="el-nav-wordmark">'
        '<span class="el-nav-wordmark-equity">Equity</span>'
        '<span class="el-nav-wordmark-lab">Lab</span>'
        "</span>"
    )


def _ensure_equitylab_favicon() -> Path:
    """Write a code-generated PNG favicon matching the SVG mark (no external assets)."""
    import math
    import struct
    import zlib

    FAVICON_PATH.parent.mkdir(parents=True, exist_ok=True)
    size = 32
    coral = (251, 113, 133, 255)
    cyan = (56, 189, 248, 255)

    def sd_rounded_box(px: float, py: float, cx: float, cy: float, hw: float, hh: float, radius: float) -> float:
        dx = abs(px - cx) - hw + radius
        dy = abs(py - cy) - hh + radius
        outside = math.hypot(max(dx, 0.0), max(dy, 0.0))
        inside = min(max(dx, dy), 0.0)
        return outside + inside - radius

    def dist_to_segment(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
        abx, aby = bx - ax, by - ay
        apx, apy = px - ax, py - ay
        ab2 = abx * abx + aby * aby
        t = 0.0 if ab2 == 0 else max(0.0, min(1.0, (apx * abx + apy * aby) / ab2))
        return math.hypot(px - (ax + abx * t), py - (ay + aby * t))

    # Geometry mirrors _equitylab_logo_svg viewBox 0..32
    card_cx, card_cy = 16.0, 16.0
    card_hw, card_hh, card_r = 8.0, 12.0, 3.25
    stroke = 0.95
    line = [(11.5, 20.75), (14.75, 15.25), (17.75, 17.1), (22.25, 9.75)]
    endpoint = (22.25, 9.75)
    endpoint_r = 1.55

    raw = bytearray()
    for y in range(size):
        raw.append(0)
        for x in range(size):
            px, py = x + 0.5, y + 0.5
            color = (0, 0, 0, 0)
            card_d = abs(sd_rounded_box(px, py, card_cx, card_cy, card_hw, card_hh, card_r))
            if card_d <= stroke:
                color = coral
            line_d = min(
                dist_to_segment(px, py, line[i][0], line[i][1], line[i + 1][0], line[i + 1][1])
                for i in range(len(line) - 1)
            )
            if line_d <= stroke:
                color = cyan
            if math.hypot(px - endpoint[0], py - endpoint[1]) <= endpoint_r:
                color = cyan
            raw.extend(color)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    png += chunk(b"IEND", b"")
    FAVICON_PATH.write_bytes(png)
    return FAVICON_PATH


def _home_feature_icon(kind: str) -> str:
    icons = {
        "ranges": (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="22" height="22" fill="none">'
            '<circle cx="9" cy="8" r="2.5" stroke="#c4b5fd" stroke-width="1.7"/>'
            '<circle cx="15.6" cy="8.6" r="2.2" stroke="#a78bfa" stroke-width="1.7"/>'
            '<path d="M4.2 18.2c.7-2.7 2.6-4.1 4.8-4.1s4.1 1.4 4.8 4.1" stroke="#c4b5fd" '
            'stroke-width="1.7" stroke-linecap="round"/>'
            '<path d="M13.4 14.4c1.6-.45 3.3.15 4.2 2.35" stroke="#a78bfa" stroke-width="1.7" '
            'stroke-linecap="round"/>'
            "</svg>"
        ),
        "simulation": (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="22" height="22" fill="none">'
            '<path d="M12 4.2 L19.2 8.1 L12 12 L4.8 8.1 Z" stroke="#7dd3fc" stroke-width="1.65" '
            'stroke-linejoin="round"/>'
            '<path d="M4.8 8.1 V15.8 L12 19.7 V12" stroke="#38bdf8" stroke-width="1.65" '
            'stroke-linejoin="round"/>'
            '<path d="M19.2 8.1 V15.8 L12 19.7" stroke="#0ea5e9" stroke-width="1.65" '
            'stroke-linejoin="round"/>'
            "</svg>"
        ),
        "decision": (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="22" height="22" fill="none">'
            '<text x="12" y="17" text-anchor="middle" font-size="16" font-weight="700" '
            'font-family="Georgia, serif" fill="#86efac">Σ</text>'
            "</svg>"
        ),
        "heatmap": (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="22" height="22" fill="none">'
            '<rect x="3.2" y="3.2" width="5.2" height="5.2" rx="1.1" fill="#fb7185"/>'
            '<rect x="9.4" y="3.2" width="5.2" height="5.2" rx="1.1" fill="#fdba74"/>'
            '<rect x="15.6" y="3.2" width="5.2" height="5.2" rx="1.1" fill="#64748b"/>'
            '<rect x="3.2" y="9.4" width="5.2" height="5.2" rx="1.1" fill="#fdba74"/>'
            '<rect x="9.4" y="9.4" width="5.2" height="5.2" rx="1.1" fill="#fb7185"/>'
            '<rect x="15.6" y="9.4" width="5.2" height="5.2" rx="1.1" fill="#f97316"/>'
            '<rect x="3.2" y="15.6" width="5.2" height="5.2" rx="1.1" fill="#64748b"/>'
            '<rect x="9.4" y="15.6" width="5.2" height="5.2" rx="1.1" fill="#f97316"/>'
            '<rect x="15.6" y="15.6" width="5.2" height="5.2" rx="1.1" fill="#fb7185"/>'
            "</svg>"
        ),
    }
    return _svg_data_uri_img(icons[kind], css_class="el-home-card-icon-art", width=26, height=26)


def _home_cred_icon(kind: str) -> str:
    icons = {
        "engine": (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="15" height="15" fill="none">'
            '<ellipse cx="12" cy="6.4" rx="6.2" ry="2.1" stroke="#fb7185" stroke-width="1.55"/>'
            '<path d="M5.8 6.4 V10 C5.8 11.15 8.5 12.1 12 12.1 S18.2 11.15 18.2 10 V6.4" '
            'stroke="#fb7185" stroke-width="1.55"/>'
            '<path d="M5.8 10 V13.6 C5.8 14.75 8.5 15.7 12 15.7 S18.2 14.75 18.2 13.6 V10" '
            'stroke="#fb7185" stroke-width="1.55"/>'
            '<path d="M5.8 13.6 V17.2 C5.8 18.35 8.5 19.3 12 19.3 S18.2 18.35 18.2 17.2 V13.6" '
            'stroke="#fb7185" stroke-width="1.55"/>'
            "</svg>"
        ),
        "storage": (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="15" height="15" fill="none">'
            '<ellipse cx="12" cy="6" rx="6.6" ry="2.2" stroke="#a78bfa" stroke-width="1.55"/>'
            '<path d="M5.4 6 V11.6 C5.4 12.8 8.3 13.8 12 13.8 S18.6 12.8 18.6 11.6 V6" '
            'stroke="#a78bfa" stroke-width="1.55"/>'
            '<path d="M5.4 11.6 V17.2 C5.4 18.4 8.3 19.4 12 19.4 S18.6 18.4 18.6 17.2 V11.6" '
            'stroke="#a78bfa" stroke-width="1.55"/>'
            "</svg>"
        ),
        "tests": (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="15" height="15" fill="none">'
            '<circle cx="12" cy="12" r="7.4" stroke="#38bdf8" stroke-width="1.55"/>'
            '<path d="M8.3 12.15 L10.85 14.7 L15.8 9.5" stroke="#38bdf8" stroke-width="1.75" '
            'stroke-linecap="round" stroke-linejoin="round"/>'
            "</svg>"
        ),
        "sampling": (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="15" height="15" fill="none">'
            '<path d="M3.2 12.2 H7 L9.4 6.8 L12.5 17.2 L15 10.8 H20.8" stroke="#4ade80" '
            'stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round"/>'
            "</svg>"
        ),
    }
    return _svg_data_uri_img(icons[kind], css_class="el-home-cred-icon-art", width=15, height=15)


def _home_hero_art_svg() -> str:
    """Hero illustration as self-contained SVG (served via data-URI img for Streamlit)."""
    heatmap = []
    palette = (
        "#1e293b", "#334155", "#581c87", "#7c3aed", "#9f1239", "#be123c",
        "#e11d48", "#fb7185", "#38bdf8", "#0ea5e9", "#881337", "#4c1d95",
    )
    n, cell, gap = 13, 8, 1.4
    step = cell + gap
    for row in range(n):
        for col in range(n):
            hot = abs(row - col) <= 2 or (row + col) % 6 == 0
            color = palette[(row * 5 + col * 3) % len(palette)]
            opacity = 0.92 if hot else 0.2 + (row + col) % 4 * 0.07
            heatmap.append(
                f'<rect x="{col * step:.1f}" y="{row * step:.1f}" width="{cell}" height="{cell}" '
                f'rx="1.4" fill="{color}" opacity="{opacity:.2f}"/>'
            )
    grid_size = n * step - gap
    svg = f"""<svg viewBox="0 0 560 400" width="560" height="400"
         fill="none" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Equity analysis visualization">
      <defs>
        <linearGradient id="elHCardFill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="#f8fafc"/>
          <stop offset="100%" stop-color="#e2e8f0"/>
        </linearGradient>
        <linearGradient id="elHChartLine" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stop-color="#fb7185"/>
          <stop offset="100%" stop-color="#f472b6"/>
        </linearGradient>
        <filter id="elHGlowBlue" x="-50%" y="-50%" width="200%" height="200%">
          <feDropShadow dx="0" dy="0" stdDeviation="8" flood-color="#38bdf8" flood-opacity="0.7"/>
        </filter>
        <filter id="elHGlowPink" x="-50%" y="-50%" width="200%" height="200%">
          <feDropShadow dx="0" dy="0" stdDeviation="8" flood-color="#fb7185" flood-opacity="0.65"/>
        </filter>
      </defs>
      <g transform="translate(48, 0)">
      <g opacity="0.9" transform="translate(24, 210)">
        <path d="M0 56 C40 50, 58 38, 86 30 C120 20, 132 38, 162 18 C192 2, 214 12, 280 4"
              stroke="#38bdf8" stroke-width="2.2" stroke-linecap="round" opacity="0.8"/>
        <path d="M0 64 C34 58, 52 50, 78 42 C108 32, 124 50, 150 32 C178 14, 204 20, 280 8"
              stroke="url(#elHChartLine)" stroke-width="2.8" stroke-linecap="round"/>
        <circle cx="280" cy="8" r="4" fill="#fda4af"/>
      </g>
      <g transform="translate(300, 16) rotate(-3)">
        <rect x="-8" y="-8" width="{grid_size + 16:.0f}" height="{grid_size + 16:.0f}" rx="10"
              fill="rgba(15,23,42,0.62)" stroke="rgba(148,163,184,0.2)"/>
        <g>{''.join(heatmap)}</g>
      </g>
      <g transform="translate(88, 48) rotate(-15)" filter="url(#elHGlowBlue)">
        <rect width="88" height="122" rx="12" fill="url(#elHCardFill)" stroke="#38bdf8" stroke-width="2.2"/>
        <text x="14" y="26" fill="#0f172a" font-size="16" font-weight="800" font-family="Inter,sans-serif">A</text>
        <text x="44" y="72" fill="#0f172a" font-size="34" font-weight="800" text-anchor="middle" font-family="Inter,sans-serif">&#9824;</text>
      </g>
      <g transform="translate(178, 70) rotate(12)" filter="url(#elHGlowPink)">
        <rect width="88" height="122" rx="12" fill="url(#elHCardFill)" stroke="#fb7185" stroke-width="2.2"/>
        <text x="14" y="26" fill="#e11d48" font-size="16" font-weight="800" font-family="Inter,sans-serif">K</text>
        <text x="44" y="72" fill="#e11d48" font-size="34" font-weight="800" text-anchor="middle" font-family="Inter,sans-serif">&#9829;</text>
      </g>
      <g transform="translate(40, 142) rotate(-4)">
        <rect width="136" height="72" rx="12" fill="rgba(15,23,42,0.86)" stroke="rgba(74,222,128,0.28)" stroke-width="1.2"/>
        <text x="16" y="26" fill="#86efac" font-size="11" font-weight="600" font-family="Inter,sans-serif">Equity</text>
        <text x="120" y="28" fill="#4ade80" font-size="16" font-weight="800" text-anchor="end" font-family="Inter,sans-serif">65.3%</text>
        <text x="16" y="52" fill="#86efac" font-size="11" font-weight="600" font-family="Inter,sans-serif">EV</text>
        <text x="120" y="54" fill="#4ade80" font-size="16" font-weight="800" text-anchor="end" font-family="Inter,sans-serif">+1.27</text>
      </g>
      </g>
    </svg>"""
    return _svg_data_uri_img(
        svg,
        css_class="el-home-hero-art",
        width=560,
        height=400,
        alt="Equity analysis visualization with cards, heatmap, and chart",
    )


def _home_feature_cards_html() -> str:
    features = (
        ("ranges", "ranges", "Weighted Range Builder",
         "Construct and refine opponent ranges with precise hand weights from 0–100%."),
        ("simulation", "simulation", "Monte Carlo Equity Engine",
         "Estimate heads-up equity with a custom simulator that switches to exact enumeration when feasible."),
        ("decision", "decision", "EV and Decision Explanation",
         "Translate equity into call EV, required equity, confidence, and clear mathematical reasoning."),
        ("heatmap", "heatmap", "Interactive Equity Heatmap",
         "Explore a 13×13 starting-hand matrix and load any hand into the analyzer with one click."),
    )
    return "".join(
        "<article class='el-home-card'>"
        f"<div class='el-home-card-icon el-home-card-icon-{tone}'>{_home_feature_icon(kind)}</div>"
        "<div class='el-home-card-copy'>"
        f"<h3 class='el-home-card-title'>{escape(title)}</h3>"
        f"<p class='el-home-card-body'>{escape(body)}</p>"
        "</div></article>"
        for kind, tone, title, body in features
    )


def _home_credibility_html() -> str:
    items = (
        ("engine", "Custom poker evaluation engine"),
        ("storage", "Persistent SQLite storage"),
        ("tests", "91 automated tests"),
        ("sampling", "Weighted Monte Carlo sampling"),
    )
    return "".join(
        "<li class='el-home-cred-item'>"
        f"<span class='el-home-cred-icon el-home-cred-icon-{kind}'>{_home_cred_icon(kind)}</span>"
        f"<span class='el-home-cred-label'>{escape(label)}</span>"
        "</li>"
        for kind, label in items
    )


def _home_hero_section_html() -> str:
    return f"""
    <div class="el-home-page">
      <div class="el-home-container">
        <section class="el-home-hero" aria-label="Hero">
          <div class="el-home-hero-copy">
            <p class="el-home-eyebrow">Poker Decision Intelligence</p>
            <h1 class="el-home-headline">
              <span class="el-home-headline-line">
                Make better <span class="el-home-gradient-text">poker</span>
              </span>
              <span class="el-home-headline-line">
                <span class="el-home-gradient-text">decisions</span> with data
              </span>
            </h1>
            <p class="el-home-supporting">
              Analyze weighted ranges, calculate equity and EV, explore board texture,
              and understand why a decision is profitable.
            </p>
          </div>
          <div class="el-home-hero-art-wrap">
            <div class="el-home-art-glow el-home-art-glow-a"></div>
            <div class="el-home-art-glow el-home-art-glow-b"></div>
            <div class="el-home-art-glow el-home-art-glow-c"></div>
            <div class="el-home-art-glow el-home-art-glow-d"></div>
            <div class="el-home-art-floor"></div>
            {_home_hero_art_svg()}
          </div>
        </section>
      </div>
    </div>
    """


def _home_why_html() -> str:
    points = (
        "Weighted opponent ranges",
        "Custom Monte Carlo engine",
        "EV and pot-odds analysis",
        "Deterministic decision explanations",
        "Interactive 13×13 equity heatmap",
    )
    items = "".join(
        f'<li class="el-home-why-item">{escape(point)}</li>' for point in points
    )
    return f'<ul class="el-home-why-list">{items}</ul>'


def _home_lower_sections_html() -> str:
    return f"""
    <div class="el-home-container">
      <section class="el-home-preview">
        <h2 class="el-home-section-label">Core Features</h2>
        <div class="el-home-card-grid">{_home_feature_cards_html()}</div>
      </section>
      <section class="el-home-why">
        <h2 class="el-home-section-label">Why EquityLab?</h2>
        {_home_why_html()}
      </section>
      <section class="el-home-credibility">
        <h2 class="el-home-section-label">Built with engineering rigor</h2>
        <ul class="el-home-cred-list">{_home_credibility_html()}</ul>
      </section>
    </div>
    """


def _render_page_header() -> None:
    """Compact product mark shown above app pages (not the Home landing)."""
    st.html(
        f"""
        <header class="el-brand">
          <div class="el-brand-row">
            {_equitylab_logo_svg(size=26)}
            <div class="el-brand-name el-brand-name-compact">{_equitylab_wordmark_html()}</div>
          </div>
        </header>
        """
    )


def _render_tab_navigation() -> None:
    is_home = st.session_state.active_tab == TAB_HOME
    if is_home:
        st.markdown('<div class="el-home-active" aria-hidden="true"></div>', unsafe_allow_html=True)
        left, center, right = st.columns([1.15, 2.7, 1.15], gap="small")
        with left:
            st.html(
                f'<div class="el-nav-brand el-home-nav-brand">{_equitylab_logo_svg(size=33)}'
                f"{_equitylab_wordmark_html()}</div>"
            )
        with center:
            tab_cols = st.columns(len(APP_TABS), gap="small")
            for index, tab in enumerate(APP_TABS):
                tab_cols[index].button(
                    tab,
                    key=f"nav-{tab}",
                    type="primary" if st.session_state.active_tab == tab else "secondary",
                    on_click=_set_active_tab,
                    args=(tab,),
                    use_container_width=True,
                )
        with right:
            st.html('<div class="el-home-nav-right" aria-hidden="true"></div>')
        st.html('<div class="el-nav-rule el-home-nav-rule"></div>')
        return

    brand_col, nav_col = st.columns([0.24, 0.76], gap="small")
    with brand_col:
        st.html(
            f'<div class="el-nav-brand">{_equitylab_logo_svg(size=26)}'
            f"{_equitylab_wordmark_html()}</div>"
        )
    with nav_col:
        columns = st.columns(len(APP_TABS), gap="small")
        for index, tab in enumerate(APP_TABS):
            columns[index].button(
                tab,
                key=f"nav-{tab}",
                type="primary" if st.session_state.active_tab == tab else "secondary",
                on_click=_set_active_tab,
                args=(tab,),
                use_container_width=True,
            )
    st.html('<div class="el-nav-rule" aria-hidden="true"></div>')


def _set_active_tab(tab: str) -> None:
    st.session_state.active_tab = tab


def _render_home_page() -> None:
    """Home landing — single wide container, CSS Grid hero, no Streamlit columns."""
    st.html(_home_hero_section_html())

    hero_cta_left, _hero_cta_right = st.columns([1.05, 0.95], gap="large")
    with hero_cta_left:
        cta_primary, cta_secondary = st.columns([0.58, 0.42], gap="small")
        with cta_primary:
            st.button(
                "Start Analyzing →",
                type="primary",
                use_container_width=True,
                key="home-cta-analyze",
                on_click=_set_active_tab,
                args=(TAB_ANALYZE,),
            )
        with cta_secondary:
            st.button(
                "Build a Range",
                type="secondary",
                use_container_width=True,
                key="home-cta-ranges",
                on_click=_set_active_tab,
                args=(TAB_RANGES,),
            )

    st.html(_home_lower_sections_html())


def _render_equity_calculator_tab() -> None:
    flash = st.session_state.pop("hand_history_flash", None)
    if flash:
        st.success(flash)

    st.html('<h2 class="el-page-title el-analyze-title">Analyze</h2>')
    _render_quick_examples()
    st.html('<div class="el-analyze-divider" aria-hidden="true"></div>')
    _render_calculation_progress()

    st.markdown('<div class="el-analyze-layout-anchor" aria-hidden="true"></div>', unsafe_allow_html=True)
    layout_cols = st.columns([2.35, 1], gap="large")
    with layout_cols[0]:
        hero_input = _render_hero_hand_picker()
        st.markdown('<div class="section-gap-hand-board" aria-hidden="true"></div>', unsafe_allow_html=True)
        board_input = _render_board_card_picker()
        st.markdown('<div class="section-gap" aria-hidden="true"></div>', unsafe_allow_html=True)

        opponent_label, pot_size, call_amount, simulations = _render_calculation_settings_panel()
        calc_ready = _calculator_inputs_are_ready(opponent_label=opponent_label)

        st.markdown('<div class="el-calc-block-gap-sm" aria-hidden="true"></div>', unsafe_allow_html=True)
        if st.button(
            "Run Monte Carlo Simulation →",
            type="primary",
            use_container_width=True,
            disabled=not calc_ready,
            key="calculate-equity-btn",
        ):
            trials = int(simulations)
            with st.spinner(f"Running {trials:,} Monte Carlo trials…"):
                _calculate_and_store_analysis(
                    hero_input, board_input, opponent_label, pot_size, call_amount, simulations
                )
            st.session_state.scroll_to_results = True

        if not calc_ready:
            st.html(_calculation_warning_card_html(opponent_label))

    with layout_cols[1]:
        _render_calculation_summary(
            st.session_state.calc_opponent_range,
            float(st.session_state.calc_pot_size),
            float(st.session_state.calc_call_amount),
        )

    _render_latest_calculator_results()
    _maybe_scroll_to_results()


def _format_trial_preset_label(trials: int) -> str:
    if trials >= 1_000:
        thousands = trials // 1_000
        return f"{thousands}k"
    return str(trials)


def _normalize_monte_carlo_trials(value: int | float | None) -> int:
    try:
        trials = int(value or DEFAULT_MONTE_CARLO_TRIALS)
    except (TypeError, ValueError):
        return DEFAULT_MONTE_CARLO_TRIALS
    if trials in MONTE_CARLO_PRESETS:
        return trials
    return min(MONTE_CARLO_PRESETS, key=lambda preset: abs(preset - trials))


def _monte_carlo_runtime_estimate(trials: int) -> str:
    trials = _normalize_monte_carlo_trials(trials)
    estimates = {
        10_000: "~0.5–1s",
        25_000: "~1–2s",
        50_000: "~2–4s",
        100_000: "~4–8s",
        250_000: "~10–20s",
    }
    return estimates.get(trials, "~1–2s")


def _monte_carlo_accuracy_label(trials: int) -> str:
    trials = _normalize_monte_carlo_trials(trials)
    labels = {
        10_000: "Good",
        25_000: "High",
        50_000: "Very high",
        100_000: "Excellent",
        250_000: "Maximum",
    }
    return labels.get(trials, "High")


def _accuracy_tone_class(label: str) -> str:
    """Muted color class for accuracy labels — does not change the label text."""
    lower = str(label).strip().lower()
    if lower in {"excellent", "maximum", "very high"}:
        return "el-sim-acc-excellent"
    if lower == "high":
        return "el-sim-acc-high"
    if lower == "good":
        return "el-sim-acc-good"
    if lower in {"moderate", "fair"}:
        return "el-sim-acc-moderate"
    return "el-sim-acc-high"


def _set_monte_carlo_trials(trials: int) -> None:
    normalized = _normalize_monte_carlo_trials(trials)
    st.session_state.calc_simulations = normalized
    st.session_state["_calc_simulations"] = normalized


def _bump_calc_amount(key: str, delta: float) -> None:
    current = float(st.session_state.get(key, 0.0) or 0.0)
    updated = max(0.0, round(current + delta, 2))
    st.session_state[key] = updated
    # Keep the visible number_input widget key in sync when present.
    widget_key = f"{key}__input"
    st.session_state[widget_key] = updated


def _ensure_pot_call_defaults() -> None:
    """Guarantee pot/call defaults of 100/25 (20% required equity).

    Uses dedicated ``*__input`` widget keys so a stuck Streamlit min_value of 0
    on the old ``calc_pot_size`` / ``calc_call_amount`` keys cannot win.
    """
    pot = float(
        st.session_state.get(
            "calc_pot_size__input",
            st.session_state.get(
                "calc_pot_size",
                st.session_state.get("_calc_pot_size", DEFAULT_POT_SIZE),
            ),
        )
        or 0.0
    )
    call = float(
        st.session_state.get(
            "calc_call_amount__input",
            st.session_state.get(
                "calc_call_amount",
                st.session_state.get("_calc_call_amount", DEFAULT_CALL_AMOUNT),
            ),
        )
        or 0.0
    )

    if pot == 0.0 and call == 0.0:
        pot, call = DEFAULT_POT_SIZE, DEFAULT_CALL_AMOUNT

    st.session_state.calc_pot_size = pot
    st.session_state.calc_call_amount = call
    st.session_state["_calc_pot_size"] = pot
    st.session_state["_calc_call_amount"] = call
    st.session_state["calc_pot_size__input"] = pot
    st.session_state["calc_call_amount__input"] = call


def _calculation_warning_copy(opponent_label: str | None = None) -> tuple[str, str]:
    """Return (message, tone) where tone is 'warn' or 'info'."""
    if not _hero_hand_is_complete():
        return "Select both hero cards to continue.", "warn"
    if not _board_selection_is_complete():
        return "Complete the board street, or clear it for preflop.", "warn"
    if not _opponent_range_is_complete(opponent_label):
        return "Choose a preset range or add hands to your custom range.", "warn"
    if not _calculation_settings_are_valid():
        return "Check pot size, call amount, or trial settings.", "warn"
    return "Complete the remaining calculator inputs to continue.", "info"


def _calculation_warning_card_html(opponent_label: str | None = None) -> str:
    message, tone = _calculation_warning_copy(opponent_label)
    is_warn = tone == "warn"
    stroke = "#fda4af" if is_warn else "#7dd3fc"
    icon = _lucide_icon_data_uri("alert-triangle" if is_warn else "lightbulb", size=14, stroke=stroke)
    tone_class = "el-calc-validation-warn" if is_warn else "el-calc-validation-info"
    return f"""
    <div class="el-calc-validation {tone_class}" role="status">
      <img class="el-calc-validation-icon" src="{icon}" alt="" width="14" height="14"/>
      <span class="el-calc-validation-msg">{escape(message)}</span>
    </div>
    """


def _calculation_tip_card_html() -> str:
    icon = _lucide_icon_data_uri("lightbulb", size=16, stroke="#38bdf8")
    body = "Select hero cards, an optional board, and an opponent range to estimate equity and EV."
    return f"""
    <div class="el-calc-tip">
      <img class="el-calc-tip-icon" src="{icon}" alt="" width="16" height="16"/>
      <div class="el-calc-tip-copy">
        <div class="el-calc-tip-kicker">Tip</div>
        <div class="el-calc-tip-body">{escape(body)}</div>
      </div>
    </div>
    """


def _simulation_info_panel_html(trials: int) -> str:
    trials = _normalize_monte_carlo_trials(trials)
    runtime = _monte_carlo_runtime_estimate(trials)
    accuracy = _monte_carlo_accuracy_label(trials)
    acc_class = _accuracy_tone_class(accuracy)
    trials_icon = _lucide_icon_data_uri("bar-chart-3", size=15, stroke="#cbd5e1")
    runtime_icon = _lucide_icon_data_uri("zap", size=15, stroke="#cbd5e1")
    accuracy_icon = _lucide_icon_data_uri("target", size=15, stroke="#cbd5e1")
    return f"""
    <div class="el-sim-info" aria-label="Simulation info">
      <div class="el-sim-stat">
        <div class="el-sim-info-label-row">
          <img src="{trials_icon}" alt="" width="15" height="15"/>
          <span class="el-sim-info-label">Trials</span>
        </div>
        <span class="el-sim-info-value">{escape(f"{trials:,}")}</span>
      </div>
      <div class="el-sim-stat">
        <div class="el-sim-info-label-row">
          <img src="{runtime_icon}" alt="" width="15" height="15"/>
          <span class="el-sim-info-label">Est. runtime</span>
        </div>
        <span class="el-sim-info-value">{escape(runtime)}</span>
      </div>
      <div class="el-sim-stat">
        <div class="el-sim-info-label-row">
          <img src="{accuracy_icon}" alt="" width="15" height="15"/>
          <span class="el-sim-info-label">Accuracy</span>
        </div>
        <span class="el-sim-info-value {acc_class}">{escape(accuracy)}</span>
      </div>
    </div>
    """


def _field_label_html(title: str, *, icon: str) -> str:
    uri = _lucide_icon_data_uri(icon, size=15, stroke="#94a3b8")
    return (
        f'<div class="el-calc-field-label">'
        f'<img src="{uri}" alt="" width="15" height="15"/>'
        f"<span>{escape(title)}</span></div>"
    )


def _render_amount_stepper(label: str, *, icon: str, key: str, step: float = 5.0) -> float:
    st.html(_field_label_html(label, icon=icon))
    widget_key = f"{key}__input"
    if widget_key not in st.session_state:
        st.session_state[widget_key] = float(st.session_state.get(key, 0.0) or 0.0)

    minus_col, input_col, plus_col = st.columns([0.9, 2.15, 0.9], gap="medium")
    with minus_col:
        st.button(
            "−",
            key=f"{key}-minus",
            on_click=_bump_calc_amount,
            args=(key, -step),
            use_container_width=True,
        )
    with input_col:
        value = st.number_input(
            label,
            min_value=0.0,
            step=step,
            format="%.2f",
            key=widget_key,
            label_visibility="collapsed",
        )
    with plus_col:
        st.button(
            "+",
            key=f"{key}-plus",
            on_click=_bump_calc_amount,
            args=(key, step),
            use_container_width=True,
        )
    amount = float(value)
    st.session_state[key] = amount
    st.session_state[f"_{key}"] = amount
    return amount


def _render_monte_carlo_presets() -> int:
    current = _normalize_monte_carlo_trials(st.session_state.get("calc_simulations"))
    st.session_state.calc_simulations = current
    st.html(_field_label_html("Monte Carlo Trials", icon="cpu"))
    st.markdown('<div class="el-calc-preset-gap" aria-hidden="true"></div>', unsafe_allow_html=True)
    cols = st.columns(len(MONTE_CARLO_PRESETS), gap="small")
    for index, trials in enumerate(MONTE_CARLO_PRESETS):
        with cols[index]:
            is_active = current == trials
            st.button(
                _format_trial_preset_label(trials),
                key=f"mc-preset-{trials}",
                type="primary" if is_active else "secondary",
                use_container_width=True,
                on_click=_set_monte_carlo_trials,
                args=(trials,),
            )
    return int(st.session_state.calc_simulations)


def _render_calculation_settings_panel() -> tuple[str, float, float, int]:
    with st.container(border=True):
        st.markdown(
            _section_heading_html("Calculation Settings"),
            unsafe_allow_html=True,
        )
        st.html(_calculation_tip_card_html())
        st.markdown('<div class="el-calc-block-gap-sm" aria-hidden="true"></div>', unsafe_allow_html=True)

        st.html(_field_label_html("Opponent Range", icon="users"))
        range_col, edit_col = st.columns([3.4, 1.15], gap="small")
        with range_col:
            opponent_label = st.selectbox(
                "Opponent range",
                _opponent_range_options(),
                key="calc_opponent_range",
                label_visibility="collapsed",
            )
        with edit_col:
            if opponent_label == "Custom":
                st.button(
                    "Edit Range",
                    key="edit-custom-range",
                    on_click=_edit_custom_range,
                    use_container_width=True,
                )

        st.markdown('<div class="el-calc-block-gap-sm" aria-hidden="true"></div>', unsafe_allow_html=True)
        _ensure_pot_call_defaults()
        pot_col, call_col = st.columns(2, gap="medium")
        with pot_col:
            pot_size = _render_amount_stepper(
                "Pot Size",
                icon="coins",
                key="calc_pot_size",
            )
        with call_col:
            call_amount = _render_amount_stepper(
                "Amount to Call",
                icon="circle-dollar-sign",
                key="calc_call_amount",
            )

    st.markdown('<div class="section-gap-calc" aria-hidden="true"></div>', unsafe_allow_html=True)

    with st.container(border=True):
        st.markdown(
            _section_heading_html("Simulation Settings"),
            unsafe_allow_html=True,
        )
        st.html(
            '<p class="el-calc-section-sub">'
            "Configure the speed and accuracy of the Monte Carlo simulation."
            "</p>"
        )
        st.markdown('<div class="el-calc-block-gap-xs" aria-hidden="true"></div>', unsafe_allow_html=True)
        simulations = _render_monte_carlo_presets()
        st.markdown('<div class="el-calc-block-gap" aria-hidden="true"></div>', unsafe_allow_html=True)
        st.html(_simulation_info_panel_html(simulations))

    _snapshot_calculator_settings()
    return opponent_label, float(pot_size), float(call_amount), int(simulations)


def _mini_card_svg(
    *,
    x: float,
    y: float,
    rank: str,
    suit: str,
    suit_fill: str,
    rotate: float = 0.0,
    shadow_filter: str = "url(#elCardShadow)",
) -> str:
    """Miniature white playing-card; optional fan angle around card center."""
    w, h = 27.0, 37.0
    cx = w / 2
    cy = 23.0
    if suit == "spade":
        center = (
            f"<path fill='{suit_fill}' d='"
            f"M{cx} {cy - 8.6} "
            f"C{cx} {cy - 8.6} {cx - 7.4} {cy - 0.3} {cx - 7.4} {cy + 3.6} "
            f"A4.9 4.9 0 0 0 {cx} {cy + 9.6} "
            f"A4.9 4.9 0 0 0 {cx + 7.4} {cy + 3.6} "
            f"C{cx + 7.4} {cy - 0.3} {cx} {cy - 8.6} {cx} {cy - 8.6}Z'/>"
            f"<path fill='{suit_fill}' d='"
            f"M{cx - 1.2} {cy + 7.9} h2.4 v3.2 h1.35 v1.4 "
            f"H{cx - 2.55} v-1.4 h1.35Z'/>"
        )
    else:  # heart
        center = (
            f"<path fill='{suit_fill}' d='"
            f"M{cx} {cy + 9.2} "
            f"C{cx} {cy + 9.2} {cx - 9.2} {cy + 1.0} {cx - 9.2} {cy - 4.5} "
            f"C{cx - 9.2} {cy - 8.3} {cx - 6.1} {cy - 10.4} {cx - 3.15} {cy - 10.4} "
            f"C{cx - 1.25} {cy - 10.4} {cx - 0.25} {cy - 9.2} {cx} {cy - 7.7} "
            f"C{cx + 0.25} {cy - 9.2} {cx + 1.25} {cy - 10.4} {cx + 3.15} {cy - 10.4} "
            f"C{cx + 6.1} {cy - 10.4} {cx + 9.2} {cy - 8.3} {cx + 9.2} {cy - 4.5} "
            f"C{cx + 9.2} {cy + 1.0} {cx} {cy + 9.2} {cx} {cy + 9.2}Z'/>"
        )
    # Local coords (0,0); rotate around bottom-center so tops fan apart and stay readable.
    return (
        f"<g filter='{shadow_filter}' "
        f"transform='translate({x},{y}) rotate({rotate},{w / 2},{h})'>"
        f"<rect x='0' y='0' width='{w}' height='{h}' rx='3.8' "
        f"fill='#ffffff' stroke='#0f172a' stroke-width='1.55'/>"
        f"<text x='4.0' y='12.2' fill='#0f172a' font-size='12.5' "
        f"font-weight='800' font-family='ui-sans-serif, system-ui, sans-serif'>{rank}</text>"
        f"{center}"
        f"</g>"
    )


def _quick_example_icon_raw_svg(kind: str) -> str:
    """Dominant Quick Start illustration (64×64 viewBox)."""
    shadow_defs = (
        "<defs>"
        "<filter id='elCardShadow' x='-22%' y='-18%' width='155%' height='155%'>"
        "<feDropShadow dx='1.0' dy='1.6' stdDeviation='1.35' "
        "flood-color='#020617' flood-opacity='0.42'/>"
        "</filter>"
        "</defs>"
    )
    if kind == "aks":
        # Bottom-pivoted fan: both top ranks/suits stay readable inside the box
        art = (
            shadow_defs
            + _mini_card_svg(
                x=22, y=10, rank="K", suit="spade", suit_fill="#0f172a", rotate=22
            )
            + _mini_card_svg(
                x=8, y=10, rank="A", suit="spade", suit_fill="#0f172a", rotate=-20
            )
        )
    elif kind == "aa":
        art = (
            shadow_defs
            + _mini_card_svg(
                x=22, y=10, rank="A", suit="spade", suit_fill="#0f172a", rotate=22
            )
            + _mini_card_svg(
                x=8, y=10, rank="A", suit="heart", suit_fill="#fb7185", rotate=-20
            )
        )
    elif kind == "flush":
        art = (
            "<defs>"
            "<linearGradient id='elDropFill' x1='32' y1='3' x2='32' y2='58' "
            "gradientUnits='userSpaceOnUse'>"
            "<stop stop-color='#bae6fd'/>"
            "<stop offset='0.4' stop-color='#38bdf8'/>"
            "<stop offset='1' stop-color='#0369a1'/>"
            "</linearGradient>"
            "<linearGradient id='elDropShine' x1='20' y1='12' x2='30' y2='36' "
            "gradientUnits='userSpaceOnUse'>"
            "<stop stop-color='#ffffff' stop-opacity='0.9'/>"
            "<stop offset='1' stop-color='#ffffff' stop-opacity='0'/>"
            "</linearGradient>"
            "<filter id='elDropSoft' x='-18%' y='-12%' width='140%' height='140%'>"
            "<feDropShadow dx='0' dy='1.4' stdDeviation='1.6' "
            "flood-color='#0284c7' flood-opacity='0.38'/>"
            "</filter>"
            "</defs>"
            "<g filter='url(#elDropSoft)'>"
            "<path fill='url(#elDropFill)' "
            "d='M32 3.5 C32 3.5 13.5 23.5 13.5 37.0 A18.5 18.5 0 0 0 50.5 37.0 "
            "C50.5 23.5 32 3.5 32 3.5 Z'/>"
            "<path fill='url(#elDropShine)' "
            "d='M22.5 16.0 C20.5 21.2 19.4 26.6 19.8 31.0 C20.2 34.6 22.2 37.2 25.2 38.2 "
            "C23.0 34.4 22.4 30.0 23.8 25.6 C24.8 22.0 26.8 18.4 29.6 15.2 Z'/>"
            "</g>"
        )
    else:  # straight
        art = (
            "<path d='M6 32 H36' stroke='#34d399' stroke-width='8' "
            "stroke-linecap='round'/>"
            "<path d='M15 20 L4 32 L15 44' fill='none' stroke='#34d399' "
            "stroke-width='8' stroke-linecap='round' stroke-linejoin='round'/>"
            "<path d='M58 32 H28' stroke='#2dd4bf' stroke-width='8' "
            "stroke-linecap='round'/>"
            "<path d='M49 20 L60 32 L49 44' fill='none' stroke='#2dd4bf' "
            "stroke-width='8' stroke-linecap='round' stroke-linejoin='round'/>"
        )

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" '
        f'width="56" height="56" aria-hidden="true">{art}</svg>'
    )


def _quick_example_icon_svg(kind: str) -> str:
    """
    Quick Start icon markup.

    Streamlit's st.html DOMPurify profile (html-only) strips raw <svg> tags, so the
    SVG is embedded as a base64 data-URI <img> while remaining fully self-contained.
    """
    glow = {
        "aks": "el-qs-icon-coral",
        "aa": "el-qs-icon-coral",
        "flush": "el-qs-icon-cyan",
        "straight": "el-qs-icon-green",
    }.get(kind, "el-qs-icon-coral")
    svg = _quick_example_icon_raw_svg(kind)
    b64 = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return (
        f'<div class="el-qs-icon {glow}" aria-hidden="true">'
        f'<img class="el-qs-icon-art" width="56" height="56" alt="" '
        f'src="data:image/svg+xml;base64,{b64}"/>'
        f"</div>"
    )


def _render_quick_examples() -> None:
    bolt_svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" width="14" height="14">'
        '<path d="M9 1 L4 9 H8 L7 15 L12 7 H8 Z" fill="#fb7185"/>'
        "</svg>"
    )
    bolt_b64 = base64.b64encode(bolt_svg.encode("utf-8")).decode("ascii")
    # st.html allows <img>; raw <svg> is stripped by Streamlit's DOMPurify html profile.
    st.html(
        f"""
        <div class="el-qs-header">
          <div class="el-qs-kicker">
            <img class="el-qs-bolt" width="14" height="14" alt=""
                 src="data:image/svg+xml;base64,{bolt_b64}"/>
            <span>Quick Start</span>
          </div>
          <p class="el-qs-hint">Try one of these common poker situations to explore EquityLab instantly.</p>
        </div>
        """
    )
    active = st.session_state.get("active_quick_example")
    columns = st.columns(len(QUICK_EXAMPLES), gap="small")
    for index, example in enumerate(QUICK_EXAMPLES):
        is_active = active == index
        active_class = " el-qs-card-active" if is_active else ""
        with columns[index]:
            st.html(
                f"""
                <div class="el-qs-card{active_class}">
                  {_quick_example_icon_svg(str(example["icon"]))}
                  <div class="el-qs-copy">
                    <div class="el-qs-title">{escape(str(example["label"]))}</div>
                    <div class="el-qs-desc">{escape(str(example["description"]))}</div>
                  </div>
                  <div class="el-qs-arrow" aria-hidden="true">→</div>
                </div>
                """
            )
            st.button(
                "Load",
                key=f"quick-example-{index}",
                on_click=_apply_quick_example,
                args=(index,),
                use_container_width=True,
                type="secondary",
            )


def _board_count_is_complete(board_card_count: int) -> bool:
    """Preflop (0) or a full flop/turn/river (3/4/5) counts as complete; partial flop does not."""
    return board_card_count in {0, 3, 4, 5}


def _board_selection_is_complete() -> bool:
    return _board_count_is_complete(len(_selected_board_cards()))


def _is_opponent_range_complete(opponent_label: str, custom_hand_count: int) -> bool:
    if opponent_label == "Custom":
        return custom_hand_count > 0
    return opponent_label in RANGE_PRESETS


def _opponent_range_is_complete(opponent_label: str | None = None) -> bool:
    label = opponent_label if opponent_label is not None else st.session_state.get("calc_opponent_range", "Random")
    if label == "Custom":
        return _is_opponent_range_complete(label, len(_selected_range_weights()))
    return _is_opponent_range_complete(str(label), 0)


def _is_calculator_ready(
    *,
    hero_complete: bool,
    board_complete: bool,
    opponent_complete: bool,
    settings_complete: bool,
) -> bool:
    return hero_complete and board_complete and opponent_complete and settings_complete


def _calculator_inputs_are_ready(
    *,
    opponent_label: str | None = None,
) -> bool:
    return _is_calculator_ready(
        hero_complete=_hero_hand_is_complete(),
        board_complete=_board_selection_is_complete(),
        opponent_complete=_opponent_range_is_complete(opponent_label),
        settings_complete=_calculation_settings_are_valid(),
    )


def _workflow_step_states(
    *,
    hero_complete: bool,
    board_complete: bool,
    opponent_complete: bool,
    settings_complete: bool,
) -> list[tuple[str, str]]:
    """Return (label, state) for the Analyze stepper. States: incomplete, complete, active, ready."""
    ready = hero_complete and board_complete and opponent_complete and settings_complete

    def _state(complete: bool, is_current: bool) -> str:
        if complete:
            return "complete"
        if is_current:
            return "active"
        return "incomplete"

    # First incomplete step is the current/attention step.
    current = None
    if not hero_complete:
        current = "hero"
    elif not board_complete:
        current = "board"
    elif not opponent_complete:
        current = "opponent"
    elif not settings_complete:
        current = "settings"

    return [
        ("Hero Hand", _state(hero_complete, current == "hero")),
        ("Board Optional", _state(board_complete, current == "board")),
        ("Opponent Range", _state(opponent_complete, current == "opponent")),
        ("Settings", _state(settings_complete, current == "settings")),
        ("Calculate", "ready" if ready else "incomplete"),
    ]


def _render_calculation_progress() -> None:
    opponent_label = st.session_state.get("calc_opponent_range", "Random")
    steps = _workflow_step_states(
        hero_complete=_hero_hand_is_complete(),
        board_complete=_board_selection_is_complete(),
        opponent_complete=_opponent_range_is_complete(opponent_label),
        settings_complete=_calculation_settings_are_valid(),
    )
    parts: list[str] = ['<div class="el-stepper" role="list" aria-label="Calculation workflow">']
    for index, (label, state) in enumerate(steps):
        if index:
            parts.append('<div class="el-step-line" aria-hidden="true"></div>')
        node = "✓" if state == "complete" else str(index + 1)
        aria = ' aria-current="step"' if state in {"active", "ready"} else ""
        parts.append(
            f'<div class="el-step el-step-{state}" role="listitem"{aria}>'
            f'<span class="el-step-node" aria-hidden="true">{node}</span>'
            f'<span class="el-step-label">{escape(label)}</span>'
            f"</div>"
        )
    parts.append("</div>")
    st.html("".join(parts))


def _summary_label_html(title: str, *, icon: str) -> str:
    uri = _lucide_icon_data_uri(icon, size=13, stroke="#94a3b8")
    return (
        f'<span class="calc-summary-label">'
        f'<img class="calc-summary-label-icon" src="{uri}" alt="" width="13" height="13"/>'
        f"<span>{escape(title)}</span></span>"
    )


def _equity_vs_required_status(equity: float, required: float) -> tuple[str, float, str]:
    """Return (status_label, signed_diff, css_tone)."""
    diff = float(equity) - float(required)
    if abs(diff) < 0.005:
        return "Break-even", diff, "el-eq-status-even"
    if diff > 0:
        return "Above Required Equity", diff, "el-eq-status-above"
    return "Below Required Equity", diff, "el-eq-status-below"


def _simulation_confidence_from_trials(trials: int) -> str:
    trials = _normalize_monte_carlo_trials(trials)
    mapping = {
        10_000: "Low",
        25_000: "Medium",
        50_000: "High",
        100_000: "Very High",
        250_000: "Very High",
    }
    return mapping.get(trials, "Medium")


def _simulation_confidence_tone(level: str) -> str:
    return {
        "Low": "el-sim-conf-low",
        "Medium": "el-sim-conf-medium",
        "High": "el-sim-conf-high",
        "Very High": "el-sim-conf-very-high",
    }.get(level, "el-sim-conf-medium")


def _decision_why_bullets(analysis: dict) -> list[str]:
    """Decision-relevant bullets only — avoid restating the synthesis paragraph."""
    result = analysis["result"]
    decision = analysis["decision"]
    equity = float(result.equity)
    required = float(decision.required_equity)
    call_ev_value = float(decision.call_ev)
    margin_pp = (equity - required) * 100.0

    bullets = [
        f"{_format_percent(equity)} equity vs {_format_percent(required)} required "
        f"({margin_pp:+.1f} pp)",
        f"Call EV {call_ev_value:+.2f} chips",
    ]

    try:
        board_keys = str(analysis.get("board_input", "")).split()
        hero_keys = str(analysis.get("hero_input", "")).split()
        if len(board_keys) >= 3 and len(hero_keys) >= 2:
            payload = _live_board_analysis_payload(hero_keys[:2], board_keys)
            if payload.get("primary_draw"):
                bullets.append(f"Major draw: {payload['primary_draw']}")
            texture = payload.get("texture")
            # Only surface texture when it is distinctive (not a generic flop label alone).
            if texture and texture not in {None, "—", "Preflop", "Standard board"}:
                texture_l = str(texture).lower()
                if any(
                    token in texture_l
                    for token in ("monotone", "two-tone", "paired", "connected", "wet", "dry")
                ):
                    bullets.append(f"Board: {texture}")
    except (ValueError, TypeError, KeyError):
        pass

    return bullets[:4]


def _recommendation_visuals(recommendation: str) -> tuple[str, str, str]:
    """Return (css_modifier, lucide_icon, stroke) for the recommendation action."""
    key = str(recommendation).strip().lower()
    if key == "call":
        return "rec-call", "check-circle", "#86efac"
    if key == "fold":
        return "rec-fold", "x-circle", "#fda4af"
    if key == "check":
        return "rec-check", "circle-check", "#93c5fd"
    if key == "raise":
        return "rec-raise", "arrow-up", "#fcd34d"
    return "rec-fold", "x-circle", "#fda4af"


def _render_calculation_summary(opponent_label: str, pot_size: float, call_amount: float) -> None:
    status_message, status_class = _calculation_status_parts(opponent_label)
    hero_display = _hero_summary_display()
    required_equity = _required_equity_preview(pot_size, call_amount)
    title_icon = _lucide_icon_data_uri("bar-chart-3", size=18, stroke="#94a3b8")
    analysis = _get_latest_analysis()
    post_calc_html = _calculation_summary_results_html(analysis) if analysis else ""
    checklist_html = _calculation_summary_checklist_html(opponent_label)

    st.html(
        f"""
        <div class="calc-summary-panel">
          <div class="calc-summary-title">
            <img class="calc-summary-title-icon" src="{title_icon}" alt="" width="18" height="18"/>
            <span>Calculation Summary</span>
          </div>
          <div class="calc-summary-body">
            {checklist_html}
            <div class="calc-summary-item">
              {_summary_label_html("Hero", icon="user")}
              <span class="calc-summary-value">{escape(hero_display)}</span>
            </div>
            <div class="calc-summary-item">
              {_summary_label_html("Board", icon="layers")}
              <span class="calc-summary-value">{escape(_board_street_status())}</span>
            </div>
            <div class="calc-summary-item">
              {_summary_label_html("Opponent Range", icon="users")}
              <span class="calc-summary-value">{escape(_opponent_range_summary(opponent_label))}</span>
            </div>
            <div class="calc-summary-item">
              {_summary_label_html("Pot Odds / Required Equity", icon="percent")}
              <span class="calc-summary-value">{escape(required_equity)}</span>
            </div>
            <div class="calc-summary-status">
              <span class="status-badge {status_class}">{escape(status_message)}</span>
            </div>
            {post_calc_html}
          </div>
        </div>
        """
    )


def _calculation_summary_checklist_html(opponent_label: str) -> str:
    hero_ok = _hero_hand_is_complete()
    board_ok = _board_selection_is_complete()
    range_ok = _opponent_range_is_complete(opponent_label)
    trials = int(st.session_state.get("calc_simulations", DEFAULT_MONTE_CARLO_TRIALS))

    def _row(done: bool, label: str) -> str:
        state = "calc-check-on" if done else "calc-check-off"
        mark = "✓" if done else "○"
        return (
            f'<div class="calc-check {state}">'
            f'<span class="calc-check-mark" aria-hidden="true">{mark}</span>'
            f"<span>{escape(label)}</span>"
            f"</div>"
        )

    return f"""
            <div class="calc-summary-checklist" aria-label="Input progress">
              {_row(hero_ok, "Hero selected" if hero_ok else "Hero incomplete")}
              {_row(board_ok, "Board complete" if board_ok else "Board incomplete")}
              {_row(range_ok, "Opponent range selected" if range_ok else "Opponent range incomplete")}
              <div class="calc-check calc-check-meta">
                <span class="calc-check-mark" aria-hidden="true">···</span>
                <span>Monte Carlo: {trials:,} trials</span>
              </div>
            </div>
    """


def _calculation_summary_results_html(analysis: dict) -> str:
    result = analysis["result"]
    decision = analysis["decision"]
    rec = str(decision.recommendation)
    rec_class, rec_icon_name, rec_icon_stroke = _recommendation_visuals(rec)
    status_label, diff, status_tone = _equity_vs_required_status(
        float(result.equity), float(decision.required_equity)
    )
    diff_text = f"{diff * 100.0:+.1f} pp vs required"
    trials = int(analysis.get("simulations", st.session_state.get("calc_simulations", DEFAULT_MONTE_CARLO_TRIALS)))
    conf_level = _simulation_confidence_from_trials(trials)
    conf_tone = _simulation_confidence_tone(conf_level)
    bar = _equity_share_bar_html(result.win_rate, result.tie_rate, result.loss_rate)
    why_items = "".join(
        f"<li>{escape(bullet)}</li>" for bullet in _decision_why_bullets(analysis)
    )
    rec_icon = _lucide_icon_data_uri(rec_icon_name, size=22, stroke=rec_icon_stroke)
    conf_icon = _lucide_icon_data_uri("shield", size=14, stroke="#94a3b8")
    return f"""
            <div class="calc-summary-divider" aria-hidden="true"></div>
            <div class="calc-summary-results el-fade-in">
              <div class="calc-summary-item">
                {_summary_label_html("Hero Equity", icon="percent")}
                <span class="calc-summary-value calc-summary-equity">{escape(_format_percent(result.equity))}</span>
                <div class="el-eq-status {status_tone}">
                  <span class="el-eq-status-label">{escape(status_label)}</span>
                  <span class="el-eq-status-diff">{escape(diff_text)}</span>
                </div>
                <div class="el-sim-confidence {conf_tone}">
                  <div class="el-sim-confidence-row">
                    <img src="{conf_icon}" alt="" width="14" height="14"/>
                    <span class="el-sim-confidence-label">Simulation Confidence</span>
                  </div>
                  <span class="el-sim-confidence-level">{escape(conf_level)}</span>
                  <span class="el-sim-confidence-trials">{escape(f"{trials:,}")} Monte Carlo trials</span>
                </div>
              </div>
              <div class="calc-summary-item">
                {_summary_label_html("Win / Tie / Loss", icon="activity")}
                {bar}
              </div>
              <div class="calc-summary-item">
                {_summary_label_html("EV", icon="circle-dollar-sign")}
                <span class="calc-summary-value">{escape(f"{decision.call_ev:+.2f}")}</span>
              </div>
              <div class="calc-summary-rec-card {rec_class}">
                {_summary_label_html("Recommendation", icon="trophy")}
                <div class="calc-summary-rec-action">
                  <img class="calc-summary-rec-icon" src="{rec_icon}" alt="" width="22" height="22"/>
                  <span class="calc-summary-rec-text">{escape(rec)}</span>
                </div>
                <div class="calc-summary-why">
                  <div class="calc-summary-why-title">Why?</div>
                  <ul class="calc-summary-why-list">{why_items}</ul>
                </div>
              </div>
            </div>
    """


def _equity_share_bar_html(win_rate: float, tie_rate: float, loss_rate: float) -> str:
    win_pct = max(0.0, float(win_rate) * 100.0)
    tie_pct = max(0.0, float(tie_rate) * 100.0)
    loss_pct = max(0.0, float(loss_rate) * 100.0)
    total = win_pct + tie_pct + loss_pct
    if total <= 0:
        win_pct, tie_pct, loss_pct = 0.0, 0.0, 100.0
        total = 100.0
    win_w = win_pct / total * 100.0
    tie_w = tie_pct / total * 100.0
    loss_w = loss_pct / total * 100.0

    def _seg(kind: str, width: float, pct: float, delay: str) -> str:
        show_inside = width >= 10.0 and pct >= 8.0
        inner = (
            f'<span class="el-equity-seg-label">{escape(f"{pct:.0f}%")}</span>'
            if show_inside
            else ""
        )
        return (
            f'<span class="el-equity-seg el-equity-{kind}" '
            f'style="width:{width:.2f}%;animation-delay:{delay}">'
            f"{inner}</span>"
        )

    def _pct_cell(width: float, pct: float) -> str:
        visible = "is-visible" if width >= 5.0 else "is-hidden"
        return (
            f'<span class="el-equity-pct {visible}" style="flex:{width:.2f} 0 0">'
            f"{escape(f'{pct:.0f}%')}</span>"
        )

    return f"""
              <div class="el-equity-bar el-equity-bar-animated" role="img" aria-label="Win {win_pct:.1f} percent, Tie {tie_pct:.1f} percent, Loss {loss_pct:.1f} percent">
                <div class="el-equity-bar-track">
                  {_seg("win", win_w, win_pct, "0ms")}
                  {_seg("tie", tie_w, tie_pct, "70ms")}
                  {_seg("loss", loss_w, loss_pct, "140ms")}
                </div>
                <div class="el-equity-bar-pcts" aria-hidden="true">
                  {_pct_cell(win_w, win_pct)}
                  {_pct_cell(tie_w, tie_pct)}
                  {_pct_cell(loss_w, loss_pct)}
                </div>
                <div class="el-equity-bar-legend">
                  <span class="el-equity-legend-item"><i class="el-equity-swatch el-equity-win"></i>Win {escape(_format_percent(win_rate))}</span>
                  <span class="el-equity-legend-item"><i class="el-equity-swatch el-equity-tie"></i>Tie {escape(_format_percent(tie_rate))}</span>
                  <span class="el-equity-legend-item"><i class="el-equity-swatch el-equity-loss"></i>Loss {escape(_format_percent(loss_rate))}</span>
                </div>
              </div>
    """


def _hero_hand_is_complete() -> bool:
    slots = _hero_slot_values()
    return slots[0] is not None and slots[1] is not None


def _calculation_settings_are_valid() -> bool:
    pot_size = float(st.session_state.calc_pot_size)
    call_amount = float(st.session_state.calc_call_amount)
    simulations = _normalize_monte_carlo_trials(st.session_state.calc_simulations)
    return (
        pot_size >= 0
        and call_amount >= 0
        and MIN_MONTE_CARLO_TRIALS <= simulations <= MAX_MONTE_CARLO_TRIALS
    )


def _hero_summary_display() -> str:
    if not _hero_hand_is_complete():
        return "Missing"

    slots = _hero_slot_values()
    notation = _hero_hand_shorthand(slots)
    cards_display = " ".join(slot for slot in slots if slot)
    if notation:
        return f"{notation} · {cards_display}"
    return cards_display


def _calculation_status_parts(opponent_label: str | None = None) -> tuple[str, str]:
    if _calculator_inputs_are_ready(opponent_label=opponent_label):
        return "Ready to calculate", "status-success"
    if not _hero_hand_is_complete():
        return "Hero hand missing", "status-warning"
    if not _board_selection_is_complete():
        return "Complete the board street", "status-warning"
    if not _opponent_range_is_complete(opponent_label):
        return "Custom range is empty", "status-warning"
    if not _calculation_settings_are_valid():
        return "Check pot, call, or trials", "status-warning"
    return "Inputs incomplete", "status-warning"


def _hero_hand_summary_parts() -> tuple[str, str | None]:
    slots = _hero_slot_values()
    if not _hero_hand_is_complete():
        return "Not selected", None

    cards_display = " ".join(slot for slot in slots if slot)
    notation = _hero_hand_shorthand(slots)
    return cards_display, notation or None


def _board_street_status() -> str:
    board_count = len(_selected_board_cards())
    if board_count == 0:
        return "Preflop"
    if board_count < 3:
        return "Preflop"
    if board_count == 3:
        return "Flop"
    if board_count == 4:
        return "Turn"
    return "River"


def _opponent_range_summary(opponent_label: str) -> str:
    if opponent_label == "Custom":
        weights = _selected_range_weights()
        notation = _format_range_notation(list(weights.keys()), weights)
        return f"Custom · {notation}" if notation else "Custom · No hands selected"
    return opponent_label


def _required_equity_preview(pot_size: float, call_amount: float) -> str:
    if call_amount <= 0:
        return "0.0%"
    return _format_percent(call_amount / (pot_size + call_amount))


def _apply_quick_example(example_index: int) -> None:
    example = QUICK_EXAMPLES[example_index]
    st.session_state.active_quick_example = example_index
    st.session_state.hero_slot_cards = list(example["hero"])
    _sync_hero_cards_from_slots()
    st.session_state.flop_slot_cards = list(example["flop"])
    _sync_flop_cards_from_slots()
    st.session_state.turn_slot_card = example["turn"]
    _sync_turn_from_slot()
    st.session_state.river_slot_card = example["river"]
    _sync_river_from_slot()
    _enforce_board_street_order()
    st.session_state.calc_opponent_range = example["opponent"]
    st.session_state.calc_pot_size = float(example["pot"])
    st.session_state.calc_call_amount = float(example["call"])
    st.session_state["calc_pot_size__input"] = float(example["pot"])
    st.session_state["calc_call_amount__input"] = float(example["call"])
    st.session_state.active_hero_slot = None
    st.session_state.active_board_slot = _first_empty_board_slot()
    st.session_state.latest_analysis = None
    st.session_state.scroll_to_results = False
    _snapshot_calculator_settings()


def _maybe_scroll_to_results() -> None:
    if not st.session_state.pop("scroll_to_results", False):
        return

    st.markdown(
        """
        <script>
        const target = document.getElementById("equity-results-section");
        if (target) {
            target.scrollIntoView({ behavior: "smooth", block: "start" });
        }
        </script>
        """,
        unsafe_allow_html=True,
    )


def _render_range_builder_tab() -> None:
    st.markdown('<h2 class="el-page-title">Ranges</h2>', unsafe_allow_html=True)
    st.caption(
        "Click a hand to select it (100%). Click again to edit its weight (0–100%)."
    )

    _maybe_open_weight_editor()
    _render_range_builder_workspace(
        ns=RANGE_NS_OPPONENT,
        key_prefix="opponent",
        grid_heading="Range Grid",
    )

    use_col, _ = st.columns([1.2, 1])
    with use_col:
        st.button(
            "Use This Range in Calculator",
            type="primary",
            use_container_width=True,
            disabled=not bool(_range_hands(RANGE_NS_OPPONENT)),
            key="use-range-in-calculator",
            on_click=_use_range_in_calculator,
        )
        if not _range_hands(RANGE_NS_OPPONENT):
            st.markdown(
                '<p class="range-empty-state">Select hands from the grid to build an opponent range.</p>',
                unsafe_allow_html=True,
            )

    _render_save_range_section()
    _render_builtin_presets(ns=RANGE_NS_OPPONENT, key_prefix="opponent")
    _render_saved_ranges()


def _render_save_range_section() -> None:
    editing_id = st.session_state.get("editing_saved_range_id")
    is_editing = editing_id is not None

    st.markdown("### Update Range" if is_editing else "### Save Range")
    if is_editing:
        editing_name = st.session_state.get("editing_saved_range_name", "")
        st.caption(f'Editing saved range: "{editing_name}"')

    save_col, _ = st.columns([1.2, 1])
    with save_col:
        range_name = st.text_input("Range name", key="range_save_name")
        action_disabled = (
            not bool(st.session_state.selected_range_hands) or not range_name.strip()
        )
        if is_editing:
            update_col, cancel_col = st.columns(2)
            with update_col:
                if st.button(
                    "Update Range",
                    disabled=action_disabled,
                    key="update-range-button",
                    use_container_width=True,
                    type="primary",
                ):
                    _update_current_range(range_name)
            with cancel_col:
                st.button(
                    "Cancel Editing",
                    key="cancel-edit-range-button",
                    use_container_width=True,
                    on_click=_cancel_editing_saved_range,
                )
        elif st.button(
            "Save Range",
            disabled=action_disabled,
            key="save-range-button",
            use_container_width=True,
        ):
            _save_current_range(range_name)


def _render_builtin_presets(*, ns: str = RANGE_NS_OPPONENT, key_prefix: str = "opponent") -> None:
    st.markdown("### Built-in Presets")
    names = list(BUILTIN_RANGE_PRESETS.keys())
    columns = st.columns(3)
    for index, name in enumerate(names):
        columns[index % 3].button(
            name,
            key=f"{key_prefix}-builtin-preset-{index}",
            on_click=_apply_builtin_preset,
            args=(name, ns),
            use_container_width=True,
        )


def _apply_builtin_preset(preset_name: str, ns: str = RANGE_NS_OPPONENT) -> None:
    notation = BUILTIN_RANGE_PRESETS.get(preset_name)
    if not notation:
        return
    hands = _grid_hands_from_range_text(notation)
    _set_range_weights(ns, {hand: 100 for hand in hands})


def _grid_hands_from_range_text(range_text: str) -> list[str]:
    """Convert range notation into unique 13x13 grid hand-class labels."""
    labels: set[str] = set()
    for first_card, second_card in parse_opponent_range(range_text):
        if first_card.rank == second_card.rank:
            labels.add(f"{first_card.rank}{second_card.rank}")
            continue
        high_rank, low_rank = sorted(
            (first_card.rank, second_card.rank),
            key=lambda rank: RANGE_RANKS.index(rank),
        )
        suitedness = "s" if first_card.suit == second_card.suit else "o"
        labels.add(f"{high_rank}{low_rank}{suitedness}")
    return list(labels)


def _selected_range_weights() -> dict[str, int]:
    return _get_range_weights(RANGE_NS_OPPONENT)


def _set_selected_range_weights(weights: dict[str, int]) -> None:
    _set_range_weights(RANGE_NS_OPPONENT, weights)


def _range_weights_state_key(ns: str) -> str:
    return "selected_range_weights" if ns == RANGE_NS_OPPONENT else f"{ns}_range_weights"


def _range_hands_state_key(ns: str) -> str:
    return "selected_range_hands" if ns == RANGE_NS_OPPONENT else f"{ns}_range_hands"


def _range_editor_hand_key(ns: str) -> str:
    return "weight_editor_hand" if ns == RANGE_NS_OPPONENT else f"{ns}_weight_editor_hand"


def _range_notation_expanded_key(ns: str) -> str:
    return "range_notation_expanded" if ns == RANGE_NS_OPPONENT else f"{ns}_range_notation_expanded"


def _get_range_weights(ns: str = RANGE_NS_OPPONENT) -> dict[str, int]:
    weights_key = _range_weights_state_key(ns)
    hands_key = _range_hands_state_key(ns)
    raw = st.session_state.get(weights_key)
    if not isinstance(raw, dict):
        raw = {hand: 100 for hand in st.session_state.get(hands_key, [])}
        st.session_state[weights_key] = raw
    return normalize_hand_weights(raw)


def _set_range_weights(ns: str, weights: dict[str, int]) -> None:
    normalized = normalize_hand_weights(weights)
    st.session_state[_range_weights_state_key(ns)] = normalized
    st.session_state[_range_hands_state_key(ns)] = sorted(
        normalized.keys(), key=_grid_hand_sort_key
    )


def _range_hands(ns: str = RANGE_NS_OPPONENT) -> list[str]:
    return list(st.session_state.get(_range_hands_state_key(ns), []))


def _hero_selection_mode() -> str:
    mode = st.session_state.get("hero_selection_mode", HERO_MODE_SINGLE)
    if mode not in {HERO_MODE_SINGLE, HERO_MODE_RANGE}:
        return HERO_MODE_SINGLE
    return mode


def _hero_is_range_mode() -> bool:
    return _hero_selection_mode() == HERO_MODE_RANGE


@st.dialog("Edit hand weight")
def _weight_editor_dialog() -> None:
    ns = st.session_state.get("weight_editor_ns", RANGE_NS_OPPONENT)
    editor_key = _range_editor_hand_key(ns)
    hand = st.session_state.get(editor_key)
    if not hand:
        return

    weights = _get_range_weights(ns)
    current = int(weights.get(hand, 100))
    role = "hero" if ns == RANGE_NS_HERO else "opponent"
    st.caption(f"Adjust how often **{hand}** appears in the {role} range.")
    new_weight = st.slider(
        "Weight",
        min_value=0,
        max_value=100,
        value=current,
        step=1,
        format="%d%%",
        key=f"{ns}-weight-slider-{hand}",
    )

    save_col, remove_col, cancel_col = st.columns(3)
    if save_col.button("Save", type="primary", use_container_width=True, key=f"{ns}-weight-editor-save"):
        updated = dict(weights)
        if new_weight <= 0:
            updated.pop(hand, None)
        else:
            updated[hand] = int(new_weight)
        _set_range_weights(ns, updated)
        st.session_state[editor_key] = None
        st.rerun()
    if remove_col.button("Remove", use_container_width=True, key=f"{ns}-weight-editor-remove"):
        updated = dict(weights)
        updated.pop(hand, None)
        _set_range_weights(ns, updated)
        st.session_state[editor_key] = None
        st.rerun()
    if cancel_col.button("Cancel", use_container_width=True, key=f"{ns}-weight-editor-cancel"):
        st.session_state[editor_key] = None
        st.rerun()


def _maybe_open_weight_editor() -> None:
    for ns in (RANGE_NS_OPPONENT, RANGE_NS_HERO):
        if st.session_state.get(_range_editor_hand_key(ns)):
            st.session_state.weight_editor_ns = ns
            _weight_editor_dialog()
            return


def _render_range_summary_panel(
    selected_hands: list[str] | None = None,
    *,
    ns: str = RANGE_NS_OPPONENT,
    key_prefix: str = "opponent",
) -> None:
    weights = _get_range_weights(ns)
    selected_hands = (
        sorted(weights.keys(), key=_grid_hand_sort_key)
        if selected_hands is None
        else list(selected_hands)
    )
    stats = _range_summary_stats(selected_hands, weights)
    ordered_hands = sorted(selected_hands, key=_grid_hand_sort_key)
    notation_limit = 18
    notation_is_long = len(ordered_hands) > notation_limit
    notation_key = _range_notation_expanded_key(ns)
    if not notation_is_long:
        st.session_state[notation_key] = False

    notation_expanded = bool(st.session_state.get(notation_key, False))
    full_notation = _format_range_notation(ordered_hands, weights)

    classes_muted = "" if stats["hand_classes"] else " range-summary-muted"
    notation_muted = "" if full_notation else " range-summary-muted"
    notation_classes = f"range-summary-notation{notation_muted}"
    if notation_is_long and not notation_expanded:
        notation_classes += " range-summary-notation-collapsed"
    elif notation_is_long and notation_expanded:
        notation_classes += " range-summary-notation-expanded"
    notation_html = escape(full_notation) if full_notation else "—"

    panel_classes = "range-summary-panel"
    if notation_is_long:
        panel_classes += " range-summary-panel-expandable"

    effective_combos = float(stats["effective_combos"])
    if effective_combos == int(effective_combos):
        effective_display = f"{int(effective_combos):,}"
    else:
        effective_display = f"{effective_combos:,.2f}"

    st.markdown(
        f"""
        <div class="{panel_classes}">
          <div class="range-summary-title">Range Summary</div>
          <div class="range-summary-body">
            <div class="range-summary-item">
              <span class="range-summary-label">Selected hand classes</span>
              <span class="range-summary-value{classes_muted}">{stats["hand_classes"]:,}</span>
            </div>
            <div class="range-summary-item">
              <span class="range-summary-label">Effective weighted combinations</span>
              <span class="range-summary-value">{effective_display} / 1,326</span>
            </div>
            <div class="range-summary-item">
              <span class="range-summary-label">Effective range percentage</span>
              <span class="range-summary-value">{stats["percentage"]:.1f}%</span>
            </div>
            <div class="range-summary-metrics">
              <div class="range-summary-metric">
                <span class="range-summary-label">Pair Combos</span>
                <span class="range-summary-value">{_format_weighted_count(stats["pairs"])}</span>
              </div>
              <div class="range-summary-metric">
                <span class="range-summary-label">Suited Combos</span>
                <span class="range-summary-value">{_format_weighted_count(stats["suited"])}</span>
              </div>
              <div class="range-summary-metric">
                <span class="range-summary-label">Offsuit Combos</span>
                <span class="range-summary-value">{_format_weighted_count(stats["offsuit"])}</span>
              </div>
            </div>
            <div class="range-summary-item range-summary-notation-block">
              <span class="range-summary-label">Range notation</span>
              <span class="{notation_classes}">{notation_html}</span>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if notation_is_long:
        st.button(
            "Show less" if notation_expanded else "Show all",
            key=f"{key_prefix}-toggle-range-notation",
            on_click=_toggle_range_notation_expanded,
            args=(ns,),
        )


def _format_weighted_count(value: float) -> str:
    if float(value) == int(value):
        return f"{int(value):,}"
    return f"{float(value):,.2f}"


def _toggle_range_notation_expanded(ns: str = RANGE_NS_OPPONENT) -> None:
    key = _range_notation_expanded_key(ns)
    st.session_state[key] = not bool(st.session_state.get(key, False))


def _render_hand_history_tab() -> None:
    st.markdown('<h2 class="el-page-title">History</h2>', unsafe_allow_html=True)
    st.caption(
        "Save previous equity analyses here so you can review hands, boards, ranges, and results later."
    )

    entries = load_hand_history_entries()
    if not entries:
        st.html(_hand_history_empty_state_html())
        return

    flash = st.session_state.pop("hand_history_action_flash", None)
    if flash:
        st.success(flash)

    st.html(_hand_history_styles())
    pending_delete_id = st.session_state.get("pending_history_delete_id")
    for entry in entries:
        entry_id = int(entry["id"])
        st.html(_hand_history_card_html(entry))
        load_col, delete_col = st.columns([3, 1])
        load_col.button(
            "Load Analysis",
            key=f"load-analysis-{entry_id}",
            on_click=_load_hand_history_analysis,
            args=(entry_id,),
            use_container_width=True,
        )
        delete_col.button(
            "Delete",
            key=f"delete-analysis-{entry_id}",
            on_click=_request_history_entry_delete,
            args=(entry_id,),
            use_container_width=True,
        )

        if pending_delete_id == entry_id:
            st.warning("Delete this saved analysis? This cannot be undone.")
            confirm_col, cancel_col = st.columns(2)
            confirm_col.button(
                "Delete permanently",
                key=f"confirm-delete-analysis-{entry_id}",
                type="primary",
                on_click=_confirm_history_entry_delete,
                args=(entry_id,),
                use_container_width=True,
            )
            cancel_col.button(
                "Cancel",
                key=f"cancel-delete-analysis-{entry_id}",
                on_click=_cancel_history_entry_delete,
                use_container_width=True,
            )


def _hand_history_styles() -> str:
    return """
    <style>
      .hand-history-list {
        display: flex;
        flex-direction: column;
        gap: 0.85rem;
        margin-top: 0.35rem;
      }
      .hand-history-entry-card {
        margin-top: 0.85rem;
      }
      .hand-history-empty-card,
      .hand-history-entry-card {
        box-sizing: border-box;
        width: 100%;
        padding: 1.35rem 1.2rem;
        border: 1px solid rgba(148, 163, 184, 0.28);
        border-radius: 0.55rem;
        background: rgba(15, 23, 42, 0.55);
        color: #f8fafc;
        font-family: inherit;
      }
      .hand-history-empty-card {
        display: flex;
        flex-direction: column;
        align-items: flex-start;
        gap: 0.45rem;
        min-height: 9.5rem;
        justify-content: center;
      }
      .hand-history-empty-title {
        margin: 0;
        color: #f8fafc;
        font-size: 1.05rem;
        font-weight: 700;
        line-height: 1.3;
      }
      .hand-history-empty-copy {
        margin: 0;
        max-width: 36rem;
        color: #94a3b8;
        font-size: 0.95rem;
        line-height: 1.55;
      }
      .hand-history-entry-header {
        display: flex;
        flex-wrap: wrap;
        align-items: baseline;
        justify-content: space-between;
        gap: 0.55rem 1rem;
        margin-bottom: 0.95rem;
      }
      .hand-history-entry-title {
        margin: 0;
        color: #f8fafc;
        font-size: 1.05rem;
        font-weight: 700;
        line-height: 1.3;
        word-break: break-word;
      }
      .hand-history-entry-timestamp {
        color: #94a3b8;
        font-size: 0.82rem;
        font-weight: 600;
        white-space: nowrap;
      }
      .hand-history-entry-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(9.5rem, 1fr));
        gap: 0.7rem;
      }
      .hand-history-entry-item {
        display: flex;
        flex-direction: column;
        gap: 0.2rem;
        padding: 0.55rem 0.6rem;
        border-radius: 0.45rem;
        border: 1px solid rgba(51, 65, 85, 0.9);
        background: rgba(30, 41, 59, 0.45);
      }
      .hand-history-entry-label {
        color: #94a3b8;
        font-size: 0.72rem;
        font-weight: 600;
        letter-spacing: 0.04em;
        text-transform: uppercase;
      }
      .hand-history-entry-value {
        color: #f8fafc;
        font-size: 0.92rem;
        font-weight: 600;
        line-height: 1.35;
        word-break: break-word;
      }
      [class*="st-key-load-analysis-"] button,
      [class*="st-key-delete-analysis-"] button,
      [class*="st-key-cancel-delete-analysis-"] button {
        background: rgba(30, 41, 59, 0.92) !important;
        border-color: rgba(148, 163, 184, 0.55) !important;
        color: #f8fafc !important;
      }
      [class*="st-key-load-analysis-"] button:hover,
      [class*="st-key-delete-analysis-"] button:hover,
      [class*="st-key-cancel-delete-analysis-"] button:hover {
        background: rgba(51, 65, 85, 0.95) !important;
        border-color: rgba(226, 232, 240, 0.72) !important;
        color: #ffffff !important;
      }
      [class*="st-key-load-analysis-"] button p,
      [class*="st-key-delete-analysis-"] button p,
      [class*="st-key-cancel-delete-analysis-"] button p {
        color: inherit !important;
      }
    </style>
    """


def _hand_history_empty_state_html() -> str:
    return f"""
    {_hand_history_styles()}
    <div class="hand-history-list">
      <div class="hand-history-empty-card">
        <div class="hand-history-empty-title">No saved analyses yet.</div>
        <p class="hand-history-empty-copy">
          Run an equity calculation and save it to build your study history.
        </p>
      </div>
    </div>
    """


def _hand_history_card_html(entry: dict) -> str:
    board_display = entry.get("board") or "—"
    hero = escape(str(entry["hero_hand"]))
    board = escape(str(board_display))
    opponent = escape(str(entry["opponent_range"]))
    return f"""
    <div class="hand-history-entry-card">
      <div class="hand-history-entry-header">
        <div class="hand-history-entry-title">{hero} vs {opponent}</div>
        <div class="hand-history-entry-timestamp">{escape(str(entry["timestamp"]))}</div>
      </div>
      <div class="hand-history-entry-grid">
        <div class="hand-history-entry-item">
          <span class="hand-history-entry-label">Hero hand</span>
          <span class="hand-history-entry-value">{hero}</span>
        </div>
        <div class="hand-history-entry-item">
          <span class="hand-history-entry-label">Board</span>
          <span class="hand-history-entry-value">{board}</span>
        </div>
        <div class="hand-history-entry-item">
          <span class="hand-history-entry-label">Opponent range</span>
          <span class="hand-history-entry-value">{opponent}</span>
        </div>
        <div class="hand-history-entry-item">
          <span class="hand-history-entry-label">Equity</span>
          <span class="hand-history-entry-value">{escape(str(entry["equity_pct"]))}</span>
        </div>
        <div class="hand-history-entry-item">
          <span class="hand-history-entry-label">Win</span>
          <span class="hand-history-entry-value">{escape(str(entry["win_pct"]))}</span>
        </div>
        <div class="hand-history-entry-item">
          <span class="hand-history-entry-label">Tie</span>
          <span class="hand-history-entry-value">{escape(str(entry["tie_pct"]))}</span>
        </div>
        <div class="hand-history-entry-item">
          <span class="hand-history-entry-label">Loss</span>
          <span class="hand-history-entry-value">{escape(str(entry["loss_pct"]))}</span>
        </div>
        <div class="hand-history-entry-item">
          <span class="hand-history-entry-label">EV of Call</span>
          <span class="hand-history-entry-value">{escape(str(entry["ev_of_call"]))}</span>
        </div>
        <div class="hand-history-entry-item">
          <span class="hand-history-entry-label">Recommendation</span>
          <span class="hand-history-entry-value">{escape(str(entry["recommendation"]))}</span>
        </div>
        <div class="hand-history-entry-item">
          <span class="hand-history-entry-label">Calculation mode</span>
          <span class="hand-history-entry-value">{escape(str(entry["calculation_mode"]))}</span>
        </div>
      </div>
    </div>
    """


def _format_calculation_mode(mode: str) -> str:
    if mode == "exact":
        return "Exact Enumeration"
    if mode == "monte-carlo":
        return "Monte Carlo"
    return str(mode)


def _opponent_range_history_label(opponent_label: str, range_text: str) -> str:
    if opponent_label == "Custom":
        return range_text or "Custom"
    if opponent_label.startswith("Saved: "):
        return f"{opponent_label} · {range_text}" if range_text else opponent_label
    return opponent_label


def _render_about_tab() -> None:
    st.markdown('<h2 class="el-page-title">About</h2>', unsafe_allow_html=True)
    with st.container(border=True):
        st.markdown(
            """
            ### EquityLab
            EquityLab is a professional Texas Hold'em analysis toolkit for studying heads-up
            decisions with a custom Monte Carlo simulation engine.

            ### Capabilities
            - **Monte Carlo engine** for large search spaces, with exact enumeration when feasible
            - **Weighted range support** for custom and saved opponent ranges
            - **Decision intelligence** for EV, required equity, confidence, and sensitivity analysis
            - Board texture, hero draws, opponent hand distributions, and equity heatmaps

            ### What you can analyze
            - Weighted opponent ranges and starting-hand heatmaps
            - Equity, EV, and call/fold decision quality
            - Board texture, hero draws, and opponent hand distributions
            - Deterministic decision explanations grounded in the math

            ### How equity is calculated
            Equity is wins plus half of ties divided by all evaluated matchups.

            ### Exact enumeration
            When the remaining search space is small enough, EquityLab enumerates every legal
            opponent hand and board runout.

            ### Monte Carlo
            For larger searches, the engine samples random opponent hands and board runouts
            using the selected trial count.

            ### Quality
            EquityLab ships with an automated test suite covering the evaluator, weighted ranges,
            board texture, decision explanation, and equity heatmap caching.
            """
        )
    st.markdown('<p class="el-dev-tools-label">Developer tools</p>', unsafe_allow_html=True)
    st.caption("Internal utilities for verifying hand classification. Not part of the main product flow.")
    st.button(
        "Open hand evaluator",
        key="about-open-tools",
        on_click=_set_active_tab,
        args=(TAB_TOOLS,),
    )


# Temporary developer page for verifying classify_completed_hand. Safe to remove later.
_HAND_EVAL_DEV_SAMPLES = (
    ("High Card", "Ah Kd 9c 7s 5h 3d 2c"),
    ("One Pair", "Ah Ad Kc 9s 7h 5d 2c"),
    ("Two Pair", "Ah Ad Kc Ks 7h 5d 2c"),
    ("Three of a Kind", "Qh Qd Qc 9s 7h 5d 2c"),
    ("Straight", "9h 8d 7c 6s 5h Kd 2c"),
    ("Flush", "Ah Kh 9h 7h 3h Qd 2s"),
    ("Full House", "Kh Kd Ks 9c 9h 2d 3c"),
    ("Four of a Kind", "Ah Ad Ac As 9h Kd 2c"),
    ("Straight Flush", "9h 8h 7h 6h 5h Kd 2c"),
)


def _render_hand_eval_dev_tab() -> None:
    st.markdown('<h2 class="el-page-title">Tools</h2>', unsafe_allow_html=True)
    st.caption(
        "Developer hand evaluator for verifying `classify_completed_hand`. "
        "Enter exactly 7 cards (2 hole + 5 board)."
    )

    if "hand_eval_dev_input" not in st.session_state:
        st.session_state.hand_eval_dev_input = _HAND_EVAL_DEV_SAMPLES[0][1]

    st.markdown("### Sample hands")
    sample_cols = st.columns(3)
    for index, (label, cards_text) in enumerate(_HAND_EVAL_DEV_SAMPLES):
        sample_cols[index % 3].button(
            label,
            key=f"hand-eval-sample-{index}",
            on_click=_load_hand_eval_sample,
            args=(cards_text,),
            use_container_width=True,
        )

    cards_text = st.text_input(
        "Seven cards",
        key="hand_eval_dev_input",
        help="Example: Ah Kd Qh Jc Ts 9d 8c",
    )

    if st.button("Evaluate Hand", type="primary", key="hand-eval-run"):
        try:
            cards = parse_cards(cards_text, expected_count=7)
            category = classify_completed_hand(cards)
            st.success(f"Category: **{category}**")
            st.write("Cards: " + " ".join(card.display() for card in cards))
        except ValueError as error:
            st.error(str(error))


def _load_hand_eval_sample(cards_text: str) -> None:
    st.session_state.hand_eval_dev_input = cards_text


def _hero_slot_values() -> list[str | None]:
    if "hero_slot_cards" not in st.session_state:
        cards = list(st.session_state.get("selected_hero_cards", []))
        st.session_state.hero_slot_cards = [
            _normalize_card_key(cards[0]) if len(cards) > 0 else None,
            _normalize_card_key(cards[1]) if len(cards) > 1 else None,
        ]
    slots = [_normalize_card_key(card) if card else None for card in st.session_state.hero_slot_cards]
    if len(slots) != 2:
        slots = [slots[index] if index < len(slots) else None for index in range(2)]
    st.session_state.hero_slot_cards = slots
    return list(slots)


def _sync_hero_cards_from_slots() -> None:
    st.session_state.selected_hero_cards = [
        card for card in _hero_slot_values() if card is not None
    ]


def _flop_slot_values() -> list[str | None]:
    if "flop_slot_cards" not in st.session_state:
        cards = list(st.session_state.get("selected_flop_cards", []))
        st.session_state.flop_slot_cards = [
            _normalize_card_key(cards[index]) if index < len(cards) else None for index in range(3)
        ]
    slots = [_normalize_card_key(card) if card else None for card in st.session_state.flop_slot_cards]
    if len(slots) != 3:
        slots = [slots[index] if index < len(slots) else None for index in range(3)]
    st.session_state.flop_slot_cards = slots
    return list(slots)


def _sync_flop_cards_from_slots() -> None:
    st.session_state.selected_flop_cards = [
        card for card in _flop_slot_values() if card is not None
    ]


def _turn_slot_value() -> str | None:
    if "turn_slot_card" not in st.session_state:
        cards = list(st.session_state.get("selected_turn_card", []))
        st.session_state.turn_slot_card = _normalize_card_key(cards[0]) if cards else None
    card = st.session_state.turn_slot_card
    if card:
        card = _normalize_card_key(card)
        st.session_state.turn_slot_card = card
    return card


def _river_slot_value() -> str | None:
    if "river_slot_card" not in st.session_state:
        cards = list(st.session_state.get("selected_river_card", []))
        st.session_state.river_slot_card = _normalize_card_key(cards[0]) if cards else None
    card = st.session_state.river_slot_card
    if card:
        card = _normalize_card_key(card)
        st.session_state.river_slot_card = card
    return card


def _sync_turn_from_slot() -> None:
    card = _turn_slot_value()
    st.session_state.selected_turn_card = [card] if card else []


def _sync_river_from_slot() -> None:
    card = _river_slot_value()
    st.session_state.selected_river_card = [card] if card else []


def _board_slot_card(state_key: str, index: int) -> str | None:
    if state_key == "selected_flop_cards":
        slots = _flop_slot_values()
        return slots[index] if 0 <= index < len(slots) else None
    if state_key == "selected_turn_card":
        return _turn_slot_value()
    if state_key == "selected_river_card":
        return _river_slot_value()
    return None


def _has_empty_board_slot() -> bool:
    if None in _flop_slot_values():
        return True
    if _turn_slot_value() is None:
        return True
    if _river_slot_value() is None:
        return True
    return False


def _is_flop_complete() -> bool:
    return None not in _flop_slot_values()


def _can_select_board_slot(state_key: str, index: int) -> bool:
    if state_key == "selected_flop_cards":
        return True
    if state_key == "selected_turn_card":
        return _is_flop_complete()
    if state_key == "selected_river_card":
        return _is_flop_complete() and _turn_slot_value() is not None
    return False


def _board_slot_help_text(state_key: str) -> str:
    if state_key == "selected_turn_card" and not _is_flop_complete():
        return "Complete the flop before selecting the turn"
    if state_key == "selected_river_card":
        if not _is_flop_complete():
            return "Complete the flop before selecting the river"
        if _turn_slot_value() is None:
            return "Deal the turn before selecting the river"
    return "Choose a card"


def _enforce_board_street_order() -> None:
    if not _is_flop_complete():
        st.session_state.turn_slot_card = None
        st.session_state.selected_turn_card = []
        st.session_state.river_slot_card = None
        st.session_state.selected_river_card = []
    elif _turn_slot_value() is None:
        st.session_state.river_slot_card = None
        st.session_state.selected_river_card = []

    active_slot = st.session_state.get("active_board_slot")
    if active_slot:
        state_key, raw_index = active_slot.split(":")
        if not _can_select_board_slot(state_key, int(raw_index)):
            st.session_state.active_board_slot = _first_empty_board_slot()


def _render_hero_selection_section() -> str:
    """
    Reserved for a future Range vs Range page.

    Not used by the Equity Calculator (which always uses the single-hand picker).
    """
    return _render_hero_hand_picker()


def _lucide_icon_data_uri(name: str, *, size: int = 18, stroke: str = "#94a3b8") -> str:
    """Inline Lucide-style icons as data URIs (Streamlit strips raw SVG in HTML)."""
    icons = {
        "bar-chart-3": (
            '<path d="M3 3v16a2 2 0 0 0 2 2h16"/>'
            '<path d="M18 17V9"/><path d="M13 17V5"/><path d="M8 17v-3"/>'
        ),
        "trophy": (
            '<path d="M6 9H4.5a2.5 2.5 0 0 1 0-5H6"/>'
            '<path d="M18 9h1.5a2.5 2.5 0 0 0 0-5H18"/>'
            '<path d="M4 22h16"/>'
            '<path d="M10 14.66V17c0 .55-.47.98-.97 1.21C7.85 18.75 7 20.24 7 22"/>'
            '<path d="M14 14.66V17c0 .55.47.98.97 1.21C16.15 18.75 17 20.24 17 22"/>'
            '<path d="M18 2H6v7a6 6 0 0 0 12 0V2Z"/>'
        ),
        "layout-grid": (
            '<rect width="7" height="7" x="3" y="3" rx="1"/>'
            '<rect width="7" height="7" x="14" y="3" rx="1"/>'
            '<rect width="7" height="7" x="14" y="14" rx="1"/>'
            '<rect width="7" height="7" x="3" y="14" rx="1"/>'
        ),
        "sliders-horizontal": (
            '<line x1="21" x2="14" y1="4" y2="4"/>'
            '<line x1="10" x2="3" y1="4" y2="4"/>'
            '<line x1="21" x2="12" y1="12" y2="12"/>'
            '<line x1="8" x2="3" y1="12" y2="12"/>'
            '<line x1="21" x2="16" y1="20" y2="20"/>'
            '<line x1="12" x2="3" y1="20" y2="20"/>'
            '<line x1="14" x2="14" y1="2" y2="6"/>'
            '<line x1="8" x2="8" y1="10" y2="14"/>'
            '<line x1="16" x2="16" y1="18" y2="22"/>'
        ),
        "users": (
            '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/>'
            '<circle cx="9" cy="7" r="4"/>'
            '<path d="M22 21v-2a4 4 0 0 0-3-3.87"/>'
            '<path d="M16 3.13a4 4 0 0 1 0 7.75"/>'
        ),
        "coins": (
            '<circle cx="8" cy="8" r="6"/>'
            '<path d="M18.09 10.37A6 6 0 1 1 10.34 18"/>'
            '<path d="M7 6h1v4"/>'
            '<path d="m16.71 13.88.7.71-2.82 2.82"/>'
        ),
        "circle-dollar-sign": (
            '<circle cx="12" cy="12" r="10"/>'
            '<path d="M16 8h-6a2 2 0 1 0 0 4h4a2 2 0 1 1 0 4H8"/>'
            '<path d="M12 18V6"/>'
        ),
        "cpu": (
            '<rect width="16" height="16" x="4" y="4" rx="2"/>'
            '<rect width="6" height="6" x="9" y="9" rx="1"/>'
            '<path d="M15 2v2"/><path d="M15 20v2"/><path d="M2 15h2"/>'
            '<path d="M2 9h2"/><path d="M20 15h2"/><path d="M20 9h2"/>'
            '<path d="M9 2v2"/><path d="M9 20v2"/>'
        ),
        "alert-triangle": (
            '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/>'
            '<path d="M12 9v4"/><path d="M12 17h.01"/>'
        ),
        "lightbulb": (
            '<path d="M15 14c.2-1 .7-1.7 1.5-2.5 1-.9 1.5-2.2 1.5-3.5A6 6 0 0 0 6 8c0 1 .2 2.2 1.5 3.5.7.7 1.3 1.5 1.5 2.5"/>'
            '<path d="M9 18h6"/><path d="M10 22h4"/>'
        ),
        "zap": (
            '<path d="M4 14a1 1 0 0 1-.78-1.63l9.9-10.2a.5.5 0 0 1 .86.46l-1.92 6.02A1 1 0 0 0 13 10h7a1 1 0 0 1 .78 1.63l-9.9 10.2a.5.5 0 0 1-.86-.46l1.92-6.02A1 1 0 0 0 11 14z"/>'
        ),
        "target": (
            '<circle cx="12" cy="12" r="10"/>'
            '<circle cx="12" cy="12" r="6"/>'
            '<circle cx="12" cy="12" r="2"/>'
        ),
        "user": (
            '<path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/>'
            '<circle cx="12" cy="7" r="4"/>'
        ),
        "layers": (
            '<polygon points="12 2 2 7 12 12 22 7 12 2"/>'
            '<polyline points="2 17 12 22 22 17"/>'
            '<polyline points="2 12 12 17 22 12"/>'
        ),
        "percent": (
            '<line x1="19" x2="5" y1="5" y2="19"/>'
            '<circle cx="6.5" cy="6.5" r="2.5"/>'
            '<circle cx="17.5" cy="17.5" r="2.5"/>'
        ),
        "activity": (
            '<path d="M22 12h-2.48a2 2 0 0 0-1.93 1.46l-2.35 8.36a.25.25 0 0 1-.48 0L9.24 2.18a.25.25 0 0 0-.48 0l-2.35 8.36A2 2 0 0 1 4.49 12H2"/>'
        ),
        "check-circle": (
            '<circle cx="12" cy="12" r="10"/>'
            '<path d="m9 12 2 2 4-4"/>'
        ),
        "circle-check": (
            '<circle cx="12" cy="12" r="10"/>'
            '<path d="m9 12 2 2 4-4"/>'
        ),
        "x-circle": (
            '<circle cx="12" cy="12" r="10"/>'
            '<path d="m15 9-6 6"/><path d="m9 9 6 6"/>'
        ),
        "arrow-up": (
            '<path d="m5 12 7-7 7 7"/>'
            '<path d="M12 19V5"/>'
        ),
        "shield": (
            '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/>'
        ),
        "circle-help": (
            '<circle cx="12" cy="12" r="10"/>'
            '<path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/>'
            '<path d="M12 17h.01"/>'
        ),
        "save": (
            '<path d="M15.2 3a2 2 0 0 1 1.4.6l3.8 3.8a2 2 0 0 1 .6 1.4V19a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z"/>'
            '<path d="M17 21v-7a1 1 0 0 0-1-1H8a1 1 0 0 0-1 1v7"/>'
            '<path d="M7 3v4a1 1 0 0 0 1 1h7"/>'
        ),
    }
    body = icons[name]
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
        f'viewBox="0 0 24 24" fill="none" stroke="{stroke}" stroke-width="2" '
        f'stroke-linecap="round" stroke-linejoin="round">{body}</svg>'
    )
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii")


def _section_heading_html(title: str, *, icon: str | None = None) -> str:
    icon_html = ""
    if icon:
        uri = _lucide_icon_data_uri(icon, size=18, stroke="#94a3b8")
        icon_html = f'<img class="el-section-heading-icon" src="{uri}" alt="" width="18" height="18"/>'
    return (
        f'<h3 class="el-section-heading">{icon_html}'
        f"<span>{escape(title)}</span></h3>"
    )


def _render_hero_hand_picker() -> str:
    with st.container(border=True):
        st.markdown(_section_heading_html("Hero Hand"), unsafe_allow_html=True)
        st.html('<p class="el-section-sub">Select your hole cards.</p>')
        st.markdown('<div class="hero-hand-panel">', unsafe_allow_html=True)
        # Side spacers keep the pair centered; tiny middle gap reads as one hand.
        slot_cols = st.columns([2.6, 1.0, 0.18, 1.0, 2.6], gap="small")
        with slot_cols[1]:
            _render_hero_slot(0)
        with slot_cols[3]:
            _render_hero_slot(1)
        st.markdown(
            _hero_selected_label(_hero_hand_shorthand(_hero_slot_values())),
            unsafe_allow_html=True,
        )
        st.markdown("</div>", unsafe_allow_html=True)

        clear_cols = st.columns([1, 1, 1])
        with clear_cols[1]:
            st.button("Clear", key="clear-hero-cards", on_click=_clear_hero_cards, use_container_width=False)

    if st.session_state.get("pending_hero_dialog"):
        st.session_state.pending_hero_dialog = False
        _hero_card_picker_dialog()

    return " ".join(st.session_state.selected_hero_cards)


def _render_hero_slot(index: int) -> None:
    slots = _hero_slot_values()
    slot_key = f"hero-slot-{index}"
    card_key = slots[index]

    if card_key:
        rank, suit = _split_card_key(card_key)
        st.button(
            f"{SUIT_SYMBOLS[suit]} {rank}",
            key=slot_key,
            on_click=_remove_hero_slot,
            args=(index,),
            help="Click to remove",
            use_container_width=False,
        )
        return

    st.button(
        "Select a card",
        key=slot_key,
        on_click=_activate_hero_slot,
        args=(index,),
        help="Choose a card",
        use_container_width=False,
    )


def _hero_selected_label(shorthand: str) -> str:
    muted_class = " el-selected-hand-muted" if not shorthand else ""
    value = escape(_hero_hand_readable_name(shorthand)) if shorthand else "—"
    return (
        f'<div class="el-selected-hand{muted_class}">'
        f'<div class="el-selected-hand-label">Selected Hand</div>'
        f'<div class="el-selected-hand-value">{value}</div>'
        f"</div>"
    )


def _hero_hand_readable_name(shorthand: str) -> str:
    """Convert compact notation (AKs / T9o / QQ) into a readable label."""
    if not shorthand:
        return "—"
    if len(shorthand) == 2 and shorthand[0] == shorthand[1]:
        return f"Pocket {_POCKET_PAIR_NAMES.get(shorthand[0], shorthand[0] + 's')}"
    if len(shorthand) == 3 and shorthand[2] == "s":
        return f"{shorthand[0]}{shorthand[1]} Suited"
    if len(shorthand) == 3 and shorthand[2] == "o":
        return f"{shorthand[0]}{shorthand[1]} Offsuit"
    return shorthand


def _render_poker_table_board() -> None:
    """Render flop | turn | river as one non-wrapping board row on desktop."""
    st.markdown(
        '<div class="el-board">'
        '<div class="el-board-labels">'
        '<div class="el-board-label el-board-label--flop">FLOP</div>'
        '<div class="el-board-gap" aria-hidden="true"></div>'
        '<div class="el-board-label">TURN</div>'
        '<div class="el-board-gap" aria-hidden="true"></div>'
        '<div class="el-board-label">RIVER</div>'
        "</div>"
        '<div class="el-board-cards-anchor" aria-hidden="true"></div>'
        "</div>",
        unsafe_allow_html=True,
    )
    # Flat row: flop ×3 | gap | turn | gap | river (no nested columns).
    board_cols = st.columns(
        [1.0, 1.0, 1.0, BOARD_STREET_GAP, 1.0, BOARD_STREET_GAP, 1.0],
        gap="small",
    )
    with board_cols[0]:
        _render_board_slot("selected_flop_cards", 0, "flop")
    with board_cols[1]:
        _render_board_slot("selected_flop_cards", 1, "flop")
    with board_cols[2]:
        _render_board_slot("selected_flop_cards", 2, "flop")
    with board_cols[4]:
        _render_board_slot("selected_turn_card", 0, "turn")
    with board_cols[6]:
        _render_board_slot("selected_river_card", 0, "river")


def _render_board_card_picker() -> str:
    with st.container(border=True):
        st.markdown(_section_heading_html("Board"), unsafe_allow_html=True)
        st.markdown('<div class="hero-hand-panel el-board-panel">', unsafe_allow_html=True)
        _render_poker_table_board()
        st.markdown(_live_board_analysis_html(), unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

        action_cols = st.columns([1, 1, 1])
        with action_cols[1]:
            st.button("Clear Board", key="clear-board-cards", on_click=_clear_board_cards, use_container_width=False)

    if st.session_state.get("pending_board_dialog"):
        st.session_state.pending_board_dialog = False
        _board_card_picker_dialog()

    return _board_backend_string()


def _render_board_slot(state_key: str, index: int, stage_key: str) -> None:
    slot_key = f"board-slot-{stage_key}-{index}"
    card_key = _board_slot_card(state_key, index)

    if card_key:
        rank, suit = _split_card_key(card_key)
        st.button(
            f"{SUIT_SYMBOLS[suit]} {rank}",
            key=slot_key,
            on_click=_remove_board_slot,
            args=(state_key, index),
            help="Click to remove",
            use_container_width=False,
        )
        return

    can_select = _can_select_board_slot(state_key, index)
    st.button(
        "Add Card",
        key=slot_key,
        on_click=_activate_board_slot,
        args=(state_key, index),
        disabled=not can_select,
        help=_board_slot_help_text(state_key),
        use_container_width=False,
    )


def _render_board_deck_picker(key_prefix: str = "board") -> None:
    selected_set = set(_selected_board_cards())
    hero_cards = {card for card in _hero_slot_values() if card}
    has_empty_slot = _has_empty_board_slot()

    for suit in SUIT_NAMES:
        row_columns = st.columns(13, gap="small")
        for index, rank in enumerate(RANGE_RANKS):
            card_key = f"{rank}{suit}"
            selected = card_key in selected_set
            disabled = (card_key in hero_cards and not selected) or (not has_empty_slot and not selected)
            with row_columns[index]:
                st.button(
                    _card_button_label(rank, suit),
                    key=f"{key_prefix}-card-{card_key}",
                    type="primary" if selected else "secondary",
                    disabled=disabled,
                    on_click=_toggle_board_card,
                    args=(card_key,),
                    use_container_width=True,
                )


@st.dialog("Choose Hero Cards", width="large")
def _hero_card_picker_dialog() -> None:
    active_slot = _validated_active_hero_slot()
    if active_slot is not None:
        st.caption(f"Selecting hole card **{active_slot + 1}** of 2.")
    elif _hero_slot_values().count(None) == 0:
        st.caption("All hole cards are filled. Click a card on the table to remove it, or clear the hand.")
    else:
        st.caption("Click an empty hole card on the table to choose a slot.")

    st.caption("Click a selected card below again to remove it.")
    _render_hero_deck_picker(key_prefix="hero-dialog")

    done_col, clear_col = st.columns(2)
    if done_col.button("Done", type="primary", use_container_width=True, key="hero-picker-done"):
        st.rerun()
    clear_col.button("Clear hand", use_container_width=True, key="hero-picker-clear", on_click=_clear_hero_cards)


def _render_hero_deck_picker(key_prefix: str = "hero-dialog") -> None:
    slots = _hero_slot_values()
    selected_set = {card for card in slots if card}
    has_empty_slot = None in slots
    board_cards = set(_selected_board_cards())

    for suit in SUIT_NAMES:
        row_columns = st.columns(13, gap="small")
        for index, rank in enumerate(RANGE_RANKS):
            card_key = f"{rank}{suit}"
            selected = card_key in selected_set
            disabled = (card_key in board_cards and not selected) or (not has_empty_slot and not selected)
            with row_columns[index]:
                st.button(
                    _card_button_label(rank, suit),
                    key=f"{key_prefix}-card-{card_key}",
                    type="primary" if selected else "secondary",
                    disabled=disabled,
                    on_click=_toggle_hero_card,
                    args=(card_key,),
                    use_container_width=True,
                )


@st.dialog("Choose Board Cards", width="large")
def _board_card_picker_dialog() -> None:
    active_slot = _validated_active_board_slot()
    if not active_slot:
        st.info("All board slots are filled. Click a card on the table to remove it, or clear the board.")
    else:
        st.caption(f"Selecting for: **{_board_slot_label(active_slot)}**")

    st.caption("Click a selected card below again to remove it.")
    _render_board_deck_picker(key_prefix="board-dialog")

    if st.button("Done", type="primary", use_container_width=True, key="board-picker-done"):
        st.rerun()


def _activate_hero_slot(index: int) -> None:
    slots = _hero_slot_values()
    if index < 0 or index > 1 or slots[index] is not None:
        return

    st.session_state.active_hero_slot = index
    st.session_state.pending_hero_dialog = True


def _activate_board_slot(state_key: str, index: int) -> None:
    if _board_slot_card(state_key, index) is not None:
        return
    if not _can_select_board_slot(state_key, index):
        return

    st.session_state.active_board_slot = f"{state_key}:{index}"
    st.session_state.pending_board_dialog = True


def _board_slot_label(active_slot: str) -> str:
    state_key, raw_index = active_slot.split(":")
    index = int(raw_index)
    stage_names = {
        "selected_flop_cards": "Flop",
        "selected_turn_card": "Turn",
        "selected_river_card": "River",
    }
    stage = stage_names.get(state_key, "Board")
    return f"{stage} card {index + 1}"


def _render_card_picker_grid(
    selection_key: str,
    disabled_cards: set[str],
    max_cards: int,
    key_prefix: str,
) -> None:
    selected_cards = list(st.session_state[selection_key])
    selected_set = set(selected_cards)
    at_max = len(selected_cards) >= max_cards

    for suit in SUIT_NAMES:
        row_columns = st.columns(13, gap="small")
        for index, rank in enumerate(RANGE_RANKS):
            card_key = f"{rank}{suit}"
            selected = card_key in selected_set
            disabled = (card_key in disabled_cards) or (at_max and not selected)
            with row_columns[index]:
                st.button(
                    _card_button_label(rank, suit),
                    key=f"{key_prefix}-card-{card_key}",
                    type="primary" if selected else "secondary",
                    disabled=disabled,
                    on_click=_toggle_card,
                    args=(selection_key, card_key, max_cards),
                    use_container_width=True,
                )


def _render_range_controls(*, ns: str = RANGE_NS_OPPONENT, key_prefix: str = "opponent") -> None:
    clear_col, all_col, pair_col, suited_col, offsuit_col = st.columns(5)
    clear_col.button(
        "Clear Range",
        key=f"{key_prefix}-range-clear",
        on_click=_clear_range,
        args=(ns,),
        use_container_width=True,
    )
    all_col.button(
        "Select All",
        key=f"{key_prefix}-range-select-all",
        on_click=_select_hand_group,
        args=(ns, _ordered_grid_hands()),
        use_container_width=True,
    )
    pair_col.button(
        "Select All Pairs",
        key=f"{key_prefix}-range-select-pairs",
        on_click=_select_hand_group,
        args=(ns, _all_pair_hands()),
        use_container_width=True,
    )
    suited_col.button(
        "Select All Suited",
        key=f"{key_prefix}-range-select-suited",
        on_click=_select_hand_group,
        args=(ns, _all_suited_hands()),
        use_container_width=True,
    )
    offsuit_col.button(
        "Select All Offsuit",
        key=f"{key_prefix}-range-select-offsuit",
        on_click=_select_hand_group,
        args=(ns, _all_offsuit_hands()),
        use_container_width=True,
    )


def _render_range_grid(*, ns: str = RANGE_NS_OPPONENT, key_prefix: str = "opponent") -> None:
    st.markdown('<div class="range-grid-shell">', unsafe_allow_html=True)
    weights = _get_range_weights(ns)
    selected = set(weights)
    weight_suffix_rules: list[str] = []
    header_columns = st.columns(14, gap="small")
    header_columns[0].markdown('<div class="range-grid-axis">·</div>', unsafe_allow_html=True)
    for index, rank in enumerate(RANGE_RANKS):
        header_columns[index + 1].markdown(
            f'<div class="range-grid-axis">{rank}</div>',
            unsafe_allow_html=True,
        )

    muted_by_category = {
        "pair": "rgba(214, 201, 174, 0.7)",
        "suited": "rgba(169, 196, 182, 0.7)",
        "offsuit": "rgba(169, 184, 201, 0.7)",
    }

    for row_rank in RANGE_RANKS:
        columns = st.columns(14, gap="small")
        columns[0].markdown(f'<div class="range-grid-axis">{row_rank}</div>', unsafe_allow_html=True)
        for column_index, column_rank in enumerate(RANGE_RANKS):
            hand = _grid_hand_label(row_rank, column_rank)
            category = _range_hand_category(hand)
            is_selected = hand in selected
            weight = int(weights.get(hand, 100))
            cell_key = f"{key_prefix}-range-cell-{category}-{row_rank}-{column_rank}"
            if is_selected and weight < 100:
                muted = muted_by_category.get(category, "rgba(148, 163, 184, 0.75)")
                weight_suffix_rules.append(
                    f"""
                    [class*="st-key-{cell_key}"] button::after {{
                        content: " · {weight}%";
                        font-size: 0.78em;
                        font-weight: 600;
                        letter-spacing: 0;
                        color: {muted};
                    }}
                    """
                )
            with columns[column_index + 1]:
                st.button(
                    hand,
                    key=cell_key,
                    type="primary" if is_selected else "secondary",
                    on_click=_on_range_cell_click,
                    args=(ns, hand),
                    use_container_width=True,
                )
    st.markdown("</div>", unsafe_allow_html=True)
    if weight_suffix_rules:
        st.markdown(
            f"<style>{''.join(weight_suffix_rules)}</style>",
            unsafe_allow_html=True,
        )


def _render_range_builder_workspace(
    *,
    ns: str,
    key_prefix: str,
    grid_heading: str = "Range Grid",
) -> None:
    """Shared weighted range grid + summary used by opponent and hero builders."""
    _render_range_controls(ns=ns, key_prefix=key_prefix)
    grid_col, summary_col = st.columns([2.75, 1], gap="large")
    with grid_col:
        with st.container(border=True):
            st.markdown(f'<h3 class="range-grid-heading">{escape(grid_heading)}</h3>', unsafe_allow_html=True)
            _render_range_grid(ns=ns, key_prefix=key_prefix)
    with summary_col:
        _render_range_summary_panel(ns=ns, key_prefix=key_prefix)


def _render_latest_calculator_results() -> None:
    st.markdown(
        '<div id="equity-results-section" class="results-anchor el-results-page"></div>',
        unsafe_allow_html=True,
    )
    analysis = _get_latest_analysis()
    if not analysis:
        return

    st.markdown('<h2 class="el-page-title el-results-title">Results</h2>', unsafe_allow_html=True)
    flash = st.session_state.pop("heatmap_flash", None)
    if flash:
        st.warning(flash)

    board = parse_cards(analysis["board_input"]) if analysis.get("board_input", "").strip() else []
    hero_hand = parse_cards(analysis["hero_input"], expected_count=2)

    _render_equity_summary(analysis["result"], analysis["decision"])
    _render_equity_heatmap(analysis, board)
    _render_board_texture_analysis(board)
    _render_ev_analysis(analysis["result"], analysis["decision"])
    _render_decision_explanation(analysis["result"], analysis["decision"])
    _render_opponent_range_breakdown(analysis["result"])
    _render_hero_analysis(hero_hand, board)
    _render_simulation_details(analysis)

    save_flash = st.session_state.pop("analysis_save_flash", None)
    if save_flash:
        st.success(save_flash)
    save_icon = _lucide_icon_data_uri("save", size=16, stroke="#94a3b8")
    st.markdown(
        f'<div class="el-save-analysis-row">'
        f'<img src="{save_icon}" alt="" width="16" height="16"/>'
        f"<span>Persist this run to History (inputs + results summary).</span>"
        f"</div>",
        unsafe_allow_html=True,
    )
    if st.button(
        "Save Analysis",
        use_container_width=True,
        key="save-analysis-to-history",
        type="secondary",
    ):
        _save_latest_analysis()


def _equity_margin_subtitle(equity: float, required: float) -> str:
    _status, diff, _tone = _equity_vs_required_status(equity, required)
    pp = abs(diff) * 100.0
    if abs(diff) < 0.005:
        return "At break-even vs required equity"
    if diff > 0:
        return f"+{pp:.1f} pp above required equity"
    return f"−{pp:.1f} pp below required equity"


def _analytics_stat_card_html(
    label: str,
    value_html: str,
    *,
    subtitle: str | None = None,
    icon_uri: str | None = None,
    extra_class: str = "",
    tooltip: str | None = None,
) -> str:
    if icon_uri:
        label_block = (
            f'<div class="el-stat-label-row">'
            f'<img class="el-stat-icon" src="{icon_uri}" alt="" width="16" height="16"/>'
            f'<div class="el-stat-label">{escape(label)}</div>'
            f"</div>"
        )
    else:
        label_block = f'<div class="el-stat-label">{escape(label)}</div>'
    sub = (
        f'<div class="el-stat-subtitle">{escape(subtitle)}</div>'
        if subtitle
        else ""
    )
    title_attr = f' title="{escape(tooltip)}"' if tooltip else ""
    return (
        f'<div class="el-stat-card {extra_class}"{title_attr}>'
        f"{label_block}"
        f'<div class="el-stat-value">{value_html}</div>'
        f"{sub}"
        f"</div>"
    )


def _recommendation_pill_html(recommendation: str) -> str:
    rec_class, _icon, _stroke = _recommendation_visuals(recommendation)
    return (
        f'<span class="el-rec-pill {rec_class} el-rec-reveal">'
        f"{escape(str(recommendation))}</span>"
    )


def _render_equity_summary(result, decision) -> None:
    subtitle = _equity_margin_subtitle(float(result.equity), float(decision.required_equity))
    _status, _diff, status_tone = _equity_vs_required_status(
        float(result.equity), float(decision.required_equity)
    )
    hero_value = escape(_format_percent(result.equity))
    win_value = escape(_format_percent(result.win_rate))
    tie_value = escape(_format_percent(result.tie_rate))
    loss_value = escape(_format_percent(result.loss_rate))
    with _dashboard_card("Equity Summary"):
        st.markdown(
            f"""
            <div class="el-equity-summary el-results-block">
              {_equity_share_bar_html(result.win_rate, result.tie_rate, result.loss_rate)}
              <div class="el-equity-stats">
                <div class="el-equity-hero-stat">
                  <div class="el-stat-label">Hero Equity</div>
                  <div class="el-equity-hero-value">{hero_value}</div>
                  <div class="el-equity-hero-sub {status_tone}">{escape(subtitle)}</div>
                </div>
                <div class="el-equity-wtl">
                  {_analytics_stat_card_html("Win", win_value)}
                  {_analytics_stat_card_html("Tie", tie_value)}
                  {_analytics_stat_card_html("Loss", loss_value)}
                </div>
              </div>
              <p class="el-results-meta">
                Matchups: {escape(_format_weighted_count(result.total))} · Mode: {escape(str(result.mode))} ·
                Hero best hand: {escape(str(result.hero_hand_label))} · Time: {result.runtime_ms:.1f} ms
              </p>
            </div>
            """,
            unsafe_allow_html=True,
        )


def _ensure_analysis_heatmap(analysis: dict, board) -> dict:
    """Return heatmap cells for this analysis, computing/caching if needed."""
    heatmap = analysis.get("heatmap")
    if isinstance(heatmap, dict) and heatmap:
        return heatmap

    opponent_range = analysis.get("opponent_range")
    simulations = int(analysis.get("simulations", DEFAULT_MONTE_CARLO_TRIALS))
    # Weights are not stored on older analyses; uniform weights match presets.
    opponent_weights = analysis.get("opponent_weights")
    heatmap = get_or_compute_equity_heatmap(
        board,
        opponent_range=opponent_range,
        opponent_weights=opponent_weights,
        simulations=simulations,
    )
    analysis["heatmap"] = heatmap
    analysis["heatmap_key"] = build_heatmap_cache_key(
        board,
        opponent_range,
        opponent_weights,
        heatmap_simulation_budget(simulations),
        heatmap_exact_max_matchups(board, 75_000),
    )
    analysis["heatmap_simulations"] = heatmap_simulation_budget(simulations)
    analysis["heatmap_cache_hit"] = last_heatmap_cache_hit()
    return heatmap


def _render_equity_heatmap(analysis: dict, board) -> None:
    heatmap = _ensure_analysis_heatmap(analysis, board)
    active_hero = _hero_hand_shorthand(_hero_slot_values()) or _hero_hand_shorthand_from_input(
        str(analysis.get("hero_input", ""))
    )
    selected_metric = st.session_state.get("heatmap_display_metric", "Equity")
    pot_size = float(analysis.get("pot_size", st.session_state.get("calc_pot_size", 100.0)))
    call_amount = float(analysis.get("call_amount", st.session_state.get("calc_call_amount", 25.0)))
    heatmap_sims = int(
        analysis.get(
            "heatmap_simulations",
            heatmap_simulation_budget(int(analysis.get("simulations", DEFAULT_MONTE_CARLO_TRIALS))),
        )
    )
    color_rules: list[str] = []

    with _dashboard_card("Equity Heatmap"):
        st.markdown('<div class="el-results-block" aria-hidden="true"></div>', unsafe_allow_html=True)
        st.caption(
            "Each cell is that starting hand vs the current opponent range and board. "
            "Hover for details. Click a cell to load it as hero and recalculate."
        )
        metric = st.selectbox(
            "Heatmap metric",
            options=("Equity", "Win %", "Tie %", "EV", "Call EV"),
            key="heatmap_display_metric",
            help="Color and cell labels follow the selected metric.",
        )
        selected_metric = metric

        st.markdown('<div class="heatmap-grid-shell range-grid-shell">', unsafe_allow_html=True)
        header_columns = st.columns(14, gap="small")
        header_columns[0].markdown('<div class="range-grid-axis">·</div>', unsafe_allow_html=True)
        for index, rank in enumerate(HEATMAP_RANKS):
            header_columns[index + 1].markdown(
                f'<div class="range-grid-axis">{rank}</div>',
                unsafe_allow_html=True,
            )

        for row_rank in HEATMAP_RANKS:
            columns = st.columns(14, gap="small")
            columns[0].markdown(f'<div class="range-grid-axis">{row_rank}</div>', unsafe_allow_html=True)
            for column_index, column_rank in enumerate(HEATMAP_RANKS):
                hand = _grid_hand_label(row_rank, column_rank)
                cell = heatmap.get(hand)
                raw_value = _heatmap_metric_value(cell, selected_metric, pot_size, call_amount)
                color_unit = _heatmap_metric_color_unit(
                    selected_metric, raw_value, pot_size, call_amount
                )
                color = equity_to_heatmap_color(color_unit)
                is_active = bool(active_hero) and hand == active_hero
                cell_key = f"heatmap-cell-{row_rank}-{column_rank}"
                text_color = _heatmap_text_color(color_unit)
                label = _heatmap_cell_label(hand, selected_metric, raw_value)
                tooltip = _heatmap_cell_tooltip(
                    hand, cell, heatmap_sims, pot_size, call_amount
                )
                if is_active:
                    color_rules.append(
                        f"""
                        [class*="st-key-{cell_key}"] button {{
                            background: {color} !important;
                            border: 2px solid #38bdf8 !important;
                            color: {text_color} !important;
                            font-size: 0.62rem !important;
                            line-height: 1.15 !important;
                            white-space: pre-line !important;
                            box-shadow: 0 0 0 2px rgba(14, 165, 233, 0.55),
                                        0 0 16px rgba(56, 189, 248, 0.45) !important;
                            z-index: 2;
                            position: relative;
                        }}
                        """
                    )
                else:
                    extreme = ""
                    if color_unit is not None:
                        if color_unit >= 0.82:
                            extreme = (
                                "outline: 1px solid rgba(52, 211, 153, 0.85) !important;"
                            )
                        elif color_unit <= 0.22:
                            extreme = (
                                "outline: 1px solid rgba(251, 113, 133, 0.8) !important;"
                            )
                    color_rules.append(
                        f"""
                        [class*="st-key-{cell_key}"] button {{
                            background: {color} !important;
                            border: 1px solid rgba(15, 23, 42, 0.85) !important;
                            color: {text_color} !important;
                            font-size: 0.62rem !important;
                            line-height: 1.15 !important;
                            white-space: pre-line !important;
                            box-shadow: none !important;
                            {extreme}
                        }}
                        """
                    )
                with columns[column_index + 1]:
                    st.button(
                        label,
                        key=cell_key,
                        help=tooltip,
                        disabled=cell is None or cell.equity is None,
                        on_click=_load_hero_from_heatmap_hand,
                        args=(hand,),
                        use_container_width=True,
                    )
        st.markdown("</div>", unsafe_allow_html=True)
        if color_rules:
            st.markdown(f"<style>{''.join(color_rules)}</style>", unsafe_allow_html=True)

        st.markdown(_heatmap_legend_html(selected_metric, pot_size, call_amount), unsafe_allow_html=True)
        board_note = (
            "Board: " + " ".join(card.key() for card in board)
            if board
            else "Board: preflop (no community cards)"
        )
        st.caption(
            f"{board_note} · Opponent: {analysis.get('opponent_label', '—')} · "
            f"Primary calc trials: {int(analysis.get('simulations', DEFAULT_MONTE_CARLO_TRIALS)):,} · "
            f"Heatmap budget: {heatmap_sims:,}/class (cells may be noisier than primary equity)"
        )


def _hero_hand_shorthand_from_input(hero_input: str) -> str:
    tokens = [token for token in hero_input.split() if token]
    if len(tokens) != 2:
        return ""
    try:
        return _hero_hand_shorthand(
            [_normalize_card_key(tokens[0]), _normalize_card_key(tokens[1])]
        )
    except Exception:
        return ""


def _heatmap_metric_value(cell, metric: str, pot_size: float, call_amount: float) -> float | None:
    if cell is None or cell.equity is None:
        return None
    if metric == "Equity":
        return float(cell.equity)
    if metric == "Win %":
        return float(cell.win_rate or 0.0)
    if metric == "Tie %":
        return float(cell.tie_rate or 0.0)
    if metric == "EV":
        return float(cell.equity) * float(pot_size)
    if metric == "Call EV":
        return float(cell.equity) * (float(pot_size) + float(call_amount)) - float(call_amount)
    return float(cell.equity)


def _heatmap_metric_color_unit(
    metric: str, value: float | None, pot_size: float, call_amount: float
) -> float | None:
    if value is None:
        return None
    if metric in {"Equity", "Win %"}:
        return max(0.0, min(1.0, float(value)))
    if metric == "Tie %":
        # Ties are usually small; stretch the scale so differences remain visible.
        return max(0.0, min(1.0, float(value) / 0.20))
    if metric == "EV":
        if pot_size <= 0:
            return 0.5
        return max(0.0, min(1.0, float(value) / float(pot_size)))
    # Call EV: -call → 0, 0 → ~call/(pot+call), +pot → 1
    pot_plus_call = float(pot_size) + float(call_amount)
    if pot_plus_call <= 0:
        return 0.5
    return max(0.0, min(1.0, (float(value) + float(call_amount)) / pot_plus_call))


def _heatmap_cell_label(hand: str, metric: str, value: float | None) -> str:
    if value is None:
        return hand
    if metric in {"Equity", "Win %", "Tie %"}:
        return f"{hand}\n{_format_percent(value)}"
    return f"{hand}\n{value:+.1f}"


def _heatmap_legend_html(metric: str, pot_size: float, call_amount: float) -> str:
    if metric in {"Equity", "Win %"}:
        low, mid, high = "0%", "50%", "100%"
        low_label, mid_label, high_label = "Low Equity", "Medium Equity", "High Equity"
        title = metric
    elif metric == "Tie %":
        low, mid, high = "0%", "~10%", "20%+"
        low_label, mid_label, high_label = "Low", "Medium", "High"
        title = "Tie %"
    elif metric == "EV":
        low, mid, high = "0", f"{pot_size / 2:,.0f}", f"{pot_size:,.0f}"
        low_label, mid_label, high_label = "Low", "Medium", "High"
        title = "EV (equity × pot)"
    else:
        low, mid, high = f"{-call_amount:,.0f}", "0", f"{pot_size:,.0f}"
        low_label, mid_label, high_label = "Low", "Break-even", "High"
        title = "Call EV"

    return (
        '<div class="heatmap-legend">'
        f'<div class="heatmap-legend-title">{escape(title)}</div>'
        '<div class="heatmap-legend-track">'
        '<span class="heatmap-legend-bar" aria-hidden="true"></span>'
        '<div class="heatmap-legend-marks">'
        f'<div class="heatmap-legend-mark"><strong>{escape(low)}</strong><span>{escape(low_label)}</span></div>'
        f'<div class="heatmap-legend-mark"><strong>{escape(mid)}</strong><span>{escape(mid_label)}</span></div>'
        f'<div class="heatmap-legend-mark"><strong>{escape(high)}</strong><span>{escape(high_label)}</span></div>'
        "</div></div></div>"
    )


def _heatmap_text_color(unit: float | None) -> str:
    if unit is None:
        return "#64748b"
    if unit <= 0.38 or unit >= 0.62:
        return "#f8fafc"
    return "#0f172a"


def _heatmap_cell_tooltip(
    hand: str,
    cell,
    heatmap_sims: int,
    pot_size: float,
    call_amount: float,
) -> str:
    if cell is None or cell.equity is None:
        return f"{hand}\nNo legal combos on this board."

    call_ev = float(cell.equity) * (pot_size + call_amount) - call_amount
    pot_ev = float(cell.equity) * pot_size
    sims_note = ""
    if cell.legal_combos > 0:
        sims_each = max(50, int(heatmap_sims) // int(cell.legal_combos))
        sims_note = f"\nSimulations: ~{sims_each * cell.legal_combos:,} (budget {heatmap_sims:,}/class)"
    return (
        f"{hand}\n"
        f"Equity: {_format_percent(cell.equity)}\n"
        f"Win %: {_format_percent(cell.win_rate)}\n"
        f"Tie %: {_format_percent(cell.tie_rate)}\n"
        f"Loss %: {_format_percent(cell.loss_rate)}\n"
        f"EV: {pot_ev:+,.2f}\n"
        f"Call EV: {call_ev:+,.2f}"
        f"{sims_note}"
    )


def _load_hero_from_heatmap_hand(hand: str) -> None:
    analysis = st.session_state.get("latest_analysis")
    board_input = _board_backend_string()
    if not board_input.strip() and isinstance(analysis, dict):
        board_input = str(analysis.get("board_input", "") or "")
    board = parse_cards(board_input) if board_input.strip() else []
    combo = pick_display_combo(hand, board)
    if combo is None:
        st.session_state.heatmap_flash = (
            f"{hand} has no legal combos with the current board cards."
        )
        return

    st.session_state.hero_slot_cards = [
        _normalize_card_key(combo[0].key()),
        _normalize_card_key(combo[1].key()),
    ]
    _sync_hero_cards_from_slots()
    st.session_state.active_hero_slot = None
    st.session_state.heatmap_selected_hand = hand
    st.session_state.heatmap_flash = None

    opponent_label = st.session_state.get(
        "calc_opponent_range",
        analysis.get("opponent_label", "Random") if isinstance(analysis, dict) else "Random",
    )
    pot_size = float(
        st.session_state.get(
            "calc_pot_size",
            analysis.get("pot_size", 100.0) if isinstance(analysis, dict) else 100.0,
        )
    )
    call_amount = float(
        st.session_state.get(
            "calc_call_amount",
            analysis.get("call_amount", 25.0) if isinstance(analysis, dict) else 25.0,
        )
    )
    simulations = int(
        st.session_state.get(
            "calc_simulations",
            analysis.get("simulations", DEFAULT_MONTE_CARLO_TRIALS)
            if isinstance(analysis, dict)
            else DEFAULT_MONTE_CARLO_TRIALS,
        )
    )
    hero_input = " ".join(st.session_state.selected_hero_cards)
    _calculate_and_store_analysis(
        hero_input, board_input, opponent_label, pot_size, call_amount, simulations
    )
    st.session_state.scroll_to_results = True


def _render_board_texture_analysis(board) -> None:
    texture = analyze_board_texture(board)
    chips = "".join(
        f'<span class="texture-chip">{escape(label)}</span>' for label in texture.labels
    )
    with _dashboard_card("Board Texture Analysis"):
        st.markdown(
            f'<div class="el-results-block">'
            f'<div class="texture-chip-row">{chips}</div>'
            f'<p class="texture-explanation">{escape(texture.explanation)}</p>'
            f"</div>",
            unsafe_allow_html=True,
        )


def _render_ev_analysis(result, decision) -> None:
    del result  # Equity lives in Equity Summary / Decision Explanation — avoid repeating it here.
    rec_class, _icon, _stroke = _recommendation_visuals(str(decision.recommendation))
    required_tip = (
        "Required Equity = Amount to Call ÷ (Pot Before Calling + Amount to Call). "
        "Break-even equity for a call."
    )
    call_ev_tip = (
        "Call EV = Equity × (Pot Before Calling + Amount to Call) − Amount to Call. "
        "Fold EV is modeled as 0; Call when this value is ≥ 0."
    )
    pot_tip = "Pot size in chips before hero calls (does not include the call amount)."
    call_tip = "Chips hero must put in to call."
    cards = "".join(
        (
            _analytics_stat_card_html(
                "Required Equity",
                escape(_format_percent(decision.required_equity)),
                tooltip=required_tip,
            ),
            _analytics_stat_card_html(
                "Call EV",
                escape(f"{float(decision.call_ev):+,.2f}"),
                tooltip=call_ev_tip,
            ),
            _analytics_stat_card_html(
                "Pot Before Calling",
                escape(f"{float(decision.pot_size):,.2f}"),
                tooltip=pot_tip,
            ),
            _analytics_stat_card_html(
                "Amount to Call",
                escape(f"{float(decision.call_amount):,.2f}"),
                tooltip=call_tip,
            ),
            _analytics_stat_card_html(
                "Recommendation",
                _recommendation_pill_html(str(decision.recommendation)),
                extra_class=f"el-stat-card-rec {rec_class}",
            ),
        )
    )
    with _dashboard_card("EV Analysis"):
        st.markdown(
            f'<div class="el-stat-row el-stat-row-5 el-results-block">{cards}</div>'
            f'<p class="el-results-meta">'
            "Pot Before Calling is the pot prior to hero's call. Hover cards for formulas."
            "</p>",
            unsafe_allow_html=True,
        )


# Decision explanation / confidence logic lives in decision_analysis (pure, testable).


def _decision_equity_margin(result, decision) -> float:
    return _pure_equity_margin(float(result.equity), float(decision.required_equity))


def _decision_confidence_level(equity_margin: float) -> str:
    return _pure_confidence_level(equity_margin)


def _build_decision_explanation(result, decision) -> str:
    return _pure_build_decision_explanation(
        float(result.equity),
        float(decision.required_equity),
        float(decision.call_ev),
        str(decision.recommendation),
    )


def _build_decision_sensitivity(result, decision) -> str:
    return _pure_build_decision_sensitivity(
        float(result.equity),
        float(decision.required_equity),
        float(decision.call_ev),
    )


def _format_chip_amount(value: float) -> str:
    return f"{value:,.2f}"


def _build_decision_calculation_steps(result, decision) -> str:
    pot = float(decision.pot_size)
    call = float(decision.call_amount)
    equity = float(result.equity)
    pot_plus_call = pot + call
    required = float(decision.required_equity)
    gross = equity * pot_plus_call
    call_ev = float(decision.call_ev)

    if call <= 0:
        required_line = (
            f"Required Equity = Amount to Call / (Pot Before Calling + Amount to Call) = "
            f"{_format_chip_amount(call)} / "
            f"({_format_chip_amount(pot)} + {_format_chip_amount(call)}) → 0 "
            f"(no chips at risk; any non-negative Call EV favors calling)."
        )
    else:
        required_line = (
            f"Required Equity = Amount to Call / (Pot Before Calling + Amount to Call) = "
            f"{_format_chip_amount(call)} / "
            f"({_format_chip_amount(pot)} + {_format_chip_amount(call)}) = "
            f"{_format_chip_amount(call)} / {_format_chip_amount(pot_plus_call)} = "
            f"{required:.4f} = {_format_percent(required)}"
        )

    ev_line = (
        f"Call EV = Equity × (Pot Before Calling + Amount to Call) − Amount to Call = "
        f"{equity:.4f} × {_format_chip_amount(pot_plus_call)} − {_format_chip_amount(call)} = "
        f"{_format_chip_amount(gross)} − {_format_chip_amount(call)} = "
        f"{call_ev:+,.2f}"
    )
    return f"{required_line}\n\n{ev_line}"


def _decision_confidence_banner(confidence: str) -> tuple[str, str]:
    """Return (emoji_prefix, css_modifier) for the confidence banner."""
    mapping = {
        "Very Strong Call": ("🟢", "call-strong"),
        "Strong Call": ("🟢", "call-strong"),
        "Marginal Call": ("🟡", "call-marginal"),
        "Marginal Fold": ("🟠", "fold-marginal"),
        "Strong Fold": ("🔴", "fold-strong"),
        "Very Strong Fold": ("🔴", "fold-strong"),
    }
    return mapping.get(confidence, ("⚪", "neutral"))


def _decision_stability_html(result, decision) -> str:
    """Render Monte Carlo decision stability against the break-even threshold."""
    if str(getattr(result, "mode", "")) != "monte-carlo":
        return ""
    completed = int(getattr(result, "boards_evaluated", 0) or 0)
    if completed <= 1:
        return ""

    stability = _pure_decision_stability(
        float(result.equity), float(decision.required_equity), completed
    )
    stability_mod = "overlap" if stability.threshold_overlaps else "stable"
    stability_copy = (
        "The approximate 95% Monte Carlo confidence interval crosses the break-even threshold. "
        "Use more trials or treat this as a close decision."
        if stability.threshold_overlaps
        else "The full approximate 95% Monte Carlo confidence interval stays on the same side of break-even."
    )
    return (
        f'<div class="decision-stability decision-stability-{stability_mod}">'
        f'<div class="decision-stability-title">Simulation-aware check: '
        f'{escape(stability.label)}</div>'
        f'<p>{escape(stability_copy)}</p>'
        f'<span>{escape(_format_percent(stability.lower_equity))}–'
        f'{escape(_format_percent(stability.upper_equity))} vs '
        f'{escape(_format_percent(float(decision.required_equity)))} required</span>'
        f'</div>'
    )


def _render_decision_explanation(result, decision) -> None:
    equity_margin = _decision_equity_margin(result, decision)
    confidence = _decision_confidence_level(equity_margin)
    explanation = _build_decision_explanation(result, decision)
    sensitivity = _build_decision_sensitivity(result, decision)
    emoji, banner_mod = _decision_confidence_banner(confidence)
    analysis = _get_latest_analysis() or {
        "result": result,
        "decision": decision,
        "simulations": st.session_state.get("calc_simulations", DEFAULT_MONTE_CARLO_TRIALS),
        "hero_input": " ".join(slot for slot in _hero_slot_values() if slot),
        "board_input": " ".join(_selected_board_cards()),
    }
    why_bullets = _decision_why_bullets(analysis)
    why_items = "".join(f"<li>{escape(b)}</li>" for b in why_bullets)

    stability_html = _decision_stability_html(result, decision)

    # Optional draw context — never claim draws alone make the call +EV.
    draw_note = ""
    try:
        board_keys = str(analysis.get("board_input", "")).split()
        hero_keys = str(analysis.get("hero_input", "")).split()
        if len(board_keys) >= 3 and len(hero_keys) >= 2:
            payload = _live_board_analysis_payload(hero_keys[:2], board_keys)
            primary = payload.get("primary_draw")
            if primary:
                draw_note = (
                    f'<p class="decision-draw-note">'
                    f"{escape(str(primary))} improves Hero's ability to realize equity on later "
                    f"streets; the Call/Fold recommendation above is driven by Call EV, not by "
                    f"the draw alone."
                    f"</p>"
                )
    except (ValueError, TypeError, KeyError):
        draw_note = ""

    with _dashboard_card("Decision Explanation"):
        st.markdown(
            f'<div class="el-results-block">'
            f'<div class="decision-status-banner decision-status-{banner_mod}">'
            f'<span class="decision-status-emoji" aria-hidden="true">{emoji}</span>'
            f'<span class="decision-status-text">{escape(confidence)}</span>'
            f"</div>"
            f'<div class="decision-why">'
            f'<div class="decision-why-title">Why?</div>'
            f'<ul class="decision-why-list">{why_items}</ul>'
            f"</div>"
            f'<p class="decision-explanation">{escape(explanation)}</p>'
            f"{stability_html}"
            f"{draw_note}"
            f'<p class="decision-sensitivity">{escape(sensitivity)}</p>'
            f"</div>",
            unsafe_allow_html=True,
        )
        with st.expander("How this was calculated", expanded=False):
            st.markdown(
                f'<pre class="decision-calc-steps">{escape(_build_decision_calculation_steps(result, decision))}</pre>',
                unsafe_allow_html=True,
            )


def _render_simulation_details(analysis: dict) -> None:
    result = analysis["result"]
    mode = str(getattr(result, "mode", "—"))
    mode_label = "Monte Carlo" if mode == "monte-carlo" else ("Exact" if mode == "exact" else mode)
    requested = int(analysis.get("simulations", getattr(result, "boards_evaluated", 0) or 0))
    completed = int(getattr(result, "boards_evaluated", 0) or 0)
    heatmap_sims = int(
        analysis.get(
            "heatmap_simulations",
            heatmap_simulation_budget(requested),
        )
    )
    heatmap_cached = bool(analysis.get("heatmap_cache_hit", False))

    uncertainty_html = ""
    if mode == "monte-carlo" and completed > 1:
        ci_text = _pure_format_monte_carlo_equity_ci(float(result.equity), completed)
        uncertainty_html = (
            f'<div class="el-sim-uncertainty">'
            f'<div class="el-stat-label">Hero equity uncertainty</div>'
            f'<div class="el-sim-uncertainty-value">{escape(ci_text)}</div>'
            f'<p class="el-results-meta">'
            "Approximate normal interval from binomial standard error using completed "
            "Monte Carlo trials. Not a guarantee of true equity."
            "</p>"
            f"</div>"
        )

    diag_rows = (
        ("Mode", mode_label),
        ("Requested trials", f"{requested:,}"),
        ("Completed trials", f"{completed:,}"),
        ("Heatmap budget (per class)", f"{heatmap_sims:,}"),
        ("Heatmap cache", "Hit (reused)" if heatmap_cached else "Miss (recomputed)"),
    )
    diag_html = "".join(
        "<div class='decision-key-row'>"
        f"<span class='decision-key-label'>{escape(label)}</span>"
        f"<span class='decision-key-value'>{escape(value)}</span>"
        "</div>"
        for label, value in diag_rows
    )

    with st.expander("Simulation Details", expanded=False):
        _render_hand_distribution(result)
        _render_performance_panel(result)
        st.markdown(
            f'<div class="el-results-block el-sim-diagnostics">'
            f'<p class="decision-key-heading">Simulation diagnostics</p>'
            f'<div class="decision-key-list">{diag_html}</div>'
            f"{uncertainty_html}"
            f'<p class="el-results-meta">'
            "Technical inspection of the run. Primary decision metrics live above."
            "</p>"
            f"</div>",
            unsafe_allow_html=True,
        )


def _render_opponent_range_breakdown(result) -> None:
    distribution = getattr(result, "opponent_hand_distribution", None) or {}
    total = result.total or 0
    rows = []
    for category in reversed(HAND_CATEGORIES):
        count = int(distribution.get(category, 0))
        share = (count / total) if total else 0.0
        percent = _format_percent(share)
        bar_w = max(0.0, min(100.0, share * 100.0))
        rows.append(
            "<div class='opp-hand-row'>"
            f"<span class='opp-hand-bar' style='width:{bar_w:.2f}%' aria-hidden='true'></span>"
            f"<span class='opp-hand-label'>{escape(category)}</span>"
            f"<span class='opp-hand-count'>{escape(_format_weighted_count(count))}</span>"
            f"<span class='opp-hand-pct'>{escape(percent)}</span>"
            "</div>"
        )
    with _dashboard_card("Opponent Final Hand Distribution"):
        st.markdown(
            "<div class='opp-hand-breakdown el-results-block'>"
            "<div class='opp-hand-row opp-hand-header'>"
            "<span class='opp-hand-label'>Hand category</span>"
            "<span class='opp-hand-count'>Count</span>"
            "<span class='opp-hand-pct'>Share</span>"
            "</div>"
            f"{''.join(rows)}"
            "</div>"
            '<p class="el-results-meta" title="'
            "Distribution of the opponent's final best five-card hand across simulated matchups."
            '">'
            "Distribution of the opponent's final best five-card hand across simulated matchups."
            "</p>",
            unsafe_allow_html=True,
        )


def _render_hero_analysis(hero_hand, board) -> None:
    situation = analyze_hero_situation(hero_hand, board)
    primary_draws, secondary_draws = _split_hero_draws(situation.draws)
    texture = analyze_board_texture(board) if len(board) >= 3 else None
    category, detail = _split_made_hand_label(situation.made_hand_label or "")
    trophy = _lucide_icon_data_uri("trophy", size=14, stroke="#fbbf24")

    hand_chips = (
        f'<span class="el-live-chip el-live-chip-hand">'
        f'<img src="{trophy}" alt="" width="14" height="14"/>'
        f"{escape(category or situation.made_hand_label or '—')}</span>"
    )
    if detail:
        hand_chips += (
            f'<span class="el-live-chip el-live-chip-detail">'
            f"{escape(_chip_high_label(detail))}</span>"
        )

    if primary_draws:
        primary_html = "".join(
            f'<span class="el-live-chip el-live-chip-draw">{escape(label)}</span>'
            for label in primary_draws
        )
    else:
        primary_html = '<span class="el-live-chip el-live-chip-empty">—</span>'

    if secondary_draws:
        secondary_html = "".join(
            f'<span class="el-live-chip el-live-chip-draw">{escape(label)}</span>'
            for label in secondary_draws
        )
    else:
        secondary_html = '<span class="el-live-chip el-live-chip-empty">—</span>'

    if texture and texture.labels:
        texture_html = "".join(
            f'<span class="el-live-chip el-live-chip-texture">{escape(label)}</span>'
            for label in texture.labels
        )
    else:
        texture_html = '<span class="el-live-chip el-live-chip-empty">—</span>'

    outs_html = (
        f'<span class="el-live-chip el-live-chip-detail">{situation.outs}</span>'
        if situation.outs is not None and (primary_draws or secondary_draws)
        else '<span class="el-live-chip el-live-chip-empty">—</span>'
    )
    street_html = (
        f'<span class="el-live-chip el-live-chip-texture">{escape(situation.street)}</span>'
    )

    rows = [
        ("Best Hand", hand_chips),
        ("Primary Draw", primary_html),
        ("Secondary Draw", secondary_html),
        ("Board Texture", texture_html),
        ("Street", street_html),
        ("Outs", outs_html),
    ]
    if situation.overcard_count:
        rows.append(
            (
                "Overcards",
                f'<span class="el-live-chip el-live-chip-detail">'
                f"{situation.overcard_count}</span>",
            )
        )

    grid = "".join(
        "<div class='hero-grid-row'>"
        f"<span class='hero-grid-label'>{escape(label)}</span>"
        f"<div class='hero-grid-value'>{value}</div>"
        "</div>"
        for label, value in rows
    )

    with _dashboard_card("Hero Analysis"):
        st.markdown(
            f'<div class="hero-analysis-grid el-results-block el-fade-up">{grid}</div>',
            unsafe_allow_html=True,
        )


def _split_hero_draws(draws: tuple[str, ...]) -> tuple[list[str], list[str]]:
    primary: list[str] = []
    secondary: list[str] = []
    for label in draws:
        if "Backdoor" in label:
            secondary.append(label)
        else:
            primary.append(label)
    return primary, secondary


def _hero_current_street(board_count: int) -> str:
    if board_count <= 0:
        return "Preflop"
    if board_count <= 3:
        return "Flop"
    if board_count == 4:
        return "Turn"
    return "River"


def _hero_current_made_hand(hero_hand, board) -> str:
    cards = [*hero_hand, *board]
    if len(cards) >= 5:
        return HAND_CATEGORIES[evaluate_best_hand(cards).category]

    rank_counts: dict[str, int] = {}
    for card in cards:
        rank_counts[card.rank] = rank_counts.get(card.rank, 0) + 1
    frequencies = sorted(rank_counts.values(), reverse=True)
    top = frequencies[0] if frequencies else 0
    pair_count = sum(1 for count in frequencies if count >= 2)

    if top >= 4:
        return "Four of a Kind"
    if top >= 3:
        return "Three of a Kind"
    if pair_count >= 2:
        return "Two Pair"
    if pair_count == 1:
        return "One Pair"
    return "Unpaired"


def _render_hand_distribution(result) -> None:
    total = float(result.total or 0)
    body_rows = []
    # Prefer strongest→weakest when labels match HAND_LABELS order.
    items = list(result.hand_distribution.items())
    for label, count in reversed(items):
        if not count:
            continue
        share = (float(count) / total) if total else 0.0
        bar_w = max(0.0, min(100.0, share * 100.0))
        body_rows.append(
            "<tr>"
            f"<td>{escape(str(label).title() if str(label)[:1].islower() else str(label))}</td>"
            f"<td class='el-dist-num'>{escape(_format_weighted_count(count))}</td>"
            f"<td class='el-dist-num el-dist-share'>"
            f"<span class='el-dist-bar' style='width:{bar_w:.2f}%' aria-hidden='true'></span>"
            f"<span class='el-dist-share-text'>{escape(_format_percent(share))}</span>"
            f"</td>"
            "</tr>"
        )
    table = (
        '<table class="el-dist-table">'
        "<thead><tr><th>Hand Category</th><th>Count</th><th>Share</th></tr></thead>"
        f"<tbody>{''.join(body_rows) if body_rows else '<tr><td colspan=\"3\">No data</td></tr>'}</tbody>"
        "</table>"
    )
    with _dashboard_card("Hero Final Hand Distribution"):
        st.markdown(
            f'<div class="el-results-block">'
            f'<p class="el-results-meta">Hero\'s final made-hand category across simulated runouts.</p>'
            f"{table}"
            f"</div>",
            unsafe_allow_html=True,
        )


def _render_range_composition(opponent_range, selected_range_hands: list[str]) -> None:
    breakdown = _custom_range_breakdown(selected_range_hands, _selected_range_weights())
    with _dashboard_card("Range Composition"):
        st.write(
            f"Pairs: {_format_weighted_count(breakdown['pairs'])} · "
            f"Suited: {_format_weighted_count(breakdown['suited'])} · "
            f"Offsuit: {_format_weighted_count(breakdown['offsuit'])} · "
            f"Legal combos: {len(opponent_range):,}"
        )


def _render_performance_panel(result) -> None:
    boards_icon = _lucide_icon_data_uri("layout-grid", size=16, stroke="#94a3b8")
    combos_icon = _lucide_icon_data_uri("users", size=16, stroke="#94a3b8")
    runtime_icon = _lucide_icon_data_uri("zap", size=16, stroke="#94a3b8")
    cards = "".join(
        (
            _analytics_stat_card_html(
                "Boards Evaluated",
                escape(f"{int(result.boards_evaluated):,}"),
                subtitle="Simulated outcomes",
                icon_uri=boards_icon,
            ),
            _analytics_stat_card_html(
                "Opponent Matchups",
                escape(f"{int(result.opponent_combinations_evaluated):,}"),
                subtitle="Evaluated opponent states",
                icon_uri=combos_icon,
            ),
            _analytics_stat_card_html(
                "Runtime",
                escape(f"{float(result.runtime_ms):.1f} ms"),
                subtitle="Engine execution time",
                icon_uri=runtime_icon,
            ),
        )
    )
    with _dashboard_card("Performance"):
        st.markdown(
            f'<div class="el-stat-row el-stat-row-3 el-results-block">{cards}</div>',
            unsafe_allow_html=True,
        )


def _render_saved_ranges() -> None:
    st.markdown("### Saved Ranges")
    flash = st.session_state.pop("saved_range_flash", None)
    if flash:
        st.success(flash)
    saved_ranges = load_saved_ranges()
    if not saved_ranges:
        st.caption("No saved ranges yet.")
        return

    for saved_range in saved_ranges:
        weights = normalize_hand_weights(saved_range.get("weights") or {})
        stats = _range_summary_stats(saved_range["hands"], weights)
        with st.container(border=True):
            name_col, classes_col, combos_col, pct_col, action_col = st.columns([2.4, 1.4, 1.6, 1.2, 1])
            name_col.markdown(f"**{saved_range['name']}**")
            classes_col.metric("Hand classes", f"{stats['hand_classes']:,}")
            combos_col.metric("Effective combos", _format_weighted_count(float(stats["effective_combos"])))
            pct_col.metric("Percentage", f"{stats['percentage']:.1f}%")
            action_col.button(
                "Load",
                key=f"load-range-{saved_range['id']}",
                on_click=_load_saved_range,
                args=(saved_range["id"],),
                use_container_width=True,
            )
            action_col.button(
                "Edit",
                key=f"edit-range-{saved_range['id']}",
                on_click=_edit_saved_range,
                args=(saved_range["id"],),
                use_container_width=True,
            )
            action_col.button(
                "Delete",
                key=f"delete-range-{saved_range['id']}",
                on_click=_delete_saved_range,
                args=(saved_range["id"],),
                use_container_width=True,
            )
            st.caption(_saved_range_preview(saved_range["hands"], weights) or "—")


def _calculate_and_store_analysis(
    hero_input: str,
    board_input: str,
    opponent_label: str,
    pot_size: float,
    call_amount: float,
    simulations: int,
) -> None:
    try:
        hero_hand = parse_cards(hero_input, expected_count=2)
        board = parse_cards(board_input) if board_input.strip() else []
        opponent_range, opponent_weights, range_text = _resolve_opponent_range(opponent_label)
        if opponent_label == "Custom" and not opponent_range:
            raise ValueError("Build a custom range in the Ranges tab before calculating with Custom.")

        result = calculate_equity(
            hero_hand,
            board,
            simulations=simulations,
            opponent_range=opponent_range,
            opponent_weights=opponent_weights,
        )
        decision = evaluate_call_decision(result.equity, pot_size, call_amount)
        heatmap = get_or_compute_equity_heatmap(
            board,
            opponent_range=opponent_range,
            opponent_weights=opponent_weights,
            simulations=simulations,
        )
        heatmap_cache_hit = last_heatmap_cache_hit()
        heatmap_sims = heatmap_simulation_budget(simulations)
        heatmap_key = build_heatmap_cache_key(
            board,
            opponent_range,
            opponent_weights,
            heatmap_sims,
            heatmap_exact_max_matchups(board, 75_000),
        )
    except ValueError as error:
        st.session_state.latest_analysis = None
        st.error(str(error))
        return

    st.session_state.latest_analysis = {
        "hero_input": hero_input,
        "board_input": board_input,
        "opponent_label": opponent_label,
        "range_text": range_text,
        "opponent_range": opponent_range,
        "opponent_weights": opponent_weights,
        "result": result,
        "decision": decision,
        "pot_size": pot_size,
        "call_amount": call_amount,
        "simulations": simulations,
        "heatmap": heatmap,
        "heatmap_key": heatmap_key,
        "heatmap_simulations": heatmap_sims,
        "heatmap_cache_hit": heatmap_cache_hit,
        "calculated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def _resolve_opponent_range(option: str) -> tuple[list, list[float] | None, str]:
    """Return (combos, weights_or_None, range_text) for equity calculation."""
    if option.startswith("Saved: "):
        saved_name = option.removeprefix("Saved: ")
        for saved_range in load_saved_ranges():
            if saved_range["name"] == saved_name:
                weights = normalize_hand_weights(saved_range.get("weights") or {})
                if not weights:
                    return [], None, ""
                hands, combo_weights = expand_weighted_range(
                    {hand: weight / 100.0 for hand, weight in weights.items()}
                )
                return hands, combo_weights, saved_range["range_text"]
        return [], None, ""

    if option == "Custom":
        weights = _selected_range_weights()
        if not weights:
            return [], None, ""
        hands, combo_weights = expand_weighted_range(
            {hand: weight / 100.0 for hand, weight in weights.items()}
        )
        return hands, combo_weights, _format_range_notation(list(weights.keys()), weights)

    range_text = RANGE_PRESETS.get(option, "")
    return parse_opponent_range(range_text), None, range_text


def _opponent_range_text(option: str) -> str:
    if option.startswith("Saved: "):
        saved_name = option.removeprefix("Saved: ")
        for saved_range in load_saved_ranges():
            if saved_range["name"] == saved_name:
                return saved_range["range_text"]
        return ""

    if option == "Custom":
        weights = _selected_range_weights()
        return _format_range_notation(list(weights.keys()), weights)

    return RANGE_PRESETS[option]


def _opponent_range_options() -> list[str]:
    saved_options = [f"Saved: {saved_range['name']}" for saved_range in load_saved_ranges()]
    return [*RANGE_PRESETS.keys(), *saved_options]


def _save_latest_analysis() -> None:
    # Guard against Streamlit double-firing Save Analysis in the same rerun.
    if st.session_state.get("_hand_history_save_guard"):
        return
    st.session_state._hand_history_save_guard = True

    analysis = _get_latest_analysis()
    if not analysis:
        return

    result = analysis["result"]
    decision = analysis["decision"]
    opponent_label = analysis["opponent_label"]
    custom_weights: dict[str, int] = {}
    if opponent_label == "Custom":
        custom_weights = _selected_range_weights()
    elif opponent_label.startswith("Saved: "):
        saved_name = opponent_label.removeprefix("Saved: ")
        for saved_range in load_saved_ranges():
            if saved_range["name"] == saved_name:
                custom_weights = normalize_hand_weights(saved_range.get("weights") or {})
                break
        if not custom_weights:
            custom_weights = {hand: 100 for hand in _grid_hands_from_range_text(analysis["range_text"])}

    insert_hand_history_entry(
        {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "hero_hand": analysis["hero_input"],
            "board": analysis["board_input"],
            "opponent_range": _opponent_range_history_label(
                opponent_label, analysis["range_text"]
            ),
            "equity": _format_percent(result.equity),
            "win": _format_percent(result.win_rate),
            "tie": _format_percent(result.tie_rate),
            "loss": _format_percent(result.loss_rate),
            "call_ev": f"{decision.call_ev:,.2f}",
            "recommendation": decision.recommendation,
            "calculation_mode": _format_calculation_mode(result.mode),
            "opponent_label": opponent_label,
            "custom_hands": custom_weights,
            "pot_size": float(analysis.get("pot_size", st.session_state.calc_pot_size)),
            "call_amount": float(analysis.get("call_amount", st.session_state.calc_call_amount)),
            "simulations": int(analysis.get("simulations", st.session_state.calc_simulations)),
        }
    )
    st.session_state.analysis_save_flash = "Analysis saved to History."


def _load_hand_history_analysis(entry_id: int) -> None:
    entry = get_hand_history_entry(entry_id)
    if not entry:
        return

    hero_cards = [
        _normalize_card_key(token)
        for token in str(entry["hero_hand"]).split()
        if token
    ]
    hero_slots: list[str | None] = [None, None]
    for index, card in enumerate(hero_cards[:2]):
        hero_slots[index] = card
    st.session_state.hero_slot_cards = hero_slots
    _sync_hero_cards_from_slots()

    board_cards = [
        _normalize_card_key(token)
        for token in str(entry.get("board") or "").split()
        if token
    ]
    flop_slots: list[str | None] = [None, None, None]
    for index, card in enumerate(board_cards[:3]):
        flop_slots[index] = card
    st.session_state.flop_slot_cards = flop_slots
    _sync_flop_cards_from_slots()
    st.session_state.turn_slot_card = board_cards[3] if len(board_cards) > 3 else None
    _sync_turn_from_slot()
    st.session_state.river_slot_card = board_cards[4] if len(board_cards) > 4 else None
    _sync_river_from_slot()
    _enforce_board_street_order()

    opponent_label = str(entry.get("opponent_label") or "")
    custom_weights = normalize_hand_weights(
        entry.get("custom_hand_weights")
        or {hand: 100 for hand in (entry.get("custom_hands") or [])}
    )
    available_options = set(_opponent_range_options())

    if opponent_label == "Custom":
        _set_selected_range_weights(custom_weights)
        st.session_state.calc_opponent_range = "Custom"
    elif opponent_label.startswith("Saved: ") and opponent_label in available_options:
        st.session_state.calc_opponent_range = opponent_label
        if custom_weights:
            _set_selected_range_weights(custom_weights)
    elif opponent_label in RANGE_PRESETS:
        st.session_state.calc_opponent_range = opponent_label
    elif custom_weights:
        _set_selected_range_weights(custom_weights)
        st.session_state.calc_opponent_range = "Custom"
    else:
        st.session_state.calc_opponent_range = "Random"

    st.session_state.calc_pot_size = float(entry.get("pot_size", DEFAULT_POT_SIZE))
    st.session_state.calc_call_amount = float(entry.get("call_amount", DEFAULT_CALL_AMOUNT))
    st.session_state["calc_pot_size__input"] = float(st.session_state.calc_pot_size)
    st.session_state["calc_call_amount__input"] = float(st.session_state.calc_call_amount)
    simulations = int(entry.get("simulations", DEFAULT_MONTE_CARLO_TRIALS))
    st.session_state.calc_simulations = _normalize_monte_carlo_trials(simulations)

    st.session_state.active_hero_slot = None
    st.session_state.active_board_slot = _first_empty_board_slot()
    st.session_state.active_tab = TAB_ANALYZE
    st.session_state.hand_history_flash = "Analysis loaded — recalculating Results…"
    _snapshot_calculator_settings()

    # Rebuild full Results from persisted inputs so History reopen is complete.
    hero_input = " ".join(card for card in hero_cards[:2] if card)
    board_input = " ".join(board_cards)
    opponent_label = str(st.session_state.calc_opponent_range)
    pot_size = float(st.session_state.calc_pot_size)
    call_amount = float(st.session_state.calc_call_amount)
    simulations = int(st.session_state.calc_simulations)
    _calculate_and_store_analysis(
        hero_input, board_input, opponent_label, pot_size, call_amount, simulations
    )
    if _get_latest_analysis():
        st.session_state.scroll_to_results = True
        st.session_state.hand_history_flash = "Analysis loaded with Results restored."
    else:
        st.session_state.scroll_to_results = False
        st.session_state.hand_history_flash = (
            "Inputs restored from History. Press Calculate to rebuild Results."
        )


def _save_current_range(range_name: str) -> None:
    cleaned_name = range_name.strip()
    weights = _selected_range_weights()
    if not cleaned_name or not weights:
        return

    try:
        insert_saved_range(
            cleaned_name,
            weights,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
    except DuplicateRangeNameError:
        st.error(f'A saved range named "{cleaned_name}" already exists. Choose a different name.')
        return

    st.success("Range saved.")


def _load_saved_range(range_id: int) -> None:
    for saved_range in load_saved_ranges():
        if saved_range["id"] == range_id:
            _set_selected_range_weights(saved_range.get("weights") or {hand: 100 for hand in saved_range["hands"]})
            return


def _edit_saved_range(range_id: int) -> None:
    saved_range = get_saved_range_by_id(range_id)
    if not saved_range:
        return
    _set_selected_range_weights(saved_range.get("weights") or {hand: 100 for hand in saved_range["hands"]})
    st.session_state.editing_saved_range_id = saved_range["id"]
    st.session_state.editing_saved_range_name = saved_range["name"]
    st.session_state.range_save_name = saved_range["name"]
    st.session_state.active_tab = TAB_RANGES


def _cancel_editing_saved_range() -> None:
    st.session_state.editing_saved_range_id = None
    st.session_state.editing_saved_range_name = None


def _update_current_range(range_name: str) -> None:
    range_id = st.session_state.get("editing_saved_range_id")
    if range_id is None:
        return

    cleaned_name = range_name.strip()
    weights = _selected_range_weights()
    if not cleaned_name or not weights:
        return

    try:
        update_saved_range_by_id(int(range_id), cleaned_name, weights)
    except DuplicateRangeNameError:
        st.error(f'A saved range named "{cleaned_name}" already exists. Choose a different name.')
        return
    except ValueError as error:
        st.error(str(error))
        return

    st.session_state.editing_saved_range_id = None
    st.session_state.editing_saved_range_name = None
    st.session_state.saved_range_flash = "Range updated."
    st.success("Range updated.")


def _delete_saved_range(range_id: int) -> None:
    """Permanently delete one saved range from SQLite without changing the grid."""
    if st.session_state.get("editing_saved_range_id") == range_id:
        st.session_state.editing_saved_range_id = None
        st.session_state.editing_saved_range_name = None
    delete_saved_range_by_id(range_id)
    st.session_state.saved_range_flash = "Range deleted."


def _request_history_entry_delete(entry_id: int) -> None:
    """Open an inline confirmation before deleting a saved analysis."""
    st.session_state.pending_history_delete_id = int(entry_id)


def _cancel_history_entry_delete() -> None:
    st.session_state.pending_history_delete_id = None


def _confirm_history_entry_delete(entry_id: int) -> None:
    """Delete the confirmed analysis and clear the pending state."""
    deleted = delete_hand_history_entry_by_id(int(entry_id))
    st.session_state.pending_history_delete_id = None
    if deleted:
        st.session_state.hand_history_action_flash = "Saved analysis deleted."


def _initialize_state() -> None:
    initialize_hand_history_db()
    # Reset once per script run so Save Analysis cannot insert twice in one rerun.
    st.session_state._hand_history_save_guard = False
    if "active_tab" not in st.session_state:
        st.session_state.active_tab = TAB_HOME
    else:
        legacy = _LEGACY_TAB_MAP.get(st.session_state.active_tab)
        if legacy is not None:
            st.session_state.active_tab = legacy
        elif st.session_state.active_tab not in {*APP_TABS, TAB_TOOLS}:
            st.session_state.active_tab = TAB_HOME
    if "selected_range_hands" not in st.session_state:
        st.session_state.selected_range_hands = []
    if "selected_range_weights" not in st.session_state:
        st.session_state.selected_range_weights = {
            hand: 100 for hand in st.session_state.selected_range_hands
        }
    else:
        # Keep list/dict views synchronized across reruns.
        _set_range_weights(RANGE_NS_OPPONENT, st.session_state.selected_range_weights)
    if "hero_range_hands" not in st.session_state:
        st.session_state.hero_range_hands = []
    if "hero_range_weights" not in st.session_state:
        st.session_state.hero_range_weights = {
            hand: 100 for hand in st.session_state.hero_range_hands
        }
    else:
        _set_range_weights(RANGE_NS_HERO, st.session_state.hero_range_weights)
    if "weight_editor_hand" not in st.session_state:
        st.session_state.weight_editor_hand = None
    if "hero_weight_editor_hand" not in st.session_state:
        st.session_state.hero_weight_editor_hand = None
    if "weight_editor_ns" not in st.session_state:
        st.session_state.weight_editor_ns = RANGE_NS_OPPONENT
    if "hero_selection_mode" not in st.session_state:
        st.session_state.hero_selection_mode = HERO_MODE_SINGLE
    if "hero_selection_mode_radio" not in st.session_state:
        st.session_state.hero_selection_mode_radio = HERO_MODE_SINGLE
    if "editing_saved_range_id" not in st.session_state:
        st.session_state.editing_saved_range_id = None
    if "editing_saved_range_name" not in st.session_state:
        st.session_state.editing_saved_range_name = None
    if "selected_hero_cards" not in st.session_state:
        st.session_state.selected_hero_cards = []
    if "active_quick_example" not in st.session_state:
        st.session_state.active_quick_example = None
    if "hero_slot_cards" not in st.session_state:
        cards = list(st.session_state.selected_hero_cards)
        st.session_state.hero_slot_cards = [
            cards[0] if len(cards) > 0 else None,
            cards[1] if len(cards) > 1 else None,
        ]
    if "selected_flop_cards" not in st.session_state:
        st.session_state.selected_flop_cards = []
    if "flop_slot_cards" not in st.session_state:
        cards = list(st.session_state.selected_flop_cards)
        st.session_state.flop_slot_cards = [
            cards[index] if index < len(cards) else None for index in range(3)
        ]
    if "selected_turn_card" not in st.session_state:
        st.session_state.selected_turn_card = []
    if "turn_slot_card" not in st.session_state:
        cards = list(st.session_state.selected_turn_card)
        st.session_state.turn_slot_card = cards[0] if cards else None
    if "selected_river_card" not in st.session_state:
        st.session_state.selected_river_card = []
    if "river_slot_card" not in st.session_state:
        cards = list(st.session_state.selected_river_card)
        st.session_state.river_slot_card = cards[0] if cards else None
    if "active_board_slot" not in st.session_state:
        st.session_state.active_board_slot = None
    if "active_hero_slot" not in st.session_state:
        st.session_state.active_hero_slot = None
    if "latest_analysis" not in st.session_state:
        st.session_state.latest_analysis = None
    if "pending_board_dialog" not in st.session_state:
        st.session_state.pending_board_dialog = False
    if "pending_hero_dialog" not in st.session_state:
        st.session_state.pending_hero_dialog = False
    if "calc_opponent_range" not in st.session_state:
        st.session_state.calc_opponent_range = st.session_state.get("_calc_opponent_range", "Random")
    _ensure_pot_call_defaults()
    if "calc_simulations" not in st.session_state:
        st.session_state.calc_simulations = _normalize_monte_carlo_trials(
            st.session_state.get("_calc_simulations", DEFAULT_MONTE_CARLO_TRIALS)
        )
    else:
        st.session_state.calc_simulations = _normalize_monte_carlo_trials(
            st.session_state.calc_simulations
        )
    if "scroll_to_results" not in st.session_state:
        st.session_state.scroll_to_results = False

    _hero_slot_values()
    _flop_slot_values()
    _enforce_board_street_order()


def _get_latest_analysis() -> dict | None:
    analysis = st.session_state.get("latest_analysis")
    if not isinstance(analysis, dict):
        if analysis is not None:
            st.session_state.latest_analysis = None
        return None

    required_keys = ("result", "decision", "opponent_label", "opponent_range")
    if not all(key in analysis for key in required_keys):
        st.session_state.latest_analysis = None
        return None

    return analysis


def _inject_styles() -> None:
    st.markdown(
        f"""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Space+Grotesk:wght@500;600;700&display=swap');

        html, body, [class*="css"] {{
            font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        }}
        .block-container {{
            max-width: 1280px;
            padding-top: 1.1rem;
            padding-bottom: 3.5rem;
        }}
        .stApp {{
            background:
                radial-gradient(1100px 420px at 8% -12%, rgba(251, 113, 133, 0.08), transparent 55%),
                radial-gradient(900px 420px at 92% 0%, rgba(56, 189, 248, 0.05), transparent 50%),
                #0f172a;
            color: #e2e8f0;
        }}
        [data-testid="stHeader"] {{
            background: transparent;
            height: 0 !important;
            min-height: 0 !important;
        }}
        /* Minimize Streamlit chrome without affecting Cloud deployability. */
        [data-testid="stToolbar"],
        [data-testid="stDecoration"],
        [data-testid="stStatusWidget"],
        [data-testid="stAppDeployButton"],
        .stDeployButton,
        #MainMenu {{
            display: none !important;
            visibility: hidden !important;
        }}
        div.stButton > button {{ min-height: 2.2rem; }}

        .el-brand {{
            margin: 0 0 0.35rem 0;
            padding: 0;
            border: none;
            background: transparent;
            box-shadow: none;
        }}
        .el-brand-row {{
            display: flex;
            align-items: center;
            gap: 0.7rem;
            margin: 0 0 0.35rem 0;
        }}
        .el-logo-mark {{
            flex: 0 0 auto;
            display: block;
        }}
        .el-brand-name {{
            margin: 0;
            font-family: "Space Grotesk", Inter, ui-sans-serif, system-ui, sans-serif;
            font-size: 2.2rem;
            font-weight: 700;
            letter-spacing: -0.04em;
            color: #f8fafc;
            line-height: 1.05;
        }}
        .el-brand-name-compact {{
            font-size: 1.35rem;
            letter-spacing: -0.03em;
        }}
        .el-page-title {{
            margin: 0 0 0.65rem 0;
            font-family: "Space Grotesk", Inter, ui-sans-serif, system-ui, sans-serif;
            font-size: 1.28rem;
            font-weight: 700;
            letter-spacing: -0.02em;
            color: #f1f5f9;
        }}
        .el-nav-brand {{
            display: flex;
            align-items: center;
            gap: 0.5rem;
            min-height: 1.95rem;
            margin: 0.05rem 0 0 0;
        }}
        .el-nav-wordmark {{
            font-family: "Space Grotesk", Inter, ui-sans-serif, system-ui, sans-serif;
            font-size: 1.05rem;
            font-weight: 700;
            letter-spacing: -0.03em;
            line-height: 1;
        }}
        .el-nav-wordmark-equity {{
            color: #f8fafc;
        }}
        .el-nav-wordmark-lab {{
            color: #fb7185;
        }}
        .el-logo-mark {{
            flex: 0 0 auto;
            display: block;
            border-radius: 0.45rem;
        }}
        .el-nav-rule {{
            height: 1px;
            margin: 0.55rem 0 0.7rem 0;
            background: rgba(51, 65, 85, 0.75);
        }}
        [class*="st-key-nav-"] button {{
            min-height: 1.95rem !important;
            height: 1.95rem !important;
            padding: 0 0.55rem !important;
            border-radius: 0.55rem !important;
            font-size: 0.82rem !important;
            font-weight: 600 !important;
            letter-spacing: 0.01em !important;
            border: 1px solid transparent !important;
            background: transparent !important;
            color: #cbd5e1 !important;
            box-shadow: none !important;
        }}
        [class*="st-key-nav-"] button:hover {{
            color: #e2e8f0 !important;
            background: rgba(30, 41, 59, 0.55) !important;
            border-color: rgba(71, 85, 105, 0.55) !important;
        }}
        [class*="st-key-nav-"] button[kind="primary"],
        [class*="st-key-nav-"] button[data-testid="baseButton-primary"],
        [class*="st-key-nav-"] button[data-testid="stBaseButton-primary"] {{
            background: rgba(15, 23, 42, 0.85) !important;
            border: 1px solid rgba(251, 113, 133, 0.55) !important;
            color: #f8fafc !important;
            font-weight: 700 !important;
            box-shadow: 0 10px 22px rgba(127, 29, 29, 0.28), 0 0 18px rgba(251, 113, 133, 0.22) !important;
        }}
        [class*="st-key-nav-"] button[kind="primary"]:hover,
        [class*="st-key-nav-"] button[data-testid="baseButton-primary"]:hover,
        [class*="st-key-nav-"] button[data-testid="stBaseButton-primary"]:hover {{
            background: rgba(30, 41, 59, 0.95) !important;
            border-color: rgba(251, 113, 133, 0.75) !important;
            color: #ffffff !important;
        }}

        /* —— Home landing (clean rebuild) —— */
        [data-testid="stMain"]:has(.el-home-active) div.block-container,
        [data-testid="stMain"]:has(.el-home-page) div.block-container {{
            max-width: none !important;
            width: 100% !important;
            padding-left: 24px !important;
            padding-right: 24px !important;
        }}
        [data-testid="stMain"]:has(.el-home-active) [data-testid="stMainBlockContainer"],
        [data-testid="stMain"]:has(.el-home-page) [data-testid="stMainBlockContainer"] {{
            max-width: none !important;
            width: 100% !important;
            padding-left: 24px !important;
            padding-right: 24px !important;
        }}
        [data-testid="stMain"]:has(.el-home-active) div[data-testid="stVerticalBlock"],
        [data-testid="stMain"]:has(.el-home-page) div[data-testid="stVerticalBlock"],
        [data-testid="stMain"]:has(.el-home-active) div[data-testid="stHorizontalBlock"],
        [data-testid="stMain"]:has(.el-home-page) div[data-testid="stHorizontalBlock"] {{
            max-width: none !important;
            min-width: 0 !important;
        }}
        [data-testid="stMain"]:has(.el-home-active) div[data-testid="column"],
        [data-testid="stMain"]:has(.el-home-page) div[data-testid="column"],
        [data-testid="stMain"]:has(.el-home-active) div[data-testid="stColumn"],
        [data-testid="stMain"]:has(.el-home-page) div[data-testid="stColumn"] {{
            max-width: none !important;
            min-width: 0 !important;
        }}
        [data-testid="stMain"]:has(.el-home-active) div[data-testid="stMarkdownContainer"],
        [data-testid="stMain"]:has(.el-home-page) div[data-testid="stMarkdownContainer"],
        [data-testid="stMain"]:has(.el-home-active) div[data-testid="stHtmlContainer"],
        [data-testid="stMain"]:has(.el-home-page) div[data-testid="stHtmlContainer"],
        [data-testid="stMain"]:has(.el-home-active) div[data-testid="stHtml"],
        [data-testid="stMain"]:has(.el-home-page) div[data-testid="stHtml"] {{
            width: 100% !important;
            max-width: none !important;
            margin: 0 !important;
            padding: 0 !important;
        }}

        .el-home-container {{
            width: min(100% - 48px, 1320px);
            margin-inline: auto;
            box-sizing: border-box;
            position: relative;
            z-index: 1;
        }}

        /* Home navbar */
        [data-testid="stMain"]:has(.el-home-active) div[data-testid="stHorizontalBlock"]:has(.el-home-nav-brand) {{
            width: min(100% - 48px, 1320px) !important;
            max-width: 1320px !important;
            margin-inline: auto !important;
            display: grid !important;
            grid-template-columns: 1fr auto 1fr !important;
            align-items: center !important;
            gap: 1rem !important;
        }}
        [data-testid="stMain"]:has(.el-home-active) div[data-testid="stHorizontalBlock"]:has(.el-home-nav-brand) > div[data-testid="stColumn"]:nth-child(2),
        [data-testid="stMain"]:has(.el-home-active) div[data-testid="stHorizontalBlock"]:has(.el-home-nav-brand) > div[data-testid="column"]:nth-child(2) {{
            display: flex !important;
            justify-content: center !important;
            width: auto !important;
            flex: 0 0 auto !important;
        }}
        [data-testid="stMain"]:has(.el-home-active) div[data-testid="stHorizontalBlock"]:has(.el-home-nav-brand) > div[data-testid="stColumn"]:nth-child(3),
        [data-testid="stMain"]:has(.el-home-active) div[data-testid="stHorizontalBlock"]:has(.el-home-nav-brand) > div[data-testid="column"]:nth-child(3) {{
            display: flex !important;
            justify-content: flex-end !important;
        }}
        [data-testid="stMain"]:has(.el-home-active) div[data-testid="stHorizontalBlock"]:has(.el-home-nav-brand) > div[data-testid="stColumn"]:nth-child(2) div[data-testid="stHorizontalBlock"],
        [data-testid="stMain"]:has(.el-home-active) div[data-testid="stHorizontalBlock"]:has(.el-home-nav-brand) > div[data-testid="column"]:nth-child(2) div[data-testid="stHorizontalBlock"] {{
            display: flex !important;
            flex-wrap: nowrap !important;
            align-items: center !important;
            justify-content: center !important;
            gap: 0.35rem !important;
            width: max-content !important;
            max-width: none !important;
        }}
        [data-testid="stMain"]:has(.el-home-active) div[data-testid="stHorizontalBlock"]:has(.el-home-nav-brand) > div[data-testid="stColumn"]:nth-child(2) div[data-testid="stColumn"],
        [data-testid="stMain"]:has(.el-home-active) div[data-testid="stHorizontalBlock"]:has(.el-home-nav-brand) > div[data-testid="column"]:nth-child(2) div[data-testid="column"] {{
            width: auto !important;
            flex: 0 0 auto !important;
            min-width: max-content !important;
            max-width: none !important;
        }}
        [data-testid="stMain"]:has(.el-home-active) [class*="st-key-nav-"] {{
            width: auto !important;
            min-width: max-content !important;
        }}
        [data-testid="stMain"]:has(.el-home-active) [class*="st-key-nav-"] button {{
            white-space: nowrap !important;
            width: auto !important;
            min-width: max-content !important;
            padding-left: 0.85rem !important;
            padding-right: 0.85rem !important;
            opacity: 1 !important;
        }}
        .el-home-nav-rule {{
            width: min(100% - 48px, 1320px) !important;
            margin-inline: auto !important;
        }}
        .el-home-nav-brand {{
            gap: 0.62rem;
            min-height: 2.2rem;
        }}
        .el-home-nav-brand .el-nav-wordmark {{
            font-size: 1.28rem;
            letter-spacing: -0.035em;
        }}
        .el-home-nav-brand .el-logo-mark {{
            width: 33px;
            height: 33px;
        }}
        [data-testid="stMain"]:has(.el-home-active) [class*="st-key-nav-"] button[kind="secondary"],
        [data-testid="stMain"]:has(.el-home-active) [class*="st-key-nav-"] button[data-testid="baseButton-secondary"],
        [data-testid="stMain"]:has(.el-home-active) [class*="st-key-nav-"] button[data-testid="stBaseButton-secondary"] {{
            position: relative !important;
            transition: color 180ms ease, background 180ms ease, border-color 180ms ease !important;
        }}
        [data-testid="stMain"]:has(.el-home-active) [class*="st-key-nav-"] button[kind="secondary"]:hover,
        [data-testid="stMain"]:has(.el-home-active) [class*="st-key-nav-"] button[data-testid="baseButton-secondary"]:hover,
        [data-testid="stMain"]:has(.el-home-active) [class*="st-key-nav-"] button[data-testid="stBaseButton-secondary"]:hover {{
            color: #f8fafc !important;
            background: transparent !important;
            border-color: transparent !important;
            box-shadow: inset 0 -1px 0 rgba(148, 163, 184, 0.72) !important;
        }}
        [data-testid="stMain"]:has(.el-home-active) [class*="st-key-nav-"] button[kind="primary"],
        [data-testid="stMain"]:has(.el-home-active) [class*="st-key-nav-"] button[data-testid="baseButton-primary"],
        [data-testid="stMain"]:has(.el-home-active) [class*="st-key-nav-"] button[data-testid="stBaseButton-primary"] {{
            box-shadow:
                0 10px 22px rgba(127, 29, 29, 0.3),
                0 0 22px rgba(251, 113, 133, 0.34),
                inset 0 0 0 1px rgba(251, 113, 133, 0.18) !important;
        }}

        .el-home-page {{
            width: 100%;
            margin: 0;
            padding: 0;
            position: relative;
        }}
        .el-home-page::before {{
            content: "";
            position: absolute;
            inset: 0 auto auto 0;
            width: min(720px, 58vw);
            height: 520px;
            background: radial-gradient(ellipse at 30% 40%, rgba(56, 189, 248, 0.07), transparent 68%);
            pointer-events: none;
            z-index: 0;
        }}
        .el-home-page::after {{
            content: "";
            position: absolute;
            top: 0;
            right: 0;
            width: min(760px, 62vw);
            height: 560px;
            background: radial-gradient(ellipse at 70% 35%, rgba(167, 139, 250, 0.08), transparent 64%),
                        radial-gradient(ellipse at 80% 55%, rgba(251, 113, 133, 0.05), transparent 60%);
            pointer-events: none;
            z-index: 0;
        }}

        .el-home-hero {{
            display: grid;
            grid-template-columns: minmax(0, 1fr) minmax(520px, 1.05fr);
            align-items: center;
            gap: 48px;
            padding: 64px 0 48px;
            width: 100%;
        }}

        .el-home-hero-copy {{
            max-width: 720px;
            min-width: 0;
            position: relative;
            z-index: 3;
        }}

        .el-home-eyebrow {{
            margin: 0 0 1.1rem 0;
            color: #fb7185;
            font-size: 0.68rem;
            font-weight: 700;
            letter-spacing: 0.16em;
            text-transform: uppercase;
        }}

        .el-home-headline {{
            margin: 0 0 1.25rem 0;
            font-family: "Space Grotesk", Inter, ui-sans-serif, system-ui, sans-serif;
            font-size: clamp(50px, 4.8vw, 72px);
            font-weight: 700;
            letter-spacing: -0.045em;
            line-height: 1.02;
            color: #f8fafc;
            max-width: 100%;
        }}

        .el-home-headline-line {{
            display: block;
        }}
        @media (min-width: 901px) {{
            .el-home-headline-line {{
                white-space: nowrap;
            }}
        }}

        .el-home-gradient-text {{
            background: linear-gradient(95deg, #fb7185 0%, #f472b6 42%, #38bdf8 100%);
            -webkit-background-clip: text;
            background-clip: text;
            color: transparent;
        }}

        .el-home-supporting {{
            margin: 0;
            max-width: 620px;
            color: #94a3b8;
            font-size: 1.05rem;
            line-height: 1.55;
        }}

        .el-home-hero-art-wrap {{
            position: relative;
            min-height: 500px;
            width: 100%;
            display: flex;
            align-items: center;
            justify-content: flex-end;
            overflow: visible;
            padding-bottom: 1rem;
            padding-left: 0.75rem;
            z-index: 1;
        }}

        .el-home-art-glow {{
            position: absolute;
            border-radius: 50%;
            filter: blur(40px);
            pointer-events: none;
        }}
        .el-home-art-glow-a {{
            width: 16rem;
            height: 16rem;
            left: 8%;
            top: 14%;
            background: rgba(56, 189, 248, 0.28);
        }}
        .el-home-art-glow-b {{
            width: 17rem;
            height: 17rem;
            right: 2%;
            top: 6%;
            background: rgba(251, 113, 133, 0.18);
        }}
        .el-home-art-glow-c {{
            width: 14rem;
            height: 14rem;
            right: 18%;
            bottom: 10%;
            background: rgba(124, 58, 237, 0.26);
        }}
        .el-home-art-glow-d {{
            width: 11rem;
            height: 11rem;
            left: 36%;
            bottom: 16%;
            background: rgba(74, 222, 128, 0.14);
        }}

        .el-home-art-floor {{
            position: absolute;
            left: -4%;
            right: -12%;
            bottom: -4%;
            height: 52%;
            background-image:
                linear-gradient(rgba(56, 189, 248, 0.1) 1px, transparent 1px),
                linear-gradient(90deg, rgba(56, 189, 248, 0.1) 1px, transparent 1px);
            background-size: 30px 30px;
            transform: perspective(480px) rotateX(64deg);
            transform-origin: center bottom;
            mask-image: linear-gradient(to top, rgba(0,0,0,0.55), transparent 88%);
            -webkit-mask-image: linear-gradient(to top, rgba(0,0,0,0.55), transparent 88%);
            pointer-events: none;
        }}

        .el-home-hero-art {{
            position: relative;
            z-index: 2;
            width: 100%;
            max-width: 640px;
            height: auto;
            display: block;
            transform: translate(-0.35rem, 1.85rem);
            transform-origin: center center;
        }}

        /* CTA row aligned with hero grid columns (Streamlit wraps columns in stLayoutWrapper) */
        [data-testid="stMain"]:has(.el-home-page) div[data-testid="stHorizontalBlock"]:has(div[data-testid="stHorizontalBlock"] [class*="st-key-home-cta-analyze"]) {{
            width: min(100% - 48px, 1320px) !important;
            max-width: 1320px !important;
            margin: -1.5rem auto 1.15rem auto !important;
            padding: 0 !important;
            gap: 72px !important;
            display: grid !important;
            grid-template-columns: minmax(0, 1fr) minmax(520px, 1.05fr) !important;
            align-items: start !important;
        }}
        [data-testid="stMain"]:has(.el-home-page) div[data-testid="stHorizontalBlock"]:has(div[data-testid="stHorizontalBlock"] [class*="st-key-home-cta-analyze"]) > [data-testid="stLayoutWrapper"]:first-child,
        [data-testid="stMain"]:has(.el-home-page) div[data-testid="stHorizontalBlock"]:has(div[data-testid="stHorizontalBlock"] [class*="st-key-home-cta-analyze"]) > div[data-testid="stColumn"]:first-child {{
            max-width: 720px !important;
            min-width: 0 !important;
            width: auto !important;
        }}
        [data-testid="stMain"]:has(.el-home-page) div[data-testid="stHorizontalBlock"]:has([class*="st-key-home-cta-analyze"]):not(:has(div[data-testid="stHorizontalBlock"])) {{
            width: 100% !important;
            max-width: 720px !important;
            margin: 0 !important;
            padding: 0 !important;
            gap: 0.85rem !important;
            display: flex !important;
            flex-wrap: nowrap !important;
        }}
        [data-testid="stMain"]:has(.el-home-page) div[data-testid="stHorizontalBlock"]:has([class*="st-key-home-cta-analyze"]):not(:has(div[data-testid="stHorizontalBlock"])) > [data-testid="stLayoutWrapper"],
        [data-testid="stMain"]:has(.el-home-page) div[data-testid="stHorizontalBlock"]:has([class*="st-key-home-cta-analyze"]):not(:has(div[data-testid="stHorizontalBlock"])) > div[data-testid="stColumn"] {{
            flex: 1 1 auto !important;
            min-width: 0 !important;
            max-width: none !important;
            width: auto !important;
        }}
        [class*="st-key-home-cta-"] button {{
            min-height: 2.95rem !important;
            border-radius: 0.68rem !important;
            font-weight: 700 !important;
            font-size: 1rem !important;
            padding-left: 1.15rem !important;
            padding-right: 1.15rem !important;
            transition: transform 200ms ease, box-shadow 200ms ease, border-color 200ms ease, background 200ms ease, letter-spacing 200ms ease !important;
        }}
        [class*="st-key-home-cta-analyze"] button[kind="primary"],
        [class*="st-key-home-cta-analyze"] button[data-testid="baseButton-primary"],
        [class*="st-key-home-cta-analyze"] button[data-testid="stBaseButton-primary"] {{
            background: linear-gradient(105deg, #fb7185 0%, #f43f5e 52%, #e11d48 100%) !important;
            border: 1px solid rgba(253, 164, 175, 0.45) !important;
            color: #ffffff !important;
            box-shadow: 0 0 0 1px rgba(251, 113, 133, 0.1), 0 12px 28px rgba(244, 63, 94, 0.36) !important;
        }}
        [class*="st-key-home-cta-analyze"] button[kind="primary"]:hover,
        [class*="st-key-home-cta-analyze"] button[data-testid="baseButton-primary"]:hover,
        [class*="st-key-home-cta-analyze"] button[data-testid="stBaseButton-primary"]:hover {{
            transform: translateY(-1px) !important;
            letter-spacing: 0.02em !important;
            box-shadow: 0 0 0 1px rgba(251, 113, 133, 0.14), 0 14px 30px rgba(244, 63, 94, 0.4) !important;
        }}
        [class*="st-key-home-cta-analyze"] button[kind="primary"] p,
        [class*="st-key-home-cta-analyze"] button[data-testid="baseButton-primary"] p,
        [class*="st-key-home-cta-analyze"] button[data-testid="stBaseButton-primary"] p,
        [class*="st-key-home-cta-analyze"] button[kind="primary"] span,
        [class*="st-key-home-cta-analyze"] button[data-testid="baseButton-primary"] span,
        [class*="st-key-home-cta-analyze"] button[data-testid="stBaseButton-primary"] span {{
            display: inline-block !important;
            transition: transform 200ms ease !important;
        }}
        [class*="st-key-home-cta-analyze"] button[kind="primary"]:hover p,
        [class*="st-key-home-cta-analyze"] button[data-testid="baseButton-primary"]:hover p,
        [class*="st-key-home-cta-analyze"] button[data-testid="stBaseButton-primary"]:hover p,
        [class*="st-key-home-cta-analyze"] button[kind="primary"]:hover span,
        [class*="st-key-home-cta-analyze"] button[data-testid="baseButton-primary"]:hover span,
        [class*="st-key-home-cta-analyze"] button[data-testid="stBaseButton-primary"]:hover span {{
            transform: translateX(3px) !important;
        }}
        [class*="st-key-home-cta-ranges"] button {{
            background: rgba(15, 23, 42, 0.35) !important;
            border: 1px solid rgba(148, 163, 184, 0.38) !important;
            color: #f8fafc !important;
            box-shadow: none !important;
        }}
        [class*="st-key-home-cta-ranges"] button:hover {{
            border-color: rgba(226, 232, 240, 0.72) !important;
            background: rgba(30, 41, 59, 0.55) !important;
            transform: translateY(-1px) !important;
        }}

        .el-home-preview {{
            margin: 2rem 0 0 0;
            width: 100%;
        }}
        .el-home-section-label {{
            margin: 0 0 1rem 0;
            color: #64748b;
            font-size: 0.68rem;
            font-weight: 700;
            letter-spacing: 0.12em;
            text-transform: uppercase;
        }}
        .el-home-card-grid {{
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 16px;
            width: 100%;
        }}
        .el-home-card {{
            display: flex;
            align-items: flex-start;
            gap: 1.1rem;
            padding: 1.35rem 1.35rem;
            border-radius: 0.88rem;
            border: 1px solid rgba(71, 85, 105, 0.72);
            background: rgba(15, 23, 42, 0.58);
            box-shadow: 0 8px 22px rgba(2, 6, 23, 0.16);
            transition: transform 200ms ease, border-color 200ms ease, box-shadow 200ms ease;
            min-height: 6.15rem;
            cursor: default;
        }}
        .el-home-card:hover {{
            transform: translateY(-3px);
            border-color: rgba(148, 163, 184, 0.62);
        }}
        .el-home-card:hover .el-home-card-title {{
            transform: translateX(2px);
        }}
        .el-home-card:hover .el-home-card-icon {{
            transform: scale(1.04) rotate(3deg);
        }}
        .el-home-card-icon {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            flex: 0 0 auto;
            width: 2.85rem;
            height: 2.85rem;
            border-radius: 0.68rem;
            border: 1px solid transparent;
            transition: transform 200ms ease;
        }}
        .el-home-card-icon-art {{
            width: 26px;
            height: 26px;
            display: block;
        }}
        .el-home-card-icon-ranges {{
            background: rgba(139, 92, 246, 0.18);
            border-color: rgba(167, 139, 250, 0.3);
        }}
        .el-home-card-icon-simulation {{
            background: rgba(14, 165, 233, 0.16);
            border-color: rgba(56, 189, 248, 0.3);
        }}
        .el-home-card-icon-decision {{
            background: rgba(34, 197, 94, 0.14);
            border-color: rgba(74, 222, 128, 0.3);
        }}
        .el-home-card-icon-heatmap {{
            background: rgba(249, 115, 22, 0.14);
            border-color: rgba(251, 146, 60, 0.3);
        }}
        .el-home-card:has(.el-home-card-icon-ranges):hover {{
            box-shadow: 0 12px 28px rgba(2, 6, 23, 0.22), 0 0 24px rgba(139, 92, 246, 0.16);
        }}
        .el-home-card:has(.el-home-card-icon-simulation):hover {{
            box-shadow: 0 12px 28px rgba(2, 6, 23, 0.22), 0 0 24px rgba(14, 165, 233, 0.16);
        }}
        .el-home-card:has(.el-home-card-icon-decision):hover {{
            box-shadow: 0 12px 28px rgba(2, 6, 23, 0.22), 0 0 24px rgba(34, 197, 94, 0.14);
        }}
        .el-home-card:has(.el-home-card-icon-heatmap):hover {{
            box-shadow: 0 12px 28px rgba(2, 6, 23, 0.22), 0 0 24px rgba(249, 115, 22, 0.14);
        }}
        .el-home-card-copy {{
            min-width: 0;
            flex: 1 1 auto;
        }}
        .el-home-card-title {{
            margin: 0 0 0.28rem 0;
            font-family: "Space Grotesk", Inter, ui-sans-serif, system-ui, sans-serif;
            color: #f8fafc;
            font-size: 1.02rem;
            font-weight: 700;
            letter-spacing: -0.015em;
            line-height: 1.25;
            transition: transform 200ms ease;
        }}
        .el-home-card-body {{
            margin: 0;
            color: #94a3b8;
            font-size: 0.88rem;
            line-height: 1.45;
        }}

        .el-home-why {{
            margin: 2.1rem 0 0 0;
            width: 100%;
        }}
        .el-home-why-list {{
            list-style: none;
            margin: 0;
            padding: 0;
            display: flex;
            flex-wrap: wrap;
            gap: 0.55rem 0.7rem;
        }}
        .el-home-why-item {{
            margin: 0;
            padding: 0.42rem 0.72rem;
            border-radius: 999px;
            border: 1px solid rgba(71, 85, 105, 0.45);
            background: rgba(15, 23, 42, 0.28);
            color: #94a3b8;
            font-size: 0.82rem;
            font-weight: 550;
            line-height: 1.3;
            letter-spacing: 0.01em;
        }}

        .el-home-credibility {{
            margin: 2.35rem 0 1.5rem 0;
            padding-top: 1.35rem;
            border-top: 1px solid rgba(51, 65, 105, 0.65);
            width: 100%;
        }}
        .el-home-cred-list {{
            list-style: none;
            margin: 0.15rem 0 0 0;
            padding: 0;
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 0.85rem 1.25rem;
            width: 100%;
        }}
        .el-home-cred-item {{
            display: flex;
            align-items: center;
            gap: 0.7rem;
            color: #e2e8f0;
            font-size: 0.9rem;
            font-weight: 550;
            line-height: 1.35;
            padding: 0.7rem 0.8rem;
            border-radius: 0.7rem;
            border: 1px solid rgba(71, 85, 105, 0.42);
            background: rgba(15, 23, 42, 0.42);
        }}
        .el-home-cred-icon {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            flex: 0 0 auto;
            width: 1.95rem;
            height: 1.95rem;
            border-radius: 0.48rem;
            border: 1px solid transparent;
        }}
        .el-home-cred-icon-engine {{
            background: rgba(251, 113, 133, 0.12);
            border-color: rgba(251, 113, 133, 0.28);
        }}
        .el-home-cred-icon-storage {{
            background: rgba(167, 139, 250, 0.12);
            border-color: rgba(167, 139, 250, 0.28);
        }}
        .el-home-cred-icon-tests {{
            background: rgba(56, 189, 248, 0.12);
            border-color: rgba(56, 189, 248, 0.28);
        }}
        .el-home-cred-icon-sampling {{
            background: rgba(74, 222, 128, 0.12);
            border-color: rgba(74, 222, 128, 0.28);
        }}

        @media (max-width: 900px) {{
            .el-home-hero {{
                grid-template-columns: 1fr;
                gap: 2.5rem;
                padding: 2.5rem 0 2rem;
            }}
            .el-home-hero-art-wrap {{
                min-height: 380px;
                justify-content: center;
                padding-left: 0;
            }}
            .el-home-hero-art {{
                max-width: min(640px, 100%);
                transform: translate(0, 0.6rem);
            }}
            .el-home-headline-line {{
                white-space: normal;
            }}
            [data-testid="stMain"]:has(.el-home-page) div[data-testid="stHorizontalBlock"]:has(div[data-testid="stHorizontalBlock"] [class*="st-key-home-cta-analyze"]) {{
                grid-template-columns: 1fr !important;
                gap: 0 !important;
                margin-top: 0 !important;
            }}
            [data-testid="stMain"]:has(.el-home-page) div[data-testid="stHorizontalBlock"]:has([class*="st-key-home-cta-analyze"]):not(:has(div[data-testid="stHorizontalBlock"])) {{
                max-width: none !important;
                flex-wrap: wrap !important;
            }}
            .el-home-card-grid,
            .el-home-cred-list {{
                grid-template-columns: 1fr;
            }}
            .el-home-why-list {{
                flex-direction: column;
                align-items: flex-start;
            }}
            [data-testid="stMain"]:has(.el-home-active) div[data-testid="stHorizontalBlock"]:has(.el-home-nav-brand) {{
                grid-template-columns: 1fr !important;
            }}
        }}
        .el-dev-tools-label {{
            margin: 1.35rem 0 0.25rem 0;
            color: #64748b;
            font-size: 0.72rem;
            font-weight: 700;
            letter-spacing: 0.08em;
            text-transform: uppercase;
        }}

        .section-gap {{ height: 0.7rem; }}
        .section-gap-hand-board {{ height: 1.05rem; }}
        .section-gap-calc {{ height: 0.85rem; }}
        .el-calc-block-gap {{ height: 0.78rem; }}
        .el-calc-block-gap-sm {{ height: 0.48rem; }}
        .el-calc-block-gap-xs {{ height: 0.28rem; }}
        .el-calc-preset-gap {{ height: 0.5rem; }}
        .el-calc-section-sub {{
            margin: 0.28rem 0 0 0 !important;
            color: #94a3b8 !important;
            font-size: 0.86rem !important;
            font-weight: 500 !important;
            line-height: 1.4 !important;
        }}
        .el-calc-field-label {{
            display: flex;
            align-items: center;
            gap: 0.35rem;
            margin: 0 0 0.32rem 0;
            color: #94a3b8;
            font-size: 0.7rem;
            font-weight: 700;
            letter-spacing: 0.08em;
            text-transform: uppercase;
        }}
        .el-calc-field-label img {{
            flex: 0 0 auto;
            opacity: 0.92;
        }}
        .el-calc-tip {{
            display: flex;
            align-items: flex-start;
            gap: 0.55rem;
            margin: 0.55rem 0 0 0;
            padding: 0.55rem 0.75rem;
            border-radius: 0.7rem;
            border: 1px solid rgba(56, 189, 248, 0.22);
            background:
                radial-gradient(120% 140% at 0% 0%, rgba(56, 189, 248, 0.1), transparent 55%),
                rgba(15, 23, 42, 0.72);
            box-shadow: 0 0 0 1px rgba(56, 189, 248, 0.04), 0 8px 18px rgba(2, 6, 23, 0.2);
        }}
        .el-calc-tip-icon {{
            flex: 0 0 auto;
            margin-top: 0.12rem;
        }}
        .el-calc-tip-kicker {{
            color: #7dd3fc;
            font-size: 0.64rem;
            font-weight: 750;
            letter-spacing: 0.1em;
            text-transform: uppercase;
            margin-bottom: 0.12rem;
        }}
        .el-calc-tip-body {{
            color: #cbd5e1;
            font-size: 0.84rem;
            line-height: 1.4;
        }}
        .el-calc-validation {{
            display: flex;
            align-items: center;
            gap: 0.42rem;
            width: 100%;
            box-sizing: border-box;
            margin: 0.45rem 0 0 0;
            padding: 0.42rem 0.7rem;
            border-radius: 0.65rem;
            font-size: 0.84rem;
            font-weight: 600;
            line-height: 1.3;
        }}
        .el-calc-validation-icon {{
            flex: 0 0 auto;
            opacity: 0.9;
        }}
        .el-calc-validation-msg {{
            min-width: 0;
        }}
        .el-calc-validation-warn {{
            color: #fecdd3;
            border: 1px solid rgba(251, 113, 133, 0.28);
            background: rgba(251, 113, 133, 0.06);
        }}
        .el-calc-validation-info {{
            color: #bae6fd;
            border: 1px solid rgba(56, 189, 248, 0.24);
            background: rgba(56, 189, 248, 0.06);
        }}
        .el-sim-info {{
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 0.55rem;
            padding: 0;
            background: transparent;
            border: none;
        }}
        .el-sim-stat {{
            display: flex;
            flex-direction: column;
            gap: 0.32rem;
            min-width: 0;
            padding: 0.78rem 0.8rem;
            border-radius: 0.72rem;
            border: 1px solid rgba(148, 163, 184, 0.16);
            background: rgba(30, 41, 59, 0.38);
            box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.03);
        }}
        .el-sim-info-label-row {{
            display: flex;
            align-items: center;
            gap: 0.38rem;
            min-height: 1rem;
        }}
        .el-sim-info-label-row img {{
            flex: 0 0 auto;
            width: 15px;
            height: 15px;
            opacity: 0.95;
        }}
        .el-sim-info-label {{
            color: #94a3b8;
            font-size: 0.64rem;
            font-weight: 700;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            line-height: 1;
        }}
        .el-sim-info-value {{
            color: #f8fafc;
            font-size: 1rem;
            font-weight: 750;
            letter-spacing: -0.015em;
            line-height: 1.2;
            animation: elSimValueFade 0.18s ease-out;
        }}
        .el-sim-acc-excellent {{
            color: #86efac !important;
        }}
        .el-sim-acc-high {{
            color: #5eead4 !important;
        }}
        .el-sim-acc-good {{
            color: #7dd3fc !important;
        }}
        .el-sim-acc-moderate {{
            color: #fcd34d !important;
        }}
        @keyframes elSimValueFade {{
            from {{ opacity: 0.4; }}
            to {{ opacity: 1; }}
        }}
        @media (max-width: 720px) {{
            .el-sim-info {{
                grid-template-columns: 1fr;
            }}
        }}
        div[data-testid="stVerticalBlockBorderWrapper"]:has(.el-calc-tip),
        div[data-testid="stVerticalBlockBorderWrapper"]:has(.el-sim-info) {{
            border-radius: 0.88rem !important;
            border-color: rgba(148, 163, 184, 0.18) !important;
            background: rgba(15, 23, 42, 0.55) !important;
            box-shadow: 0 10px 24px rgba(2, 6, 23, 0.2) !important;
            width: 100% !important;
            box-sizing: border-box !important;
        }}
        div[data-testid="stVerticalBlockBorderWrapper"]:has(.el-calc-tip) > div,
        div[data-testid="stVerticalBlockBorderWrapper"]:has(.el-sim-info) > div {{
            padding-top: 0.85rem !important;
            padding-bottom: 0.85rem !important;
        }}
        div[data-testid="stVerticalBlockBorderWrapper"]:has(.el-calc-tip) [data-testid="stHeaderActionElements"],
        div[data-testid="stVerticalBlockBorderWrapper"]:has(.el-sim-info) [data-testid="stHeaderActionElements"],
        div[data-testid="stVerticalBlockBorderWrapper"]:has(.el-calc-tip) h3 a,
        div[data-testid="stVerticalBlockBorderWrapper"]:has(.el-sim-info) h3 a {{
            display: none !important;
        }}
        .st-key-calculate-equity-btn,
        div[data-testid="stElementContainer"]:has(.el-calc-validation),
        div[data-testid="stMarkdownContainer"]:has(.el-calc-validation) {{
            width: 100% !important;
            box-sizing: border-box !important;
        }}
        [class*="st-key-mc-preset-"] button {{
            min-height: 2.15rem !important;
            border-radius: 999px !important;
            font-weight: 700 !important;
            font-size: 0.9rem !important;
            letter-spacing: -0.01em !important;
            transition: transform 170ms ease, box-shadow 170ms ease, border-color 170ms ease,
                background 170ms ease, color 170ms ease, filter 170ms ease !important;
        }}
        [class*="st-key-mc-preset-"] button[kind="secondary"],
        [class*="st-key-mc-preset-"] button[data-testid="baseButton-secondary"] {{
            background: rgba(2, 6, 23, 0.72) !important;
            border: 1px solid rgba(100, 116, 139, 0.3) !important;
            color: #94a3b8 !important;
            box-shadow: none !important;
            transform: scale(1) !important;
        }}
        [class*="st-key-mc-preset-"] button[kind="secondary"]:hover,
        [class*="st-key-mc-preset-"] button[data-testid="baseButton-secondary"]:hover {{
            transform: scale(1.02) !important;
            border-color: rgba(148, 163, 184, 0.48) !important;
            color: #e2e8f0 !important;
        }}
        [class*="st-key-mc-preset-"] button[kind="primary"],
        [class*="st-key-mc-preset-"] button[data-testid="baseButton-primary"],
        [class*="st-key-mc-preset-"] button[data-testid="stBaseButton-primary"] {{
            background: linear-gradient(105deg, #fb7185 0%, #f43f5e 52%, #e11d48 100%) !important;
            border: 1px solid rgba(253, 164, 175, 0.45) !important;
            color: #ffffff !important;
            font-weight: 800 !important;
            transform: scale(1.02) !important;
            box-shadow: 0 0 0 1px rgba(251, 113, 133, 0.12), 0 0 16px rgba(244, 63, 94, 0.32) !important;
        }}
        [class*="st-key-mc-preset-"] button[kind="primary"] p,
        [class*="st-key-mc-preset-"] button[data-testid="baseButton-primary"] p,
        [class*="st-key-mc-preset-"] button[data-testid="stBaseButton-primary"] p,
        [class*="st-key-mc-preset-"] button[kind="primary"] span,
        [class*="st-key-mc-preset-"] button[data-testid="baseButton-primary"] span,
        [class*="st-key-mc-preset-"] button[data-testid="stBaseButton-primary"] span {{
            color: #ffffff !important;
            font-weight: 800 !important;
        }}
        [class*="st-key-mc-preset-"] button[kind="primary"]:hover,
        [class*="st-key-mc-preset-"] button[data-testid="baseButton-primary"]:hover,
        [class*="st-key-mc-preset-"] button[data-testid="stBaseButton-primary"]:hover {{
            transform: scale(1.03) !important;
            filter: brightness(1.03);
            box-shadow: 0 0 0 1px rgba(251, 113, 133, 0.16), 0 0 18px rgba(244, 63, 94, 0.38) !important;
        }}
        [class*="st-key-calc_pot_size-minus"] button,
        [class*="st-key-calc_pot_size-plus"] button,
        [class*="st-key-calc_call_amount-minus"] button,
        [class*="st-key-calc_call_amount-plus"] button {{
            min-height: 1.9rem !important;
            height: 1.9rem !important;
            min-width: 1.9rem !important;
            max-width: 1.9rem !important;
            width: 1.9rem !important;
            margin: 0.22rem auto 0 auto !important;
            padding: 0 !important;
            border-radius: 999px !important;
            font-size: 1rem !important;
            font-weight: 700 !important;
            line-height: 1 !important;
            color: #cbd5e1 !important;
            background: rgba(15, 23, 42, 0.92) !important;
            border: 1px solid rgba(71, 85, 105, 0.55) !important;
            box-shadow: inset 0 1px 0 rgba(255,255,255,0.03) !important;
            transition: transform 160ms ease, box-shadow 160ms ease, border-color 160ms ease,
                color 160ms ease, filter 160ms ease !important;
        }}
        [class*="st-key-calc_pot_size-minus"] button:hover,
        [class*="st-key-calc_pot_size-plus"] button:hover,
        [class*="st-key-calc_call_amount-minus"] button:hover,
        [class*="st-key-calc_call_amount-plus"] button:hover {{
            border-color: rgba(148, 163, 184, 0.55) !important;
            color: #f8fafc !important;
            filter: brightness(1.08);
            box-shadow: 0 0 0 1px rgba(148, 163, 184, 0.1), 0 0 10px rgba(148, 163, 184, 0.14) !important;
        }}
        [class*="st-key-calc_pot_size-minus"] button:active,
        [class*="st-key-calc_pot_size-plus"] button:active,
        [class*="st-key-calc_call_amount-minus"] button:active,
        [class*="st-key-calc_call_amount-plus"] button:active {{
            transform: scale(0.96) !important;
        }}
        div[data-testid="stNumberInput"]:has(input[aria-label="Pot Size"]) button,
        div[data-testid="stNumberInput"]:has(input[aria-label="Amount to Call"]) button {{
            display: none !important;
        }}
        div[data-testid="stNumberInput"]:has(input[aria-label="Pot Size"]),
        div[data-testid="stNumberInput"]:has(input[aria-label="Amount to Call"]) {{
            margin-bottom: 0 !important;
            max-width: 11.5rem !important;
            margin-left: auto !important;
            margin-right: auto !important;
        }}
        div[data-testid="stNumberInput"]:has(input[aria-label="Pot Size"]) input,
        div[data-testid="stNumberInput"]:has(input[aria-label="Amount to Call"]) input {{
            text-align: center !important;
            font-weight: 700 !important;
            font-size: 1.05rem !important;
            min-height: 2.35rem !important;
            border-radius: 0.7rem !important;
            border: 1px solid rgba(71, 85, 105, 0.52) !important;
            background: rgba(2, 6, 23, 0.55) !important;
            color: #f8fafc !important;
            transition: border-color 160ms ease, box-shadow 160ms ease !important;
        }}
        div[data-testid="stNumberInput"]:has(input[aria-label="Pot Size"]) input:hover,
        div[data-testid="stNumberInput"]:has(input[aria-label="Amount to Call"]) input:hover {{
            border-color: rgba(148, 163, 184, 0.42) !important;
        }}
        div[data-testid="stNumberInput"]:has(input[aria-label="Pot Size"]) input:focus,
        div[data-testid="stNumberInput"]:has(input[aria-label="Amount to Call"]) input:focus {{
            border-color: rgba(56, 189, 248, 0.48) !important;
            box-shadow: 0 0 0 1px rgba(56, 189, 248, 0.14) !important;
        }}
        .st-key-calc_opponent_range [data-baseweb="select"] > div {{
            background: rgba(2, 6, 23, 0.68) !important;
            border: 1px solid rgba(71, 85, 105, 0.55) !important;
            border-radius: 0.72rem !important;
            min-height: 2.7rem !important;
            padding-left: 0.35rem !important;
            padding-right: 0.35rem !important;
            box-shadow: none !important;
            transition: border-color 160ms ease, box-shadow 160ms ease !important;
        }}
        .st-key-calc_opponent_range [data-baseweb="select"] > div:hover {{
            border-color: rgba(148, 163, 184, 0.45) !important;
            box-shadow: 0 0 0 1px rgba(148, 163, 184, 0.08), 0 0 12px rgba(148, 163, 184, 0.1) !important;
        }}
        .st-key-calc_opponent_range [data-baseweb="select"] > div[aria-expanded="true"],
        .st-key-calc_opponent_range [data-baseweb="select"] > div:focus-within {{
            border-color: rgba(56, 189, 248, 0.52) !important;
            box-shadow: 0 0 0 1px rgba(56, 189, 248, 0.18), 0 0 14px rgba(56, 189, 248, 0.12) !important;
        }}
        .st-key-calc_opponent_range [data-baseweb="select"] [data-testid="stMarkdownContainer"],
        .st-key-calc_opponent_range [data-baseweb="select"] div {{
            color: #f1f5f9 !important;
        }}
        .st-key-calc_opponent_range [data-baseweb="select"] svg {{
            color: #cbd5e1 !important;
            opacity: 0.95;
        }}
        @media (prefers-reduced-motion: reduce) {{
            .el-sim-info-value,
            [class*="st-key-mc-preset-"] button,
            [class*="st-key-calc_pot_size-minus"] button,
            [class*="st-key-calc_pot_size-plus"] button,
            [class*="st-key-calc_call_amount-minus"] button,
            [class*="st-key-calc_call_amount-plus"] button,
            .st-key-calculate-equity-btn button {{
                animation: none !important;
                transition: none !important;
            }}
            [class*="st-key-mc-preset-"] button:hover,
            [class*="st-key-mc-preset-"] button[kind="secondary"]:hover,
            [class*="st-key-mc-preset-"] button[kind="primary"],
            [class*="st-key-mc-preset-"] button[kind="primary"]:hover {{
                transform: none !important;
            }}
        }}
        .el-analyze-title {{
            font-size: 1.85rem !important;
            margin: 0.1rem 0 1.05rem 0 !important;
        }}
        .el-analyze-divider {{
            height: 1px;
            margin: 1.05rem 0 1rem 0;
            background: rgba(51, 65, 85, 0.75);
        }}
        .el-analyze-layout-anchor {{
            display: none;
        }}
        /* Analyze two-column shell: wide main + summary sidebar. */
        div[data-testid="stHorizontalBlock"]:has(.calc-summary-panel):has(.st-key-hero-slot-0),
        div[data-testid="stHorizontalBlock"]:has(.calc-summary-panel):has(.st-key-clear-hero-cards) {{
            display: grid !important;
            grid-template-columns: minmax(0, 1fr) minmax(280px, 340px) !important;
            gap: 1.5rem !important;
            align-items: start !important;
            width: 100% !important;
            max-width: none !important;
            flex-wrap: nowrap !important;
        }}
        div[data-testid="stHorizontalBlock"]:has(.calc-summary-panel):has(.st-key-hero-slot-0) > div[data-testid="stColumn"],
        div[data-testid="stHorizontalBlock"]:has(.calc-summary-panel):has(.st-key-clear-hero-cards) > div[data-testid="stColumn"] {{
            width: auto !important;
            min-width: 0 !important;
            max-width: none !important;
            flex: none !important;
        }}
        /* Panels fill the left column — never shrink-wrap to card content. */
        div[data-testid="stHorizontalBlock"]:has(.calc-summary-panel):has(.st-key-hero-slot-0) > div[data-testid="stColumn"]:first-child [data-testid="stVerticalBlockBorderWrapper"],
        div[data-testid="stHorizontalBlock"]:has(.calc-summary-panel):has(.st-key-clear-hero-cards) > div[data-testid="stColumn"]:first-child [data-testid="stVerticalBlockBorderWrapper"] {{
            width: 100% !important;
            max-width: none !important;
        }}
        @media (max-width: 900px) {{
            div[data-testid="stHorizontalBlock"]:has(.calc-summary-panel):has(.st-key-hero-slot-0),
            div[data-testid="stHorizontalBlock"]:has(.calc-summary-panel):has(.st-key-clear-hero-cards) {{
                grid-template-columns: minmax(0, 1fr) !important;
            }}
            .calc-summary-panel {{
                position: static;
                min-height: 0;
            }}
        }}
        .el-qs-header {{
            margin: 0 0 0.85rem 0;
        }}
        .el-qs-kicker {{
            display: inline-flex;
            align-items: center;
            gap: 0.4rem;
            margin: 0 0 0.35rem 0;
            color: #fb7185;
            font-size: 0.72rem;
            font-weight: 700;
            letter-spacing: 0.1em;
            text-transform: uppercase;
        }}
        .el-qs-hint {{
            margin: 0 !important;
            color: #94a3b8;
            font-size: 0.9rem;
            line-height: 1.45;
        }}
        .el-qs-card {{
            display: flex;
            align-items: center;
            gap: 0.7rem;
            min-height: 5.15rem;
            height: 5.15rem;
            padding: 0.35rem 0.85rem 0.35rem 0.45rem;
            border-radius: 0.85rem;
            border: 1px solid rgba(71, 85, 105, 0.8);
            background: rgba(15, 23, 42, 0.72);
            box-shadow: 0 8px 20px rgba(2, 6, 23, 0.22);
            pointer-events: none;
            box-sizing: border-box;
            transition:
                transform 0.15s ease,
                border-color 0.15s ease,
                background 0.15s ease,
                box-shadow 0.15s ease;
        }}
        .el-qs-card-active {{
            border-color: rgba(251, 113, 133, 0.7);
            box-shadow:
                0 0 0 1px rgba(251, 113, 133, 0.28),
                0 0 22px rgba(251, 113, 133, 0.12),
                0 8px 20px rgba(2, 6, 23, 0.22);
            background: rgba(30, 41, 59, 0.55);
        }}
        .el-qs-icon {{
            flex: 0 0 4.35rem;
            display: flex;
            align-items: center;
            justify-content: center;
            width: 4.35rem;
            height: 4.35rem;
            border-radius: 0.7rem;
            border: 1px solid rgba(71, 85, 105, 0.55);
            box-sizing: border-box;
            transition: border-color 0.15s ease, box-shadow 0.15s ease, background 0.15s ease;
        }}
        .el-qs-icon-art {{
            display: block;
            width: 3.85rem;
            height: 3.85rem;
        }}
        .el-qs-icon-coral {{
            background: rgba(251, 113, 133, 0.1);
            border-color: rgba(251, 113, 133, 0.42);
            box-shadow: 0 0 0 1px rgba(251, 113, 133, 0.1), 0 0 18px rgba(251, 113, 133, 0.28);
        }}
        .el-qs-icon-cyan {{
            background: rgba(56, 189, 248, 0.1);
            border-color: rgba(56, 189, 248, 0.42);
            box-shadow: 0 0 0 1px rgba(56, 189, 248, 0.1), 0 0 18px rgba(56, 189, 248, 0.28);
        }}
        .el-qs-icon-green {{
            background: rgba(52, 211, 153, 0.1);
            border-color: rgba(52, 211, 153, 0.42);
            box-shadow: 0 0 0 1px rgba(52, 211, 153, 0.1), 0 0 18px rgba(52, 211, 153, 0.26);
        }}
        .el-qs-bolt {{
            display: block;
            width: 14px;
            height: 14px;
        }}
        .el-qs-copy {{
            flex: 1 1 auto;
            min-width: 0;
            display: flex;
            flex-direction: column;
            justify-content: center;
            gap: 0.2rem;
        }}
        .el-qs-title {{
            color: #f8fafc;
            font-size: 0.95rem;
            font-weight: 700;
            letter-spacing: -0.015em;
            line-height: 1.15;
            margin: 0;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }}
        .el-qs-desc {{
            color: #64748b;
            font-size: 0.68rem;
            line-height: 1.35;
            margin: 0;
            display: -webkit-box;
            -webkit-line-clamp: 2;
            -webkit-box-orient: vertical;
            overflow: hidden;
        }}
        .el-qs-arrow {{
            flex: 0 0 auto;
            align-self: center;
            color: #fb7185;
            font-size: 1.1rem;
            font-weight: 600;
            opacity: 0.9;
            line-height: 1;
            padding-left: 0.1rem;
        }}
        [class*="st-key-quick-example-"] {{
            margin-top: -5.15rem !important;
            position: relative;
            z-index: 2;
        }}
        [class*="st-key-quick-example-"] button {{
            min-height: 5.15rem !important;
            height: 5.15rem !important;
            padding: 0 !important;
            border-radius: 0.85rem !important;
            border: 1px solid transparent !important;
            background: transparent !important;
            color: transparent !important;
            box-shadow: none !important;
            font-size: 0 !important;
        }}
        [class*="st-key-quick-example-"] button:hover {{
            border-color: transparent !important;
            background: transparent !important;
        }}
        [class*="st-key-quick-example-"] button:focus {{
            box-shadow: none !important;
        }}
        div[data-testid="stColumn"]:has([class*="st-key-quick-example-"] button:hover) .el-qs-card {{
            transform: translateY(-2px);
            border-color: rgba(148, 163, 184, 0.78);
            background: rgba(30, 41, 59, 0.72);
        }}
        div[data-testid="stColumn"]:has([class*="st-key-quick-example-"] button:hover) .el-qs-card-active {{
            border-color: rgba(251, 113, 133, 0.88);
        }}
        div[data-testid="stColumn"]:has([class*="st-key-quick-example-"] button:hover) .el-qs-icon-coral {{
            border-color: rgba(251, 113, 133, 0.72);
            background: rgba(251, 113, 133, 0.16);
            box-shadow: 0 0 0 1px rgba(251, 113, 133, 0.18), 0 0 24px rgba(251, 113, 133, 0.46);
        }}
        div[data-testid="stColumn"]:has([class*="st-key-quick-example-"] button:hover) .el-qs-icon-cyan {{
            border-color: rgba(56, 189, 248, 0.72);
            background: rgba(56, 189, 248, 0.16);
            box-shadow: 0 0 0 1px rgba(56, 189, 248, 0.18), 0 0 24px rgba(56, 189, 248, 0.46);
        }}
        div[data-testid="stColumn"]:has([class*="st-key-quick-example-"] button:hover) .el-qs-icon-green {{
            border-color: rgba(52, 211, 153, 0.72);
            background: rgba(52, 211, 153, 0.16);
            box-shadow: 0 0 0 1px rgba(52, 211, 153, 0.18), 0 0 24px rgba(52, 211, 153, 0.42);
        }}

        [data-testid="stVerticalBlockBorderWrapper"] {{
            border: 1px solid rgba(148, 163, 184, 0.22) !important;
            border-radius: 0.85rem !important;
            background: rgba(15, 23, 42, 0.52) !important;
            box-shadow: 0 8px 22px rgba(2, 6, 23, 0.24) !important;
        }}
        [data-testid="stVerticalBlockBorderWrapper"] h3,
        .el-card-title {{
            margin: 0.1rem 0 0.15rem 0;
            letter-spacing: -0.015em;
            font-weight: 700;
            font-size: 1.12rem;
            color: #f1f5f9;
        }}
        .el-section-sub {{
            margin: 0 0 0.45rem 0 !important;
            color: #94a3b8;
            font-size: 0.86rem;
            line-height: 1.35;
        }}

        .el-stepper {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.35rem;
            margin: 0 0 1.25rem 0;
            padding: 0.15rem 0.15rem 0.35rem 0.15rem;
            overflow-x: auto;
        }}
        .el-step {{
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 0.4rem;
            min-width: 4.8rem;
            flex: 0 0 auto;
        }}
        .el-step-node {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 1.7rem;
            height: 1.7rem;
            border-radius: 999px;
            border: 1.5px solid #475569;
            background: rgba(15, 23, 42, 0.8);
            color: #94a3b8;
            font-size: 0.78rem;
            font-weight: 700;
        }}
        .el-step-label {{
            font-size: 0.78rem;
            font-weight: 600;
            color: #94a3b8;
            white-space: nowrap;
            letter-spacing: -0.01em;
        }}
        .el-step-line {{
            flex: 1 1 auto;
            height: 1px;
            min-width: 1.25rem;
            margin: 0 0.15rem 1.35rem 0.15rem;
            background: rgba(71, 85, 105, 0.85);
        }}
        .el-step-active .el-step-node,
        .el-step-ready .el-step-node,
        .el-step-goal .el-step-node {{
            border-color: #fb7185;
            color: #fb7185;
            background: rgba(251, 113, 133, 0.1);
            box-shadow: 0 0 0 3px rgba(251, 113, 133, 0.12);
        }}
        .el-step-active .el-step-label,
        .el-step-ready .el-step-label,
        .el-step-goal .el-step-label {{
            color: #fb7185;
        }}
        .el-step-ready .el-step-node {{
            font-weight: 800;
            box-shadow: 0 0 0 3px rgba(251, 113, 133, 0.18), 0 0 16px rgba(251, 113, 133, 0.22);
        }}
        .el-step-complete .el-step-node {{
            border-color: #34d399;
            color: #6ee7b7;
            background: rgba(52, 211, 153, 0.1);
            font-size: 0.85rem;
        }}
        .el-step-complete .el-step-label {{
            color: #6ee7b7;
        }}
        .el-step-incomplete .el-step-node,
        .el-step-optional .el-step-node,
        .el-step-upcoming .el-step-node {{
            border-color: #475569;
            color: #64748b;
            background: transparent;
        }}
        .el-step-incomplete .el-step-label,
        .el-step-optional .el-step-label,
        .el-step-upcoming .el-step-label {{
            color: #64748b;
        }}

        .calc-summary-panel {{
            position: sticky;
            top: 5.3rem;
            box-sizing: border-box;
            display: flex;
            flex-direction: column;
            justify-content: flex-start;
            gap: 0.85rem;
            min-height: 19.5rem;
            padding: 1.3rem 1.35rem 1.15rem;
            border: 1px solid rgba(71, 85, 105, 0.75);
            border-radius: 0.95rem;
            background: rgba(15, 23, 42, 0.72);
            box-shadow: 0 10px 28px rgba(2, 6, 23, 0.28);
        }}
        .calc-summary-divider {{
            height: 1px;
            margin: 0.35rem 0 0.15rem 0;
            background: rgba(71, 85, 105, 0.55);
        }}
        .calc-summary-results {{
            display: flex;
            flex-direction: column;
            gap: 0.45rem;
        }}
        .calc-summary-results .calc-summary-item {{
            padding: 0.72rem 0;
        }}
        .calc-summary-equity {{
            font-size: 1.55rem !important;
            letter-spacing: -0.02em;
        }}
        .el-eq-status {{
            display: flex;
            flex-direction: column;
            gap: 0.12rem;
            margin-top: 0.15rem;
        }}
        .el-eq-status-label {{
            font-size: 0.78rem;
            font-weight: 700;
            letter-spacing: 0.01em;
            line-height: 1.25;
        }}
        .el-eq-status-diff {{
            color: #94a3b8;
            font-size: 0.72rem;
            font-weight: 600;
        }}
        .el-eq-status-above .el-eq-status-label {{ color: #86efac; }}
        .el-eq-status-below .el-eq-status-label {{ color: #fda4af; }}
        .el-eq-status-even .el-eq-status-label {{ color: #fde68a; }}
        .el-sim-confidence {{
            display: flex;
            flex-direction: column;
            gap: 0.18rem;
            margin-top: 0.55rem;
            padding: 0.55rem 0.65rem;
            border-radius: 0.55rem;
            border: 1px solid rgba(71, 85, 105, 0.45);
            background: rgba(15, 23, 42, 0.45);
        }}
        .el-sim-confidence-row {{
            display: inline-flex;
            align-items: center;
            gap: 0.35rem;
        }}
        .el-sim-confidence-label {{
            color: #64748b;
            font-size: 0.64rem;
            font-weight: 700;
            letter-spacing: 0.08em;
            text-transform: uppercase;
        }}
        .el-sim-confidence-level {{
            font-size: 0.92rem;
            font-weight: 750;
            letter-spacing: -0.01em;
        }}
        .el-sim-confidence-trials {{
            color: #94a3b8;
            font-size: 0.72rem;
            font-weight: 600;
        }}
        .el-sim-conf-low .el-sim-confidence-level {{ color: #fda4af; }}
        .el-sim-conf-medium .el-sim-confidence-level {{ color: #fde68a; }}
        .el-sim-conf-high .el-sim-confidence-level {{ color: #86efac; }}
        .el-sim-conf-very-high .el-sim-confidence-level {{ color: #6ee7b7; }}
        .calc-summary-rec-card {{
            display: flex;
            flex-direction: column;
            gap: 0.55rem;
            margin: 0.2rem 0 0.15rem 0;
            padding: 1.2rem 1rem 1.1rem;
            min-height: 7.4rem;
            border-radius: 0.85rem;
            border: 1px solid rgba(148, 163, 184, 0.28);
            background: rgba(15, 23, 42, 0.72);
            box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04);
        }}
        .calc-summary-rec-card .calc-summary-label {{
            color: rgba(226, 232, 240, 0.72);
        }}
        .calc-summary-rec-action {{
            display: inline-flex;
            align-items: center;
            gap: 0.55rem;
            margin-top: 0.1rem;
        }}
        .calc-summary-rec-icon {{
            flex: 0 0 auto;
            display: block;
            filter: drop-shadow(0 0 8px rgba(255, 255, 255, 0.12));
        }}
        .calc-summary-rec-text {{
            font-size: 1.72rem;
            font-weight: 800;
            letter-spacing: -0.03em;
            line-height: 1.05;
            text-transform: capitalize;
        }}
        .calc-summary-why {{
            margin-top: 0.35rem;
            padding-top: 0.55rem;
            border-top: 1px solid rgba(148, 163, 184, 0.18);
        }}
        .calc-summary-why-title {{
            margin: 0 0 0.35rem 0;
            color: #94a3b8;
            font-size: 0.66rem;
            font-weight: 700;
            letter-spacing: 0.1em;
            text-transform: uppercase;
        }}
        .calc-summary-why-list {{
            margin: 0;
            padding: 0 0 0 1.05rem;
            display: flex;
            flex-direction: column;
            gap: 0.28rem;
            color: #cbd5e1;
            font-size: 0.78rem;
            font-weight: 550;
            line-height: 1.35;
        }}
        .calc-summary-why-list li::marker {{
            color: #64748b;
        }}
        .rec-badge {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            min-width: 3.6rem;
            padding: 0.22rem 0.55rem;
            border-radius: 999px;
            font-size: 0.78rem;
            font-weight: 700;
            letter-spacing: 0.02em;
        }}
        .rec-call {{
            color: #bbf7d0;
            background: rgba(34, 197, 94, 0.16);
            border: 1px solid rgba(74, 222, 128, 0.35);
        }}
        .rec-fold {{
            color: #fecdd3;
            background: rgba(244, 63, 94, 0.16);
            border: 1px solid rgba(251, 113, 133, 0.4);
        }}
        .rec-check {{
            color: #bfdbfe;
            background: rgba(59, 130, 246, 0.16);
            border: 1px solid rgba(96, 165, 250, 0.4);
        }}
        .rec-raise {{
            color: #fde68a;
            background: rgba(245, 158, 11, 0.16);
            border: 1px solid rgba(251, 191, 36, 0.4);
        }}
        .calc-summary-rec-card.rec-call {{
            color: #bbf7d0;
            background: linear-gradient(180deg, rgba(22, 101, 52, 0.28), rgba(15, 23, 42, 0.78));
            border-color: rgba(74, 222, 128, 0.42);
            box-shadow:
                0 0 0 1px rgba(34, 197, 94, 0.12),
                0 0 28px rgba(34, 197, 94, 0.18),
                inset 0 1px 0 rgba(187, 247, 208, 0.08);
        }}
        .calc-summary-rec-card.rec-fold {{
            color: #fecdd3;
            background: linear-gradient(180deg, rgba(136, 19, 55, 0.28), rgba(15, 23, 42, 0.78));
            border-color: rgba(251, 113, 133, 0.42);
            box-shadow:
                0 0 0 1px rgba(244, 63, 94, 0.12),
                0 0 28px rgba(244, 63, 94, 0.18),
                inset 0 1px 0 rgba(254, 205, 211, 0.08);
        }}
        .calc-summary-rec-card.rec-check {{
            color: #bfdbfe;
            background: linear-gradient(180deg, rgba(30, 64, 175, 0.28), rgba(15, 23, 42, 0.78));
            border-color: rgba(96, 165, 250, 0.42);
            box-shadow:
                0 0 0 1px rgba(59, 130, 246, 0.12),
                0 0 28px rgba(59, 130, 246, 0.18),
                inset 0 1px 0 rgba(191, 219, 254, 0.08);
        }}
        .calc-summary-rec-card.rec-raise {{
            color: #fde68a;
            background: linear-gradient(180deg, rgba(146, 64, 14, 0.28), rgba(15, 23, 42, 0.78));
            border-color: rgba(251, 191, 36, 0.42);
            box-shadow:
                0 0 0 1px rgba(245, 158, 11, 0.12),
                0 0 28px rgba(245, 158, 11, 0.18),
                inset 0 1px 0 rgba(253, 230, 138, 0.08);
        }}
        .el-equity-bar {{
            margin-top: 0.28rem;
            width: 100%;
        }}
        .el-equity-bar-track {{
            display: flex;
            width: 100%;
            height: 1.28rem;
            overflow: hidden;
            gap: 2px;
            border-radius: 0.45rem;
            background: rgba(30, 41, 59, 0.9);
            box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04);
        }}
        .el-equity-seg {{
            display: flex;
            align-items: center;
            justify-content: center;
            height: 100%;
            min-width: 0;
            overflow: hidden;
            transform-origin: left center;
        }}
        .el-equity-bar-animated .el-equity-seg {{
            animation: elEquitySegGrow 0.85s cubic-bezier(0.22, 1, 0.36, 1) both;
        }}
        @keyframes elEquitySegGrow {{
            from {{ transform: scaleX(0.04); opacity: 0.35; }}
            to {{ transform: scaleX(1); opacity: 1; }}
        }}
        .el-equity-seg-label {{
            color: rgba(15, 23, 42, 0.92);
            font-size: 0.68rem;
            font-weight: 800;
            letter-spacing: -0.01em;
            line-height: 1;
            white-space: nowrap;
            pointer-events: none;
        }}
        .el-equity-tie .el-equity-seg-label {{
            color: rgba(15, 23, 42, 0.88);
        }}
        .el-equity-win {{ background: #34d399; }}
        .el-equity-tie {{ background: #94a3b8; }}
        .el-equity-loss {{ background: #fb7185; }}
        .el-equity-bar-pcts {{
            display: flex;
            width: 100%;
            gap: 2px;
            margin-top: 0.28rem;
        }}
        .el-equity-pct {{
            min-width: 0;
            text-align: center;
            color: #94a3b8;
            font-size: 0.68rem;
            font-weight: 700;
            letter-spacing: -0.01em;
            line-height: 1.2;
        }}
        .el-equity-pct.is-hidden {{
            visibility: hidden;
        }}
        .el-equity-bar-legend {{
            display: flex;
            flex-wrap: wrap;
            gap: 0.45rem 0.75rem;
            margin-top: 0.38rem;
            color: #94a3b8;
            font-size: 0.72rem;
            font-weight: 600;
        }}
        .el-equity-legend-item {{
            display: inline-flex;
            align-items: center;
            gap: 0.3rem;
        }}
        .el-equity-swatch {{
            width: 0.55rem;
            height: 0.55rem;
            border-radius: 999px;
            display: inline-block;
        }}

        .el-best-hand-panel {{
            display: flex;
            flex-direction: column;
            gap: 0.72rem;
        }}
        .el-best-hand-block {{
            margin: 0;
            padding: 0;
        }}
        .el-best-hand-block + .el-best-hand-block {{
            padding-top: 0.55rem;
            border-top: 1px solid rgba(71, 85, 105, 0.35);
        }}
        .el-best-hand-panel .el-live-board-label {{
            margin-bottom: 0.42rem;
            color: #64748b;
            font-size: 0.64rem;
            letter-spacing: 0.1em;
        }}
        .el-best-hand-panel .el-live-chip-row {{
            gap: 0.4rem;
        }}
        .el-best-hand-meta {{
            margin: 0.15rem 0 0 0;
            color: #64748b;
            font-size: 0.72rem;
            font-weight: 600;
            letter-spacing: 0.02em;
        }}
        .hero-analysis-panel.el-best-hand-panel {{
            padding: 0.15rem 0 0.05rem 0;
        }}
        .decision-why {{
            margin: 0 0 0.75rem 0;
            padding: 0.65rem 0.75rem;
            border-radius: 0.55rem;
            border: 1px solid rgba(71, 85, 105, 0.45);
            background: rgba(15, 23, 42, 0.42);
        }}
        .decision-why-title {{
            margin: 0 0 0.35rem 0;
            color: #94a3b8;
            font-size: 0.66rem;
            font-weight: 700;
            letter-spacing: 0.1em;
            text-transform: uppercase;
        }}
        .decision-why-list {{
            margin: 0;
            padding: 0 0 0 1.05rem;
            display: flex;
            flex-direction: column;
            gap: 0.28rem;
            color: #cbd5e1;
            font-size: 0.82rem;
            font-weight: 550;
            line-height: 1.35;
        }}
        .decision-why-list li::marker {{
            color: #64748b;
        }}

        .el-live-board {{
            margin: 0.85rem auto 0.15rem auto;
            padding: 0.8rem 0.95rem;
            max-width: 28rem;
            border-radius: 0.8rem;
            border: 1px solid rgba(71, 85, 105, 0.55);
            background: rgba(15, 23, 42, 0.55);
        }}
        .el-live-board-muted {{
            opacity: 0.78;
        }}
        .el-live-board-block {{
            margin: 0.55rem 0 0 0;
        }}
        .el-live-board-block:first-child {{
            margin-top: 0.1rem;
        }}
        .el-live-board.el-best-hand-panel .el-live-board-block {{
            margin: 0;
        }}
        .el-live-board-label {{
            color: #64748b;
            font-size: 0.66rem;
            font-weight: 650;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            margin: 0 0 0.35rem 0;
        }}
        .el-live-chip-row {{
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            gap: 0.35rem;
        }}
        .el-live-chip {{
            display: inline-flex;
            align-items: center;
            gap: 0.28rem;
            padding: 0.28rem 0.55rem;
            border-radius: 999px;
            font-size: 0.84rem;
            font-weight: 750;
            line-height: 1.15;
            letter-spacing: -0.01em;
            border: 1px solid rgba(148, 163, 184, 0.28);
            background: rgba(30, 41, 59, 0.85);
            color: #f1f5f9;
        }}
        .el-live-chip img {{
            display: block;
            flex-shrink: 0;
        }}
        .el-live-chip-hand {{
            border-color: rgba(251, 191, 36, 0.42);
            background: linear-gradient(180deg, rgba(120, 53, 15, 0.55), rgba(69, 26, 3, 0.72));
            color: #fde68a;
        }}
        .el-live-chip-detail {{
            font-weight: 700;
            color: #e2e8f0;
            background: rgba(51, 65, 85, 0.72);
        }}
        .el-live-chip-draw {{
            border-color: rgba(56, 189, 248, 0.4);
            background: linear-gradient(180deg, rgba(12, 74, 110, 0.55), rgba(8, 47, 73, 0.72));
            color: #7dd3fc;
        }}
        .el-live-chip-texture {{
            font-weight: 650;
            color: #cbd5e1;
            background: rgba(30, 41, 59, 0.9);
        }}
        .el-live-chip-empty {{
            font-weight: 600;
            color: #64748b;
            background: transparent;
            border-color: rgba(71, 85, 105, 0.45);
        }}
        .el-live-board-texture-detail {{
            margin: 0.45rem 0 0 0;
            color: #94a3b8;
            font-size: 0.76rem;
            line-height: 1.35;
        }}

        .hero-draw-value {{
            color: #e2e8f0;
            font-size: 0.86rem;
            font-weight: 650;
            text-align: right;
        }}
        .hero-draw-primary .hero-draw-value {{
            color: #86efac;
        }}

        [class*="st-key-calculate-equity-btn"] button {{
            transition: transform 200ms ease, box-shadow 200ms ease, border-color 200ms ease,
                letter-spacing 200ms ease, opacity 200ms ease !important;
        }}
        [class*="st-key-calculate-equity-btn"] button:not(:disabled) {{
            box-shadow: 0 0 0 1px rgba(251, 113, 133, 0.1), 0 12px 28px rgba(244, 63, 94, 0.36) !important;
        }}
        [class*="st-key-calculate-equity-btn"] button:not(:disabled):hover {{
            transform: translateY(-1px) !important;
            box-shadow: 0 0 0 1px rgba(251, 113, 133, 0.14), 0 14px 30px rgba(244, 63, 94, 0.4) !important;
        }}
        [class*="st-key-calculate-equity-btn"] button:not(:disabled):active {{
            transform: translateY(1px) scale(0.985) !important;
        }}

        .el-fade-in {{
            animation: elFadeIn 180ms ease-out;
        }}
        .el-fade-up {{
            animation: elFadeUp 200ms ease-out;
        }}
        @keyframes elFadeIn {{
            from {{ opacity: 0; }}
            to {{ opacity: 1; }}
        }}
        @keyframes elFadeUp {{
            from {{ opacity: 0; transform: translateY(6px); }}
            to {{ opacity: 1; transform: translateY(0); }}
        }}
        @media (prefers-reduced-motion: reduce) {{
            .el-fade-in,
            .el-fade-up,
            .rec-badge,
            .card-deal-in {{
                animation: none !important;
            }}
            [class*="st-key-board-slot-"] button,
            [class*="st-key-hero-slot-"] button,
            [class*="st-key-picker-"] button {{
                animation: none !important;
                transition: none !important;
            }}
        }}
        [class*="st-key-board-slot-"] button,
        [class*="st-key-hero-slot-"] button {{
            transition: transform 200ms cubic-bezier(0.22, 1, 0.36, 1),
                opacity 200ms ease, box-shadow 220ms ease, filter 200ms ease,
                border-color 200ms ease !important;
        }}
        [class*="st-key-board-slot-"] button[kind="primary"],
        [class*="st-key-hero-slot-"] button[kind="primary"],
        [class*="st-key-board-slot-"] button[data-testid="baseButton-primary"],
        [class*="st-key-hero-slot-"] button[data-testid="baseButton-primary"] {{
            animation: elCardIn 240ms cubic-bezier(0.22, 1, 0.36, 1);
        }}
        @keyframes elCardIn {{
            from {{ opacity: 0.4; transform: scale(0.9); filter: brightness(1.08); }}
            to {{ opacity: 1; transform: scale(1); filter: brightness(1); }}
        }}
        .rec-badge {{
            animation: elFadeIn 200ms ease-out;
        }}
        .results-anchor + div,
        div[data-testid="stVerticalBlockBorderWrapper"]:has(.el-card-title) {{
            animation: elFadeUp 200ms ease-out;
        }}
        .calc-summary-value {{
            transition: opacity 160ms ease;
        }}

        div[data-testid="stMarkdownContainer"]:has(.calc-summary-panel),
        div[data-testid="stHtmlContainer"]:has(.calc-summary-panel) {{
            margin: 0 !important;
        }}
        /* Keep summary top flush with Hero Hand column top. */
        div[data-testid="stColumn"]:has(.calc-summary-panel) {{
            margin-top: 0 !important;
            padding-top: 0 !important;
        }}
        .calc-summary-title {{
            margin: 0;
            display: flex;
            align-items: center;
            gap: 0.45rem;
            color: #f1f5f9;
            font-size: 1.15rem;
            font-weight: 700;
            line-height: 1.25;
            letter-spacing: -0.015em;
        }}
        .calc-summary-title-icon {{
            flex: 0 0 auto;
            width: 18px;
            height: 18px;
            opacity: 0.9;
        }}
        .calc-summary-body {{
            display: flex;
            flex-direction: column;
            justify-content: flex-start;
            gap: 0;
            flex: 1 1 auto;
        }}
        .calc-summary-status {{
            margin-top: auto;
            padding-top: 0.7rem;
        }}
        .status-badge {{
            display: flex;
            align-items: center;
            justify-content: center;
            width: 100%;
            box-sizing: border-box;
            padding: 0.82rem 0.85rem;
            border-radius: 0.7rem;
            font-size: 0.92rem;
            font-weight: 650;
            letter-spacing: 0.01em;
            text-align: center;
            transition: box-shadow 0.18s ease, border-color 0.18s ease, color 0.18s ease;
        }}
        .texture-chip-row {{
            display: flex;
            flex-wrap: wrap;
            gap: 0.4rem;
            margin: 0.15rem 0 0.55rem 0;
        }}
        .texture-chip {{
            display: inline-flex;
            align-items: center;
            padding: 0.28rem 0.65rem;
            border-radius: 999px;
            border: 1px solid rgba(56, 189, 248, 0.35);
            background: rgba(14, 116, 144, 0.22);
            color: #a5f3fc;
            font-size: 0.74rem;
            font-weight: 650;
            letter-spacing: 0.01em;
            white-space: nowrap;
        }}
        .texture-explanation {{
            margin: 0;
            color: #94a3b8;
            font-size: 0.88rem;
            line-height: 1.45;
        }}
        .decision-explanation {{
            margin: 0;
            color: #94a3b8;
            font-size: 0.88rem;
            line-height: 1.45;
        }}
        .decision-confidence {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.75rem;
            margin: 0 0 0.75rem 0;
            padding: 0.55rem 0.7rem;
            border-radius: 0.45rem;
            border: 1px solid rgba(51, 65, 85, 0.7);
            background: rgba(15, 23, 42, 0.45);
        }}
        .decision-confidence-label {{
            color: #64748b;
            font-size: 0.68rem;
            font-weight: 700;
            letter-spacing: 0.06em;
            text-transform: uppercase;
        }}
        .decision-confidence-value {{
            font-size: 0.95rem;
            font-weight: 700;
            letter-spacing: 0.01em;
        }}
        .decision-confidence-call .decision-confidence-value {{
            color: #86efac;
        }}
        .decision-confidence-fold .decision-confidence-value {{
            color: #fda4af;
        }}
        .decision-stability {{
            margin: 0.8rem 0 0;
            padding: 0.8rem 0.9rem;
            border: 1px solid rgba(148, 163, 184, 0.3);
            border-radius: 0.55rem;
            background: rgba(15, 23, 42, 0.55);
        }}
        .decision-stability-stable {{ border-color: rgba(52, 211, 153, 0.45); }}
        .decision-stability-overlap {{ border-color: rgba(251, 191, 36, 0.55); }}
        .decision-stability-title {{ color: #f8fafc; font-weight: 700; }}
        .decision-stability p {{ margin: 0.3rem 0; color: #cbd5e1; }}
        .decision-stability span {{ color: #94a3b8; font-size: 0.84rem; }}
        .decision-sensitivity {{
            margin: 0.65rem 0 0 0;
            color: #cbd5e1;
            font-size: 0.86rem;
            line-height: 1.45;
        }}
        .decision-key-heading {{
            margin: 0.85rem 0 0.45rem 0;
            color: #94a3b8;
            font-size: 0.72rem;
            font-weight: 700;
            letter-spacing: 0.06em;
            text-transform: uppercase;
        }}
        .decision-key-list {{
            display: flex;
            flex-direction: column;
            gap: 0.15rem;
        }}
        .decision-key-row {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.75rem;
            padding: 0.42rem 0.55rem;
            border-radius: 0.4rem;
            border: 1px solid rgba(51, 65, 85, 0.55);
            background: rgba(15, 23, 42, 0.35);
        }}
        .decision-key-label {{
            color: #e2e8f0;
            font-size: 0.9rem;
            font-weight: 600;
        }}
        .decision-key-value {{
            color: #a5f3fc;
            font-size: 0.88rem;
            font-weight: 650;
            font-variant-numeric: tabular-nums;
            text-align: right;
        }}
        .decision-calc-steps {{
            margin: 0;
            padding: 0.75rem 0.85rem;
            border-radius: 0.45rem;
            border: 1px solid rgba(51, 65, 85, 0.55);
            background: rgba(15, 23, 42, 0.45);
            color: #cbd5e1;
            font-size: 0.82rem;
            line-height: 1.55;
            white-space: pre-wrap;
            font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
        }}
        .heatmap-grid-shell {{
            margin-top: 0.35rem;
        }}
        .heatmap-legend {{
            margin: 0.7rem 0 0.15rem 0;
            padding: 0.55rem 0.7rem;
            border-radius: 0.55rem;
            border: 1px solid rgba(148, 163, 184, 0.2);
            background: rgba(15, 23, 42, 0.42);
        }}
        .heatmap-legend-title {{
            margin: 0 0 0.35rem 0;
            color: #94a3b8;
            font-size: 0.68rem;
            font-weight: 700;
            letter-spacing: 0.06em;
            text-transform: uppercase;
        }}
        .heatmap-legend-track {{
            display: flex;
            flex-direction: column;
            gap: 0.35rem;
        }}
        .heatmap-legend-bar {{
            display: block;
            height: 0.55rem;
            border-radius: 999px;
            background: linear-gradient(90deg, #fb7185, #fbbf24, #34d399);
        }}
        .heatmap-legend-marks {{
            display: flex;
            justify-content: space-between;
            gap: 0.5rem;
        }}
        .heatmap-legend-mark {{
            display: flex;
            flex-direction: column;
            gap: 0.1rem;
            min-width: 0;
        }}
        .heatmap-legend-mark:nth-child(2) {{
            text-align: center;
            align-items: center;
        }}
        .heatmap-legend-mark:nth-child(3) {{
            text-align: right;
            align-items: flex-end;
        }}
        .heatmap-legend-mark strong {{
            color: #e2e8f0;
            font-size: 0.78rem;
            font-weight: 700;
            font-variant-numeric: tabular-nums;
        }}
        .heatmap-legend-mark span {{
            color: #64748b;
            font-size: 0.68rem;
            font-weight: 550;
        }}
        .el-dist-share {{
            position: relative;
            overflow: hidden;
        }}
        .el-dist-bar {{
            position: absolute;
            left: 0;
            top: 0;
            bottom: 0;
            background: linear-gradient(90deg, rgba(52, 211, 153, 0.18), rgba(52, 211, 153, 0.05));
            pointer-events: none;
        }}
        .el-dist-share-text {{
            position: relative;
            z-index: 1;
        }}
        .decision-draw-note {{
            margin: 0.45rem 0 0 0;
            color: #94a3b8;
            font-size: 0.82rem;
            line-height: 1.4;
        }}
        .el-sim-uncertainty {{
            margin-top: 0.65rem;
            padding: 0.55rem 0.7rem;
            border-radius: 0.55rem;
            border: 1px solid rgba(148, 163, 184, 0.2);
            background: rgba(15, 23, 42, 0.4);
        }}
        .el-sim-uncertainty-value {{
            color: #e2e8f0;
            font-size: 0.95rem;
            font-weight: 700;
            font-variant-numeric: tabular-nums;
        }}
        .el-save-analysis-row {{
            display: inline-flex;
            align-items: center;
            gap: 0.4rem;
            margin: 0.35rem 0 0.25rem 0;
            color: #64748b;
            font-size: 0.78rem;
            font-weight: 550;
        }}
        .el-save-analysis-row img {{
            flex-shrink: 0;
            opacity: 0.9;
        }}
        @media (prefers-reduced-motion: reduce) {{
            .el-fade-in,
            .el-fade-up,
            .el-rec-reveal,
            .el-equity-bar-animated .el-equity-seg,
            .el-stat-card,
            .el-equity-hero-stat,
            [class*="st-key-heatmap-cell-"] button,
            div[data-testid="stVerticalBlockBorderWrapper"]:has(.el-results-block) {{
                animation: none !important;
                transition: none !important;
            }}
            .el-stat-card:hover,
            .el-equity-hero-stat:hover,
            [class*="st-key-heatmap-cell-"] button:hover:not(:disabled) {{
                transform: none !important;
            }}
        }}
        .decision-status-banner {{
            display: flex;
            align-items: center;
            gap: 0.7rem;
            margin: 0 0 0.85rem 0;
            padding: 0.85rem 1rem;
            border-radius: 0.55rem;
            border: 1px solid rgba(51, 65, 85, 0.7);
            background: rgba(15, 23, 42, 0.55);
        }}
        .decision-status-emoji {{
            font-size: 1.35rem;
            line-height: 1;
        }}
        .decision-status-text {{
            font-size: 1.15rem;
            font-weight: 750;
            letter-spacing: 0.01em;
        }}
        .decision-status-call-strong {{
            border-color: rgba(34, 197, 94, 0.45);
            background: rgba(20, 83, 45, 0.35);
        }}
        .decision-status-call-strong .decision-status-text {{
            color: #86efac;
        }}
        .decision-status-call-marginal {{
            border-color: rgba(234, 179, 8, 0.45);
            background: rgba(113, 63, 18, 0.35);
        }}
        .decision-status-call-marginal .decision-status-text {{
            color: #fde047;
        }}
        .decision-status-fold-marginal {{
            border-color: rgba(249, 115, 22, 0.45);
            background: rgba(124, 45, 18, 0.35);
        }}
        .decision-status-fold-marginal .decision-status-text {{
            color: #fdba74;
        }}
        .decision-status-fold-strong {{
            border-color: rgba(244, 63, 94, 0.45);
            background: rgba(127, 29, 29, 0.35);
        }}
        .decision-status-fold-strong .decision-status-text {{
            color: #fda4af;
        }}
        .hero-draw-outs {{
            color: #a5f3fc;
            font-size: 0.88rem;
            font-weight: 700;
            font-variant-numeric: tabular-nums;
        }}
        .opp-hand-breakdown {{
            display: flex;
            flex-direction: column;
            gap: 0.12rem;
            margin: 0.05rem 0 0.15rem 0;
        }}
        .opp-hand-row {{
            position: relative;
            display: grid;
            grid-template-columns: minmax(0, 1.6fr) minmax(4.5rem, 0.7fr) minmax(4.5rem, 0.7fr);
            gap: 0.75rem;
            align-items: center;
            padding: 0.36rem 0.55rem;
            border-radius: 0.45rem;
            border: 1px solid rgba(148, 163, 184, 0.16);
            background: rgba(15, 23, 42, 0.35);
            overflow: hidden;
        }}
        .opp-hand-bar {{
            position: absolute;
            left: 0;
            top: 0;
            bottom: 0;
            z-index: 0;
            background: linear-gradient(90deg, rgba(56, 189, 248, 0.16), rgba(56, 189, 248, 0.05));
            pointer-events: none;
        }}
        .opp-hand-row > span:not(.opp-hand-bar) {{
            position: relative;
            z-index: 1;
        }}
        .opp-hand-header {{
            border-color: transparent;
            background: transparent;
            padding-top: 0;
            padding-bottom: 0.12rem;
            overflow: visible;
        }}
        .opp-hand-header .opp-hand-bar {{
            display: none;
        }}
        .opp-hand-header span {{
            color: #64748b;
            font-size: 0.68rem;
            font-weight: 650;
            letter-spacing: 0.06em;
            text-transform: uppercase;
        }}
        .opp-hand-label {{
            color: #e2e8f0;
            font-size: 0.88rem;
            font-weight: 600;
        }}
        .opp-hand-count,
        .opp-hand-pct {{
            color: #cbd5e1;
            font-size: 0.86rem;
            font-variant-numeric: tabular-nums;
            text-align: right;
        }}
        .opp-hand-pct {{
            color: #a5f3fc;
            font-weight: 650;
        }}
        .hero-draw-heading {{
            margin: 0.85rem 0 0.45rem 0;
            color: #94a3b8;
            font-size: 0.72rem;
            font-weight: 700;
            letter-spacing: 0.06em;
            text-transform: uppercase;
        }}
        .hero-draw-list {{
            display: flex;
            flex-direction: column;
            gap: 0.15rem;
        }}
        .hero-draw-row {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.75rem;
            padding: 0.42rem 0.55rem;
            border-radius: 0.4rem;
            border: 1px solid rgba(51, 65, 85, 0.55);
            background: rgba(15, 23, 42, 0.35);
        }}
        .hero-draw-label {{
            color: #e2e8f0;
            font-size: 0.9rem;
            font-weight: 600;
        }}
        .hero-draw-check {{
            color: #86efac;
            font-size: 1rem;
            font-weight: 700;
            line-height: 1;
        }}
        .hero-draw-empty {{
            margin: 0;
            color: #94a3b8;
            font-size: 0.88rem;
            line-height: 1.45;
        }}
        .status-warning {{
            color: #fb7185;
            background: transparent;
            border: 1.5px solid rgba(251, 113, 133, 0.75);
        }}
        .status-success {{
            color: #6ee7b7;
            background: rgba(52, 211, 153, 0.07);
            border: 1.5px solid rgba(52, 211, 153, 0.62);
            box-shadow: 0 0 0 1px rgba(52, 211, 153, 0.08), 0 0 12px rgba(52, 211, 153, 0.16);
        }}
        .st-key-calculate-equity-btn button {{
            min-height: 3.4rem !important;
            border-radius: 0.68rem !important;
            font-weight: 700 !important;
            font-size: 1rem !important;
            width: 100% !important;
            transition: transform 200ms ease, box-shadow 200ms ease, border-color 200ms ease,
                background 200ms ease, letter-spacing 200ms ease, opacity 200ms ease, filter 200ms ease !important;
        }}
        .st-key-calculate-equity-btn button:not(:disabled) {{
            background: linear-gradient(105deg, #fb7185 0%, #f43f5e 52%, #e11d48 100%) !important;
            border: 1px solid rgba(253, 164, 175, 0.45) !important;
            color: #ffffff !important;
            font-weight: 750 !important;
            letter-spacing: -0.01em !important;
            opacity: 1 !important;
            box-shadow: 0 0 0 1px rgba(251, 113, 133, 0.1), 0 12px 28px rgba(244, 63, 94, 0.36) !important;
        }}
        .st-key-calculate-equity-btn button:not(:disabled):hover {{
            transform: translateY(-1px) !important;
            letter-spacing: 0.02em !important;
            box-shadow: 0 0 0 1px rgba(251, 113, 133, 0.14), 0 14px 30px rgba(244, 63, 94, 0.4) !important;
        }}
        .st-key-calculate-equity-btn button:not(:disabled):active {{
            transform: translateY(1px) scale(0.985) !important;
        }}
        .st-key-calculate-equity-btn button:not(:disabled) p,
        .st-key-calculate-equity-btn button:not(:disabled) span {{
            display: inline-block !important;
            color: #ffffff !important;
            font-weight: 750 !important;
            transition: transform 200ms ease !important;
        }}
        .st-key-calculate-equity-btn button:not(:disabled):hover p,
        .st-key-calculate-equity-btn button:not(:disabled):hover span {{
            transform: translateX(3px) !important;
        }}
        .st-key-calculate-equity-btn button:disabled {{
            background: linear-gradient(105deg, #fb7185 0%, #f43f5e 52%, #e11d48 100%) !important;
            border: 1px solid rgba(253, 164, 175, 0.45) !important;
            color: #ffffff !important;
            font-weight: 750 !important;
            opacity: 0.42 !important;
            box-shadow: none !important;
            cursor: not-allowed !important;
        }}
        .st-key-calculate-equity-btn button:disabled p,
        .st-key-calculate-equity-btn button:disabled span {{
            color: #ffffff !important;
        }}
        [class*="st-key-edit-custom-range"] button {{
            min-height: 2.7rem !important;
            border-radius: 0.72rem !important;
            font-weight: 650 !important;
        }}
        .calc-summary-checklist {{
            display: flex;
            flex-direction: column;
            gap: 0.42rem;
            margin: 0 0 0.55rem 0;
            padding: 0.55rem 0.65rem;
            border-radius: 0.65rem;
            border: 1px solid rgba(71, 85, 105, 0.4);
            background: rgba(2, 6, 23, 0.35);
        }}
        .calc-check {{
            display: flex;
            align-items: center;
            gap: 0.45rem;
            font-size: 0.8rem;
            font-weight: 600;
            line-height: 1.25;
            color: #94a3b8;
        }}
        .calc-check-mark {{
            width: 1.05rem;
            text-align: center;
            font-size: 0.78rem;
            font-weight: 750;
            flex-shrink: 0;
        }}
        .calc-check-on {{
            color: #bbf7d0;
        }}
        .calc-check-on .calc-check-mark {{
            color: #4ade80;
        }}
        .calc-check-off {{
            color: #64748b;
        }}
        .calc-check-meta {{
            color: #94a3b8;
            margin-top: 0.1rem;
            padding-top: 0.4rem;
            border-top: 1px solid rgba(71, 85, 105, 0.35);
        }}
        .calc-check-meta .calc-check-mark {{
            color: #64748b;
            letter-spacing: 0.02em;
        }}
        .calc-summary-item {{
            display: flex;
            flex-direction: column;
            gap: 0.3rem;
            margin: 0;
            padding: 0.74rem 0;
            border-bottom: 1px solid rgba(71, 85, 105, 0.38);
        }}
        .calc-summary-checklist + .calc-summary-item {{
            padding-top: 0.3rem;
        }}
        .calc-summary-item:has(+ .calc-summary-status) {{
            border-bottom: none;
            padding-bottom: 0.18rem;
        }}
        .calc-summary-label {{
            display: inline-flex;
            align-items: center;
            gap: 0.35rem;
            color: #64748b;
            font-size: 0.68rem;
            font-weight: 650;
            letter-spacing: 0.09em;
            text-transform: uppercase;
        }}
        .calc-summary-label-icon {{
            display: block;
            flex-shrink: 0;
            opacity: 0.9;
        }}
        .calc-summary-value {{
            color: #f8fafc;
            font-size: 1.23rem;
            font-weight: 750;
            letter-spacing: -0.015em;
            line-height: 1.25;
            animation: elValueFade 0.18s ease-out;
        }}
        @keyframes elValueFade {{
            from {{ opacity: 0.35; transform: translateY(2px); }}
            to {{ opacity: 1; transform: translateY(0); }}
        }}
        .range-summary-panel {{
            position: relative;
            z-index: 1;
            box-sizing: border-box;
            display: flex;
            flex-direction: column;
            gap: 0.85rem;
            width: 100%;
            padding: 1.25rem 1.05rem;
            border: 1px solid rgba(148, 163, 184, 0.28);
            border-radius: 0.55rem;
            background: rgba(15, 23, 42, 0.55);
            min-height: 22rem;
        }}
        .range-summary-panel-expandable {{
            border-bottom-left-radius: 0;
            border-bottom-right-radius: 0;
            border-bottom-color: transparent;
            min-height: 0;
            padding-bottom: 0.25rem;
        }}
        div[data-testid="stMarkdownContainer"]:has(.range-summary-panel) {{
            margin: 0 !important;
        }}
        div[data-testid="stMarkdownContainer"]:has(.range-summary-panel-expandable) {{
            margin-bottom: 0 !important;
        }}
        .range-summary-title {{
            margin: 0;
            color: #f8fafc;
            font-size: 1.05rem;
            font-weight: 700;
            line-height: 1.2;
            white-space: nowrap;
        }}
        .range-summary-body {{
            display: flex;
            flex-direction: column;
            gap: 0.85rem;
        }}
        .range-summary-item {{
            display: flex;
            flex-direction: column;
            gap: 0.28rem;
            min-width: 0;
        }}
        .range-summary-label {{
            color: #64748b;
            font-size: 0.68rem;
            font-weight: 500;
            letter-spacing: 0.06em;
            text-transform: uppercase;
        }}
        .range-summary-value {{
            color: #f8fafc;
            font-size: 1.42rem;
            font-weight: 700;
            letter-spacing: -0.02em;
            line-height: 1.15;
            word-break: break-word;
        }}
        .range-summary-notation {{
            color: #cbd5e1;
            font-size: 0.88rem;
            font-weight: 600;
            line-height: 1.4;
            word-break: break-word;
        }}
        .range-summary-notation-collapsed {{
            display: block;
            max-width: 100%;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            word-break: normal;
        }}
        .range-summary-notation-expanded {{
            display: block;
            white-space: normal;
            word-break: break-word;
            overflow-wrap: anywhere;
        }}
        .range-summary-notation-block {{
            gap: 0.22rem;
        }}
        .range-summary-muted {{
            color: #64748b !important;
            font-weight: 500 !important;
        }}
        .range-summary-metrics {{
            display: flex;
            flex-direction: column;
            gap: 0.55rem;
        }}
        .range-summary-metric {{
            display: flex;
            flex-direction: column;
            gap: 0.28rem;
            padding: 0.75rem 0.85rem;
            border-radius: 0.45rem;
            border: 1px solid rgba(51, 65, 85, 0.9);
            background: rgba(30, 41, 59, 0.45);
            min-width: 0;
        }}
        .range-summary-metric .range-summary-label {{
            color: #64748b;
            font-size: 0.68rem;
            font-weight: 500;
            letter-spacing: 0.06em;
            text-transform: uppercase;
        }}
        .range-summary-metric .range-summary-value {{
            color: #f8fafc;
            font-size: 1.42rem;
            font-weight: 700;
            letter-spacing: -0.02em;
            line-height: 1.15;
        }}
        .range-empty-state {{
            margin: 0.45rem 0 0 0 !important;
            color: #94a3b8;
            font-size: 0.9rem;
        }}
        /* Keep Show all / Show less visually inside the notation area of the card. */
        div[data-testid="stVerticalBlockBorderWrapper"] div[data-testid="stVerticalBlock"]:has(.range-summary-panel-expandable):has([class*="toggle-range-notation"]),
        div[data-testid="column"] div[data-testid="stVerticalBlock"]:has(.range-summary-panel-expandable):has([class*="toggle-range-notation"]) {{
            gap: 0 !important;
        }}
        div[data-testid="stElementContainer"]:has([class*="toggle-range-notation"]),
        div[data-testid="stVerticalBlock"] > div:has(> div [class*="toggle-range-notation"]) {{
            border: 1px solid rgba(148, 163, 184, 0.28);
            border-top: none;
            border-radius: 0 0 0.55rem 0.55rem;
            background: rgba(15, 23, 42, 0.55);
            padding: 0 1.05rem 1rem !important;
            margin-top: -0.05rem !important;
        }}
        [class*="toggle-range-notation"] button {{
            background: transparent !important;
            background-color: transparent !important;
            border: none !important;
            box-shadow: none !important;
            color: #7dd3fc !important;
            font-size: 0.76rem !important;
            font-weight: 600 !important;
            min-height: 1.15rem !important;
            height: auto !important;
            padding: 0.05rem 0 0 0 !important;
            width: auto !important;
            text-decoration: none !important;
            justify-content: flex-start !important;
            letter-spacing: 0.01em !important;
        }}
        [class*="toggle-range-notation"] button:hover {{
            background: transparent !important;
            color: #bae6fd !important;
            border: none !important;
            box-shadow: none !important;
            text-decoration: underline !important;
            text-underline-offset: 0.12em !important;
        }}
        [class*="toggle-range-notation"] {{
            margin: 0 !important;
            width: fit-content !important;
        }}
        .hand-history-list {{
            display: flex;
            flex-direction: column;
            gap: 0.85rem;
            margin-top: 0.85rem;
        }}
        .hand-history-empty-card,
        .hand-history-entry-card {{
            box-sizing: border-box;
            width: 100%;
            padding: 1.35rem 1.2rem;
            border: 1px solid rgba(148, 163, 184, 0.28);
            border-radius: 0.55rem;
            background: rgba(15, 23, 42, 0.55);
        }}
        .hand-history-empty-card {{
            display: flex;
            flex-direction: column;
            align-items: flex-start;
            gap: 0.45rem;
            min-height: 9.5rem;
            justify-content: center;
        }}
        .hand-history-empty-title {{
            margin: 0;
            color: #f8fafc;
            font-size: 1.05rem;
            font-weight: 700;
            line-height: 1.3;
        }}
        .hand-history-empty-copy {{
            margin: 0;
            max-width: 36rem;
            color: #94a3b8;
            font-size: 0.95rem;
            line-height: 1.55;
        }}
        .hand-history-entry-header {{
            display: flex;
            flex-wrap: wrap;
            align-items: baseline;
            justify-content: space-between;
            gap: 0.55rem 1rem;
            margin-bottom: 0.95rem;
        }}
        .hand-history-entry-title {{
            margin: 0;
            color: #f8fafc;
            font-size: 1.05rem;
            font-weight: 700;
            line-height: 1.3;
            word-break: break-word;
        }}
        .hand-history-entry-timestamp {{
            color: #94a3b8;
            font-size: 0.82rem;
            font-weight: 600;
            white-space: nowrap;
        }}
        .hand-history-entry-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(9.5rem, 1fr));
            gap: 0.7rem;
        }}
        .hand-history-entry-item {{
            display: flex;
            flex-direction: column;
            gap: 0.2rem;
            padding: 0.55rem 0.6rem;
            border-radius: 0.45rem;
            border: 1px solid rgba(51, 65, 85, 0.9);
            background: rgba(30, 41, 59, 0.45);
        }}
        .hand-history-entry-label {{
            color: #94a3b8;
            font-size: 0.72rem;
            font-weight: 600;
            letter-spacing: 0.04em;
            text-transform: uppercase;
        }}
        .hand-history-entry-value {{
            color: #f8fafc;
            font-size: 0.92rem;
            font-weight: 600;
            line-height: 1.35;
            word-break: break-word;
        }}
        .st-key-use-range-in-calculator button:not(:disabled) {{
            background: linear-gradient(145deg, #ef4444 0%, #dc2626 100%) !important;
            border: 1px solid #b91c1c !important;
            color: #ffffff !important;
            font-weight: 700 !important;
            min-height: 2.55rem !important;
            box-shadow: 0 10px 24px rgba(220, 38, 38, 0.24) !important;
        }}
        .st-key-use-range-in-calculator button:not(:disabled):hover {{
            background: linear-gradient(145deg, #f87171 0%, #ef4444 100%) !important;
            border-color: #dc2626 !important;
        }}
        .st-key-use-range-in-calculator button:disabled {{
            opacity: 0.5 !important;
        }}
        /* Two-column Range Builder shell: grid left, summary right. */
        div[data-testid="stHorizontalBlock"]:has([class*="-range-cell-"]):has(.range-summary-panel) {{
            align-items: flex-start !important;
            gap: 1.25rem !important;
        }}
        div[data-testid="stHorizontalBlock"]:has([class*="-range-cell-"]):has(.range-summary-panel) > div:first-child {{
            flex: 1 1 0 !important;
            min-width: 0 !important;
            max-width: calc(100% - 19.5rem) !important;
        }}
        div[data-testid="stHorizontalBlock"]:has([class*="-range-cell-"]):has(.range-summary-panel) > div:last-child {{
            flex: 0 0 18.5rem !important;
            width: 18.5rem !important;
            max-width: 18.5rem !important;
            min-width: 18.5rem !important;
        }}
        .range-grid-heading {{
            margin: 0 0 0.55rem 0 !important;
            padding: 0 !important;
            color: #f8fafc !important;
            font-size: 1.05rem !important;
            font-weight: 700 !important;
            line-height: 1.2 !important;
            white-space: nowrap !important;
            writing-mode: horizontal-tb !important;
        }}
        div[data-testid="stMarkdownContainer"]:has(.range-grid-heading) {{
            margin: 0 0 0.35rem 0 !important;
        }}
        .range-grid-shell {{
            width: 100%;
            overflow-x: auto;
            padding-bottom: 0.15rem;
        }}
        div[data-testid="stMarkdownContainer"]:has(.range-grid-shell) {{
            margin: 0 !important;
        }}
        div[data-testid="stVerticalBlockBorderWrapper"]:has([class*="-range-cell-"]) {{
            overflow-x: auto !important;
            max-width: 100% !important;
        }}
        /* Grid rows only (not the page layout row). */
        div[data-testid="stHorizontalBlock"]:has([class*="-range-cell-"]):not(:has(.range-summary-panel)),
        div[data-testid="stHorizontalBlock"]:has(.range-grid-axis):not(:has(.range-summary-panel)) {{
            gap: 0.18rem !important;
            flex-wrap: nowrap !important;
            min-width: 46.5rem;
        }}
        div[data-testid="stHorizontalBlock"]:has([class*="-range-cell-"]):not(:has(.range-summary-panel)) > div,
        div[data-testid="stHorizontalBlock"]:has(.range-grid-axis):not(:has(.range-summary-panel)) > div {{
            min-width: 2.85rem !important;
            flex: 1 0 2.85rem !important;
        }}
        div[data-testid="stHorizontalBlock"]:has([class*="-range-cell-"]):not(:has(.range-summary-panel)) > div:first-child,
        div[data-testid="stHorizontalBlock"]:has(.range-grid-axis):not(:has(.range-summary-panel)) > div:first-child {{
            min-width: 1.55rem !important;
            flex: 0 0 1.55rem !important;
        }}
        .range-grid-axis {{
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 2rem;
            color: #cbd5e1;
            font-size: 0.78rem;
            font-weight: 700;
            line-height: 1;
            white-space: nowrap;
        }}
        [class*="-range-cell-"] {{
            display: flex !important;
            justify-content: center !important;
        }}
        [class*="-range-cell-"] button {{
            width: 100% !important;
            min-width: 2.85rem !important;
            min-height: 2.35rem !important;
            height: 2.35rem !important;
            padding: 0 0.2rem !important;
            font-size: 0.72rem !important;
            font-weight: 700 !important;
            letter-spacing: 0 !important;
            line-height: 1 !important;
            white-space: nowrap !important;
            word-break: keep-all !important;
            overflow-wrap: normal !important;
            overflow: hidden !important;
            text-overflow: clip !important;
            text-align: center !important;
        }}
        /* Selected range cells: muted pair / suited / offsuit colors. */
        [class*="-range-cell-pair-"] button[kind="primary"],
        [class*="-range-cell-pair-"] button[data-testid="baseButton-primary"],
        [class*="-range-cell-pair-"] button[data-testid="stBaseButton-primary"] {{
            background: #5a4a32 !important;
            background-color: #5a4a32 !important;
            border: 1px solid #6b5a3e !important;
            color: #d6c9ae !important;
        }}
        [class*="-range-cell-pair-"] button[kind="primary"]:hover,
        [class*="-range-cell-pair-"] button[data-testid="baseButton-primary"]:hover,
        [class*="-range-cell-pair-"] button[data-testid="stBaseButton-primary"]:hover {{
            background: #675640 !important;
            background-color: #675640 !important;
            border-color: #7a6848 !important;
            color: #e8dcc4 !important;
        }}
        [class*="-range-cell-suited-"] button[kind="primary"],
        [class*="-range-cell-suited-"] button[data-testid="baseButton-primary"],
        [class*="-range-cell-suited-"] button[data-testid="stBaseButton-primary"] {{
            background: #2a3f38 !important;
            background-color: #2a3f38 !important;
            border: 1px solid #355248 !important;
            color: #a9c4b6 !important;
        }}
        [class*="-range-cell-suited-"] button[kind="primary"]:hover,
        [class*="-range-cell-suited-"] button[data-testid="baseButton-primary"]:hover,
        [class*="-range-cell-suited-"] button[data-testid="stBaseButton-primary"]:hover {{
            background: #345048 !important;
            background-color: #345048 !important;
            border-color: #416557 !important;
            color: #bdd4c8 !important;
        }}
        [class*="-range-cell-offsuit-"] button[kind="primary"],
        [class*="-range-cell-offsuit-"] button[data-testid="baseButton-primary"],
        [class*="-range-cell-offsuit-"] button[data-testid="stBaseButton-primary"] {{
            background: #2c3848 !important;
            background-color: #2c3848 !important;
            border: 1px solid #3a4758 !important;
            color: #a9b8c9 !important;
        }}
        [class*="-range-cell-offsuit-"] button[kind="primary"]:hover,
        [class*="-range-cell-offsuit-"] button[data-testid="baseButton-primary"]:hover,
        [class*="-range-cell-offsuit-"] button[data-testid="stBaseButton-primary"]:hover {{
            background: #364557 !important;
            background-color: #364557 !important;
            border-color: #4a586a !important;
            color: #c0cddc !important;
        }}
        @media (max-width: 1100px) {{
            div[data-testid="stHorizontalBlock"]:has([class*="-range-cell-"]):has(.range-summary-panel) {{
                flex-direction: column !important;
            }}
            div[data-testid="stHorizontalBlock"]:has([class*="-range-cell-"]):has(.range-summary-panel) > div:first-child,
            div[data-testid="stHorizontalBlock"]:has([class*="-range-cell-"]):has(.range-summary-panel) > div:last-child {{
                flex: 1 1 auto !important;
                width: 100% !important;
                max-width: 100% !important;
                min-width: 100% !important;
            }}
            .range-summary-panel {{
                min-height: 0;
            }}
        }}
        .results-anchor {{
            scroll-margin-top: 5.5rem;
        }}
        /* —— Results page denser rhythm & analytics polish —— */
        .el-results-title {{
            margin: 0 0 0.45rem 0 !important;
        }}
        div[data-testid="stVerticalBlockBorderWrapper"]:has(.el-results-block) {{
            padding: 0.48rem 0.85rem 0.52rem !important;
            border-radius: 0.85rem !important;
            border-color: rgba(148, 163, 184, 0.22) !important;
            animation: elFadeUp 180ms ease-out;
        }}
        div[data-testid="stVerticalBlockBorderWrapper"]:has(.el-results-block) h3,
        div[data-testid="stVerticalBlockBorderWrapper"]:has(.el-results-block) .el-card-title {{
            margin: 0 0 0.35rem 0 !important;
            font-size: 1.12rem !important;
            font-weight: 700 !important;
            letter-spacing: -0.015em;
            color: #f1f5f9 !important;
        }}
        div[data-testid="stVerticalBlock"]:has(> div .el-results-title) {{
            gap: 0.55rem !important;
        }}
        div[data-testid="stExpander"]:has(.el-results-block) {{
            margin: 0.15rem 0 !important;
        }}
        .el-results-meta {{
            margin: 0.55rem 0 0.05rem 0 !important;
            color: #64748b !important;
            font-size: 0.72rem !important;
            font-weight: 550;
            line-height: 1.35;
            letter-spacing: 0.01em;
        }}
        .el-results-block {{
            margin: 0;
        }}
        .el-stat-row {{
            display: grid;
            gap: 0.55rem;
            width: 100%;
            margin: 0;
        }}
        .el-stat-row-3 {{ grid-template-columns: repeat(3, minmax(0, 1fr)); }}
        .el-stat-row-4 {{ grid-template-columns: repeat(4, minmax(0, 1fr)); }}
        .el-stat-row-5 {{ grid-template-columns: repeat(5, minmax(0, 1fr)); }}
        @media (max-width: 1100px) {{
            .el-stat-row-5 {{ grid-template-columns: repeat(3, minmax(0, 1fr)); }}
            .el-stat-row-4 {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
        }}
        @media (max-width: 720px) {{
            .el-stat-row-5,
            .el-stat-row-4,
            .el-stat-row-3 {{ grid-template-columns: 1fr 1fr; }}
        }}
        .el-stat-card {{
            display: flex;
            flex-direction: column;
            gap: 0.28rem;
            min-width: 0;
            padding: 0.65rem 0.7rem;
            border-radius: 0.65rem;
            border: 1px solid rgba(148, 163, 184, 0.2);
            background: rgba(15, 23, 42, 0.42);
            transition: transform 160ms ease, border-color 160ms ease, box-shadow 160ms ease;
        }}
        .el-stat-card:hover {{
            transform: translateY(-2px);
            border-color: rgba(148, 163, 184, 0.38);
            box-shadow: 0 8px 18px rgba(2, 6, 23, 0.32);
        }}
        .el-stat-label-row {{
            display: inline-flex;
            align-items: center;
            gap: 0.35rem;
        }}
        .el-stat-icon {{
            display: block;
            flex-shrink: 0;
            opacity: 0.9;
        }}
        .el-stat-label {{
            color: #64748b;
            font-size: 0.66rem;
            font-weight: 650;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            line-height: 1.2;
        }}
        .el-stat-value {{
            color: #f8fafc;
            font-size: 1.22rem;
            font-weight: 750;
            letter-spacing: -0.02em;
            line-height: 1.15;
            font-variant-numeric: tabular-nums;
        }}
        .el-stat-subtitle {{
            color: #64748b;
            font-size: 0.72rem;
            font-weight: 550;
            line-height: 1.25;
        }}
        .el-rec-pill {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            padding: 0.22rem 0.65rem;
            border-radius: 999px;
            font-size: 0.92rem;
            font-weight: 750;
            letter-spacing: 0.02em;
            line-height: 1.2;
        }}
        .el-rec-reveal {{
            animation: elRecSlide 180ms ease-out;
        }}
        @keyframes elRecSlide {{
            from {{ opacity: 0; transform: translateY(4px); }}
            to {{ opacity: 1; transform: translateY(0); }}
        }}
        .el-equity-summary .el-equity-bar {{
            margin-top: 0.1rem;
            margin-bottom: 0.15rem;
        }}
        .el-equity-stats {{
            display: grid;
            grid-template-columns: minmax(9.5rem, 1.15fr) minmax(0, 2fr);
            gap: 0.75rem;
            align-items: stretch;
            margin-top: 0.85rem;
        }}
        .el-equity-hero-stat {{
            display: flex;
            flex-direction: column;
            justify-content: center;
            gap: 0.22rem;
            padding: 0.7rem 0.8rem;
            border-radius: 0.65rem;
            border: 1px solid rgba(148, 163, 184, 0.2);
            background: rgba(15, 23, 42, 0.42);
            transition: transform 160ms ease, border-color 160ms ease, box-shadow 160ms ease;
        }}
        .el-equity-hero-stat:hover {{
            transform: translateY(-2px);
            border-color: rgba(148, 163, 184, 0.38);
            box-shadow: 0 8px 18px rgba(2, 6, 23, 0.32);
        }}
        .el-equity-hero-value {{
            color: #f8fafc;
            font-size: 2.15rem;
            font-weight: 800;
            letter-spacing: -0.035em;
            line-height: 1.05;
            font-variant-numeric: tabular-nums;
        }}
        .el-equity-hero-sub {{
            color: #86efac;
            font-size: 0.78rem;
            font-weight: 650;
            line-height: 1.3;
        }}
        .el-equity-hero-sub.el-eq-status-below {{
            color: #fda4af;
        }}
        .el-equity-hero-sub.el-eq-status-even {{
            color: #fde68a;
        }}
        .el-equity-wtl {{
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 0.55rem;
        }}
        .el-equity-wtl .el-stat-value {{
            font-size: 1.08rem;
        }}
        @media (max-width: 900px) {{
            .el-equity-stats {{
                grid-template-columns: 1fr;
            }}
        }}
        .hero-analysis-grid {{
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 0.4rem 0.85rem;
            margin: 0.05rem 0;
        }}
        @media (max-width: 720px) {{
            .hero-analysis-grid {{
                grid-template-columns: 1fr;
            }}
        }}
        .hero-grid-row {{
            display: grid;
            grid-template-columns: 7.2rem minmax(0, 1fr);
            gap: 0.45rem;
            align-items: center;
            min-width: 0;
            padding: 0.35rem 0.45rem;
            border-radius: 0.5rem;
            border: 1px solid rgba(148, 163, 184, 0.14);
            background: rgba(15, 23, 42, 0.28);
        }}
        .hero-grid-label {{
            color: #64748b;
            font-size: 0.66rem;
            font-weight: 650;
            letter-spacing: 0.07em;
            text-transform: uppercase;
            line-height: 1.2;
        }}
        .hero-grid-value {{
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            gap: 0.3rem;
            min-width: 0;
        }}
        .hero-grid-value .el-live-chip {{
            font-size: 0.78rem;
            padding: 0.22rem 0.48rem;
        }}
        .el-dist-table {{
            width: 100%;
            border-collapse: collapse;
            margin: 0.1rem 0 0.15rem 0;
        }}
        .el-dist-table th {{
            color: #64748b;
            font-size: 0.66rem;
            font-weight: 650;
            letter-spacing: 0.07em;
            text-transform: uppercase;
            text-align: left;
            padding: 0.28rem 0.55rem;
            border-bottom: 1px solid rgba(71, 85, 105, 0.45);
        }}
        .el-dist-table th:nth-child(2),
        .el-dist-table th:nth-child(3),
        .el-dist-table td.el-dist-num {{
            text-align: right;
        }}
        .el-dist-table td {{
            color: #e2e8f0;
            font-size: 0.88rem;
            font-weight: 600;
            padding: 0.4rem 0.55rem;
            border-bottom: 1px solid rgba(51, 65, 85, 0.4);
        }}
        .el-dist-table td.el-dist-num {{
            color: #a5f3fc;
            font-variant-numeric: tabular-nums;
            font-weight: 650;
        }}
        .el-dist-table tbody tr {{
            transition: background 150ms ease;
        }}
        .el-dist-table tbody tr:hover {{
            background: rgba(30, 41, 59, 0.45);
        }}
        [class*="st-key-heatmap-cell-"] button {{
            transition: transform 160ms ease, filter 160ms ease, box-shadow 160ms ease !important;
        }}
        [class*="st-key-heatmap-cell-"] button:hover:not(:disabled) {{
            transform: scale(1.07) !important;
            filter: brightness(1.12) saturate(1.08) !important;
            z-index: 3;
            position: relative;
        }}
        .decision-key-heading {{
            margin: 0.7rem 0 0.4rem 0;
        }}
        .decision-explanation,
        .texture-explanation {{
            color: #94a3b8;
        }}
        div[data-testid="stVerticalBlockBorderWrapper"] {{
            padding: 0.52rem 0.85rem 0.58rem !important;
            border-radius: 0.85rem !important;
        }}
        div[data-testid="stVerticalBlockBorderWrapper"] h3 {{
            margin: 0 0 0.08rem 0 !important;
            padding-top: 0 !important;
            font-size: 1.12rem !important;
        }}
        div[data-testid="stVerticalBlockBorderWrapper"]:has(.hero-hand-panel):not(:has(.el-board-panel)) {{
            padding: 0.38rem 0.95rem 0.4rem !important;
        }}
        div[data-testid="stVerticalBlockBorderWrapper"]:has(.el-board-panel) {{
            padding: 0.5rem 0.95rem 0.32rem !important;
        }}
        div[data-testid="stVerticalBlockBorderWrapper"]:has(.hero-hand-panel) h3,
        div[data-testid="stVerticalBlockBorderWrapper"]:has(.el-board-panel) h3 {{
            margin: 0 0 0.05rem 0 !important;
        }}
        .hero-hand-panel {{
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            width: 100%;
            margin: 0;
            padding: 0;
        }}
        /* Tighter hero copy → cards rhythm (Board panel has no section sub). */
        div[data-testid="stVerticalBlockBorderWrapper"]:has(.hero-hand-panel):not(:has(.el-board-panel)) .el-section-sub {{
            margin: 0 0 0.15rem 0 !important;
        }}
        div[data-testid="stHorizontalBlock"]:has(.st-key-hero-slot-0):not(:has(.st-key-board-slot-flop-0)):not(:has(.calc-summary-panel)) {{
            gap: 0.15rem !important;
            justify-content: center !important;
            margin: 0 auto !important;
        }}
        .poker-board-stack {{
            display: flex;
            flex-direction: column;
            align-items: center;
            width: 100%;
            margin: 0;
        }}
        .hero-selected-label {{
            margin: 0 !important;
            padding-top: 0.3rem;
            text-align: center;
            font-size: 0.86rem;
            color: #94a3b8;
            line-height: 1.2;
        }}
        .hero-selected-label strong {{
            color: #f8fafc;
            font-weight: 700;
            letter-spacing: 0.04em;
        }}
        .hero-selected-muted {{
            color: #64748b;
        }}
        .hero-selected-muted strong {{
            color: #64748b;
            font-weight: 600;
        }}
        .el-selected-hand {{
            margin: 0.06rem 0 0.02rem 0;
            text-align: center;
        }}
        .el-selected-hand-label {{
            margin: 0 0 0.08rem 0;
            color: #64748b;
            font-size: 0.62rem;
            font-weight: 700;
            letter-spacing: 0.11em;
            text-transform: uppercase;
        }}
        .el-selected-hand-value {{
            margin: 0;
            color: #ffffff;
            font-size: 1.38rem;
            font-weight: 800;
            letter-spacing: -0.02em;
            line-height: 1.12;
            text-shadow: 0 1px 12px rgba(251, 113, 133, 0.16);
        }}
        .el-selected-hand-muted .el-selected-hand-value {{
            color: #64748b;
            font-weight: 600;
            text-shadow: none;
        }}
        .el-best-hand {{
            display: flex;
            align-items: center;
            gap: 0.72rem;
            margin: 0.14rem auto 0.02rem auto;
            padding: 0.68rem 1.12rem 0.72rem 0.88rem;
            width: fit-content;
            max-width: 100%;
            text-align: center;
            border-radius: 0.9rem;
            border: 1px solid rgba(148, 163, 184, 0.12);
            background: linear-gradient(180deg, rgba(30, 41, 59, 0.42), rgba(15, 23, 42, 0.32));
            backdrop-filter: blur(16px) saturate(1.15);
            -webkit-backdrop-filter: blur(16px) saturate(1.15);
            box-shadow: 0 10px 24px rgba(2, 6, 23, 0.26), inset 0 1px 0 rgba(255, 255, 255, 0.06);
            animation: elBestHandIn 0.18s ease-out;
        }}
        @keyframes elBestHandIn {{
            from {{ opacity: 0; transform: translateY(4px); }}
            to {{ opacity: 1; transform: translateY(0); }}
        }}
        .el-best-hand-icon {{
            flex: 0 0 auto;
            width: 22px;
            height: 22px;
            opacity: 0.95;
        }}
        .el-best-hand-copy {{
            display: flex;
            flex-direction: column;
            align-items: center;
            min-width: 0;
            text-align: center;
        }}
        .el-best-hand-label {{
            margin: 0 0 0.08rem 0;
            color: #64748b;
            font-size: 0.6rem;
            font-weight: 700;
            letter-spacing: 0.1em;
            text-transform: uppercase;
            text-align: center;
        }}
        .el-best-hand-category {{
            margin: 0;
            color: #f8fafc;
            font-size: 1.14rem;
            font-weight: 750;
            letter-spacing: -0.015em;
            line-height: 1.15;
            text-align: center;
            transform: translateX(-0.28rem);
        }}
        .el-best-hand-detail {{
            margin: 0.12rem 0 0 0;
            color: #94a3b8;
            font-size: 0.76rem;
            font-weight: 550;
            line-height: 1.2;
            text-align: center;
            transform: translateX(-0.28rem);
        }}
        .el-best-hand-muted .el-best-hand-category {{
            color: #64748b;
            font-weight: 600;
        }}
        .el-section-heading {{
            display: flex !important;
            align-items: center;
            gap: 0.45rem;
            margin: 0 0 0.05rem 0 !important;
            padding: 0 !important;
            color: #f1f5f9 !important;
            font-size: 1.15rem !important;
            font-weight: 700 !important;
            letter-spacing: -0.015em !important;
            line-height: 1.25 !important;
        }}
        .el-section-heading-icon {{
            flex: 0 0 auto;
            width: 18px;
            height: 18px;
            opacity: 0.9;
        }}
        /* Hide Streamlit header anchor / chain-link affordance in Analyze panels. */
        div[data-testid="stVerticalBlockBorderWrapper"]:has(.hero-hand-panel) [data-testid="stHeaderActionElements"],
        div[data-testid="stVerticalBlockBorderWrapper"]:has(.el-board-panel) [data-testid="stHeaderActionElements"],
        div[data-testid="stVerticalBlockBorderWrapper"]:has(.hero-hand-panel) h3 a,
        div[data-testid="stVerticalBlockBorderWrapper"]:has(.el-board-panel) h3 a {{
            display: none !important;
        }}
        .st-key-clear-hero-cards button,
        .st-key-clear-board-cards button {{
            min-height: 1.85rem !important;
            min-width: 7.25rem !important;
            max-width: none !important;
            width: auto !important;
            margin: 0.35rem auto 0 auto !important;
            display: block !important;
            padding-left: 1.1rem !important;
            padding-right: 1.1rem !important;
            font-size: 0.8rem !important;
            font-weight: 600 !important;
            white-space: nowrap !important;
            background: rgba(30, 41, 59, 0.55) !important;
            border: 1px solid #334155 !important;
            color: #94a3b8 !important;
            transition: transform 0.17s ease, box-shadow 0.17s ease, border-color 0.17s ease,
                background 0.17s ease, color 0.17s ease !important;
        }}
        .st-key-clear-hero-cards button:hover:not(:disabled),
        .st-key-clear-board-cards button:hover:not(:disabled) {{
            transform: translateY(-1px) !important;
            border-color: #475569 !important;
            color: #cbd5e1 !important;
            background: rgba(51, 65, 85, 0.62) !important;
            box-shadow: 0 6px 14px rgba(2, 6, 23, 0.28) !important;
        }}
        .st-key-clear-hero-cards button:active:not(:disabled),
        .st-key-clear-board-cards button:active:not(:disabled) {{
            transform: translateY(1px) scale(0.98) !important;
            box-shadow: 0 2px 6px rgba(2, 6, 23, 0.22) !important;
        }}
        .st-key-clear-board-cards button {{
            margin-top: 0.1rem !important;
        }}
        .st-key-clear-hero-cards,
        .st-key-clear-board-cards {{
            display: flex !important;
            justify-content: center !important;
            align-items: center !important;
            width: 100% !important;
            min-width: 0 !important;
        }}
        .st-key-clear-hero-cards [data-testid="stButton"],
        .st-key-clear-board-cards [data-testid="stButton"],
        .st-key-clear-hero-cards .stButton,
        .st-key-clear-board-cards .stButton {{
            display: flex !important;
            justify-content: center !important;
            width: 100% !important;
        }}
        div[data-testid="stHorizontalBlock"]:has(.st-key-clear-hero-cards):not(:has(.calc-summary-panel)),
        div[data-testid="stHorizontalBlock"]:has(.st-key-clear-board-cards):not(:has(.calc-summary-panel)) {{
            justify-content: center !important;
        }}
        div[data-testid="stHorizontalBlock"]:has(.st-key-clear-hero-cards):not(:has(.calc-summary-panel)) > div[data-testid="stColumn"],
        div[data-testid="stHorizontalBlock"]:has(.st-key-clear-board-cards):not(:has(.calc-summary-panel)) > div[data-testid="stColumn"] {{
            display: flex !important;
            justify-content: center !important;
        }}
        div[data-testid="stElementContainer"]:has(.st-key-clear-board-cards),
        div[data-testid="stElementContainer"]:has(.st-key-clear-hero-cards) {{
            display: flex !important;
            justify-content: center !important;
            width: 100% !important;
        }}
        div[data-testid="stElementContainer"]:has(.st-key-clear-board-cards) {{
            margin-top: 0 !important;
        }}
        div[data-testid="stVerticalBlockBorderWrapper"]:has(.el-board-panel) [data-testid="stVerticalBlock"] {{
            gap: 0.28rem !important;
        }}
        .st-key-clear-hero-cards button:hover,
        .st-key-clear-board-cards button:hover {{
            border-color: #475569 !important;
            color: #cbd5e1 !important;
            background: rgba(30, 41, 59, 0.8) !important;
            transform: translateY(-1px) !important;
            box-shadow: 0 6px 14px rgba(2, 6, 23, 0.28) !important;
        }}
        .st-key-clear-hero-cards button:active,
        .st-key-clear-board-cards button:active {{
            transform: translateY(0) scale(0.98) !important;
            box-shadow: 0 2px 6px rgba(2, 6, 23, 0.22) !important;
        }}
        .st-key-calculate-equity-btn button:hover:not(:disabled) {{
            transform: translateY(-1px) !important;
            box-shadow: 0 0 0 1px rgba(251, 113, 133, 0.14), 0 14px 30px rgba(244, 63, 94, 0.4) !important;
        }}
        .st-key-calculate-equity-btn button:active:not(:disabled) {{
            transform: translateY(1px) scale(0.985) !important;
        }}
        .poker-card-row {{
            display: flex;
            gap: 0.75rem;
            align-items: center;
            justify-content: center;
        }}
        .hero-card-row {{
            margin: 0;
        }}
        @keyframes cardDealIn {{
            from {{
                opacity: 0;
                transform: translateY(8px) scale(0.98);
            }}
            to {{
                opacity: 1;
                transform: translateY(0) scale(1);
            }}
        }}
        @keyframes cardSelectIn {{
            from {{
                opacity: 0.55;
                transform: scale(0.88);
                filter: brightness(1.12);
            }}
            55% {{
                opacity: 1;
                transform: scale(1.03);
                filter: brightness(1.04);
            }}
            to {{
                opacity: 1;
                transform: scale(1);
                filter: brightness(1);
            }}
        }}
        .card-deal-in {{
            animation: cardDealIn 0.18s ease-out;
        }}
        .playing-card-face {{
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            gap: 0.28rem;
            width: {BOARD_CARD_WIDTH}px;
            height: {BOARD_CARD_HEIGHT}px;
            min-width: {BOARD_CARD_WIDTH}px;
            min-height: {BOARD_CARD_HEIGHT}px;
            box-sizing: border-box;
            border-radius: {CARD_RADIUS_PX}px;
            font-size: 1.75rem;
            font-weight: 800;
            line-height: 1;
            color: #ffffff;
            background: #0f172a;
            box-shadow: 0 10px 22px rgba(2, 6, 23, 0.4);
            transition: transform 0.18s ease, box-shadow 0.18s ease;
        }}
        .hero-card-face {{
            width: {HERO_CARD_WIDTH}px;
            height: {HERO_CARD_HEIGHT}px;
            min-width: {HERO_CARD_WIDTH}px;
            min-height: {HERO_CARD_HEIGHT}px;
            font-size: 2.3rem;
            box-shadow: 0 12px 26px rgba(2, 6, 23, 0.42);
        }}
        .hero-card-face .playing-card-rank {{
            font-size: 2.3rem;
        }}
        .hero-card-face .playing-card-caption {{
            font-size: 0.9rem;
        }}
        .playing-card-rank {{
            font-size: 1.75rem;
            line-height: 1;
        }}
        .playing-card-caption {{
            font-size: 0.74rem;
            font-weight: 700;
            opacity: 0.92;
        }}
        .playing-card-empty {{
            display: flex;
            align-items: center;
            justify-content: center;
            width: {BOARD_CARD_WIDTH}px;
            height: {BOARD_CARD_HEIGHT}px;
            min-width: {BOARD_CARD_WIDTH}px;
            min-height: {BOARD_CARD_HEIGHT}px;
            box-sizing: border-box;
            border-radius: {CARD_RADIUS_PX}px;
            border: 1.5px dashed rgba(71, 85, 105, 0.5);
            background: linear-gradient(180deg, rgba(15, 23, 42, 0.92), rgba(2, 6, 23, 0.98));
            box-shadow: inset 0 1px 0 rgba(255,255,255,0.03), 0 8px 16px rgba(2, 6, 23, 0.28);
        }}
        .hero-card-slot-idle {{
            width: {HERO_CARD_WIDTH}px;
            height: {HERO_CARD_HEIGHT}px;
            min-width: {HERO_CARD_WIDTH}px;
            min-height: {HERO_CARD_HEIGHT}px;
            box-sizing: border-box;
            border-radius: {CARD_RADIUS_PX}px;
            border: 1.5px dashed rgba(71, 85, 105, 0.5);
            background: linear-gradient(180deg, rgba(15, 23, 42, 0.92), rgba(2, 6, 23, 0.98));
        }}
        .el-board {{
            width: 100%;
            max-width: {BOARD_ROW_MAX_WIDTH_REM}rem;
            margin: 0 auto;
        }}
        .el-board-labels {{
            display: grid;
            grid-template-columns:
                minmax(calc({BOARD_CARD_WIDTH}px * 3 + 0.48rem), auto)
                minmax(0.28rem, 0.42fr)
                {BOARD_CARD_WIDTH}px
                minmax(0.28rem, 0.42fr)
                {BOARD_CARD_WIDTH}px;
            justify-content: center;
            align-items: end;
            width: 100%;
            margin: 0 auto 0.1rem auto;
            column-gap: 0.22rem;
        }}
        .el-board-label {{
            margin: 0;
            color: #94a3b8;
            font-size: {BOARD_LABEL_FONT_REM}rem;
            font-weight: 700;
            letter-spacing: 0.1em;
            text-indent: 0.1em;
            text-transform: uppercase;
            line-height: 1.05;
            text-align: center;
            pointer-events: none;
        }}
        .el-board-label--flop {{
            grid-column: 1;
        }}
        .el-board-gap {{
            min-width: 0;
        }}
        .el-board-cards-anchor {{
            display: none;
        }}
        /* Flat board row only — exclude Analyze page layout ancestors that also contain board slots. */
        div[data-testid="stHorizontalBlock"]:has(.st-key-board-slot-flop-0):not(:has(.st-key-hero-slot-0)):not(:has(.calc-summary-panel)) {{
            display: grid !important;
            grid-template-columns: repeat(3, max-content) minmax(0.28rem, 0.42fr) max-content minmax(0.28rem, 0.42fr) max-content !important;
            justify-content: center !important;
            align-items: end !important;
            gap: 0.22rem !important;
            flex-wrap: nowrap !important;
            width: 100% !important;
            max-width: {BOARD_ROW_MAX_WIDTH_REM}rem !important;
            margin-left: auto !important;
            margin-right: auto !important;
        }}
        div[data-testid="stHorizontalBlock"]:has(.st-key-board-slot-flop-0):not(:has(.st-key-hero-slot-0)):not(:has(.calc-summary-panel)) > div[data-testid="stColumn"] {{
            width: auto !important;
            min-width: 0 !important;
            flex: none !important;
        }}
        /* Spacer columns stay empty and do not stretch cards. */
        div[data-testid="stHorizontalBlock"]:has(.st-key-board-slot-flop-0):not(:has(.st-key-hero-slot-0)):not(:has(.calc-summary-panel)) > div[data-testid="stColumn"]:nth-child(4),
        div[data-testid="stHorizontalBlock"]:has(.st-key-board-slot-flop-0):not(:has(.st-key-hero-slot-0)):not(:has(.calc-summary-panel)) > div[data-testid="stColumn"]:nth-child(6) {{
            min-width: 0.55rem !important;
            pointer-events: none;
        }}
        div[data-testid="stMarkdownContainer"]:has(.el-board) {{
            margin-bottom: 0 !important;
        }}
        div[data-testid="stMarkdownContainer"]:has(.el-best-hand) {{
            margin-top: 0 !important;
            margin-bottom: 0 !important;
        }}
        div[data-testid="stMarkdownContainer"]:has(.el-selected-hand) {{
            margin-top: 0 !important;
            margin-bottom: 0 !important;
        }}
        @media (max-width: 640px) {{
            .el-board,
            div[data-testid="stHorizontalBlock"]:has(.st-key-board-slot-flop-0):not(:has(.st-key-hero-slot-0)):not(:has(.calc-summary-panel)) {{
                max-width: 100% !important;
            }}
            .el-board-labels {{
                grid-template-columns: minmax(0, 3fr) minmax(0, 1fr) minmax(0, 1fr);
                grid-template-rows: auto auto;
                row-gap: 0.35rem;
                column-gap: 0.45rem;
            }}
            .el-board-labels .el-board-gap {{
                display: none;
            }}
            .el-board-label--flop {{
                grid-column: 1 / -1;
            }}
            div[data-testid="stHorizontalBlock"]:has(.st-key-board-slot-flop-0):not(:has(.st-key-hero-slot-0)):not(:has(.calc-summary-panel)) {{
                display: grid !important;
                grid-template-columns: repeat(3, max-content) !important;
                grid-template-rows: auto auto !important;
                justify-content: center !important;
                column-gap: 0.28rem !important;
                row-gap: 0.55rem !important;
            }}
            div[data-testid="stHorizontalBlock"]:has(.st-key-board-slot-flop-0):not(:has(.st-key-hero-slot-0)):not(:has(.calc-summary-panel)) > div[data-testid="stColumn"]:nth-child(4),
            div[data-testid="stHorizontalBlock"]:has(.st-key-board-slot-flop-0):not(:has(.st-key-hero-slot-0)):not(:has(.calc-summary-panel)) > div[data-testid="stColumn"]:nth-child(6) {{
                display: none !important;
            }}
            div[data-testid="stHorizontalBlock"]:has(.st-key-board-slot-flop-0):not(:has(.st-key-hero-slot-0)):not(:has(.calc-summary-panel)) > div[data-testid="stColumn"]:nth-child(5) {{
                grid-column: 1 / 2;
                grid-row: 2;
                justify-self: end;
            }}
            div[data-testid="stHorizontalBlock"]:has(.st-key-board-slot-flop-0):not(:has(.st-key-hero-slot-0)):not(:has(.calc-summary-panel)) > div[data-testid="stColumn"]:nth-child(7) {{
                grid-column: 3 / 4;
                grid-row: 2;
                justify-self: start;
            }}
        }}
        [class*="st-key-hero-slot-"],
        [class*="st-key-board-slot-"] {{
            display: flex !important;
            justify-content: center !important;
            width: 100% !important;
        }}
        [class*="st-key-board-slot-"] .stButton,
        [class*="st-key-board-slot-"] [data-testid="stButton"] {{
            width: auto !important;
            margin-left: auto !important;
            margin-right: auto !important;
            display: flex !important;
            justify-content: center !important;
        }}
        [class*="st-key-board-slot-flop-"],
        .st-key-board-slot-turn-0,
        .st-key-board-slot-river-0 {{
            flex-direction: column !important;
            align-items: center !important;
            justify-content: flex-end !important;
            width: {BOARD_CARD_WIDTH}px !important;
            min-width: {BOARD_CARD_WIDTH}px !important;
            max-width: {BOARD_CARD_WIDTH}px !important;
            margin: 0 !important;
        }}
        div[data-testid="stMarkdownContainer"]:has(.hero-hand-panel) {{
            margin-bottom: 0 !important;
        }}
        {_hero_slot_button_styles()}
        {_board_slot_button_styles()}
        {_card_picker_styles()}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _filled_slot_button_css(selector: str, rank: str, suit: str, *, width: int, height: int) -> str:
    """CSS for a filled hero/board slot — suit gradient face with soft depth."""
    del width, height, rank  # Size comes from slot button rules; rank shown via button label.
    colors = SUIT_STYLES[suit]
    return (
        f"{selector} {{"
        f"background: {colors['gradient']} !important;"
        f"background-image: {colors['gradient']} !important;"
        f"border: 1.5px solid {colors['selected_border']} !important;"
        f"border-radius: {CARD_RADIUS_PX}px !important;"
        f"color: #ffffff !important;"
        f"text-shadow: 0 1px 2px rgba(2, 6, 23, 0.35) !important;"
        f"box-shadow: {colors['selected_glow']}, "
        f"0 10px 22px rgba(2, 6, 23, 0.4), "
        f"inset 0 1px 0 rgba(255, 255, 255, 0.22), "
        f"inset 0 -2px 6px rgba(2, 6, 23, 0.28) !important;"
        f"animation: cardSelectIn 0.26s cubic-bezier(0.22, 1, 0.36, 1) !important;"
        f"transition: transform 0.2s cubic-bezier(0.22, 1, 0.36, 1), box-shadow 0.22s ease, "
        f"border-color 0.2s ease, filter 0.2s ease !important;"
        f"}}"
        f"{selector}:hover:not(:disabled) {{"
        f"transform: translateY(-3px) !important;"
        f"filter: brightness(1.05);"
        f"box-shadow: {colors['selected_glow']}, "
        f"0 14px 26px rgba(2, 6, 23, 0.46), "
        f"inset 0 1px 0 rgba(255, 255, 255, 0.26), "
        f"inset 0 -2px 6px rgba(2, 6, 23, 0.3) !important;"
        f"}}"
        f"{selector}:active:not(:disabled) {{"
        f"transform: translateY(-1px) scale(0.99) !important;"
        f"}}"
    )


def _hero_slot_button_styles() -> str:
    rules = [
        f"""
        [class*="st-key-hero-slot-"] button {{
            width: {HERO_CARD_WIDTH}px !important;
            min-width: {HERO_CARD_WIDTH}px !important;
            height: {HERO_CARD_HEIGHT}px !important;
            min-height: {HERO_CARD_HEIGHT}px !important;
            padding: 0 !important;
            border-radius: {CARD_RADIUS_PX}px !important;
            font-size: 2.7rem !important;
            font-weight: 800 !important;
            line-height: 1 !important;
            letter-spacing: -0.02em !important;
            transition: transform 0.17s ease, box-shadow 0.17s ease, border-color 0.17s ease, background 0.17s ease, filter 0.17s ease !important;
        }}
        [class*="st-key-hero-slot-"] button:disabled {{
            opacity: 0.45 !important;
            cursor: default !important;
            transform: none !important;
        }}
        """
    ]

    for index in range(2):
        key = f"hero-slot-{index}"
        slots = st.session_state.get("hero_slot_cards", [None, None])
        selector = f".st-key-{key} button"
        card_key = slots[index] if index < len(slots) else None
        if card_key:
            rank, suit = _split_card_key(card_key)
            rules.append(
                _filled_slot_button_css(
                    selector, rank, suit, width=HERO_CARD_WIDTH, height=HERO_CARD_HEIGHT
                )
            )
        else:
            empty_icon = (
                "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' "
                "viewBox='0 0 40 48' fill='none'%3E%3Crect x='8' y='6' width='24' height='34' "
                "rx='3.5' stroke='%2364748b' stroke-width='1.35'/%3E%3Cpath d='M26 10 L28 12 L30 10' "
                "stroke='%2364748b' stroke-width='1.2' stroke-linecap='round' stroke-linejoin='round'/%3E"
                "%3C/svg%3E\")"
            )
            rules.append(
                f"{selector} {{"
                f"display: flex !important;"
                f"flex-direction: column !important;"
                f"align-items: center !important;"
                f"justify-content: center !important;"
                f"gap: 0.55rem !important;"
                f"background: linear-gradient(180deg, rgba(15,23,42,0.92), rgba(2,6,23,0.98)) !important;"
                f"border: 1.5px dashed rgba(71, 85, 105, 0.55) !important;"
                f"border-radius: {CARD_RADIUS_PX}px !important;"
                f"color: #64748b !important;"
                f"font-size: 0.78rem !important;"
                f"font-weight: 500 !important;"
                f"white-space: normal !important;"
                f"line-height: 1.2 !important;"
                f"box-shadow: inset 0 1px 0 rgba(255,255,255,0.03), 0 8px 16px rgba(2, 6, 23, 0.28) !important;"
                f"transition: transform 0.17s ease, box-shadow 0.17s ease, border-color 0.17s ease, background 0.17s ease !important;"
                f"}}"
            )
            rules.append(
                f"{selector}::before {{"
                f'content: "" !important;'
                f"display: block !important;"
                f"width: 2.2rem !important;"
                f"height: 2.65rem !important;"
                f"background-image: {empty_icon} !important;"
                f"background-repeat: no-repeat !important;"
                f"background-position: center !important;"
                f"background-size: contain !important;"
                f"}}"
            )
            rules.append(
                f"{selector}:hover:not(:disabled) {{"
                f"transform: translateY(-3px) !important;"
                f"border-color: rgba(148, 163, 184, 0.55) !important;"
                f"color: #94a3b8 !important;"
                f"background: linear-gradient(180deg, rgba(30,41,59,0.88), rgba(15,23,42,0.96)) !important;"
                f"box-shadow: inset 0 1px 0 rgba(255,255,255,0.05), 0 12px 22px rgba(2, 6, 23, 0.34) !important;"
                f"}}"
            )

    return "\n".join(rules)


def _board_slot_button_styles() -> str:
    slot_defs = [
        ("selected_flop_cards", 0, "flop"),
        ("selected_flop_cards", 1, "flop"),
        ("selected_flop_cards", 2, "flop"),
        ("selected_turn_card", 0, "turn"),
        ("selected_river_card", 0, "river"),
    ]
    rules = [
        f"""
        [class*="st-key-board-slot-"] button {{
            width: {BOARD_CARD_WIDTH}px !important;
            min-width: {BOARD_CARD_WIDTH}px !important;
            height: {BOARD_CARD_HEIGHT}px !important;
            min-height: {BOARD_CARD_HEIGHT}px !important;
            padding: 0 !important;
            border-radius: {CARD_RADIUS_PX}px !important;
            font-size: 2.05rem !important;
            font-weight: 800 !important;
            line-height: 1 !important;
            letter-spacing: -0.02em !important;
            transition: transform 0.2s cubic-bezier(0.22, 1, 0.36, 1), box-shadow 0.22s ease,
                border-color 0.2s ease, background 0.2s ease, filter 0.2s ease !important;
        }}
        [class*="st-key-board-slot-"] button:disabled {{
            opacity: 0.45 !important;
            cursor: default !important;
            transform: none !important;
        }}
        """
    ]

    for state_key, index, stage_key in slot_defs:
        key = f"board-slot-{stage_key}-{index}"
        selector = f".st-key-{key} button"
        if state_key == "selected_flop_cards":
            slots = st.session_state.get("flop_slot_cards", [None, None, None])
            card_key = slots[index] if index < len(slots) else None
        elif state_key == "selected_turn_card":
            card_key = st.session_state.get("turn_slot_card")
        else:
            card_key = st.session_state.get("river_slot_card")
        if card_key:
            rank, suit = _split_card_key(card_key)
            rules.append(
                _filled_slot_button_css(
                    selector, rank, suit, width=BOARD_CARD_WIDTH, height=BOARD_CARD_HEIGHT
                )
            )
        else:
            rules.append(
                f"{selector} {{"
                f"background: linear-gradient(180deg, rgba(15,23,42,0.92), rgba(2,6,23,0.98)) !important;"
                f"border: 1.5px dashed rgba(71, 85, 105, 0.5) !important;"
                f"border-radius: {CARD_RADIUS_PX}px !important;"
                f"color: #64748b !important;"
                f"font-size: 0.62rem !important;"
                f"font-weight: 600 !important;"
                f"white-space: normal !important;"
                f"line-height: 1.1 !important;"
                f"box-shadow: inset 0 1px 0 rgba(255,255,255,0.03), 0 8px 16px rgba(2, 6, 23, 0.28) !important;"
                f"transition: transform 0.17s ease, box-shadow 0.17s ease, border-color 0.17s ease, background 0.17s ease !important;"
                f"}}"
            )
            rules.append(
                f"{selector}:hover:not(:disabled) {{"
                f"transform: translateY(-3px) !important;"
                f"border-color: rgba(148, 163, 184, 0.5) !important;"
                f"color: #94a3b8 !important;"
                f"background: linear-gradient(180deg, rgba(30,41,59,0.88), rgba(15,23,42,0.96)) !important;"
                f"box-shadow: inset 0 1px 0 rgba(255,255,255,0.05), 0 12px 22px rgba(2, 6, 23, 0.34) !important;"
                f"}}"
            )

    return "\n".join(rules)


def _card_picker_styles() -> str:
    rules: list[str] = []

    for prefix in ("hero", "board", "hero-dialog", "board-dialog"):
        for suit, colors in SUIT_STYLES.items():
            selected_selectors = [
                f'.st-key-{prefix}-card-{rank}{suit} button[kind="primary"]' for rank in RANGE_RANKS
            ]
            unselected_selectors = [
                f'.st-key-{prefix}-card-{rank}{suit} button[kind="secondary"]:not(:disabled)' for rank in RANGE_RANKS
            ]
            selected_style = (
                f"background: {colors['gradient']} !important;"
                f"border: 1.5px solid {colors['selected_border']} !important;"
                f"color: #ffffff !important;"
                f"box-shadow: {colors['selected_glow']}, inset 0 1px 0 rgba(255,255,255,0.18) !important;"
                f"animation: cardSelectIn 0.26s cubic-bezier(0.22, 1, 0.36, 1) !important;"
                f"transition: transform 0.2s cubic-bezier(0.22, 1, 0.36, 1), "
                f"box-shadow 0.22s ease, filter 0.2s ease !important;"
            )
            rules.append(f"{','.join(selected_selectors)} {{{selected_style}}}")
            rules.append(
                f"{','.join(unselected_selectors)} {{"
                f"color: {colors['text']} !important;"
                f"border: 1px solid {colors['border']} !important;"
                f"}}"
            )

    return "\n".join(rules)


@contextmanager
def _dashboard_card(title: str):
    with st.container(border=True):
        st.markdown(f'<h3 class="el-card-title">{escape(title)}</h3>', unsafe_allow_html=True)
        yield


def _toggle_hero_card(card_key: str) -> None:
    slots = list(_hero_slot_values())
    st.session_state.active_quick_example = None
    if card_key in slots:
        slots = [None if card == card_key else card for card in slots]
        st.session_state.hero_slot_cards = slots
        _sync_hero_cards_from_slots()
        st.session_state.active_hero_slot = _first_empty_hero_slot()
        return

    if card_key in set(_selected_board_cards()):
        return

    active_slot = _validated_active_hero_slot() or _first_empty_hero_slot()
    if active_slot is None or slots[active_slot] is not None:
        return

    slots[active_slot] = card_key
    st.session_state.hero_slot_cards = slots
    _sync_hero_cards_from_slots()
    st.session_state.active_hero_slot = _first_empty_hero_slot()


def _toggle_card(selection_key: str, card_key: str, max_cards: int) -> None:
    selected = list(st.session_state[selection_key])
    if card_key in selected:
        selected.remove(card_key)
    elif len(selected) < max_cards:
        selected.append(card_key)
    st.session_state[selection_key] = selected


def _toggle_board_card(card_key: str) -> None:
    existing_slot = _find_board_card_slot(card_key)
    if existing_slot:
        _remove_board_slot(*existing_slot)
        return

    active_slot = _validated_active_board_slot() or _first_empty_board_slot()
    if not active_slot:
        return

    state_key, raw_index = active_slot.split(":")
    index = int(raw_index)

    if state_key == "selected_flop_cards":
        hero_cards = {card for card in _hero_slot_values() if card}
        if card_key in hero_cards:
            return
        slots = list(_flop_slot_values())
        if slots[index] is not None:
            return
        slots[index] = card_key
        st.session_state.flop_slot_cards = slots
        _sync_flop_cards_from_slots()
    elif state_key == "selected_turn_card":
        if not _can_select_board_slot(state_key, index) or _turn_slot_value() is not None:
            return
        st.session_state.turn_slot_card = card_key
        _sync_turn_from_slot()
    elif state_key == "selected_river_card":
        if not _can_select_board_slot(state_key, index) or _river_slot_value() is not None:
            return
        st.session_state.river_slot_card = card_key
        _sync_river_from_slot()

    st.session_state.active_board_slot = _first_empty_board_slot()


def _validated_active_hero_slot() -> int | None:
    active_slot = st.session_state.active_hero_slot
    if active_slot is None:
        return None

    slots = _hero_slot_values()
    if 0 <= active_slot < len(slots) and slots[active_slot] is None:
        return active_slot

    return None


def _first_empty_hero_slot() -> int | None:
    for index, card_key in enumerate(_hero_slot_values()):
        if card_key is None:
            return index
    return None


def _remove_hero_slot(index: int) -> None:
    slots = list(_hero_slot_values())
    if 0 <= index < len(slots):
        slots[index] = None
        st.session_state.hero_slot_cards = slots
        _sync_hero_cards_from_slots()
    st.session_state.active_hero_slot = _first_empty_hero_slot()
    st.session_state.active_quick_example = None


def _validated_active_board_slot() -> str | None:
    active_slot = st.session_state.active_board_slot
    if not active_slot:
        return None

    state_key, raw_index = active_slot.split(":")
    index = int(raw_index)
    if _board_slot_card(state_key, index) is None and _can_select_board_slot(state_key, index):
        return active_slot

    st.session_state.active_board_slot = None
    return None


def _first_empty_board_slot() -> str | None:
    for index, card_key in enumerate(_flop_slot_values()):
        if card_key is None:
            return f"selected_flop_cards:{index}"

    if _turn_slot_value() is None:
        return "selected_turn_card:0"

    if _river_slot_value() is None:
        return "selected_river_card:0"

    return None


def _find_board_card_slot(card_key: str) -> tuple[str, int] | None:
    for index, slot_card in enumerate(_flop_slot_values()):
        if slot_card == card_key:
            return "selected_flop_cards", index

    if _turn_slot_value() == card_key:
        return "selected_turn_card", 0

    if _river_slot_value() == card_key:
        return "selected_river_card", 0

    return None


def _remove_board_slot(state_key: str, index: int) -> None:
    if state_key == "selected_flop_cards":
        slots = list(_flop_slot_values())
        if 0 <= index < len(slots):
            slots[index] = None
            st.session_state.flop_slot_cards = slots
            _sync_flop_cards_from_slots()
    elif state_key == "selected_turn_card":
        st.session_state.turn_slot_card = None
        _sync_turn_from_slot()
    elif state_key == "selected_river_card":
        st.session_state.river_slot_card = None
        _sync_river_from_slot()

    _enforce_board_street_order()
    st.session_state.active_board_slot = _first_empty_board_slot()


def _clear_hero_cards() -> None:
    st.session_state.hero_slot_cards = [None, None]
    st.session_state.selected_hero_cards = []
    st.session_state.active_hero_slot = None
    st.session_state.active_quick_example = None


def _clear_flop_cards() -> None:
    st.session_state.flop_slot_cards = [None, None, None]
    st.session_state.selected_flop_cards = []
    st.session_state.active_board_slot = _first_empty_board_slot()


def _clear_turn_card() -> None:
    st.session_state.turn_slot_card = None
    st.session_state.selected_turn_card = []
    st.session_state.active_board_slot = _first_empty_board_slot()


def _clear_river_card() -> None:
    st.session_state.river_slot_card = None
    st.session_state.selected_river_card = []
    st.session_state.active_board_slot = _first_empty_board_slot()


def _clear_board_cards() -> None:
    st.session_state.flop_slot_cards = [None, None, None]
    st.session_state.selected_flop_cards = []
    st.session_state.turn_slot_card = None
    st.session_state.selected_turn_card = []
    st.session_state.river_slot_card = None
    st.session_state.selected_river_card = []
    st.session_state.active_board_slot = None


def _clear_range(ns: str = RANGE_NS_OPPONENT) -> None:
    _set_range_weights(ns, {})


def _select_hand_group(ns: str, hands: list[str]) -> None:
    weights = dict(_get_range_weights(ns))
    for hand in hands:
        weights.setdefault(hand, 100)
    _set_range_weights(ns, weights)


def _snapshot_calculator_settings() -> None:
    """Persist calculator widget values in non-widget keys so tab switches don't reset them."""
    if "calc_pot_size" in st.session_state:
        st.session_state["_calc_pot_size"] = float(st.session_state.calc_pot_size)
    if "calc_call_amount" in st.session_state:
        st.session_state["_calc_call_amount"] = float(st.session_state.calc_call_amount)
    if "calc_simulations" in st.session_state:
        st.session_state["_calc_simulations"] = int(st.session_state.calc_simulations)
    if "calc_opponent_range" in st.session_state:
        st.session_state["_calc_opponent_range"] = st.session_state.calc_opponent_range


def _restore_calculator_settings(*, preserve_opponent_range: bool = False) -> None:
    """Restore calculator inputs from the durable snapshot."""
    if "_calc_pot_size" in st.session_state:
        pot = float(st.session_state["_calc_pot_size"])
        call = float(st.session_state.get("_calc_call_amount", DEFAULT_CALL_AMOUNT))
        if pot == 0.0 and call == 0.0:
            pot, call = DEFAULT_POT_SIZE, DEFAULT_CALL_AMOUNT
        st.session_state.calc_pot_size = pot
        st.session_state.calc_call_amount = call
        st.session_state["calc_pot_size__input"] = pot
        st.session_state["calc_call_amount__input"] = call
    elif "_calc_call_amount" in st.session_state:
        st.session_state.calc_call_amount = float(st.session_state["_calc_call_amount"])
        st.session_state["calc_call_amount__input"] = float(st.session_state.calc_call_amount)
    if "_calc_simulations" in st.session_state:
        st.session_state.calc_simulations = _normalize_monte_carlo_trials(
            st.session_state["_calc_simulations"]
        )
    if not preserve_opponent_range and "_calc_opponent_range" in st.session_state:
        st.session_state.calc_opponent_range = st.session_state["_calc_opponent_range"]


def _use_range_in_calculator() -> None:
    if not _range_hands(RANGE_NS_OPPONENT):
        return
    # Restore pot/call/trials from the Edit Range snapshot; only opponent range updates.
    _restore_calculator_settings(preserve_opponent_range=True)
    st.session_state.calc_opponent_range = "Custom"
    st.session_state["_calc_opponent_range"] = "Custom"
    st.session_state.active_tab = TAB_ANALYZE
    st.session_state.latest_analysis = None
    st.session_state.scroll_to_results = False


def _edit_custom_range() -> None:
    """Open Ranges with the current Custom range loaded in the grid."""
    _snapshot_calculator_settings()
    st.session_state.calc_opponent_range = "Custom"
    st.session_state["_calc_opponent_range"] = "Custom"
    st.session_state.active_tab = TAB_RANGES
    st.session_state.scroll_to_results = False


def _on_range_cell_click(ns: str, hand: str) -> None:
    weights = dict(_get_range_weights(ns))
    editor_key = _range_editor_hand_key(ns)
    if hand not in weights:
        weights[hand] = 100
        _set_range_weights(ns, weights)
        st.session_state[editor_key] = None
        return
    st.session_state[editor_key] = hand


def _toggle_hand(hand: str) -> None:
    # Backward-compatible alias used by older callbacks.
    _on_range_cell_click(RANGE_NS_OPPONENT, hand)


def _toggle_hand_group(hands: list[str]) -> None:
    weights = dict(_get_range_weights(RANGE_NS_OPPONENT))
    selected = set(weights)
    if set(hands).issubset(selected):
        for hand in hands:
            weights.pop(hand, None)
    else:
        for hand in hands:
            weights.setdefault(hand, 100)
    _set_range_weights(RANGE_NS_OPPONENT, weights)


def _live_board_analysis_payload(
    hero_keys: list[str] | list[str | None],
    board_keys: list[str],
) -> dict[str, str | None]:
    """Pure payload for compact live board analysis (testable without Streamlit)."""
    if len(board_keys) == 0:
        return {
            "made_hand": None,
            "primary_draw": None,
            "texture": "Preflop",
            "texture_detail": "No community cards yet.",
        }
    if len(board_keys) < 3:
        return {
            "made_hand": None,
            "primary_draw": None,
            "texture": None,
            "texture_detail": "Complete the flop to analyze board texture.",
        }

    board = parse_cards(" ".join(board_keys))
    texture = analyze_board_texture(board)
    texture_label = ", ".join(texture.labels) if texture.labels else "Standard board"
    payload: dict[str, str | None] = {
        "made_hand": None,
        "primary_draw": None,
        "texture": texture_label,
        "texture_detail": texture.explanation,
    }

    if len(hero_keys) == 2 and hero_keys[0] and hero_keys[1]:
        hero = parse_cards(f"{hero_keys[0]} {hero_keys[1]}", expected_count=2)
        made = describe_hand(evaluate_best_hand([*hero, *board]))
        category, detail = _split_made_hand_label(made)
        payload["made_hand"] = f"{category}, {detail}" if detail else category
        situation = analyze_hero_situation(hero, board)
        primary, _secondary = _split_hero_draws(situation.draws)
        if primary:
            payload["primary_draw"] = primary[0]
    return payload


def _live_board_analysis_html() -> str:
    hero_slots = _hero_slot_values()
    board_keys = _selected_board_cards()
    try:
        data = _live_board_analysis_payload(hero_slots, board_keys)
    except ValueError:
        data = {
            "made_hand": None,
            "primary_draw": None,
            "texture": None,
            "texture_detail": "Unable to analyze the current board.",
        }

    made = data.get("made_hand")
    draw = data.get("primary_draw")
    texture = data.get("texture")
    detail = data.get("texture_detail") or ""
    muted = " el-live-board-muted" if not made and not draw else ""

    made_chips = ""
    if made and made != "—":
        if ", " in made:
            category, detail_chip = made.split(", ", 1)
        else:
            category, detail_chip = made, ""
        trophy = _lucide_icon_data_uri("trophy", size=14, stroke="#fbbf24")
        made_chips = (
            f'<span class="el-live-chip el-live-chip-hand">'
            f'<img src="{trophy}" alt="" width="14" height="14"/>'
            f"{escape(category)}</span>"
        )
        if detail_chip:
            made_chips += (
                f'<span class="el-live-chip el-live-chip-detail">'
                f"{escape(_chip_high_label(detail_chip))}</span>"
            )
    else:
        made_chips = '<span class="el-live-chip el-live-chip-empty">—</span>'

    if draw:
        draw_chips = f'<span class="el-live-chip el-live-chip-draw">{escape(str(draw))}</span>'
    else:
        draw_chips = '<span class="el-live-chip el-live-chip-empty">—</span>'

    if texture and texture != "—":
        texture_chips = "".join(
            f'<span class="el-live-chip el-live-chip-texture">{escape(part.strip())}</span>'
            for part in str(texture).split(",")
            if part.strip()
        )
    else:
        texture_chips = '<span class="el-live-chip el-live-chip-empty">—</span>'

    detail_html = (
        f'<div class="el-live-board-texture-detail">{escape(detail)}</div>' if detail else ""
    )
    return f"""
    <div class="el-live-board el-best-hand-panel{muted}">
      <div class="el-live-board-block el-best-hand-block">
        <div class="el-live-board-label">Best Hand</div>
        <div class="el-live-chip-row">{made_chips}</div>
      </div>
      <div class="el-live-board-block el-best-hand-block">
        <div class="el-live-board-label">Draw</div>
        <div class="el-live-chip-row">{draw_chips}</div>
      </div>
      <div class="el-live-board-block el-best-hand-block">
        <div class="el-live-board-label">Board Texture</div>
        <div class="el-live-chip-row">{texture_chips}</div>
      </div>
      {detail_html}
    </div>
    """


def _hero_made_hand_label() -> str | None:
    slots = _hero_slot_values()
    if slots[0] is None or slots[1] is None:
        return None
    if None in _flop_slot_values():
        return None

    card_text = " ".join([*st.session_state.selected_hero_cards, *_selected_board_cards()])
    try:
        cards = parse_cards(card_text)
        return describe_hand(evaluate_best_hand(cards))
    except ValueError:
        return None


_RANK_DISPLAY_NAMES = {
    "A": "Ace",
    "K": "King",
    "Q": "Queen",
    "J": "Jack",
    "T": "Ten",
    "10": "Ten",
    "9": "Nine",
    "8": "Eight",
    "7": "Seven",
    "6": "Six",
    "5": "Five",
    "4": "Four",
    "3": "Three",
    "2": "Two",
}
_RANK_PLURAL_DISPLAY = {
    "Aces": "Aces",
    "Kings": "Kings",
    "Queens": "Queens",
    "Jacks": "Jacks",
    "10s": "Tens",
    "9s": "Nines",
    "8s": "Eights",
    "7s": "Sevens",
    "6s": "Sixes",
    "5s": "Fives",
    "4s": "Fours",
    "3s": "Threes",
    "2s": "Twos",
}


def _pretty_rank_high(token: str) -> str:
    cleaned = token.strip()
    if cleaned.endswith("-high"):
        cleaned = cleaned[:-5]
    name = _RANK_DISPLAY_NAMES.get(cleaned, cleaned)
    return f"{name} High"


def _chip_high_label(detail: str) -> str:
    """Compact chip text: 'Jack High' → 'J-high'."""
    text = detail.strip()
    if not text.lower().endswith(" high"):
        return text
    name = text[: -len(" High")].strip()
    for code, display in _RANK_DISPLAY_NAMES.items():
        if display == name:
            return f"{code}-high" if code != "10" else "T-high"
    return text


def _pretty_rank_plural(token: str) -> str:
    return _RANK_PLURAL_DISPLAY.get(token.strip(), token.strip())


def _split_made_hand_label(label: str) -> tuple[str, str]:
    """Split engine describe_hand() text into (category, detail)."""
    text = label.strip()
    lower = text.lower()

    if lower == "royal flush":
        return "Royal Flush", "Ace High"
    if lower.startswith("straight flush,"):
        return "Straight Flush", _pretty_rank_high(text.split(",", 1)[1])
    if lower.startswith("four of a kind,"):
        return "Four of a Kind", _pretty_rank_plural(text.split(",", 1)[1])
    if lower.startswith("full house,"):
        detail = text.split(",", 1)[1].strip()
        if " full of " in detail:
            top, bottom = detail.split(" full of ", 1)
            detail = f"{_pretty_rank_plural(top)} full of {_pretty_rank_plural(bottom)}"
        return "Full House", detail
    if lower.startswith("flush,"):
        return "Flush", _pretty_rank_high(text.split(",", 1)[1])
    if lower.startswith("straight,"):
        return "Straight", _pretty_rank_high(text.split(",", 1)[1])
    if lower.startswith("three of a kind,"):
        return "Three of a Kind", _pretty_rank_plural(text.split(",", 1)[1])
    if lower.startswith("two pair,"):
        detail = text.split(",", 1)[1].strip()
        if " and " in detail:
            left, right = detail.split(" and ", 1)
            detail = f"{_pretty_rank_plural(left)} and {_pretty_rank_plural(right)}"
        return "Two Pair", detail
    if lower.startswith("pair of "):
        rank = text[8:].strip()
        return "One Pair", f"Pair of {_pretty_rank_plural(rank)}"
    if lower.startswith("high card,"):
        return "High Card", _pretty_rank_high(text.split(",", 1)[1])
    return text, ""


def _hero_made_hand_label_html() -> str:
    label = _hero_made_hand_label()
    trophy = _lucide_icon_data_uri("trophy", size=22, stroke="#fbbf24")
    if not label:
        return (
            '<div class="el-best-hand el-best-hand-muted">'
            f'<img class="el-best-hand-icon" src="{trophy}" alt="" width="22" height="22"/>'
            '<div class="el-best-hand-copy">'
            '<div class="el-best-hand-label">Current Best Hand</div>'
            '<div class="el-best-hand-category">—</div>'
            "</div></div>"
        )
    category, detail = _split_made_hand_label(label)
    detail_html = (
        f'<div class="el-best-hand-detail">{escape(detail)}</div>' if detail else ""
    )
    return (
        '<div class="el-best-hand">'
        f'<img class="el-best-hand-icon" src="{trophy}" alt="" width="22" height="22"/>'
        '<div class="el-best-hand-copy">'
        '<div class="el-best-hand-label">Current Best Hand</div>'
        f'<div class="el-best-hand-category">{escape(category)}</div>'
        f"{detail_html}"
        "</div></div>"
    )


def _selected_board_cards() -> list[str]:
    board_cards = [card for card in _flop_slot_values() if card is not None]
    turn_card = _turn_slot_value()
    if turn_card:
        board_cards.append(turn_card)
    river_card = _river_slot_value()
    if river_card:
        board_cards.append(river_card)
    return board_cards


def _board_backend_string() -> str:
    return " ".join(_selected_board_cards())


def _board_display_string() -> str:
    flop = " ".join(card for card in _flop_slot_values() if card) or "—"
    turn = _turn_slot_value() or "—"
    river = _river_slot_value() or "—"
    return f"{flop} | {turn} | {river}"


def _hero_hand_shorthand(selected_cards: list[str] | list[str | None]) -> str:
    if len(selected_cards) != 2 or not selected_cards[0] or not selected_cards[1]:
        return ""

    first_key, second_key = selected_cards[0], selected_cards[1]
    first_rank, first_suit = _split_card_key(first_key)
    second_rank, second_suit = _split_card_key(second_key)
    high_rank, low_rank = sorted((first_rank, second_rank), key=lambda rank: RANGE_RANKS.index(rank))

    if first_rank == second_rank:
        return f"{high_rank}{low_rank}"

    suited = "s" if first_suit == second_suit else "o"
    return f"{high_rank}{low_rank}{suited}"


def _split_card_key(card_key: str) -> tuple[str, str]:
    normalized = _normalize_card_key(card_key)
    return normalized[0], normalized[1]


def _normalize_card_key(card_key: str) -> str:
    if len(card_key) != 2:
        return card_key
    return f"{card_key[0].upper()}{card_key[1].lower()}"


def _card_display_notation(card_key: str) -> str:
    rank, suit = _split_card_key(card_key)
    return f"{SUIT_SYMBOLS[suit]} {rank}"


def _colored_card_text(rank: str, suit: str, *, hero: bool = False) -> str:
    colors = SUIT_STYLES[suit]
    notation = _card_display_notation(f"{rank}{suit}")
    card_class = "playing-card-face hero-card-face card-deal-in" if hero else "playing-card-face card-deal-in"
    return (
        f"<div class='{card_class}' style="
        f"'background:{colors['background']};"
        f"border:2px solid {colors['selected_border']};"
        f"color:#ffffff;"
        f"box-shadow:{colors['selected_glow']}, 0 12px 26px rgba(2, 6, 23, 0.48)'>"
        f"<div class='playing-card-rank'>{SUIT_SYMBOLS[suit]} {rank}</div>"
        f"<div class='playing-card-caption'>{notation}</div>"
        f"</div>"
    )


def _empty_hero_slot_html() -> str:
    return "<div class='hero-card-slot-idle' aria-hidden='true'></div>"


def _card_button_label(rank: str, suit: str) -> str:
    return f"{SUIT_SYMBOLS[suit]} {rank}"


def _format_percent(value: float) -> str:
    return f"{value * 100:.1f}%"


def _format_range_notation(
    selected_range_hands: list[str],
    weights: dict[str, int] | None = None,
) -> str:
    ordered = sorted(selected_range_hands, key=_grid_hand_sort_key)
    if not ordered:
        return ""
    weight_map = weights if weights is not None else _selected_range_weights()
    parts: list[str] = []
    for hand in ordered:
        weight = int(weight_map.get(hand, 100))
        if weight >= 100:
            parts.append(hand)
        else:
            parts.append(f"{hand}:{weight}%")
    return ", ".join(parts)


def _range_notation_preview(
    hands: list[str],
    limit: int = 18,
    weights: dict[str, int] | None = None,
) -> str:
    """Display-only truncated range notation for the Range Summary."""
    ordered = sorted(hands, key=_grid_hand_sort_key)
    if not ordered:
        return ""
    weight_map = weights if weights is not None else {hand: 100 for hand in ordered}
    notation = _format_range_notation(ordered, weight_map)
    tokens = [token.strip() for token in notation.split(",") if token.strip()]
    if len(tokens) <= limit:
        return notation
    return ", ".join(tokens[:limit]) + ", ..."


def _saved_range_preview(
    hands: list[str],
    weights: dict[str, int] | None = None,
    limit: int = 8,
) -> str:
    """Compact hand-class preview for Saved Ranges cards."""
    return _range_notation_preview(hands, limit=limit, weights=weights)


def _hand_combo_count(hand: str) -> int:
    """Return combinations for one grid hand class."""
    if len(hand) == 2 and hand[0] == hand[1]:
        return 6  # pocket pair, e.g. AA
    if len(hand) == 3 and hand.endswith("s"):
        return 4  # suited, e.g. AKs
    if len(hand) == 3 and hand.endswith("o"):
        return 12  # offsuit, e.g. AKo
    raise ValueError(f"Invalid range hand class: {hand}")


def _selected_range_combo_count(selected_range_hands: list[str]) -> float:
    breakdown = _custom_range_breakdown(selected_range_hands, _selected_range_weights())
    return breakdown["pairs"] + breakdown["suited"] + breakdown["offsuit"]


def _custom_range_breakdown(
    selected_range_hands: list[str],
    weights: dict[str, int] | None = None,
) -> dict[str, float]:
    weight_map = weights if weights is not None else {hand: 100 for hand in selected_range_hands}
    pairs = suited = offsuit = 0.0
    for hand in selected_range_hands:
        factor = int(weight_map.get(hand, 100)) / 100.0
        if len(hand) == 2 and hand[0] == hand[1]:
            pairs += 6 * factor
        elif len(hand) == 3 and hand.endswith("s"):
            suited += 4 * factor
        elif len(hand) == 3 and hand.endswith("o"):
            offsuit += 12 * factor
        else:
            raise ValueError(f"Invalid range hand class: {hand}")
    return {"pairs": pairs, "suited": suited, "offsuit": offsuit}


def _range_summary_stats(
    selected_range_hands: list[str],
    weights: dict[str, int] | None = None,
) -> dict[str, object]:
    weight_map = weights if weights is not None else {hand: 100 for hand in selected_range_hands}
    breakdown = _custom_range_breakdown(selected_range_hands, weight_map)
    effective_combos = breakdown["pairs"] + breakdown["suited"] + breakdown["offsuit"]
    return {
        "hand_classes": len(selected_range_hands),
        "total_combos": effective_combos,
        "effective_combos": effective_combos,
        "percentage": (effective_combos / 1326) * 100 if effective_combos else 0.0,
        "pairs": breakdown["pairs"],
        "suited": breakdown["suited"],
        "offsuit": breakdown["offsuit"],
        "notation": _format_range_notation(selected_range_hands, weight_map),
    }


def _grid_hand_label(row_rank: str, column_rank: str) -> str:
    if row_rank == column_rank:
        return f"{row_rank}{column_rank}"
    high_rank, low_rank = sorted((row_rank, column_rank), key=lambda rank: RANGE_RANKS.index(rank))
    if RANGE_RANKS.index(row_rank) < RANGE_RANKS.index(column_rank):
        return f"{high_rank}{low_rank}s"
    return f"{high_rank}{low_rank}o"


def _range_hand_category(hand: str) -> str:
    if len(hand) == 2 and hand[0] == hand[1]:
        return "pair"
    if len(hand) == 3 and hand.endswith("s"):
        return "suited"
    return "offsuit"


def _grid_hand_sort_key(hand: str) -> tuple[int, int, int]:
    if len(hand) == 2:
        rank_index = RANGE_RANKS.index(hand[0])
        return (rank_index, rank_index, -1)

    high_rank = hand[0]
    low_rank = hand[1]
    suitedness = hand[2]
    suitedness_order = 0 if suitedness == "s" else 1
    return (RANGE_RANKS.index(high_rank), RANGE_RANKS.index(low_rank), suitedness_order)


def _ordered_grid_hands() -> list[str]:
    return [_grid_hand_label(row_rank, column_rank) for row_rank in RANGE_RANKS for column_rank in RANGE_RANKS]


def _all_pair_hands() -> list[str]:
    return [f"{rank}{rank}" for rank in RANGE_RANKS]


def _all_suited_hands() -> list[str]:
    return [hand for hand in _ordered_grid_hands() if len(hand) == 3 and hand.endswith("s")]


def _all_offsuit_hands() -> list[str]:
    return [hand for hand in _ordered_grid_hands() if len(hand) == 3 and hand.endswith("o")]


if __name__ == "__main__":
    main()
