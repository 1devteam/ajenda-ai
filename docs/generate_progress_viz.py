"""
Ajenda AI — Project Progress & Gap Visualization
Generates a multi-panel dashboard PNG.
"""

import matplotlib

matplotlib.use("Agg")
import matplotlib.gridspec as gridspec
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import FancyBboxPatch
from matplotlib.ticker import MaxNLocator

# ─────────────────────────────────────────────
# COLOUR PALETTE
# ─────────────────────────────────────────────
DARK_BG = "#0d1117"
PANEL_BG = "#161b22"
BORDER = "#30363d"
GREEN = "#3fb950"
AMBER = "#d29922"
RED = "#f85149"
BLUE = "#58a6ff"
PURPLE = "#bc8cff"
TEAL = "#39d353"
MUTED = "#8b949e"
WHITE = "#e6edf3"

plt.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "font.size": 9,
        "text.color": WHITE,
        "axes.facecolor": PANEL_BG,
        "axes.edgecolor": BORDER,
        "axes.labelcolor": WHITE,
        "xtick.color": MUTED,
        "ytick.color": MUTED,
        "grid.color": BORDER,
        "figure.facecolor": DARK_BG,
        "legend.facecolor": PANEL_BG,
        "legend.edgecolor": BORDER,
    }
)

fig = plt.figure(figsize=(20, 24))
fig.patch.set_facecolor(DARK_BG)

gs = gridspec.GridSpec(4, 3, figure=fig, hspace=0.52, wspace=0.38, top=0.93, bottom=0.04, left=0.06, right=0.97)

# ─────────────────────────────────────────────
# TITLE
# ─────────────────────────────────────────────
fig.text(
    0.5,
    0.965,
    "Ajenda AI  ·  Project Progress & Gap Report",
    ha="center",
    va="center",
    fontsize=22,
    fontweight="bold",
    color=WHITE,
)
fig.text(
    0.5, 0.948, "Branch: main  ·  Version: 1.1.0  ·  April 2026", ha="center", va="center", fontsize=11, color=MUTED
)

# ══════════════════════════════════════════════
# PANEL 1 — Architectural Layer Completeness (horizontal bar)
# ══════════════════════════════════════════════
ax1 = fig.add_subplot(gs[0, :2])
ax1.set_facecolor(PANEL_BG)

layers = [
    ("Security Middleware Stack", 100, GREEN),
    ("Auth (JWT + API Keys + RBAC)", 100, GREEN),
    ("Multi-Tenancy (RLS + Middleware)", 100, GREEN),
    ("SaaS Lifecycle (Provision/Suspend/Delete)", 100, GREEN),
    ("Quota Enforcement (Per-Task)", 100, GREEN),
    ("Regulatory Compliance Layer", 100, GREEN),
    ("Resilient Runtime (Recovering/DLQ)", 100, GREEN),
    ("Database Migrations (6 total)", 100, GREEN),
    ("CI/CD Pipeline", 0, RED),
    ("Webhook / Event Delivery", 0, RED),
    ("Production IaC (Terraform/K8s)", 0, RED),
    ("Admin Control Plane UI", 10, AMBER),
]

layers_rev = list(reversed(layers))
names = [l[0] for l in layers_rev]
values = [l[1] for l in layers_rev]
colors = [l[2] for l in layers_rev]

y_pos = np.arange(len(names))
bars = ax1.barh(y_pos, values, height=0.6, color=colors, alpha=0.85)

# Background track
ax1.barh(y_pos, [100] * len(names), height=0.6, color=BORDER, alpha=0.4, zorder=0)

ax1.set_xlim(0, 115)
ax1.set_yticks(y_pos)
ax1.set_yticklabels(names, fontsize=9)
ax1.set_xlabel("Completion (%)", color=MUTED, fontsize=9)
ax1.set_title("Architectural Layer Completeness", color=WHITE, fontsize=12, fontweight="bold", pad=10)
ax1.tick_params(axis="x", colors=MUTED)
ax1.spines["top"].set_visible(False)
ax1.spines["right"].set_visible(False)
ax1.spines["left"].set_color(BORDER)
ax1.spines["bottom"].set_color(BORDER)
ax1.grid(axis="x", alpha=0.2)

for bar, val in zip(bars, values):
    label = f"{val}%" if val > 0 else "Not Started"
    ax1.text(val + 1.5, bar.get_y() + bar.get_height() / 2, label, va="center", color=WHITE, fontsize=8.5)

legend_patches = [
    mpatches.Patch(color=GREEN, label="Complete"),
    mpatches.Patch(color=AMBER, label="In Progress"),
    mpatches.Patch(color=RED, label="Not Started"),
]
ax1.legend(handles=legend_patches, loc="lower right", fontsize=8.5)

# ══════════════════════════════════════════════
# PANEL 2 — Test Suite Breakdown (donut)
# ══════════════════════════════════════════════
ax2 = fig.add_subplot(gs[0, 2])
ax2.set_facecolor(PANEL_BG)
ax2.set_aspect("equal")

