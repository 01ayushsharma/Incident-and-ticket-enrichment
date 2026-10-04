"""Render docs/architecture-diagram.png.

    python scripts/generate_architecture_diagram.py

Generated rather than drawn by hand so it cannot drift from the codebase
without someone editing this file. Uses matplotlib, which is already an
indirect dependency, so it adds nothing to the install.

The diagram must show, per the submission guidelines: the GUI, copilot
orchestration, MCP client, MCP server, the Alarm Management API, the
secondary source, the RAG ingestion pipeline, the retrieval index, the
document store, observability, and the authentication boundaries.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.patches as patches
import matplotlib.pyplot as plt

OUTPUT = Path(__file__).resolve().parents[1] / "docs" / "architecture-diagram.png"

# A restrained palette: one hue per concern, mid-tone so black text reads on
# every box and the whole thing survives greyscale printing.
COLOURS = {
    "gui": "#4C6EF5",
    "copilot": "#7048E8",
    "mcp": "#0CA678",
    "source": "#E8590C",
    "rag": "#1098AD",
    "store": "#868E96",
    "obs": "#495057",
}


def box(
    ax,
    x,
    y,
    w,
    h,
    label,
    sublabel="",
    colour="#495057",
    text_colour="white",
    fontsize=9.5,
    radius=0.02,
):
    ax.add_patch(
        patches.FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle=f"round,pad=0.003,rounding_size={radius}",
            linewidth=0,
            facecolor=colour,
            zorder=2,
        )
    )
    centre_y = y + h / 2
    if sublabel:
        ax.text(
            x + w / 2,
            centre_y + 0.018,
            label,
            ha="center",
            va="center",
            fontsize=fontsize,
            fontweight="bold",
            color=text_colour,
            zorder=3,
        )
        ax.text(
            x + w / 2,
            centre_y - 0.022,
            sublabel,
            ha="center",
            va="center",
            fontsize=fontsize - 2.3,
            color=text_colour,
            alpha=0.92,
            zorder=3,
        )
    else:
        ax.text(
            x + w / 2,
            centre_y,
            label,
            ha="center",
            va="center",
            fontsize=fontsize,
            fontweight="bold",
            color=text_colour,
            zorder=3,
        )


def arrow(
    ax,
    start,
    end,
    label="",
    colour="#343A40",
    style="-|>",
    offset=0.012,
    fontsize=7.6,
    dashed=False,
):
    ax.annotate(
        "",
        xy=end,
        xytext=start,
        arrowprops={
            "arrowstyle": style,
            "color": colour,
            "linewidth": 1.5,
            "shrinkA": 2,
            "shrinkB": 2,
            "linestyle": "--" if dashed else "-",
            "connectionstyle": "arc3,rad=0",
        },
        zorder=4,
    )
    if label:
        mid_x = (start[0] + end[0]) / 2
        mid_y = (start[1] + end[1]) / 2
        ax.text(
            mid_x + offset,
            mid_y,
            label,
            ha="left",
            va="center",
            fontsize=fontsize,
            color=colour,
            zorder=5,
            bbox={"facecolor": "white", "edgecolor": "none", "pad": 1.2, "alpha": 0.9},
        )


def boundary(ax, x, y, w, h, label):
    """A dashed authentication boundary."""
    ax.add_patch(
        patches.FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle="round,pad=0.006,rounding_size=0.015",
            linewidth=1.4,
            edgecolor="#C92A2A",
            facecolor="none",
            linestyle=(0, (5, 3)),
            zorder=1,
        )
    )
    # Above the rectangle, not inside it: inside collides with the first box.
    ax.text(
        x + 0.004,
        y + h + 0.008,
        label,
        ha="left",
        va="bottom",
        fontsize=7.4,
        color="#C92A2A",
        fontweight="bold",
        zorder=3,
    )


def build() -> None:
    fig, ax = plt.subplots(figsize=(14.5, 10.5), dpi=170)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    fig.patch.set_facecolor("white")

    ax.text(
        0.5,
        0.975,
        "Incident and Ticket Enrichment Copilot",
        ha="center",
        fontsize=16,
        fontweight="bold",
        color="#212529",
    )
    ax.text(
        0.5,
        0.949,
        "Alarm data reached exclusively through MCP  ·  answers grounded in "
        "retrieved documents  ·  ticket writes gated on human approval",
        ha="center",
        fontsize=9,
        color="#868E96",
    )

    # ---- GUI ------------------------------------------------------------
    box(
        ax,
        0.30,
        0.862,
        0.40,
        0.056,
        "Streamlit GUI  :8501",
        "chat · ticket preview · citations · MCP trace · approval · audit",
        COLOURS["gui"],
        fontsize=10,
    )

    # ---- Copilot backend -------------------------------------------------
    boundary(
        ax,
        0.055,
        0.575,
        0.60,
        0.232,
        "AUTH BOUNDARY — no source-system credential exists in this process",
    )
    box(
        ax,
        0.075,
        0.745,
        0.56,
        0.048,
        "Copilot backend  :8080   (FastAPI)",
        "POST /chat · POST /tickets/approve · GET /tools · GET /health · audit",
        COLOURS["copilot"],
        fontsize=10,
    )

    box(
        ax,
        0.088,
        0.672,
        0.155,
        0.062,
        "Orchestrator",
        "planner\nintent · plan · validate",
        COLOURS["copilot"],
        fontsize=8.6,
    )
    box(
        ax,
        0.265,
        0.672,
        0.155,
        0.062,
        "Workflow",
        "multi-step chaining\nstate threading",
        COLOURS["copilot"],
        fontsize=8.6,
    )
    box(
        ax,
        0.442,
        0.672,
        0.180,
        0.062,
        "Drafting + synthesis",
        "ESC-010 template\ngrounded answer",
        COLOURS["copilot"],
        fontsize=8.6,
    )

    box(
        ax,
        0.082,
        0.594,
        0.255,
        0.05,
        "MCP client + tool registry",
        "discovery · validation · trace · partial failure",
        COLOURS["mcp"],
        fontsize=8.8,
    )
    box(
        ax,
        0.355,
        0.594,
        0.267,
        0.05,
        "Retrieval service",
        "hybrid search · filters · citations · injection defence",
        COLOURS["rag"],
        fontsize=8.8,
    )

    # ---- LLM provider ----------------------------------------------------
    box(
        ax,
        0.70,
        0.672,
        0.26,
        0.062,
        "LLM provider (replaceable)",
        "fake · ollama · gemini · anthropic · openai\ndefault: deterministic, no key",
        "#5F3DC4",
        fontsize=8.6,
    )
    arrow(ax, (0.622, 0.700), (0.70, 0.700), "", colour="#5F3DC4")
    ax.text(
        0.661,
        0.716,
        "plan +\nsynthesis",
        ha="center",
        va="center",
        fontsize=7.2,
        color="#5F3DC4",
        zorder=5,
    )

    # ---- MCP server ------------------------------------------------------
    boundary(
        ax,
        0.055,
        0.340,
        0.40,
        0.168,
        "AUTH BOUNDARY — both source-system credentials live here only",
    )
    box(
        ax,
        0.075,
        0.428,
        0.36,
        0.062,
        "MCP server  :9000",
        "20 typed tools · streamable HTTP or stdio · independently runnable",
        COLOURS["mcp"],
        fontsize=10,
    )
    # Single-line sublabels: a second line overflows a box this short.
    box(
        ax,
        0.075,
        0.362,
        0.172,
        0.052,
        "Tool contracts",
        "typed schemas · projection",
        COLOURS["mcp"],
        fontsize=8.2,
    )
    box(
        ax,
        0.263,
        0.362,
        0.172,
        0.052,
        "Connectors",
        "auth · retry · timeout",
        COLOURS["mcp"],
        fontsize=8.2,
    )

    # ---- Source systems --------------------------------------------------
    box(
        ax,
        0.055,
        0.225,
        0.19,
        0.072,
        "Alarm Management API  :8000",
        "28 assets · 5,024 alarms\nsearch · summary · trends ·\ncorrelation · flood · KPI",
        COLOURS["source"],
        fontsize=8.4,
    )
    box(
        ax,
        0.265,
        0.225,
        0.19,
        0.072,
        "Ticketing API  :8100",
        "272 historical tickets\nsimilarity search\nWRITE TARGET",
        COLOURS["source"],
        fontsize=8.4,
    )

    # ---- RAG pipeline ----------------------------------------------------
    box(
        ax,
        0.525,
        0.432,
        0.22,
        0.062,
        "Retrieval index",
        "ChromaDB · 202 chunks\nONNX MiniLM + BM25",
        COLOURS["rag"],
        fontsize=8.6,
    )
    box(
        ax,
        0.525,
        0.336,
        0.22,
        0.058,
        "Ingestion pipeline",
        "extract · chunk · metadata\nembed · index",
        COLOURS["rag"],
        fontsize=8.6,
    )
    box(
        ax,
        0.525,
        0.234,
        0.22,
        0.058,
        "Document store",
        "rag/documents/ · 21 files\nprocedures · guides · notes",
        COLOURS["store"],
        fontsize=8.6,
    )

    # ---- Observability ---------------------------------------------------
    # Drawn by hand rather than through box(): the body is far taller than a
    # centred sublabel can hold without running into the title.
    box(ax, 0.785, 0.234, 0.175, 0.26, "", "", COLOURS["obs"])
    ax.text(
        0.8725,
        0.474,
        "Observability",
        ha="center",
        va="center",
        fontsize=9.5,
        fontweight="bold",
        color="white",
        zorder=3,
    )
    ax.text(
        0.8725,
        0.450,
        "structured JSON logs\n"
        "one line per event\n"
        "trace_id · request_id\n"
        "conversation_id\n"
        "mcp server · tool\n"
        "duration · outcome\n"
        "api status · retries\n"
        "retrieval score · docs\n"
        "llm latency · tokens\n"
        "secrets redacted",
        ha="center",
        va="top",
        fontsize=7.4,
        color="white",
        alpha=0.93,
        linespacing=1.95,
        zorder=3,
    )

    # ---- Flows -----------------------------------------------------------
    arrow(ax, (0.50, 0.862), (0.50, 0.795), "HTTP/JSON", colour=COLOURS["gui"])
    arrow(ax, (0.21, 0.596), (0.21, 0.492), "MCP protocol", colour=COLOURS["mcp"])
    arrow(ax, (0.487, 0.596), (0.525, 0.496), "query", colour=COLOURS["rag"])
    arrow(
        ax, (0.15, 0.356), (0.15, 0.299), "bearer + trace", colour=COLOURS["source"], fontsize=7.2
    )
    arrow(
        ax, (0.355, 0.356), (0.355, 0.299), "bearer + trace", colour=COLOURS["source"], fontsize=7.2
    )
    arrow(ax, (0.635, 0.292), (0.635, 0.334), "", colour=COLOURS["rag"])
    arrow(ax, (0.635, 0.394), (0.635, 0.430), "", colour=COLOURS["rag"])

    # Everything logs to observability.
    for y in (0.463, 0.393, 0.261):
        arrow(
            ax,
            (0.745, y),
            (0.785, y),
            "",
            colour=COLOURS["obs"],
            dashed=True,
        )
    arrow(ax, (0.455, 0.261), (0.525, 0.261), "", colour=COLOURS["obs"], dashed=True)

    # ---- The write path --------------------------------------------------
    ax.add_patch(
        patches.FancyBboxPatch(
            (0.055, 0.108),
            0.905,
            0.082,
            boxstyle="round,pad=0.008,rounding_size=0.015",
            linewidth=1.4,
            edgecolor="#C92A2A",
            facecolor="#FFF5F5",
            zorder=1,
        )
    )
    ax.text(
        0.075,
        0.170,
        "THE ONLY WRITE PATH",
        fontsize=8.6,
        fontweight="bold",
        color="#C92A2A",
        va="top",
    )
    ax.text(
        0.075,
        0.146,
        "POST /chat produces a DRAFT and cannot create a ticket under any plan.   "
        "Creation requires POST /tickets/approve with a draft the operator has seen "
        "and may edit.\n"
        "Three independent gates:   (1) MCP tool refuses unless approved=true   ·   "
        "(2) Ticketing API refuses unless confirmed=true   ·   "
        "(3) Idempotency-Key makes a replayed approval return the same ticket.",
        fontsize=8,
        color="#862E2E",
        va="top",
        linespacing=1.6,
    )

    # ---- Legend ----------------------------------------------------------
    ax.text(0.055, 0.062, "Data flow", fontsize=7.8, color="#495057", fontweight="bold")
    ax.plot([0.115, 0.155], [0.0635, 0.0635], color="#343A40", linewidth=1.5)
    ax.text(0.163, 0.062, "request", fontsize=7.6, color="#495057")
    ax.plot([0.215, 0.255], [0.0635, 0.0635], color=COLOURS["obs"], linewidth=1.5, linestyle="--")
    ax.text(0.263, 0.062, "telemetry", fontsize=7.6, color="#495057")
    ax.add_patch(
        patches.Rectangle(
            (0.33, 0.058),
            0.022,
            0.011,
            facecolor="none",
            edgecolor="#C92A2A",
            linestyle=(0, (4, 2)),
            linewidth=1.2,
        )
    )
    ax.text(0.36, 0.062, "authentication boundary", fontsize=7.6, color="#495057")

    ax.text(
        0.5,
        0.022,
        "Every process emits one structured JSON log line per event carrying the "
        "same trace_id, so a single grep reconstructs a request across all six.",
        ha="center",
        fontsize=7.8,
        color="#868E96",
        style="italic",
    )

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUTPUT, bbox_inches="tight", facecolor="white", dpi=170)
    plt.close(fig)
    print(f"wrote {OUTPUT.relative_to(OUTPUT.parents[1])} ({OUTPUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    build()
