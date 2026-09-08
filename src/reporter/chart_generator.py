"""
Chart Generator Module for QA Reports.

Generates static PNG chart images using Matplotlib for inclusion in HTML reports:
    - Pass Rate Trend across builds
    - Failure Count Trend across builds
    - Failure distribution by Module
    - Module Risk Scores

All functions handle missing/insufficient data gracefully by returning None.
"""

import os
from typing import Any, Dict, List, Optional
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # Non-interactive headless backend
import matplotlib.pyplot as plt


# ---------------------------------------------------------------------------
# Styling Constants
# ---------------------------------------------------------------------------

PRIMARY_COLOR = "#2563eb"     # Blue
DANGER_COLOR = "#dc2626"      # Red
WARNING_COLOR = "#d97706"     # Amber
SUCCESS_COLOR = "#16a34a"     # Green
NEUTRAL_COLOR = "#64748b"     # Slate Gray
BG_COLOR = "#ffffff"          # White
GRID_COLOR = "#f1f5f9"        # Very light slate grid
BORDER_COLOR = "#e2e8f0"      # Subtle border


def _setup_figure(width: float = 6.0, height: float = 3.5):
    """Initializes a styled Matplotlib figure and axis."""
    fig, ax = plt.subplots(figsize=(width, height), dpi=120)
    fig.patch.set_facecolor(BG_COLOR)
    ax.set_facecolor(BG_COLOR)
    ax.grid(True, linestyle="--", alpha=0.7, color=GRID_COLOR, zorder=0)
    for spine in ax.spines.values():
        spine.set_color(BORDER_COLOR)
        spine.set_linewidth(1.0)
    return fig, ax


# ---------------------------------------------------------------------------
# Public Chart Generators
# ---------------------------------------------------------------------------

def generate_pass_rate_chart(
    pass_rate_history: List[float],
    builds: List[int],
    output_path: str,
) -> Optional[str]:
    """
    Generates a line chart showing Pass Rate (%) trend across historical builds.

    Args:
        pass_rate_history: List of pass rates (oldest -> newest).
        builds: List of build numbers corresponding to pass rates.
        output_path: Target filepath for PNG output.

    Returns:
        The output_path if generated successfully, else None.
    """
    if not pass_rate_history or not builds or len(builds) < 2:
        return None

    try:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        fig, ax = _setup_figure(width=6.0, height=3.5)

        build_labels = [f"Build {b}" for b in builds]
        ax.plot(
            build_labels,
            pass_rate_history,
            marker="o",
            color=PRIMARY_COLOR,
            linewidth=2.5,
            markersize=6,
            markerfacecolor="#ffffff",
            markeredgecolor=PRIMARY_COLOR,
            markeredgewidth=2,
            zorder=3,
            label="Pass Rate (%)",
        )

        for i, (x, y) in enumerate(zip(build_labels, pass_rate_history)):
            ax.annotate(
                f"{y}%",
                (x, y),
                textcoords="offset points",
                xytext=(0, 9),
                ha="center",
                fontsize=8.5,
                fontweight="bold",
                color="#0f172a",
                bbox=dict(boxstyle="round,pad=0.2", fc="#eff6ff", ec="#bfdbfe", lw=0.8, alpha=0.9),
                zorder=4,
            )

        ax.set_ylim(-5, 108)
        ax.set_ylabel("Pass Rate (%)", fontsize=9, fontweight="bold", color="#334155")
        ax.set_title("Pass Rate Trend Across Builds", fontsize=11, fontweight="bold", pad=14, color="#0f172a")

        plt.xticks(rotation=15, fontsize=8.5, color="#475569")
        plt.yticks(fontsize=8.5, color="#475569")
        fig.tight_layout()
        fig.savefig(output_path, bbox_inches="tight", dpi=120)
        plt.close(fig)
        return output_path
    except Exception:
        plt.close("all")
        return None


def generate_failure_trend_chart(
    failure_history: List[int],
    builds: List[int],
    output_path: str,
) -> Optional[str]:
    """
    Generates a line/bar chart showing total failure count across historical builds.

    Args:
        failure_history: List of failure counts (oldest -> newest).
        builds: List of build numbers corresponding to failure counts.
        output_path: Target filepath for PNG output.

    Returns:
        The output_path if generated successfully, else None.
    """
    if not failure_history or not builds or len(builds) < 2:
        return None

    try:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        fig, ax = _setup_figure(width=6.0, height=3.5)

        build_labels = [f"Build {b}" for b in builds]
        ax.plot(
            build_labels,
            failure_history,
            marker="s",
            color=DANGER_COLOR,
            linewidth=2.5,
            markersize=6,
            markerfacecolor="#ffffff",
            markeredgecolor=DANGER_COLOR,
            markeredgewidth=2,
            zorder=3,
            label="Failures",
        )

        max_val = max(failure_history) if failure_history else 5
        for i, (x, y) in enumerate(zip(build_labels, failure_history)):
            ax.annotate(
                str(y),
                (x, y),
                textcoords="offset points",
                xytext=(0, 9),
                ha="center",
                fontsize=8.5,
                fontweight="bold",
                color="#991b1b",
                bbox=dict(boxstyle="round,pad=0.2", fc="#fef2f2", ec="#fecaca", lw=0.8, alpha=0.9),
                zorder=4,
            )

        ax.set_ylim(-0.5, max_val + max(2, max_val * 0.25))
        ax.set_ylabel("Failures Count", fontsize=9, fontweight="bold", color="#334155")
        ax.set_title("Failure Count Trend Across Builds", fontsize=11, fontweight="bold", pad=14, color="#0f172a")

        plt.xticks(rotation=15, fontsize=8.5, color="#475569")
        plt.yticks(fontsize=8.5, color="#475569")
        fig.tight_layout()
        fig.savefig(output_path, bbox_inches="tight", dpi=120)
        plt.close(fig)
        return output_path
    except Exception:
        plt.close("all")
        return None


