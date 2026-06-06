"""
Capacity vs Voltage analysis for OperaXN.
Charge/discharge classification is sign-based here; structured for
integration with ICI analysis classify_charge_discharge.
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt


def classify_phases(echem_df: pd.DataFrame):
    """
    Split echem_df into charge and discharge DataFrames.
    Uses current sign: positive = charge, negative = discharge.
    Returns (charge_df, discharge_df), each with a 't_s' column
    (elapsed seconds from start of the full dataset).
    """
    df = echem_df.copy()

    try:
        ts = pd.to_datetime(df["timestamp"])
        df["t_s"] = (ts - ts.iloc[0]).dt.total_seconds()
    except Exception:
        df["t_s"] = np.arange(len(df), dtype=float)

    current = df["current"].fillna(0).values
    labels = np.empty(len(current), dtype=object)

    for i in range(len(current)):
        if current[i] > 0:
            labels[i] = "charge"
        elif current[i] < 0:
            labels[i] = "discharge"
        else:
            # rest — inherit from previous label, default to "rest" at start
            labels[i] = labels[i - 1] if i > 0 and labels[i - 1] in ("charge", "discharge") else "rest"

    df["phase"] = labels

    charge_df = df[df["phase"] == "charge"].copy()
    discharge_df = df[df["phase"] == "discharge"].copy()

    return charge_df, discharge_df

def assign_cycles(echem_df: pd.DataFrame) -> pd.DataFrame:
    """
    Add a 'cycle' column (1-indexed). A cycle starts with charge and ends
    after the following discharge. Rest periods are already merged into
    their parent phase by classify_phases.
    """
    df = echem_df.copy()

    try:
        ts = pd.to_datetime(df["timestamp"])
        df["t_s"] = (ts - ts.iloc[0]).dt.total_seconds()
    except Exception:
        df["t_s"] = np.arange(len(df), dtype=float)

    current = df["current"].fillna(0).values
    labels = np.empty(len(current), dtype=object)

    # Same phase assignment as classify_phases
    for i in range(len(current)):
        if current[i] > 0:
            labels[i] = "charge"
        elif current[i] < 0:
            labels[i] = "discharge"
        else:
            labels[i] = labels[i - 1] if i > 0 and labels[i - 1] in ("charge", "discharge") else "rest"

    # Assign cycle numbers
    cycles = np.zeros(len(labels), dtype=int)
    cycle_num = 0
    prev = None

    for i in range(len(labels)):
        if labels[i] == "charge" and prev != "charge":
            cycle_num += 1          # new charge block = new cycle
        if labels[i] in ("charge", "discharge"):
            cycles[i] = cycle_num
        # rest before any cycle starts stays 0
        prev = labels[i]

    df["phase"] = labels
    df["cycle"] = cycles
    return df


def compute_capacity(df: pd.DataFrame) -> np.ndarray:
    """
    Cumulative capacity (mAh) via trapezoidal integration of |I| over time.
    Resets to 0 at the start of the passed segment.
    """
    if df.empty:
        return np.array([])

    t = df["t_s"].values
    i_mA = np.abs(df["current"].fillna(0).values)

    dt = np.diff(t, prepend=t[0])
    i_mid = np.concatenate(([i_mA[0]], (i_mA[:-1] + i_mA[1:]) / 2))
    capacity = np.cumsum(i_mid * dt) / 3600.0  # mAh
    return capacity


def parse_cycle_selection(input_str, available_cycles):
    s = input_str.strip().lower()
    if s in ("all", "0", ""):
        return list(available_cycles)
    selected = set()
    for part in s.split(","):
        part = part.strip()
        if "-" in part:
            try:
                a, b = part.split("-", 1)
                selected.update(range(int(a), int(b) + 1))
            except ValueError:
                pass
        else:
            try:
                selected.add(int(part))
            except ValueError:
                pass
    return sorted(c for c in selected if c in available_cycles)


def plot_capacity_vs_voltage(ax, echem_df, mass_mg=0.0, cycles_to_plot=None):
    ax.clear()
    use_specific = mass_mg > 0
    ax.set_xlabel("Specific Capacity (mAh/g)" if use_specific else "Capacity (mAh)")
    ax.set_ylabel("Voltage (V)")
    ax.grid(True, alpha=0.3)
    if echem_df is None or echem_df.empty:
        ax.text(0.5, 0.5, "No echem data loaded", ha="center", va="center", transform=ax.transAxes, color="grey", fontsize=11)
        return
    df = assign_cycles(echem_df)
    all_cycles = sorted([c for c in df["cycle"].unique() if c > 0])
    cycles = cycles_to_plot if cycles_to_plot is not None else all_cycles
    cmap = plt.cm.tab10 if len(all_cycles) <= 10 else plt.cm.viridis
    colors = {c: cmap(i / max(len(all_cycles) - 1, 1)) for i, c in enumerate(all_cycles)}
    for cycle_num in cycles:
        cycle_df = df[df["cycle"] == cycle_num]
        color = colors.get(cycle_num, "grey")
        charge_df = cycle_df[cycle_df["phase"] == "charge"]
        if not charge_df.empty:
            cap = compute_capacity(charge_df)
            if use_specific:
                cap = cap / (mass_mg / 1000.0)
            ax.plot(cap, charge_df["echem_data"].values, color=color, linewidth=1.5, label=f"Cycle {cycle_num}")
        discharge_df = cycle_df[cycle_df["phase"] == "discharge"]
        if not discharge_df.empty:
            cap = compute_capacity(discharge_df)
            if use_specific:
                cap = cap / (mass_mg / 1000.0)
            ax.plot(cap, discharge_df["echem_data"].values, color=color, linewidth=1.5)
    ax.legend(fontsize=7, loc="best")

def plot_time_vs_voltage(ax, echem_df, cycles_to_plot=None):
    ax.clear()
    ax.set_xlabel("Time (h)")
    ax.set_ylabel("Voltage (V)")
    ax.grid(True, alpha=0.3)
    if echem_df is None or echem_df.empty:
        ax.text(0.5, 0.5, "No echem data loaded", ha="center", va="center", transform=ax.transAxes, color="grey", fontsize=11)
        return
    df = assign_cycles(echem_df)
    all_cycles = sorted([c for c in df["cycle"].unique() if c > 0])
    cycles = cycles_to_plot if cycles_to_plot is not None else all_cycles
    cmap = plt.cm.tab10 if len(all_cycles) <= 10 else plt.cm.viridis
    colors = {c: cmap(i / max(len(all_cycles) - 1, 1)) for i, c in enumerate(all_cycles)}
    for cycle_num in cycles:
        cycle_df = df[df["cycle"] == cycle_num]
        ax.plot(cycle_df["t_s"].values / 3600.0, cycle_df["echem_data"].values,
                color=colors.get(cycle_num, "grey"), linewidth=1.5, label=f"Cycle {cycle_num}")
    ax.legend(fontsize=7, loc="best")