test_labels = ["Unit\n(36 files)", "Integration\n(33 files)", "Contract\n(2 files)", "Deployment\n(1 file)"]
test_counts = [162, 42, 6, 4]
test_colors = [BLUE, PURPLE, TEAL, AMBER]

wedges, texts, autotexts = ax2.pie(
    test_counts,
    labels=test_labels,
    autopct="%1.0f%%",
    colors=test_colors,
    startangle=90,
    pctdistance=0.78,
    wedgeprops={"width": 0.52, "edgecolor": DARK_BG, "linewidth": 2},
    textprops={"color": WHITE, "fontsize": 8},
)
for at in autotexts:
    at.set_color(DARK_BG)
    at.set_fontweight("bold")
    at.set_fontsize(8)

ax2.text(0, 0, "214\nTests", ha="center", va="center", fontsize=14, fontweight="bold", color=GREEN)
ax2.set_title("Test Suite Breakdown\n(214 passed · 0 failed)", color=WHITE, fontsize=12, fontweight="bold", pad=10)

# ══════════════════════════════════════════════
# PANEL 3 — PR Merge Timeline (scatter/timeline)
# ══════════════════════════════════════════════
ax3 = fig.add_subplot(gs[1, :])
ax3.set_facecolor(PANEL_BG)

prs = [
    (1, "Apr 2", "#1 P0+P1 Remediation\n(5 critical fixes)", GREEN, 1),
    (2, "Apr 3", "#2 Phase 2 Enterprise SaaS\nArchitecture", BLUE, 2),
    (4, "Apr 3", "#4 Security\n(Remove hardcoded secrets)", AMBER, 1),
    (9, "Apr 3", "#9 Phase 3 Advanced\n(RLS, Recovering, Testcontainers)", PURPLE, 3),
    (7, "Apr 3", "#7 Compliance Layer\n(EU AI Act, CO SB24-205)", TEAL, 2),
    (8, "Apr 7", "#8 SaaS Multi-Tenancy\n(162 → 214 tests)", GREEN, 3),
]

x_positions = [1, 2, 3, 4, 5, 6]
y_base = 2

ax3.axhline(y=y_base, color=BORDER, linewidth=2, zorder=1)

for i, (pr_num, date, label, color, size_tier) in enumerate(prs):
    x = x_positions[i]
    dot_size = [120, 200, 320][size_tier - 1]
    ax3.scatter(x, y_base, s=dot_size, color=color, zorder=3, edgecolors=DARK_BG, linewidth=2)
    ax3.text(x, y_base + 0.18, date, ha="center", va="bottom", color=MUTED, fontsize=8)
    ax3.text(
        x,
        y_base - 0.22,
        label,
        ha="center",
        va="top",
        color=WHITE,
        fontsize=7.8,
        multialignment="center",
        bbox=dict(boxstyle="round,pad=0.3", facecolor=PANEL_BG, edgecolor=color, linewidth=1),
    )

ax3.set_xlim(0.3, 6.7)
ax3.set_ylim(0.8, 3.5)
ax3.set_yticks([])
ax3.set_xticks([])
ax3.spines["top"].set_visible(False)
ax3.spines["right"].set_visible(False)
ax3.spines["left"].set_visible(False)
ax3.spines["bottom"].set_color(BORDER)
ax3.set_title(
    "Pull Request Merge Timeline  (6 PRs merged to main)", color=WHITE, fontsize=12, fontweight="bold", pad=10
)

# ══════════════════════════════════════════════
# PANEL 4 — Test Growth Over PRs (line chart)
# ══════════════════════════════════════════════
ax4 = fig.add_subplot(gs[2, :2])
ax4.set_facecolor(PANEL_BG)

pr_labels = [
    "Phase 1\n(baseline)",
    "PR #1\nRemediation",
    "PR #2\nPhase 2",
    "PR #4\nSecurity",
    "PR #9\nPhase 3",
    "PR #7\nCompliance",
    "PR #8\nSaaS",
]
test_totals = [85, 95, 110, 112, 130, 162, 214]
failures = [10, 0, 0, 0, 0, 0, 0]

x = np.arange(len(pr_labels))

ax4.fill_between(x, test_totals, alpha=0.15, color=GREEN)
ax4.plot(x, test_totals, color=GREEN, linewidth=2.5, marker="o", markersize=7, label="Tests Passing", zorder=3)
ax4.fill_between(x, failures, alpha=0.25, color=RED)
ax4.plot(x, failures, color=RED, linewidth=2, marker="s", markersize=6, linestyle="--", label="Failures", zorder=3)

for xi, (total, fail) in enumerate(zip(test_totals, failures)):
    ax4.annotate(
        str(total),
        (xi, total),
        textcoords="offset points",
        xytext=(0, 8),
        ha="center",
        color=GREEN,
        fontsize=8.5,
        fontweight="bold",
    )

