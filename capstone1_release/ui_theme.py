"""Reusable enterprise-style presentation helpers for the Streamlit front end.

Pure UI/CSS/formatting utilities only — no business logic, API calls, or data
mutation lives here, so any page in ``app.py`` can import it safely.
"""
from __future__ import annotations

from datetime import datetime

import streamlit as st

ACCENT_COLOR = "#2452E8"

METHOD_BADGE_COLORS: dict[str, str] = {
    "GET": "blue",
    "POST": "green",
    "PUT": "orange",
    "PATCH": "violet",
    "DELETE": "red",
    "HEAD": "gray",
    "OPTIONS": "gray",
}


def inject_global_styles() -> None:
    """Apply a light, enterprise-dashboard look on top of Streamlit's defaults."""
    st.markdown(
        f"""
        <style>
        .block-container {{
            padding-top: 1.5rem;
            padding-bottom: 2rem;
            max-width: 100%;
        }}
        div[data-testid="stMetric"] {{
            background: #FFFFFF;
            border: 1px solid #E5E7EB;
            border-radius: 10px;
            padding: 0.9rem 1rem;
        }}
        div[data-testid="stMetricLabel"],
        div[data-testid="stMetricValue"],
        div[data-testid="stMetricDelta"] {{
            color: #111827 !important;
        }}
        div[data-testid="stExpander"] {{
            border: 1px solid #E5E7EB;
            border-radius: 10px;
            background: #FFFFFF;
        }}
        div[data-testid="stExpander"] summary,
        div[data-testid="stExpander"] summary * {{
            color: #111827 !important;
        }}
        div[data-testid="stVerticalBlockBorderWrapper"] {{
            border-radius: 12px;
        }}
        .stButton>button[kind="primary"] {{
            background-color: {ACCENT_COLOR};
            border-color: {ACCENT_COLOR};
            border-radius: 8px;
            font-weight: 600;
        }}
        .stButton>button {{
            border-radius: 8px;
        }}
        .app-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 0.75rem 0 1.25rem 0;
            border-bottom: 1px solid #E5E7EB;
            margin-bottom: 1.25rem;
        }}
        .app-header h1 {{
            font-size: 1.5rem;
            margin: 0;
            font-weight: 700;
            color: #111827;
        }}
        .app-header p {{
            margin: 0.15rem 0 0 0;
            color: #6B7280;
            font-size: 0.9rem;
        }}
        .app-header-icons {{
            display: flex;
            gap: 0.9rem;
            font-size: 1.2rem;
            color: #6B7280;
        }}
        .page-subtitle {{
            color: #6B7280;
            font-size: 0.95rem;
            margin-top: -0.6rem;
            margin-bottom: 1.25rem;
        }}
        section[data-testid="stSidebar"] {{
            border-right: 1px solid #E5E7EB;
        }}

        /* Dashboard-only spacing polish (scoped via st.container(key="dashboard_page")) */
        .st-key-dashboard_page div[data-testid="stElementContainer"] {{
            margin-bottom: 0.4rem;
        }}
        .st-key-dashboard_page div[data-testid="stMetric"] {{
            padding: 1.3rem 1.4rem;
        }}
        .st-key-dashboard_page h4 {{
            margin-top: 0.3rem;
            margin-bottom: 0.9rem;
        }}
        .st-key-dashboard_page hr {{
            margin: 2rem 0;
        }}
        .st-key-dashboard_spec_card {{
            padding: 0.5rem 0.25rem;
        }}

        /* Data Ingestion-only spacing polish (scoped via st.container(key="ingestion_page")) */
        .st-key-ingestion_page div[data-testid="stElementContainer"] {{
            margin-bottom: 0.75rem;
        }}
        .st-key-ingestion_page div[data-testid="stMetric"] {{
            padding: 1.25rem 1.5rem;
        }}
        .st-key-ingestion_page div[data-testid="stMetricLabel"] {{
            font-size: 0.85rem;
            color: #6B7280;
        }}
        .st-key-ingestion_page div[data-testid="stMetricValue"] {{
            font-size: 1rem;
            line-height: 1.35;
            white-space: normal;
            overflow-wrap: anywhere;
        }}
        .st-key-ingestion_page div[data-testid="stVerticalBlockBorderWrapper"] {{
            padding: 0.5rem;
        }}
        .st-key-ingestion_page div[data-testid="stExpander"] {{
            margin-top: 0.85rem;
            margin-bottom: 0.85rem;
        }}
        .st-key-ingestion_page h4 {{
            margin-top: 0.5rem;
            margin-bottom: 1.1rem;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_app_header(title: str, subtitle: str) -> None:
    """Compact enterprise top header with title/subtitle and utility icons."""
    st.markdown(
        f"""
        <div class="app-header">
            <div>
                <h1>{title}</h1>
                <p>{subtitle}</p>
            </div>
            <div class="app-header-icons">
                <span title="Help">&#10067;</span>
                <span title="Settings">&#9881;&#65039;</span>
                <span title="Account">&#128100;</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_page_header(title: str, subtitle: str) -> None:
    """Standard page title + muted subtitle used at the top of every page."""
    st.title(title)
    st.markdown(f'<p class="page-subtitle">{subtitle}</p>', unsafe_allow_html=True)


def method_badge(method: str) -> None:
    """Render an HTTP method as a small color-coded badge."""
    st.badge(method.upper(), color=METHOD_BADGE_COLORS.get(method.upper(), "gray"))


def empty_state(icon: str, title: str, description: str) -> None:
    """A centered placeholder card shown when a page/section has no data yet."""
    with st.container(border=True):
        st.markdown(
            f"""
            <div style="text-align:center; padding: 2rem 1rem;">
                <div style="font-size:2rem;">{icon}</div>
                <div style="font-weight:600; font-size:1.05rem; margin-top:0.5rem; color:#111827;">{title}</div>
                <div style="color:#6B7280; margin-top:0.25rem;">{description}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def format_file_size(num_bytes: int) -> str:
    """Human-readable file size, e.g. ``245.0 KB``."""
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def format_timestamp(value: str) -> str:
    """Render a stored ISO-8601 timestamp for display, e.g. ``Aug 25, 2026, 09:57 PM``."""
    try:
        return datetime.fromisoformat(value).strftime("%b %d, %Y, %I:%M %p")
    except (TypeError, ValueError):
        return value
