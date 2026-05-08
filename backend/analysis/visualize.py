"""Visualize a single 10-second gait insight record produced by analyze.py.

This is a snapshot view of one window — long-term trending happens in the
downstream database. We just want to confirm the extracted metrics make sense
for this window: signals, detected steps, stance phases, foot clearance, the
model's class probabilities, and the headline numbers.
"""

from __future__ import annotations

import argparse
import json
import os

import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import numpy as np
import pandas as pd

from analyze import RAW_COLS, load_data, slice_window


HERE = os.path.dirname(os.path.abspath(__file__))


def load_insights(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def reload_window(insights: dict) -> pd.DataFrame:
    src = insights["source"]
    fs = insights["window"]["sample_rate_hz"]
    seconds = insights["window"]["duration_s"]
    path = src["input_file"]
    with open(path) as f:
        first = f.readline().strip().lower()
    has_header = (first.startswith("mac_timestamp") or "esp32_ms" in first
                  or "ax,ay" in first or "accel_x" in first)
    df, _fs, _is_si = load_data(path, has_header=has_header)
    return slice_window(df, fs=fs, seconds=seconds, offset_s=src["offset_s"])


def plot_raw_signals(ax_a, ax_g, window: pd.DataFrame, fs: int):
    t = np.arange(len(window)) / fs
    ax_a.plot(t, window["accel_x"], label="ax", linewidth=0.9)
    ax_a.plot(t, window["accel_y"], label="ay", linewidth=0.9)
    ax_a.plot(t, window["accel_z"], label="az", linewidth=0.9)
    ax_a.set_title("Raw accelerometer (counts)")
    ax_a.set_ylabel("accel")
    ax_a.legend(loc="upper right", fontsize=8)
    ax_a.grid(alpha=0.3)

    ax_g.plot(t, window["gyro_x"], label="gx", linewidth=0.9)
    ax_g.plot(t, window["gyro_y"], label="gy", linewidth=0.9)
    ax_g.plot(t, window["gyro_z"], label="gz", linewidth=0.9)
    ax_g.set_title("Raw gyroscope (counts)")
    ax_g.set_ylabel("gyro")
    ax_g.set_xlabel("time (s)")
    ax_g.legend(loc="upper right", fontsize=8)
    ax_g.grid(alpha=0.3)


def plot_steps_and_stance(ax, insights: dict, fs: int):
    mag_filt = np.asarray(insights["signals"]["filtered_accel_magnitude"])
    peaks = np.asarray(insights["signals"]["step_peak_indices"], dtype=int)
    stance = np.asarray(insights["signals"]["stance_mask"], dtype=int)
    t = np.arange(len(mag_filt)) / fs

    ax.plot(t, mag_filt, color="#1f77b4", linewidth=1.0, label="filtered |accel|")
    if len(peaks) > 0:
        ax.plot(peaks / fs, mag_filt[peaks], "rx", markersize=10,
                label=f"{len(peaks)} steps")

    in_stance = stance.astype(bool)
    if in_stance.any():
        edges = np.diff(in_stance.astype(int))
        starts = np.where(edges == 1)[0] + 1
        ends = np.where(edges == -1)[0] + 1
        if in_stance[0]:
            starts = np.r_[0, starts]
        if in_stance[-1]:
            ends = np.r_[ends, len(in_stance)]
        for s, e in zip(starts, ends):
            ax.axvspan(s / fs, e / fs, color="green", alpha=0.08)

    ax.set_title("Step detection & stance phases (green)")
    ax.set_xlabel("time (s)")
    ax.set_ylabel("filtered |accel|")
    ax.legend(loc="upper right", fontsize=8)
    ax.grid(alpha=0.3)


def plot_class_probabilities(ax, insights: dict):
    probs = insights["state"]["class_probabilities"]
    classes = list(probs.keys())
    values = [probs[c] for c in classes]
    colors = ["#7f8c8d" if c != insights["state"]["predicted_state"] else "#27ae60"
              for c in classes]
    bars = ax.bar(classes, values, color=colors)
    ax.set_ylim(0, 1)
    ax.set_title("Model class probabilities")
    ax.set_ylabel("probability")
    for bar, v in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2, v + 0.02, f"{v:.2f}",
                ha="center", fontsize=9)
    ax.grid(alpha=0.3, axis="y")


def plot_per_window_predictions(ax, insights: dict, fs: int):
    rows = insights["state"]["per_window_predictions"]
    if not rows:
        ax.set_visible(False)
        return
    classes = list(insights["state"]["class_probabilities"].keys())
    starts_s = [r["window_start_sample"] / fs for r in rows]
    stacked = np.array([[r["probabilities"][c] for c in classes] for r in rows])

    bottom = np.zeros(len(rows))
    palette = ["#3498db", "#e74c3c", "#2ecc71", "#9b59b6"]
    for i, c in enumerate(classes):
        ax.bar(starts_s, stacked[:, i], bottom=bottom,
               width=(starts_s[1] - starts_s[0]) * 0.9 if len(starts_s) > 1 else 0.5,
               label=c, color=palette[i % len(palette)])
        bottom += stacked[:, i]
    ax.set_ylim(0, 1)
    ax.set_xlabel("window start (s)")
    ax.set_ylabel("class probability")
    ax.set_title("Per-sub-window prediction timeline")
    ax.legend(loc="upper right", fontsize=8)
    ax.grid(alpha=0.3, axis="y")