def generate_module_failure_chart(
    failures_by_module: Dict[str, int],
    output_path: str,
) -> Optional[str]:
    """
    Generates a horizontal bar chart showing failure counts per module in current build.

    Args:
        failures_by_module: Dict mapping module_name -> failure_count.
        output_path: Target filepath for PNG output.

    Returns:
        The output_path if generated successfully, else None.
    """
    if not failures_by_module:
        return None

    # Filter out modules with 0 failures
    active_failures = {m: c for m, c in failures_by_module.items() if c > 0}
    if not active_failures:
        return None

    try:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        fig, ax = _setup_figure(width=6.0, height=3.5)

        # Sort modules ascending for horizontal bar chart (highest at top)
        sorted_mods = sorted(active_failures.items(), key=lambda x: x[1])
        modules = [x[0] for x in sorted_mods]
        counts = [x[1] for x in sorted_mods]

        bars = ax.barh(modules, counts, color=DANGER_COLOR, height=0.55, edgecolor="#b91c1c", linewidth=0.5, zorder=3)

        for bar in bars:
            width = bar.get_width()
            ax.annotate(
                f" {int(width)}",
                xy=(width, bar.get_y() + bar.get_height() / 2),
                xytext=(4, 0),
                textcoords="offset points",
                ha="left",
                va="center",
                fontsize=8.5,
                fontweight="bold",
                color="#991b1b",
            )

        max_val = max(counts)
        ax.set_xlim(0, max_val + max(1, max_val * 0.25))
        ax.set_xlabel("Failures", fontsize=9, fontweight="bold", color="#334155")
        ax.set_title("Failures by Module (Current Build)", fontsize=11, fontweight="bold", pad=14, color="#0f172a")

        plt.xticks(fontsize=8.5, color="#475569")
        plt.yticks(fontsize=8.5, color="#475569")
        fig.tight_layout()
        fig.savefig(output_path, bbox_inches="tight", dpi=120)
        plt.close(fig)
        return output_path
    except Exception:
        plt.close("all")
        return None


def generate_risk_chart(
    modules_report: Dict[str, Dict[str, Any]],
    output_path: str,
) -> Optional[str]:
    """
    Generates a horizontal bar chart displaying risk scores for each module.

    Bar colors correspond to risk levels:
        - HIGH (>= 70): Red
        - MEDIUM (40-69): Amber
        - LOW (0-39): Green

    Args:
        modules_report: Dict mapping module_name -> module_data_dict from Risk Analyzer.
        output_path: Target filepath for PNG output.

    Returns:
        The output_path if generated successfully, else None.
    """
    if not modules_report:
        return None

    try:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        fig, ax = _setup_figure(width=6.0, height=3.5)

        # Sort modules by score ascending for horizontal bar chart (highest risk at top)
        sorted_modules = sorted(
            modules_report.items(), key=lambda x: (x[1]["score"], x[0])
        )

        modules = [x[0] for x in sorted_modules]
        scores = [x[1]["score"] for x in sorted_modules]
        colors = []
        for x in sorted_modules:
            level = x[1]["level"]
            if level == "HIGH":
                colors.append(DANGER_COLOR)
            elif level == "MEDIUM":
                colors.append(WARNING_COLOR)
            else:
                colors.append(SUCCESS_COLOR)

        bars = ax.barh(modules, scores, color=colors, height=0.55, edgecolor="#94a3b8", linewidth=0.5, zorder=3)

        for bar, score in zip(bars, scores):
            width = bar.get_width()
            ax.annotate(
                f" {score}/100",
                xy=(width, bar.get_y() + bar.get_height() / 2),
                xytext=(4, 0),
                textcoords="offset points",
                ha="left",
                va="center",
                fontsize=8.5,
                fontweight="bold",
                color="#0f172a",
            )

        ax.set_xlim(0, 115)
        ax.set_xlabel("Risk Score", fontsize=9, fontweight="bold", color="#334155")
        ax.set_title("Module Risk Scores (0-100)", fontsize=11, fontweight="bold", pad=14, color="#0f172a")

        plt.xticks(fontsize=8.5, color="#475569")
        plt.yticks(fontsize=8.5, color="#475569")
        fig.tight_layout()
        fig.savefig(output_path, bbox_inches="tight", dpi=120)
        plt.close(fig)
        return output_path
    except Exception:
        plt.close("all")
        return None
