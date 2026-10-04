"""ABB-branded presentation layer for the Streamlit GUI.

Colours, fonts and radii come from `.streamlit/config.toml`, which defines
an ABB light and an ABB dark palette (switched from the top-right menu).
This module holds only what the config cannot express: the chat layout, the
brand mark, the sticky sidebar footer and the cards. Its own colours are
`light-dark()` pairs, resolved against the `color-scheme` Streamlit sets on
the app for the active theme, so a theme switch needs no rerun. Application logic stays in app.py,
which addresses elements through keyed containers (`st-key-*` classes)
rather than Streamlit's internal test ids wherever it can.
"""

from __future__ import annotations

import base64
from pathlib import Path

import streamlit as st

ASSETS = Path(__file__).resolve().parent / "assets"
LOGO_MARK = str(ASSETS / "abb-mark.svg")

CSS = """
<style>
:root {
  --abb-red: #FF000F;
  --abb-red-tint: light-dark(#FFF0F1, #2A1214);
  --ink: light-dark(#1F1F1F, #EDEDED);
  --ink-2: light-dark(#555555, #B3B3B3);
  --ink-3: light-dark(#8C8C8C, #858585);
  --line: light-dark(#E3E3E3, #323232);
  --surface: light-dark(#FFFFFF, #141414);
  --surface-2: light-dark(#F4F4F4, #222222);
  --sidebar: light-dark(#F7F7F7, #0E0E0E);
  --hover: light-dark(#EBEBEB, #1E1E1E);
  --active: light-dark(#E3E3E3, #262626);
  --ok: light-dark(#1F9D55, #3DBE74);
  --scrollbar: light-dark(#D4D4D4, #3A3A3A);
}

/* ── Chrome ─────────────────────────────────────────────────────── */
[data-testid="stDecoration"] { display: none; }
/* Opaque, so text scrolling underneath is hidden rather than half-visible. */
header[data-testid="stHeader"] { background: var(--surface); }
.block-container { padding-top: 3.25rem; padding-bottom: 7rem; max-width: 1440px; }
h1, h2, h3, h4 { letter-spacing: -0.015em; }

/* Sidebar logo: the image is the ABB mark only, so the product name follows
   the theme's text colour instead of being baked into the SVG. */
[data-testid="stSidebarHeader"] > div:first-child { display: flex; align-items: center; }
[data-testid="stSidebarHeader"] > div:first-child::after {
  content: "Alarm Copilot";
  margin-left: 0.7rem;
  padding-left: 0.7rem;
  border-left: 1px solid var(--line);
  color: var(--ink);
  font-weight: 600;
  font-size: 1rem;
  line-height: 1.4rem;
  white-space: nowrap;
}

/* The sidebar collapse control is hover-only by default; keep it visible. */
[data-testid="stSidebarCollapseButton"] { display: inline-flex !important; visibility: visible !important; opacity: 1 !important; }

/* ── Brand mark ─────────────────────────────────────────────────── */
.abb-mark { display: inline-block; height: 1em; width: auto; vertical-align: middle; user-select: none; }

/* ── Welcome ────────────────────────────────────────────────────── */
.st-key-welcome { max-width: 760px; margin: 9vh auto 0; }
.welcome-head { text-align: center; margin-bottom: 1.5rem; }
.welcome-brand { display: inline-flex; align-items: center; gap: 1rem; margin-bottom: 1rem; }
.welcome-brand .abb-mark { height: 2.6rem; }
.welcome-brand h1 {
  font-size: 2.3rem; font-weight: 600; margin: 0; padding: 0 0 0 1rem; line-height: 2.6rem;
  border-left: 2px solid var(--line); color: var(--ink); letter-spacing: -0.02em;
}
.welcome-head p { color: var(--ink-2); font-size: 1.15rem; margin: 0; }
.st-key-welcome [data-testid="stChatInput"] { box-shadow: 0 2px 14px light-dark(rgba(0, 0, 0, 0.06), rgba(0, 0, 0, 0.4)); }
.st-key-suggestions { margin-top: 0.6rem; }
.st-key-suggestions .stButton > button {
  justify-content: flex-start;
  text-align: left;
  min-height: 3.6rem;
  padding: 0.6rem 0.9rem;
  border-color: var(--line);
  background: var(--surface);
  color: var(--ink);
  font-weight: 400;
}
.st-key-suggestions .stButton > button:hover { border-color: var(--abb-red); color: var(--ink); background: var(--abb-red-tint); }
.st-key-suggestions .stButton > button > div { justify-content: flex-start; width: 100%; }
.st-key-suggestions .stButton > button p { font-size: 0.86rem; line-height: 1.4; white-space: normal; text-align: left; }
.st-key-suggestions .stButton > button strong { font-weight: 600; }
.welcome-foot { text-align: center; color: var(--ink-3); font-size: 0.78rem; margin-top: 1.4rem; }

/* ── Conversation ───────────────────────────────────────────────── */
.st-key-chat-solo { max-width: 780px; margin: 0 auto; }
.st-key-topbar { border-bottom: 1px solid var(--line); padding-bottom: 0.35rem; margin-bottom: 0.6rem; }
.st-key-topbar p { font-weight: 600; margin: 0; }
/* Starred: red star in the top bar and beside the chat in the sidebar. */
.st-key-star-on [data-testid="stIconMaterial"],
[class*="st-key-open-star-"] [data-testid="stIconMaterial"] { color: var(--abb-red); }

[class*="st-key-umsg-"] {
  scroll-margin-top: 4.5rem;  /* clear the header when scrolled into view */
  background: var(--surface-2);
  border-radius: 1.1rem 1.1rem 0.3rem 1.1rem;
  padding: 0.6rem 1rem;
  max-width: 85%;
}
/* Streamlit pulls markdown up by 1rem; inside a padded bubble that clips. */
[class*="st-key-umsg-"] [data-testid="stMarkdownContainer"] { margin-bottom: 0 !important; }
[class*="st-key-umsg-"] p { margin: 0; }
[class*="st-key-amsg-"] { padding: 0.25rem 0 0.4rem; }
[class*="st-key-amsg-"] [data-testid="stMarkdownContainer"] p,
[class*="st-key-amsg-"] [data-testid="stMarkdownContainer"] li { line-height: 1.65; }
.amsg-head { display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.15rem; color: var(--ink-2); font-size: 0.8rem; font-weight: 600; }
.amsg-head .abb-mark { height: 0.85rem; }
.sources-line { font-size: 0.8rem; color: var(--ink-2); margin-top: 0.15rem; }
.sources-line .src {
  display: inline-block; margin: 0.15rem 0.3rem 0 0; padding: 0.05rem 0.45rem;
  border: 1px solid var(--line); border-radius: 999px; background: var(--surface); white-space: nowrap;
}
.sources-line .src b { color: var(--abb-red); font-weight: 600; }

/* Answer action row: thumbs, share, evidence */
[class*="st-key-actions-"] { margin-top: -0.2rem; }
[class*="st-key-actions-"] .stButton > button,
[class*="st-key-actions-"] [data-testid="stPopover"] button { color: var(--ink-2); font-size: 0.82rem; }
[class*="st-key-actions-"] [data-testid="stCaptionContainer"] { color: var(--ink-3); font-size: 0.76rem; }

/* ── Cards: incident draft and created ticket ───────────────────── */
[class*="st-key-draft-"] { border-left: 3px solid var(--abb-red) !important; }
[class*="st-key-ticket-"] { border-left: 3px solid var(--ok) !important; }
.card-kicker { font-size: 0.72rem; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; color: var(--ink-3); }
.ticket-key { font-size: 1.05rem; font-weight: 700; color: var(--ink); }

/* ── Evidence panel ─────────────────────────────────────────────── */
[data-testid="stColumn"]:has(.st-key-evidence-panel) {
  position: sticky;
  top: 4.25rem;
  align-self: flex-start;
  max-height: calc(100vh - 5.25rem);
  overflow-y: auto;
  border-left: 1px solid var(--line);
  padding-left: 1.4rem;
}
.st-key-evidence-panel [data-testid="stMetricValue"] { font-size: 1.35rem; }
.evidence-meta { font-size: 0.76rem; color: var(--ink-3); word-break: break-all; }
.alarm-line { font-size: 0.92rem; }
.alarm-band { display: inline-block; padding: 0.05rem 0.5rem; border-radius: 0.35rem; background: var(--abb-red); color: #fff; font-weight: 600; font-size: 0.78rem; margin-right: 0.4rem; }

/* Pinned input: follow the chat column, not the full width. */
[data-testid="stBottomBlockContainer"] { max-width: 820px; padding-bottom: 1.2rem; }
body:has(.st-key-evidence-panel) [data-testid="stBottomBlockContainer"] { max-width: 1440px; padding-right: calc(40% + 1rem); }
/* ...and leave the evidence panel visible beside it. The bottom spacing
   moves inside the columns row so the sticky panel can reach the bottom. */
body:has(.st-key-evidence-panel) .block-container { padding-bottom: 0.5rem; }
.chat-end { height: 7.5rem; }
body:has(.st-key-evidence-panel) [data-testid="stBottom"] > div { background: transparent !important; }
body:has(.st-key-evidence-panel) [data-testid="stBottomBlockContainer"] { background: linear-gradient(to right, var(--surface) 0 58%, transparent 58%); }
[data-testid="stChatInput"] { border-radius: 1rem; }

/* ── Sidebar ────────────────────────────────────────────────────── */
section[data-testid="stSidebar"] .stButton button { justify-content: flex-start; text-align: left; font-weight: 400; }
section[data-testid="stSidebar"] .stButton button > div,
section[data-testid="stSidebar"] .stButton button > div > span { justify-content: flex-start; width: 100%; min-width: 0; }
section[data-testid="stSidebar"] .stButton button p {
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 0.86rem;
}
section[data-testid="stSidebar"] .stButton button[kind="tertiary"] { padding: 0.3rem 0.55rem; border-radius: 0.5rem; color: var(--ink); }
section[data-testid="stSidebar"] .stButton button[kind="tertiary"]:hover { background: var(--hover); color: var(--ink); }
/* The open chat */
section[data-testid="stSidebar"] [class*="st-key-active-"] .stButton > button { background: var(--active); font-weight: 500; }
.side-label { font-size: 0.72rem; font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; color: var(--ink-3); margin: 0.9rem 0 0.1rem 0.55rem; }
.st-key-new-chat .stButton > button { justify-content: flex-start; font-weight: 500 !important; background: var(--surface); color: var(--ink); }
.st-key-new-chat .stButton > button:hover { border-color: var(--abb-red); color: var(--ink); }

/* Footer pinned to the bottom of the sidebar: stretch the content
   column to full height, then push the footer's wrapper down. */
[data-testid="stSidebarContent"] { display: flex; flex-direction: column; }
[data-testid="stSidebarUserContent"],
[data-testid="stSidebarUserContent"] > div { flex: 1 0 auto; display: flex; flex-direction: column; }
[data-testid="stSidebarUserContent"] { padding-bottom: 0 !important; }
[data-testid="stSidebarUserContent"] > div > [data-testid="stVerticalBlock"] { flex: 1 0 auto; }
[data-testid="stLayoutWrapper"]:has(> .st-key-sidebar-footer) {
  margin-top: auto;
  position: sticky;
  bottom: 0;
  z-index: 2;
  background: var(--sidebar);
}
.st-key-sidebar-footer { margin-top: 1rem; padding: 0.6rem 0 1rem; border-top: 1px solid var(--line); gap: 0.4rem; }
.user-chip { display: flex; align-items: center; gap: 0.6rem; }
.user-avatar {
  width: 2rem; height: 2rem; border-radius: 50%; flex-shrink: 0;
  background: var(--ink); color: var(--surface); font-weight: 600; font-size: 0.78rem;
  display: flex; align-items: center; justify-content: center;
}
.user-name { font-size: 0.86rem; font-weight: 500; color: var(--ink); line-height: 1.2; }
.user-sub { font-size: 0.72rem; color: var(--ink-3); line-height: 1.2; }

/* ── Misc ───────────────────────────────────────────────────────── */
blockquote { border-left: 3px solid var(--abb-red) !important; background: var(--surface-2); border-radius: 0 0.5rem 0.5rem 0; padding: 0.4rem 0.9rem; }
[data-testid="stExpander"] details { border-color: var(--line); }
::-webkit-scrollbar { width: 8px; height: 8px; }
::-webkit-scrollbar-thumb { background: var(--scrollbar); border-radius: 8px; }
::-webkit-scrollbar-track { background: transparent; }
</style>
"""

# Inline as a data URI: an <img> keeps the SVG's mask id private, so the
# mark can appear many times on one page.
_MARK_SVG = base64.b64encode((ASSETS / "abb-mark.svg").read_bytes()).decode()
MARK_HTML = f'<img class="abb-mark" alt="ABB" src="data:image/svg+xml;base64,{_MARK_SVG}">'


def apply_abb_theme() -> None:
    st.logo(LOGO_MARK, size="large", icon_image=LOGO_MARK)
    st.html(CSS)