def plot_foot_clearance(ax, insights: dict):
    clearances = insights["signals"]["foot_clearance_per_stride_cm"]
    if not clearances:
        ax.text(0.5, 0.5, "no swings detected", ha="center", va="center",
                transform=ax.transAxes, fontsize=11, color="gray")
        ax.set_axis_off()
        return
    idx = np.arange(1, len(clearances) + 1)
    ax.bar(idx, clearances, color="#e67e22")
    mean = float(np.mean(clearances))
    ax.axhline(mean, color="black", linestyle="--", linewidth=0.8,
               label=f"mean={mean:.1f} cm")
    ax.set_title("Estimated foot clearance per stride")
    ax.set_xlabel("stride #")
    ax.set_ylabel("clearance (cm)")
    ax.legend(loc="upper right", fontsize=8)
    ax.grid(alpha=0.3, axis="y")


def render_summary_card(ax, insights: dict):
    m = insights["metrics"]
    s = insights["state"]
    sim = m.get("gait_similarity_score")
    sim_txt = f"{sim:.1f} / 10" if isinstance(sim, (int, float)) else "n/a"

    lines = [
        f"State:         {s['predicted_state']}  (conf {s['confidence']:.2f})",
        f"Steps:         {m['step_count']}",
        f"Cadence:       {m['cadence_spm']:.1f} spm",
        f"Foot clearance:{m['foot_clearance_mean_cm']:.1f} cm "
        f"(min {m['foot_clearance_min_cm']:.1f}, max {m['foot_clearance_max_cm']:.1f})",
        f"Similarity:    {sim_txt}",
        f"Classification:{m['gait_classification']}  "
        f"(conf {m['gait_classification_confidence']:.2f})",
        f"Stride length: {m['stride_length_m_est']:.2f} m (est)",
        f"Walking speed: {m['walking_speed_mps_est']:.2f} m/s (est)",
        f"Sit/stand:     {m['sit_stand_transitions']} transitions",
        f"Intensity:     {m['movement_intensity_mps2']:.2f} m/s²",
        f"Jerk RMS:      {m['jerk_rms_mps3']:.2f} m/s³",
        f"Stance frac:   {m['stance_phase_fraction']:.2f}",
    ]
    ax.text(0.02, 0.98, "\n".join(lines),
            family="monospace", fontsize=10, va="top", ha="left",
            transform=ax.transAxes)
    ax.set_title("Summary metrics", loc="left")
    ax.set_axis_off()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--insights", default=os.path.join(HERE, "insights.json"))
    parser.add_argument("--save", default=None,
                        help="If set, save the figure here instead of showing it.")
    args = parser.parse_args(argv)

    insights = load_insights(args.insights)
    fs = insights["window"]["sample_rate_hz"]

    try:
        window = reload_window(insights)
    except Exception as e:
        window = None
        print(f"warning: could not reload raw window ({e}); skipping signal plots.")

    fig = plt.figure(figsize=(15, 11))
    gs = gridspec.GridSpec(4, 3, figure=fig, hspace=0.55, wspace=0.3)

    ax_summary = fig.add_subplot(gs[0, :2])
    render_summary_card(ax_summary, insights)

    ax_probs = fig.add_subplot(gs[0, 2])
    plot_class_probabilities(ax_probs, insights)

    if window is not None:
        ax_a = fig.add_subplot(gs[1, :2])
        ax_g = fig.add_subplot(gs[2, :2])
        plot_raw_signals(ax_a, ax_g, window, fs)
    else:
        fig.add_subplot(gs[1, :2]).set_axis_off()
        fig.add_subplot(gs[2, :2]).set_axis_off()

    ax_clear = fig.add_subplot(gs[1, 2])
    plot_foot_clearance(ax_clear, insights)

    ax_perwin = fig.add_subplot(gs[2, 2])
    plot_per_window_predictions(ax_perwin, insights, fs)

    ax_steps = fig.add_subplot(gs[3, :])
    plot_steps_and_stance(ax_steps, insights, fs)

    fig.suptitle(
        f"SteadyStep gait insight  —  {insights['window']['duration_s']:.0f}s window  "
        f"@ {fs} Hz  ·  generated {insights['generated_at']}",
        fontsize=12,
    )

    if args.save:
        fig.savefig(args.save, dpi=120, bbox_inches="tight")
        print(f"Saved figure to {args.save}")
    else:
        plt.show()


if __name__ == "__main__":
    main()
