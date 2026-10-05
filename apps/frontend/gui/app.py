"""Incident and Ticket Enrichment Copilot - Streamlit GUI.

    streamlit run apps/frontend/gui/app.py

The layout follows the chat tools people already know: conversations in the
sidebar, the conversation in the middle, and an evidence panel on the right
for whichever answer is selected (the latest by default). An answer without
its MCP trace and its citations is not auditable, so every answer also shows
its sources inline, and the panel is open unless the user closes it.

State lives in st.session_state for the browser session. Each chat keeps the
full backend response of every answer, so earlier answers keep their
evidence, and approved tickets stay listed after the conversation moves on.
"""

from __future__ import annotations

import os
import sys
import time
import uuid
from html import escape
from pathlib import Path
from typing import Any

import streamlit as st

# Allow `streamlit run apps/frontend/gui/app.py` from the repository root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gui.client import ApiResult, CopilotClient
from gui.theme import LOGO_MARK, MARK_HTML, apply_abb_theme

st.set_page_config(
    page_title="Incident & Ticket Enrichment Copilot",
    page_icon=LOGO_MARK,
    layout="wide",
    initial_sidebar_state="expanded",
)

# (title, subtitle, prompt sent)
EXAMPLE_PROMPTS = [
    (
        "Prepare an incident",
        "for the top active alarm in EastRefinery",
        "Prepare an incident for the highest-priority active alarm in EastRefinery",
    ),
    (
        "Investigate Boiler Feed Pump 101",
        "recurring alarms, causes and procedure",
        "Investigate recurring high-severity alarms for Boiler Feed Pump 101 over the "
        "last 90 days, identify likely contributing factors, retrieve the relevant "
        "operating procedure, and provide recommended actions with source evidence",
    ),
    (
        "Mandatory response",
        "to a boiler drum level low alarm",
        "What is the mandatory response to a boiler drum level low alarm?",
    ),
    (
        "Open tickets on linked assets",
        "for Crude Charge Motor 501",
        "Show open tickets linked to correlated assets for Crude Charge Motor 501",
    ),
]

STATUS_ICON = {
    "ok": ":material/check_circle:",
    "tool_error": ":material/warning:",
    "invalid_arguments": ":material/block:",
    "not_found": ":material/help:",
    "transport_error": ":material/power_off:",
}

# There is no sign-in yet (see docs/known-limitations.md); the name is a
# display label only and is not sent to the backend.
OPERATOR_NAME = os.getenv("COPILOT_OPERATOR_NAME", "Operator")