ax4.set_xticks(x)
ax4.set_xticklabels(pr_labels, fontsize=8.5)
ax4.set_ylabel("Test Count", color=MUTED)
ax4.set_title("Test Suite Growth Across PRs", color=WHITE, fontsize=12, fontweight="bold", pad=10)
ax4.legend(fontsize=9)
ax4.spines["top"].set_visible(False)
ax4.spines["right"].set_visible(False)
ax4.spines["left"].set_color(BORDER)
ax4.spines["bottom"].set_color(BORDER)
ax4.grid(axis="y", alpha=0.2)
ax4.yaxis.set_major_locator(MaxNLocator(integer=True))
ax4.set_ylim(-5, 240)

# ══════════════════════════════════════════════
# PANEL 5 — Gap Priority Matrix (bubble chart)
# ══════════════════════════════════════════════
ax5 = fig.add_subplot(gs[2, 2])
ax5.set_facecolor(PANEL_BG)

# x = effort (1=low, 5=high), y = impact (1=low, 5=high), size = urgency
gaps = [
    ("CI/CD\nPipeline", 1.2, 4.8, 600, RED),
    ("Webhook /\nEvent Delivery", 2.5, 4.2, 450, AMBER),
    ("Production\nIaC", 4.0, 4.5, 400, AMBER),
    ("Admin\nUI", 3.2, 3.0, 300, BLUE),
]

for label, effort, impact, size, color in gaps:
    ax5.scatter(effort, impact, s=size, color=color, alpha=0.75, edgecolors=DARK_BG, linewidth=2, zorder=3)
    ax5.text(effort, impact + 0.28, label, ha="center", va="bottom", color=WHITE, fontsize=8, multialignment="center")

ax5.set_xlim(0, 5.5)
ax5.set_ylim(2, 5.5)
ax5.set_xlabel("Implementation Effort  →", color=MUTED, fontsize=8.5)
ax5.set_ylabel("Business Impact  →", color=MUTED, fontsize=8.5)
ax5.set_title("Gap Priority Matrix", color=WHITE, fontsize=12, fontweight="bold", pad=10)
ax5.spines["top"].set_visible(False)
ax5.spines["right"].set_visible(False)
ax5.spines["left"].set_color(BORDER)
ax5.spines["bottom"].set_color(BORDER)
ax5.grid(alpha=0.15)

# Quadrant labels
ax5.text(0.5, 5.35, "Quick Wins", color=GREEN, fontsize=7.5, alpha=0.7)
ax5.text(3.5, 5.35, "Strategic Bets", color=AMBER, fontsize=7.5, alpha=0.7)
ax5.axvline(x=2.75, color=BORDER, linestyle="--", alpha=0.5)
ax5.axhline(y=3.75, color=BORDER, linestyle="--", alpha=0.5)

# ══════════════════════════════════════════════
# PANEL 6 — Overall Completion Gauge (bottom row)
# ══════════════════════════════════════════════
ax6 = fig.add_subplot(gs[3, :])
ax6.set_facecolor(PANEL_BG)
ax6.set_aspect("auto")
ax6.axis("off")

# Draw a horizontal progress bar across the full width
bar_y = 0.55
bar_h = 0.25
total_complete = 8  # layers complete
total_layers = 12  # total layers

pct = total_complete / total_layers

# Background
ax6.add_patch(
    FancyBboxPatch(
        (0.02, bar_y),
        0.96,
        bar_h,
        boxstyle="round,pad=0.01",
        facecolor=BORDER,
        edgecolor=BORDER,
        transform=ax6.transAxes,
    )
)

# Fill
fill_w = 0.96 * pct
ax6.add_patch(
    FancyBboxPatch(
        (0.02, bar_y),
        fill_w,
        bar_h,
        boxstyle="round,pad=0.01",
        facecolor=GREEN,
        edgecolor=GREEN,
        alpha=0.85,
        transform=ax6.transAxes,
    )
)

# Amber gap segment
gap_start = 0.02 + fill_w
gap_w = 0.96 * (1 / 12)  # admin UI partial
ax6.add_patch(
    FancyBboxPatch(
        (gap_start, bar_y),
        gap_w,
        bar_h,
        boxstyle="round,pad=0.01",
        facecolor=AMBER,
        edgecolor=AMBER,
        alpha=0.6,
        transform=ax6.transAxes,
    )
)

ax6.text(
    0.5,
    bar_y + bar_h + 0.12,
    f"Overall Platform Completeness:  {total_complete}/{total_layers} Layers  ({pct * 100:.0f}%)",
    ha="center",
    va="bottom",
    transform=ax6.transAxes,
    fontsize=13,
    fontweight="bold",
    color=WHITE,
)

ax6.text(
    0.5,
    bar_y - 0.22,
    "8 of 12 architectural layers complete  ·  4 gaps remaining  ·  CI/CD is highest-priority unblocked action",
    ha="center",
    va="top",
    transform=ax6.transAxes,
    fontsize=9.5,
    color=MUTED,
)

# ─────────────────────────────────────────────
# SAVE
# ─────────────────────────────────────────────
output_path = "/home/ubuntu/ajenda-repo/docs/ajenda_progress_report.png"
plt.savefig(output_path, dpi=150, bbox_inches="tight", facecolor=DARK_BG)
print(f"Saved: {output_path}")