# --------------------------------------------------------------------------
# State
# --------------------------------------------------------------------------
def init_state() -> None:
    defaults: dict[str, Any] = {
        # key -> {key, conversation_id, title, messages, saved, updated, decisions}
        "chats": {},
        "current": None,
        "show_evidence": True,
        "evidence_index": None,  # None follows the latest answer
        "feedback_target": None,  # (chat key, message index) awaiting a comment
        "ticket_view": None,  # (chat key, message index) shown in a dialog
        "scroll_to": None,  # container key to bring to the top on the next run
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


@st.cache_resource
def get_client() -> CopilotClient:
    return CopilotClient()


# Health and the tool catalog are read on every rerun for the sidebar status
# line, but change rarely; a short TTL keeps reruns off the network. Chat
# answers are never cached - alarm state is live.
@st.cache_data(ttl=15, show_spinner=False)
def cached_health(base_url: str) -> ApiResult:
    return get_client().health()


@st.cache_data(ttl=300, show_spinner=False)
def cached_tools(base_url: str) -> ApiResult:
    return get_client().tools()


def _shorten(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def current_chat() -> dict[str, Any] | None:
    return st.session_state.chats.get(st.session_state.current)


def _new_chat() -> dict[str, Any]:
    key = uuid.uuid4().hex[:10]
    chat: dict[str, Any] = {
        "key": key,
        "conversation_id": None,
        "title": "New chat",
        "messages": [],
        "saved": False,
        "updated": time.time(),
        "decisions": {},  # draft_id -> ticket key | "declined"
    }
    st.session_state.chats[key] = chat
    st.session_state.current = key
    return chat


def start_turn(prompt: str) -> None:
    """Record the question; the answer is fetched on the next run so the
    question is on screen while the copilot works."""
    chat = current_chat() or _new_chat()
    if not chat["messages"]:
        chat["title"] = _shorten(prompt, 60)
    chat["messages"].append({"role": "user", "content": prompt})
    chat["updated"] = time.time()
    st.session_state.evidence_index = None


def open_chat(key: str | None) -> None:
    st.session_state.current = key
    st.session_state.evidence_index = None


def show_evidence(index: int) -> None:
    st.session_state.evidence_index = index
    st.session_state.show_evidence = True


def hide_evidence() -> None:
    st.session_state.show_evidence = False


def selected_index(chat: dict[str, Any]) -> int | None:
    """The answer whose evidence the panel shows."""
    messages = chat["messages"]
    index = st.session_state.evidence_index
    if index is not None and index < len(messages) and messages[index].get("response"):
        return index
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("response"):
            return i
    return None


def all_tickets() -> list[tuple[dict[str, Any], int, dict[str, Any]]]:
    """(chat, message index, created ticket) for every ticket this session."""
    found = []
    for chat in st.session_state.chats.values():
        for index, message in enumerate(chat["messages"]):
            ticket = (message.get("response") or {}).get("created_ticket")
            if ticket:
                found.append((chat, index, ticket))
    return sorted(found, key=lambda t: t[0]["updated"], reverse=True)


# --------------------------------------------------------------------------
# Sidebar
# --------------------------------------------------------------------------
def render_sidebar(client: CopilotClient) -> bool:
    """Returns True when the user asked for the system status dialog."""
    with st.sidebar:
        with st.container(key="new-chat"):
            st.button(
                "New chat",
                icon=":material/edit_square:",
                use_container_width=True,
                on_click=open_chat,
                args=(None,),
            )
        query = st.text_input(
            "Search chats",
            placeholder="Search chats",
            icon=":material/search:",
            label_visibility="collapsed",
            key="search",
        ).strip()

        chats = sorted(
            (c for c in st.session_state.chats.values() if c["messages"]),
            key=lambda c: c["updated"],
            reverse=True,
        )
        if query:
            needle = query.lower()
            chats = [
                c
                for c in chats
                if needle in c["title"].lower()
                or any(needle in m["content"].lower() for m in c["messages"])
            ]

        tickets = all_tickets()
        if tickets and not query:
            st.html('<div class="side-label">Tickets created</div>')
            for chat, index, ticket in tickets:
                st.button(
                    f"{ticket['key']} · {ticket['title']}",
                    key=f"tk-{chat['key']}-{index}",
                    icon=":material/confirmation_number:",
                    type="tertiary",
                    use_container_width=True,
                    on_click=lambda c=chat["key"], i=index: st.session_state.update(
                        ticket_view=(c, i)
                    ),
                )

        starred = [c for c in chats if c["saved"]]
        if starred:
            st.html('<div class="side-label">Starred</div>')
            for chat in starred:
                _chat_row(chat)

        st.html(f'<div class="side-label">{"Results" if query else "Recents"}</div>')
        recents = [c for c in chats if not c["saved"]]
        if not chats:
            st.caption("No chats match." if query else "Your conversations will appear here.")
        for chat in recents:
            _chat_row(chat)

        return _sidebar_footer(client)


def _chat_row(chat: dict[str, Any]) -> None:
    active = chat["key"] == st.session_state.current
    with st.container(key=f"active-{chat['key']}" if active else None):
        st.button(
            chat["title"],
            key=f"open-star-{chat['key']}" if chat["saved"] else f"open-{chat['key']}",
            icon=":material/star:" if chat["saved"] else None,
            type="tertiary",
            use_container_width=True,
            on_click=open_chat,
            args=(chat["key"],),
        )


def _sidebar_footer(client: CopilotClient) -> bool:
    health = cached_health(client.base_url)
    if not health.ok:
        status = ":red[●] Backend unreachable"
    elif health.payload.get("status") == "ok":
        status = ":green[●] All systems operational"
    else:
        status = ":orange[●] Running degraded"

    initials = "".join(part[0] for part in OPERATOR_NAME.split()[:2]).upper() or "OP"
    with st.container(key="sidebar-footer"):
        open_status = st.button(
            status,
            key="status-btn",
            type="tertiary",
            use_container_width=True,
            help="MCP server, retrieval index, language model and tool catalog",
        )
        st.html(
            f'<div class="user-chip"><div class="user-avatar">{escape(initials)}</div>'
            f'<div><div class="user-name">{escape(OPERATOR_NAME)}</div>'
            '<div class="user-sub">Local session · sign-in not configured</div></div></div>'
        )
    return open_status


# --------------------------------------------------------------------------
# Dialogs
# --------------------------------------------------------------------------
@st.dialog("System status", width="large")
def status_dialog(client: CopilotClient) -> None:
    cached_health.clear()
    health = cached_health(client.base_url)
    if not health.ok:
        st.error(health.error)
        st.info(
            "Start the stack with `docker compose up --build`, or run the services "
            "individually with `make run-alarm-api`, `make run-ticketing-api`, "
            "`make run-mcp` and `make run-backend`."
        )
        return

    body = health.payload
    mcp, rag, llm = body.get("mcp", {}), body.get("rag", {}), body.get("llm", {})
    status_tab, tools_tab = st.tabs(["Status", "MCP tools"])

    with status_tab:
        a, b, c = st.columns(3)
        a.metric("MCP tools", mcp.get("tools", 0) if mcp.get("connected") else "—")
        b.metric("Indexed chunks", max(rag.get("indexed_chunks", 0), 0))
        c.metric("Backend", body.get("status", "unknown"))

        st.markdown("**MCP server**")
        if mcp.get("connected"):
            st.caption(
                f"`{mcp.get('server')}` v{mcp.get('server_version')} · "
                f"`{mcp.get('transport')}` · {mcp.get('url')}"
            )
        else:
            st.error(mcp.get("error") or "Not connected")

        st.markdown("**Retrieval index**")
        if rag.get("indexed_chunks", 0) > 0:
            st.caption(f"Collection `{rag.get('collection')}`")
        else:
            st.error(rag.get("hint") or "Index is empty")

        st.markdown("**Language model**")
        provider = llm.get("provider", "unknown")
        st.caption(f"**{provider}** · `{llm.get('model')}`")
        if provider == "fake":
            st.caption(
                "Deterministic provider: tool orchestration, retrieval and citations "
                "are fully live; only the narrative is templated. Set `LLM_PROVIDER` "
                "for model-written prose."
            )

    with tools_tab:
        tools = cached_tools(client.base_url)
        if not tools.ok:
            st.error(tools.error)
            return
        catalog = tools.payload
        st.caption(
            f"{catalog.get('count', 0)} tools discovered from the MCP server at startup. "
            "Write tools run only after a human approves."
        )
        for tool in catalog.get("tools", []):
            with st.container(horizontal=True, vertical_alignment="center", gap="small"):
                st.markdown(f"`{tool['name']}`")
                if tool["read_only"]:
                    st.badge("read", color="gray")
                else:
                    st.badge("write", color="red")
            st.caption(_shorten(tool["description"], 180))


def _close_ticket_view() -> None:
    st.session_state.ticket_view = None


@st.dialog("Ticket", width="large", on_dismiss=_close_ticket_view)
def ticket_dialog() -> None:
    chat_key, index = st.session_state.ticket_view
    chat = st.session_state.chats[chat_key]
    response = chat["messages"][index]["response"]
    render_ticket_card(
        response["created_ticket"], response.get("ticket_draft"), key=f"dlg-{chat_key}-{index}"
    )
    st.caption(f"From the chat “{chat['title']}”.")
    if st.button("Open conversation", icon=":material/forum:"):
        st.session_state.current = chat_key
        st.session_state.ticket_view = None
        show_evidence(index)
        st.rerun()


def _send_feedback(chat: dict[str, Any], index: int, rating: str, comment: str | None) -> None:
    response = chat["messages"][index]["response"]
    result = get_client().feedback(
        chat["conversation_id"],
        trace_id=response["trace_id"],
        rating=rating,
        comment=comment,
    )
    if result.ok:
        st.toast("Thanks, your feedback is in the audit trail.", icon=":material/check:")
    else:
        st.toast(f"Feedback not recorded: {result.error}", icon=":material/error:")


def _on_feedback(chat_key: str, index: int) -> None:
    value = st.session_state.get(f"fb-{chat_key}-{index}")
    chat = st.session_state.chats[chat_key]
    message = chat["messages"][index]
    if value is None:
        message["feedback"] = None
        return
    message["feedback"] = "up" if value == 1 else "down"
    if value == 1:
        _send_feedback(chat, index, "up", None)
    else:
        # A thumbs-down is only useful with a reason; ask for one. Closing
        # the dialog still records the rating.
        st.session_state.feedback_target = (chat_key, index)


def _dismiss_feedback() -> None:
    target = st.session_state.feedback_target
    st.session_state.feedback_target = None
    if target:
        chat_key, index = target
        _send_feedback(st.session_state.chats[chat_key], index, "down", None)


@st.dialog("What could be better?", on_dismiss=_dismiss_feedback)
def feedback_dialog() -> None:
    chat_key, index = st.session_state.feedback_target
    comment = st.text_area(
        "Comment",
        placeholder="For example: cited the wrong procedure, missed an open ticket, "
        "picked the wrong asset",
        label_visibility="collapsed",
        max_chars=2000,
    )
    st.caption("Saved to this conversation's audit trail, linked to the answer's trace id.")
    if st.button("Send feedback", type="primary"):
        st.session_state.feedback_target = None
        _send_feedback(st.session_state.chats[chat_key], index, "down", comment.strip() or None)
        st.rerun()


# --------------------------------------------------------------------------
# Welcome
# --------------------------------------------------------------------------
def _use_suggestion(text: str) -> None:
    """Put a suggestion in the input for editing rather than sending it.

    Runs as a callback, i.e. before the input is drawn on the next run,
    which is when Streamlit accepts a value for it from Session State.
    """
    st.session_state["hero-input"] = text
    st.session_state.focus_input = True


def render_welcome() -> None:
    with st.container(key="welcome"):
        st.html(
            f'<div class="welcome-head"><div class="welcome-brand">{MARK_HTML}'
            "<h1>Incident &amp; Ticket Enrichment Copilot</h1></div>"
            "<p>How can I help with your plant today?</p></div>"
        )
        prompt = st.chat_input("Ask about an alarm, an asset or an incident…", key="hero-input")
        with st.container(key="suggestions"):
            columns = st.columns(2)
            for index, (title, subtitle, full) in enumerate(EXAMPLE_PROMPTS):
                with columns[index % 2]:
                    st.button(
                        f"**{title}**  \n{subtitle}",
                        key=f"example-{index}",
                        use_container_width=True,
                        wrap=True,
                        on_click=_use_suggestion,
                        args=(full,),
                    )
        st.html(
            '<div class="welcome-foot">Alarm data reached only through MCP tools · '
            "answers cite plant documents · tickets are created only with your approval</div>"
        )
    if st.session_state.pop("focus_input", False):
        _focus_input()
    if prompt:
        start_turn(prompt)
        st.rerun()


def _focus_input() -> None:
    """Focus the chat input with the cursor at the end, ready to edit."""
    st.html(
        """<script>setTimeout(() => {
  const box = document.querySelector('.st-key-welcome [data-testid="stChatInputTextArea"]');
  if (box) { box.focus(); box.setSelectionRange(box.value.length, box.value.length); }
}, 150);</script>""",
        unsafe_allow_javascript=True,
    )


# --------------------------------------------------------------------------
# Conversation
# --------------------------------------------------------------------------
def render_chat_view(client: CopilotClient, chat: dict[str, Any]) -> None:
    pending = chat["messages"][-1]["role"] == "user"
    # Called before the messages so the pinned input stays put while an
    # answer is being fetched.
    if prompt := st.chat_input("Reply to the copilot…", key="chat-input", disabled=pending):
        start_turn(prompt)
        st.rerun()

    index = selected_index(chat)
    if st.session_state.show_evidence and index is not None:
        left, right = st.columns([3, 2], gap="large")
    else:
        left, right = st.container(key="chat-solo"), None

    with left:
        _topbar(chat, panel_hidden=right is None and index is not None)
        for i, message in enumerate(chat["messages"]):
            if message["role"] == "user":
                with (
                    st.container(horizontal=True, horizontal_alignment="right"),
                    st.container(key=f"umsg-{chat['key']}-{i}", width="content"),
                ):
                    st.markdown(message["content"])
            else:
                render_answer(client, chat, i)
        if pending:
            _answer_pending(client, chat)
        if right is not None:
            st.html('<div class="chat-end"></div>')

    if right is not None and index is not None:
        with right:
            render_evidence(client, chat, index)

    if target := st.session_state.pop("scroll_to", None):
        _scroll_into_view(target)


def _scroll_into_view(container_key: str) -> None:
    """Bring a new answer's question to the top of the view.

    Streamlit keeps a chat pinned to the bottom, so a long answer pushes its
    question out of sight - and it re-pins whenever late content grows the
    page. So the question is held in place for a few seconds while the page
    settles, and released the moment the user scrolls or types.
    """
    st.html(
        f"""<script>(() => {{
  const selector = ".st-key-{container_key}";
  const events = ["wheel", "touchstart", "keydown", "mousedown"];
  let timer = null;
  const release = () => {{
    clearInterval(timer);
    events.forEach((e) => window.removeEventListener(e, release, true));
  }};
  const hold = () => {{
    const el = document.querySelector(selector);
    if (!el) return;
    const margin = parseFloat(getComputedStyle(el).scrollMarginTop) || 0;
    if (Math.abs(el.getBoundingClientRect().top - margin) > 4) el.scrollIntoView({{block: "start"}});
  }};
  events.forEach((e) => window.addEventListener(e, release, true));
  timer = setInterval(hold, 100);
  setTimeout(release, 3000);
}})();</script>""",
        unsafe_allow_javascript=True,
    )


def _topbar(chat: dict[str, Any], *, panel_hidden: bool) -> None:
    with st.container(key="topbar", horizontal=True, vertical_alignment="center", gap="small"):
        st.markdown(escape(chat["title"]))
        st.space("stretch")
        st.button(
            "",
            key="star-on" if chat["saved"] else "star-off",
            icon=":material/star:" if chat["saved"] else ":material/star_border:",
            type="tertiary",
            help="Unstar this chat" if chat["saved"] else "Star this chat",
            on_click=lambda: chat.update(saved=not chat["saved"]),
        )
        if panel_hidden:
            st.button(
                "Evidence",
                key="open-panel",
                icon=":material/right_panel_open:",
                type="tertiary",
                on_click=lambda: st.session_state.update(show_evidence=True),
            )


def _answer_pending(client: CopilotClient, chat: dict[str, Any]) -> None:
    prompt = chat["messages"][-1]["content"]
    with st.container(key=f"amsg-{chat['key']}-pending"):
        st.html(f'<div class="amsg-head">{MARK_HTML}</div>')
        with st.spinner("Planning, calling MCP tools and retrieving documents…"):
            result = client.chat(prompt, chat["conversation_id"])
    if result.ok:
        payload = result.payload
        chat["conversation_id"] = payload["conversation_id"]
        chat["messages"].append(
            {"role": "assistant", "content": payload["message"], "response": payload}
        )
    else:
        chat["messages"].append({"role": "assistant", "content": result.error, "error": True})
    chat["updated"] = time.time()
    st.session_state.scroll_to = f"umsg-{chat['key']}-{len(chat['messages']) - 2}"
    st.rerun()


def render_answer(client: CopilotClient, chat: dict[str, Any], index: int) -> None:
    message = chat["messages"][index]
    response = message.get("response") or {}
    with st.container(key=f"amsg-{chat['key']}-{index}"):
        st.html(f'<div class="amsg-head">{MARK_HTML}</div>')
        if message.get("error"):
            st.error(message["content"], icon=":material/error:")
            return
        st.markdown(message["content"])
        if not message.get("approval"):
            _sources_line(response)

        created = response.get("created_ticket")
        if created:
            render_ticket_card(created, response.get("ticket_draft"), key=f"{chat['key']}-{index}")
        # Approval replies echo the draft back; only the answer that
        # proposed it carries the editable card.
        elif response.get("ticket_draft") and not message.get("approval"):
            render_draft(client, chat, index, response["ticket_draft"])

        _action_row(chat, index)


def _sources_line(response: dict[str, Any]) -> None:
    citations = response.get("citations") or []
    if citations:
        chips = "".join(
            f'<span class="src"><b>{escape(c["marker"])}</b> {escape(c["doc_id"])} · '
            f"{escape(_shorten(c['title'], 40))}</span>"
            for c in citations
        )
        st.html(f'<div class="sources-line">{chips}</div>')
    elif response.get("low_confidence"):
        st.caption(
            "No document cleared the relevance threshold, so nothing is cited. "
            "The answer says so rather than guessing."
        )


def _action_row(chat: dict[str, Any], index: int) -> None:
    message = chat["messages"][index]
    response = message["response"]
    open_now = st.session_state.show_evidence and selected_index(chat) == index

    with st.container(
        key=f"actions-{chat['key']}-{index}",
        horizontal=True,
        vertical_alignment="center",
        gap="small",
    ):
        st.feedback(
            "thumbs",
            key=f"fb-{chat['key']}-{index}",
            default={"up": 1, "down": 0}.get(message.get("feedback") or ""),
            on_change=_on_feedback,
            args=(chat["key"], index),
        )
        with st.popover("Share", icon=":material/ios_share:", type="tertiary"):
            text = export_markdown(chat, index)
            st.caption("Copy the answer with its sources, or download it.")
            st.code(text, language="markdown", wrap_lines=True, height=240)
            st.download_button(
                "Download Markdown",
                data=text,
                file_name=f"alarm-copilot-{response.get('trace_id', 'answer')[:18]}.md",
                mime="text/markdown",
                icon=":material/download:",
                key=f"dl-{chat['key']}-{index}",
                on_click="ignore",
            )
        st.button(
            "Evidence",
            key=f"ev-{chat['key']}-{index}",
            icon=":material/fact_check:",
            type="tertiary",
            disabled=open_now,
            on_click=show_evidence,
            args=(index,),
        )
        st.caption(_answer_stats(response))


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}{'' if count == 1 else 's'}"


def _answer_stats(response: dict[str, Any]) -> str:
    parts = [
        _plural(len(response.get("mcp_trace") or []), "tool call"),
        _plural(len(response.get("citations") or []), "source"),
    ]
    if response.get("duration_ms"):
        parts.append(f"{response['duration_ms'] / 1000:.1f}s")
    return " · ".join(parts)


def export_markdown(chat: dict[str, Any], index: int) -> str:
    """One answer as a self-contained Markdown note, sources included."""
    message = chat["messages"][index]
    response = message.get("response") or {}
    question = next(
        (m["content"] for m in reversed(chat["messages"][:index]) if m["role"] == "user"), ""
    )
    lines = ["# Incident & Ticket Enrichment Copilot", ""]
    if question:
        lines += [f"**Question:** {question}", ""]
    lines += [message["content"], ""]

    created = response.get("created_ticket")
    if created:
        lines += [f"**Ticket:** {created['key']} ({created['priority']}, {created['status']})", ""]
    citations = response.get("citations") or []
    if citations:
        lines.append("## Sources")
        lines += [
            f"- {c['marker']} {c['doc_id']}, {c['title']} (`{c['source_path']}`)" for c in citations
        ]
        lines.append("")
    trace = response.get("mcp_trace") or []
    if trace:
        lines.append("## MCP tools called")
        lines += [
            f"{s['sequence']}. `{s['tool']}`: {s.get('status')}, {s.get('duration_ms', 0):.0f} ms"
            for s in trace
        ]
        lines.append("")
    lines.append(
        f"_Trace `{response.get('trace_id', '')}` · conversation `{chat['conversation_id']}`_"
    )
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Ticket draft and created ticket
# --------------------------------------------------------------------------
def render_draft(
    client: CopilotClient, chat: dict[str, Any], index: int, draft: dict[str, Any]
) -> None:
    draft_id = draft["draft_id"]
    decision = chat["decisions"].get(draft_id)
    if decision == "declined":
        with st.container(horizontal=True, vertical_alignment="center", gap="small"):
            st.caption("Draft discarded. Nothing was written.")
            st.button(
                "Reopen draft",
                key=f"reopen-{draft_id}",
                type="tertiary",
                icon=":material/undo:",
                on_click=lambda: chat["decisions"].pop(draft_id, None),
            )
        return
    if decision:
        st.caption(f"Approved and created as **{decision}**.")
        return

    with st.container(border=True, key=f"draft-{draft_id}"):
        st.html('<div class="card-kicker">Incident draft · awaiting your approval</div>')
        st.caption(
            "Nothing has been written yet. Edit anything below, then approve. "
            "The copilot cannot create a ticket on its own."
        )
        with st.form(key=f"form-{draft_id}", border=False):
            title = st.text_input("Title", value=draft["title"], max_chars=300)
            col_a, col_b = st.columns(2)
            priorities = ["P1", "P2", "P3", "P4"]
            priority = col_a.selectbox(
                "Priority", priorities, index=priorities.index(draft.get("priority", "P3"))
            )
            assignee = col_b.text_input("Assignee", value=draft.get("assignee") or "")
            labels_text = st.text_input(
                "Labels (comma separated)", value=", ".join(draft.get("labels") or [])
            )
            description = st.text_area("Description", value=draft["description"], height=320)
            st.caption(
                f"Asset `{draft.get('asset_id')}` · alarms "
                f"{', '.join(draft.get('linked_alarm_ids') or []) or 'none'} · "
                f"{len(draft.get('citations') or [])} citation(s) attached"
            )
            with st.container(horizontal=True, gap="small"):
                approve = st.form_submit_button(
                    "Approve and create ticket", type="primary", icon=":material/check:"
                )
                decline = st.form_submit_button("Discard", icon=":material/close:")

    if approve or decline:
        with st.spinner("Submitting your decision…"):
            result = client.approve(
                conversation_id=chat["conversation_id"],
                draft_id=draft_id,
                approved=bool(approve),
                title=title,
                description=description,
                priority=priority,
                assignee=assignee or None,
                labels=[label.strip() for label in labels_text.split(",") if label.strip()],
            )
        if not result.ok:
            st.error(result.error)
            return
        payload = result.payload
        created = payload.get("created_ticket")
        chat["decisions"][draft_id] = created["key"] if created else "declined"
        chat["messages"].append(
            {
                "role": "assistant",
                "content": payload["message"],
                "response": payload,
                "approval": True,
            }
        )
        chat["updated"] = time.time()
        st.session_state.evidence_index = None
        st.rerun()


def render_ticket_card(ticket: dict[str, Any], draft: dict[str, Any] | None, *, key: str) -> None:
    with st.container(border=True, key=f"ticket-{key}"):
        st.html('<div class="card-kicker">Ticket in the ticketing system</div>')
        with st.container(horizontal=True, vertical_alignment="center", gap="small"):
            st.html(f'<span class="ticket-key">{escape(ticket["key"])}</span>', width="content")
            st.badge(
                ticket["priority"],
                color="red" if ticket["priority"] in {"P1", "P2"} else "orange",
            )
            st.badge(ticket["status"], color="green")
            if not ticket["created"]:
                st.badge("existing ticket, no duplicate", color="gray")
        st.markdown(f"**{ticket['title']}**")
        st.caption(
            f"Written through the MCP `create_ticket` tool after your approval · "
            f"`{ticket['url_path']}`"
        )
        if draft:
            with st.expander("Approved content"):
                st.caption(
                    f"Assignee {draft.get('assignee') or 'unassigned'} · labels "
                    f"{', '.join(draft.get('labels') or []) or 'none'} · asset "
                    f"`{draft.get('asset_id')}`"
                )
                st.markdown(draft["description"])


# --------------------------------------------------------------------------
# Evidence panel
# --------------------------------------------------------------------------
def render_evidence(client: CopilotClient, chat: dict[str, Any], index: int) -> None:
    messages = chat["messages"]
    response = messages[index]["response"]
    question = next((m["content"] for m in reversed(messages[:index]) if m["role"] == "user"), "")
    with st.container(key="evidence-panel"):
        with st.container(horizontal=True, vertical_alignment="center", gap="small"):
            st.markdown("**Evidence**")
            st.space("stretch")
            st.button(
                "",
                key="close-panel",
                icon=":material/close:",
                type="tertiary",
                help="Hide the evidence panel",
                on_click=hide_evidence,
            )
        if question:
            st.caption(f"For: “{_shorten(question, 110)}”")
        meta = [f"intent {response.get('intent')}"]
        if response.get("tools_discovered"):
            meta.append(f"{response['tools_discovered']} tools available")
        if response.get("duration_ms"):
            meta.append(f"{response['duration_ms']:.0f} ms")
        meta.append(f"trace {response.get('trace_id', '')}")
        st.html(f'<div class="evidence-meta">{escape(" · ".join(meta))}</div>')
        _degradation(response)
        _alarm(response)

        trace = response.get("mcp_trace") or []
        citations = response.get("citations") or []
        tabs = st.tabs(
            [f"Sources ({len(citations)})", f"MCP trace ({len(trace)})", "Tickets", "Audit"]
        )
        with tabs[0]:
            _citations(response)
        with tabs[1]:
            _plan(response)
            _mcp_trace(trace)
        with tabs[2]:
            _similar_tickets(response)
            _linked_tickets(response)
        with tabs[3]:
            _audit(client, chat["conversation_id"])


def _degradation(response: dict[str, Any]) -> None:
    notices = response.get("degraded") or []
    if notices:
        with st.expander(f"{len(notices)} degradation notice(s)", icon=":material/warning:"):
            for notice in notices:
                st.warning(f"**{notice['component']}** — {notice['detail']}")
                st.caption(notice["impact"])


def _alarm(response: dict[str, Any]) -> None:
    alarm = response.get("alarm")
    alarms = response.get("alarms") or []
    if not alarm:
        return
    band = alarm.get("priority_band") or "—"
    st.html(
        f'<div class="alarm-line"><span class="alarm-band">{escape(str(band))}</span>'
        f"<b>{escape(alarm['alarm_name'])}</b> on {escape(alarm['asset_name'])}</div>"
    )
    a, b, c = st.columns(3)
    score = alarm.get("priority_score")
    a.metric("Priority", f"{score:.0f}/100" if score else "—")
    b.metric("Severity", alarm.get("severity", "—"))
    c.metric("In 90 days", alarm.get("occurrences_last_90_days") or "—")
    details = (
        f"{alarm['site']} / {alarm['unit']} · `{alarm['alarm_id']}` · status {alarm['status']}"
    )
    if alarm.get("measured_value") is not None:
        unit = alarm.get("unit_of_measure") or ""
        details += (
            f" · reading {alarm['measured_value']} {unit} against a limit of "
            f"{alarm.get('limit_value')} {unit}"
        )
    st.caption(details)
    if alarm.get("priority_rationale"):
        st.caption(alarm["priority_rationale"])
    if len(alarms) > 1:
        with st.expander(f"Other open alarms considered ({len(alarms) - 1})"):
            for other in alarms[1:]:
                st.markdown(
                    f"- **{other['priority_band']}** ({other['priority_score']:.0f}) "
                    f"{other['alarm_name']} on {other['asset_name']}"
                )


def _citations(response: dict[str, Any]) -> None:
    citations = response.get("citations") or []
    if not citations:
        st.caption("No documents were cited for this answer.")
        return
    for citation in citations:
        heading = f" > {citation['heading']}" if citation.get("heading") else ""
        with st.expander(
            f"{citation['marker']} **{citation['doc_id']}** {citation['title']}{heading}"
        ):
            st.caption(
                f"{citation['doc_type']} · `{citation['source_path']}` · "
                f"relevance {citation['score']:.3f}"
            )
            st.markdown(f"> {citation['excerpt']}")


def _mcp_trace(trace: list[dict[str, Any]]) -> None:
    if not trace:
        st.caption("No tools were called for this answer.")
        return
    a, b, c = st.columns(3)
    a.metric("Tool calls", len(trace))
    b.metric("Upstream calls", sum(s.get("upstream_calls", 0) for s in trace))
    c.metric("Total", f"{sum(s.get('duration_ms', 0) for s in trace):.0f} ms")
    for step in trace:
        with st.expander(
            f"{step['sequence']}. `{step['tool']}` · {step.get('duration_ms', 0):.0f} ms",
            icon=STATUS_ICON.get(step.get("status", ""), ":material/radio_button_unchecked:"),
            expanded=step.get("status") != "ok",
        ):
            st.caption(
                f"source: {step.get('source_system') or 'n/a'} · "
                f"upstream calls: {step.get('upstream_calls', 0)} · "
                f"trace: `{step.get('trace_id', '')}`"
            )
            st.json(step.get("arguments") or {}, expanded=False)
            if step.get("error"):
                st.error(step["error"])


def _similar_tickets(response: dict[str, Any]) -> None:
    tickets = response.get("similar_tickets") or []
    st.markdown("**Similar historical tickets**")
    if not tickets:
        st.caption("No comparable ticket cleared the similarity threshold.")
        return
    for ticket in tickets:
        with st.expander(f"`{ticket['key']}` {ticket['title']} · {ticket['score']:.2f}"):
            st.caption(
                f"{ticket['status']} · {ticket['priority']} · "
                f"matched on {', '.join(ticket['matched_on'])}"
            )
            if ticket.get("root_cause"):
                st.markdown(f"**Root cause.** {ticket['root_cause']}")
            if ticket.get("resolution"):
                st.markdown(f"**Resolution.** {ticket['resolution']}")
            if ticket.get("time_to_resolve_hours"):
                st.caption(f"Resolved in {ticket['time_to_resolve_hours']:.1f} h")


def _linked_tickets(response: dict[str, Any]) -> None:
    tickets = response.get("open_linked_tickets") or []
    if not tickets:
        return
    st.markdown("**Open tickets on linked assets**")
    st.caption("ESC-010 §7 asks that related work be linked rather than duplicated.")
    for ticket in tickets:
        st.markdown(
            f"- `{ticket['key']}` **[{ticket['priority']}/{ticket['status']}]** {ticket['title']}"
        )


def _plan(response: dict[str, Any]) -> None:
    plan = response.get("plan") or {}
    with st.expander(f"Plan · intent `{plan.get('intent')}` · by `{plan.get('source')}`"):
        if plan.get("reasoning"):
            st.caption(plan["reasoning"])
        steps = plan.get("steps") or []
        if not steps:
            st.caption("No tool steps were planned.")
        for number, step in enumerate(steps, start=1):
            optional = " _(optional)_" if step.get("optional") else ""
            st.markdown(f"{number}. `{step['tool']}`{optional} — {step.get('why', '')}")


def _audit(client: CopilotClient, conversation_id: str | None) -> None:
    if not conversation_id:
        return
    result = client.audit(conversation_id)
    if not result.ok:
        st.caption(result.error)
        return
    entries = result.payload.get("entries") or []
    if not entries:
        st.caption("No audited actions yet.")
    for entry in entries:
        st.markdown(
            f"`{entry['timestamp'][11:19]}` **{entry['actor']}** · "
            f"`{entry['action']}` — {entry['detail']}"
        )


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def main() -> None:
    init_state()
    apply_abb_theme()
    client = get_client()
    open_status = render_sidebar(client)

    chat = current_chat()
    if chat is None or not chat["messages"]:
        render_welcome()
    else:
        render_chat_view(client, chat)

    # Streamlit shows one dialog at a time.
    if st.session_state.feedback_target:
        feedback_dialog()
    elif st.session_state.ticket_view:
        ticket_dialog()
    elif open_status:
        status_dialog(client)


main()
