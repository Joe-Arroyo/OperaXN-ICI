"""
ICI Analysis Window for OperaXN.

Three separate matplotlib figures sit in proper expanding Tk frames —
no overlay geometry conflicts, same resize behaviour as the main window.

Plots that are live:
  - Overview V vs t  (phase-coloured, cycle + pulse highlight)
  - Pulse zoom       (V + I for selected pulse + relaxation)

Stubs (ready for analysis):
  - ICI fit  ΔV vs √Δt
  - R² vs Pulse #
  - R / k  charge & discharge vs Voltage

Usage (from gui.py):
    from .ici import ICIWindow
    ICIWindow(self.master, self.state.echem_df)
"""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox
from typing import Optional

import numpy as np
import pandas as pd

from matplotlib.figure import Figure
from matplotlib.gridspec import GridSpec
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from .config import OPERAXNTheme, FIGURE_DPI
from .capacity import assign_cycles, compute_capacity


# ─────────────────────────────────────────────────────────────────────────────
# Theme
# ─────────────────────────────────────────────────────────────────────────────

_C      = OPERAXNTheme.COLORS
BG      = _C['bg_primary']
BG2     = _C['bg_secondary']
BG3     = _C['bg_tertiary']
CANVAS  = _C['canvas_bg']
ACCENT  = _C['accent_primary']
TEXT    = _C['text_primary']
DIM     = _C['text_dim']
BORDER  = _C['border']
INPUT   = _C['input_bg']

CHARGE_COLOR    = '#00d4ff'
DISCHARGE_COLOR = '#ff6b6b'
CURRENT_COLOR   = '#ffd43b'
HIGHLIGHT_COLOR = '#ffffff'

_FONT     = OPERAXNTheme.FONTS['small']
_FONT_BTN = OPERAXNTheme.FONTS['button']
_PAD_S    = OPERAXNTheme.PADDING['small']
_PAD_M    = OPERAXNTheme.PADDING['medium']


# ─────────────────────────────────────────────────────────────────────────────
# Data helpers
# ─────────────────────────────────────────────────────────────────────────────

def _prepare_df(echem_df: pd.DataFrame) -> pd.DataFrame:
    return assign_cycles(echem_df)


def _detect_pulses(phase_df: pd.DataFrame, max_rest: float = 1800.0) -> list[dict]:
    """
    Mirrors pyICI's assign_valid_pulses logic.
    A pulse = active period (current != 0) followed by rest (current == 0).
    Valid only if 0 < rest_duration <= max_rest.
    This naturally excludes the CV step (rest too long) and inter-cycle rests.
    """
    if phase_df.empty:
        return []

    df      = phase_df.reset_index(drop=True)
    current = df['current'].fillna(0).values
    t_s     = df['t_s'].values
    n       = len(current)

    pulses, i = [], 0
    while i < n:
        if current[i] == 0:
            i += 1
            continue

        # Active period
        pulse_start = i
        while i < n and current[i] != 0:
            i += 1
        pulse_end = i - 1

        # Rest period
        rest_start = i
        while i < n and current[i] == 0:
            i += 1
        rest_end = i - 1

        # Valid only if rest exists and is within limit
        if rest_end < rest_start:
            continue
        rest_duration = t_s[rest_end] - t_s[rest_start]
        if not (0 < rest_duration <= max_rest):
            continue

        pm = np.zeros(n, dtype=bool); pm[pulse_start:pulse_end + 1] = True
        rm = np.zeros(n, dtype=bool); rm[rest_start:rest_end + 1]   = True

        pulses.append({
            'pulse_mask':    pm,
            'relax_mask':    rm,
            'pulse_start_t': t_s[pulse_start],
            'pulse_end_t':   t_s[pulse_end],
            'relax_end_t':   t_s[rest_end],
        })

    return pulses

def _compute_fit(seg: pd.DataFrame, pulse: dict, r1_start: float, r1_length: float,
                  cap_arr: np.ndarray | None = None) -> dict | None:
    """ΔV vs √Δt linear fit for one pulse. r1_start/r1_length are a time window
    (seconds) into the rest period: fit points with r1_start <= Δt < r1_start+r1_length.
    Returns None if rest data is insufficient.

    cap_arr, if given, is the cumulative capacity (mAh) for `seg` (same length,
    same row order — see compute_capacity), used to attach a capacity value to
    this pulse's V0 point by position rather than by voltage (voltage can repeat
    across pulses in flat regions, capacity is monotonic)."""
    active = seg[pulse['pulse_mask']]
    rest   = seg[pulse['relax_mask']]
    if active.empty or rest.empty:
        return None

    V0  = active['echem_data'].iloc[-1]
    t0  = active['t_s'].iloc[-1]
    I_A = active['current'].iloc[-1] / 1000.0  # mA → A

    if cap_arr is not None and len(cap_arr) == len(seg):
        pulse_cap = cap_arr[pulse['pulse_mask']]
        capacity  = float(pulse_cap[-1]) if len(pulse_cap) else np.nan
    else:
        capacity = np.nan

    delta_V = rest['echem_data'].values - V0
    t_rest0 = rest['t_s'].values[0]
    elapsed = rest['t_s'].values - t_rest0
    sqrt_dt = np.sqrt(np.maximum(elapsed, 0.0))

    win_mask = (elapsed >= r1_start) & (elapsed < r1_start + r1_length)
    if win_mask.sum() < 2:
        return None

    X = sqrt_dt[win_mask]
    y = delta_V[win_mask]

    X_mean, y_mean = np.mean(X), np.mean(y)
    dX = X - X_mean
    denom = np.dot(dX, dX)
    if denom == 0:
        return None
    slope     = np.dot(dX, y - y_mean) / denom
    intercept = y_mean - slope * X_mean
    y_pred    = slope * X + intercept

    ss_res = np.sum((y - y_pred) ** 2)
    ss_tot = np.sum((y - y_mean) ** 2)
    r2 = 1.0 - ss_res / ss_tot if ss_tot != 0 else np.nan

    n_pts   = len(X)
    s2      = ss_res / max(n_pts - 2, 1)
    sum_dx2 = denom
    var_sl  = s2 / sum_dx2
    var_ic  = s2 * (1.0 / n_pts + X_mean ** 2 / sum_dx2)

    R = -intercept / I_A if I_A != 0 else np.nan
    k = -slope     / I_A if I_A != 0 else np.nan
    R_err = abs(R) * np.sqrt(var_ic) / abs(intercept) if (I_A and intercept) else np.nan
    k_err = abs(k) * np.sqrt(var_sl) / abs(slope)     if (I_A and slope)     else np.nan

    return dict(
        sqrt_dt=sqrt_dt, delta_V=delta_V,
        X_fit=X, y_fit=y_pred,
        slope=slope, intercept=intercept, r2=r2,
        V0=V0, I_A=I_A, R=R, k=k, R_err=R_err, k_err=k_err,
        capacity=capacity,
    )


def _compute_all_pulses(seg: pd.DataFrame, pulses: list[dict], get_r1) -> list[dict]:
    """get_r1(pulse_idx) -> (r1_start_s, r1_length_s) for that pulse."""
    cap_arr = compute_capacity(seg) if not seg.empty else np.array([])
    results = []
    for i, p in enumerate(pulses):
        r1_start, r1_length = get_r1(i + 1)
        fit = _compute_fit(seg, p, r1_start, r1_length, cap_arr=cap_arr)
        if fit is not None:
            fit['pulse_idx'] = i + 1
            results.append(fit)
    return results


# ─────────────────────────────────────────────────────────────────────────────
# Shared widget helpers  (match main-window style)
# ─────────────────────────────────────────────────────────────────────────────

class _Btn(tk.Button):
    _STYLES = {
        'primary':    (ACCENT, _C['button_text']),
        'secondary':  (BG3,    TEXT),
        'toggle_on':  (ACCENT, _C['button_text']),
        'toggle_off': (BG3,    DIM),
    }

    def __init__(self, master, text, command=None, style='secondary', **kw):
        bg, fg = self._STYLES.get(style, self._STYLES['secondary'])
        super().__init__(
            master, text=text, command=command,
            bg=bg, fg=fg,
            activebackground=_C['accent_hover'],
            activeforeground=_C['button_text'],
            font=_FONT_BTN, relief=tk.FLAT, cursor='hand2',
            padx=10, pady=3, **kw,
        )
        self._bg   = bg
        self._hover = _C['accent_hover'] if style == 'primary' else BG2
        self.bind('<Enter>', lambda _: self._h(True))
        self.bind('<Leave>', lambda _: self._h(False))

    def _h(self, on):
        if self['state'] != 'disabled':
            self.config(bg=self._hover if on else self._bg)


def _spinbox(master, var, **kw):
    return tk.Spinbox(
        master, textvariable=var,
        bg=INPUT, fg=TEXT, buttonbackground=BG2,
        relief=tk.FLAT, font=_FONT,
        highlightbackground=BORDER, highlightthickness=1,
        **kw,
    )


def _label(master, text, dim=False, **kw):
    return tk.Label(
        master, text=text,
        bg=kw.pop('bg', BG2),
        fg=DIM if dim else TEXT,
        font=_FONT, **kw,
    )


def _separator(master, horizontal=True):
    if horizontal:
        return tk.Frame(master, bg=BORDER, height=1)
    return tk.Frame(master, bg=BORDER, width=1)


def _canvas_frame(master):
    """Styled border frame that matches the main window's plot container."""
    outer = tk.Frame(
        master,
        bg=CANVAS,
        relief=tk.FLAT,
        highlightbackground=BORDER,
        highlightcolor=ACCENT,
        highlightthickness=2,
    )
    return outer


# ─────────────────────────────────────────────────────────────────────────────
# Selector strip  (Cycle | Pulse | Phase)
# ─────────────────────────────────────────────────────────────────────────────

class _SelectorStrip(tk.Frame):
    def __init__(self, master, on_change):
        super().__init__(master, bg=BG2, pady=4)
        self._on_change = on_change
        self._build()

    def _build(self):
        # Cycle
        cf = tk.Frame(self, bg=BG2); cf.pack(side='left', padx=_PAD_M)
        _label(cf, 'Cycle:').pack(side='left')
        self.cycle_var = tk.IntVar(value=1)
        _Btn(cf, '◀', width=2, command=self._prev_cycle).pack(side='left', padx=2)
        self._cycle_spin = _spinbox(cf, self.cycle_var, from_=1, to=999, width=4,
                                    command=self._on_change)
        self._cycle_spin.pack(side='left', padx=2)
        _Btn(cf, '▶', width=2, command=self._next_cycle).pack(side='left', padx=2)
        self.cycle_var.trace_add('write', lambda *_: self._on_change())

        _separator(self, horizontal=False).pack(side='left', fill='y', padx=_PAD_M, pady=3)

        # Pulse
        pf = tk.Frame(self, bg=BG2); pf.pack(side='left', padx=_PAD_M)
        _label(pf, 'Pulse:').pack(side='left')
        self.pulse_var = tk.IntVar(value=1)
        _Btn(pf, '◀', width=2, command=self._prev_pulse).pack(side='left', padx=2)
        self._pulse_spin = _spinbox(pf, self.pulse_var, from_=1, to=999, width=4,
                                    command=self._on_change)
        self._pulse_spin.pack(side='left', padx=2)
        _Btn(pf, '▶', width=2, command=self._next_pulse).pack(side='left', padx=2)
        self.pulse_var.trace_add('write', lambda *_: self._on_change())

        _separator(self, horizontal=False).pack(side='left', fill='y', padx=_PAD_M, pady=3)

        # Phase toggle
        ph = tk.Frame(self, bg=BG2); ph.pack(side='left', padx=_PAD_M)
        _label(ph, 'Phase:').pack(side='left')
        self.phase_var = tk.StringVar(value='charge')
        self._btn_chg = _Btn(ph, 'Charge',    style='toggle_on',
                              command=lambda: self._set_phase('charge'))
        self._btn_chg.pack(side='left', padx=2)
        self._btn_dis = _Btn(ph, 'Discharge', style='toggle_off',
                              command=lambda: self._set_phase('discharge'))
        self._btn_dis.pack(side='left', padx=2)

        _separator(self, horizontal=False).pack(side='left', fill='y', padx=_PAD_M, pady=3)

        # R² scope
        sc = tk.Frame(self, bg=BG2); sc.pack(side='left', padx=_PAD_M)
        _label(sc, 'R² scope:').pack(side='left')
        self.scope_var = tk.StringVar(value='phase')
        self._scope_btns = {}
        for _val, _txt in (('phase', 'Phase'), ('cycle', 'Cycle'), ('all', 'All')):
            _b = _Btn(sc, _txt,
                      style='toggle_on' if _val == 'phase' else 'toggle_off',
                      command=lambda v=_val: self._set_scope(v))
            _b.pack(side='left', padx=2)
            self._scope_btns[_val] = _b

        _separator(self, horizontal=False).pack(side='left', fill='y', padx=_PAD_M, pady=3)

        self.show_all_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            self, text='Show all cycles',
            variable=self.show_all_var,
            command=self._on_change,
            bg=BG2, fg=DIM,
            activebackground=BG2, activeforeground=TEXT,
            selectcolor=BG3,
            font=_FONT,
        ).pack(side='left', padx=_PAD_M)

    def _prev_cycle(self):
        v = self.cycle_var.get()
        if v > 1: self.cycle_var.set(v - 1)

    def _next_cycle(self):
        v = self.cycle_var.get()
        if v < int(self._cycle_spin.cget('to')):
            self.cycle_var.set(v + 1)

    def _prev_pulse(self):
        v = self.pulse_var.get()
        if v > 1: self.pulse_var.set(v - 1)

    def _next_pulse(self):
        v = self.pulse_var.get()
        if v < int(self._pulse_spin.cget('to')):
            self.pulse_var.set(v + 1)

    def set_pulse_range(self, max_pulse: int) -> None:
        clamped = max(1, max_pulse)
        self._pulse_spin.config(to=clamped)
        if self.pulse_var.get() > clamped:
            self.pulse_var.set(1)

    def _set_phase(self, phase):
        self.phase_var.set(phase)
        on  = dict(bg=ACCENT, fg=_C['button_text'])
        off = dict(bg=BG3,    fg=DIM)
        self._btn_chg.config(**(on if phase == 'charge'    else off))
        self._btn_dis.config(**(on if phase == 'discharge' else off))
        self._on_change()

    def _set_scope(self, scope):
        self.scope_var.set(scope)
        on  = dict(bg=ACCENT, fg=_C['button_text'])
        off = dict(bg=BG3,    fg=DIM)
        for val, btn in self._scope_btns.items():
            btn.config(**(on if val == scope else off))
        self._on_change()

    def set_cycle_range(self, max_cycle: int) -> None:
        self._cycle_spin.config(to=max_cycle)
        self.cycle_var.set(1)

# ─────────────────────────────────────────────────────────────────────────────
# Regression bar  (bottom)
# ─────────────────────────────────────────────────────────────────────────────

class _RegressionBar(tk.Frame):
    def __init__(self, master, on_apply, on_export):
        super().__init__(master, bg=BG2, pady=4)
        self._on_apply  = on_apply
        self._on_export = on_export
        self._build()

    def _build(self):
        _label(self, 'Regression window:').pack(side='left', padx=(_PAD_M, _PAD_S))
        _label(self, 'Start (s):', dim=True).pack(side='left')
        self.start_var = tk.DoubleVar(value=0.5)
        _spinbox(self, self.start_var, from_=0.0, to=9999.0,
                 increment=0.1, format='%.2f', width=6).pack(side='left', padx=(_PAD_S, _PAD_M))
        _label(self, 'Length (s):', dim=True).pack(side='left')
        self.length_var = tk.DoubleVar(value=1.0)
        _spinbox(self, self.length_var, from_=0.1, to=9999.0,
                 increment=0.1, format='%.2f', width=6).pack(side='left', padx=(_PAD_S, _PAD_M))

        _separator(self, horizontal=False).pack(side='left', fill='y', padx=_PAD_M, pady=3)
        _label(self, 'Max rest (s):', dim=True).pack(side='left')
        self.max_rest_var = tk.DoubleVar(value=300.0)
        _spinbox(self, self.max_rest_var, from_=1.0, to=99999.0,
                 increment=10.0, format='%.0f', width=7).pack(side='left', padx=(_PAD_S, _PAD_M))

        _Btn(self, 'Apply (this pulse)', style='primary',
             command=lambda: self._on_apply('pulse')).pack(side='left', padx=_PAD_S)
        _Btn(self, 'Apply (all pulses)', style='secondary',
             command=lambda: self._on_apply('cycle')).pack(side='left', padx=_PAD_S)
        _Btn(self, 'Apply (all cycles)', style='secondary',
             command=lambda: self._on_apply('all')).pack(side='left', padx=_PAD_S)

        _separator(self, horizontal=False).pack(side='left', fill='y', padx=_PAD_M, pady=3)
        _Btn(self, '⬇ Export CSV', style='secondary',
             command=self._on_export).pack(side='left', padx=_PAD_S)


# ─────────────────────────────────────────────────────────────────────────────
# R/k axis bar  (right panel header — Voltage | Capacity | Specific Capacity)
# ─────────────────────────────────────────────────────────────────────────────

class _RKAxisBar(tk.Frame):
    """Packed inline (side='right') inside the bottom regression bar, so it
    adds no new row/height to the layout — right panel keeps its original size."""

    def __init__(self, master, on_change):
        super().__init__(master, bg=BG2)
        self._on_change = on_change
        self._build()

    def _build(self):
        _separator(self, horizontal=False).pack(side='left', fill='y', padx=_PAD_M, pady=3)
        _label(self, 'Mass (mg):', dim=True).pack(side='left')
        self.mass_var = tk.StringVar(value='0')
        mass_entry = _spinbox(self, self.mass_var, from_=0.0, to=99999.0,
                               increment=0.1, format='%.2f', width=7,
                               command=self._on_change)
        mass_entry.pack(side='left', padx=(_PAD_S, _PAD_M))
        mass_entry.bind('<Return>', lambda *_: self._on_change())
        mass_entry.bind('<FocusOut>', lambda *_: self._on_change())
        self.mass_var.trace_add('write', lambda *_: self._on_change())

        _separator(self, horizontal=False).pack(side='left', fill='y', padx=_PAD_M, pady=3)
        _label(self, 'R/k vs:').pack(side='left', padx=(_PAD_S, _PAD_S))
        self.xaxis_var = tk.StringVar(value='voltage')
        self._btns = {}
        for val, txt in (('voltage', 'Voltage'),
                          ('capacity', 'Capacity'),
                          ('specific_capacity', 'Specific Capacity')):
            b = _Btn(self, txt,
                     style='toggle_on' if val == 'voltage' else 'toggle_off',
                     command=lambda v=val: self._set_xaxis(v))
            b.pack(side='left', padx=2)
            self._btns[val] = b

    def _set_xaxis(self, val):
        self.xaxis_var.set(val)
        on  = dict(bg=ACCENT, fg=_C['button_text'])
        off = dict(bg=BG3,    fg=DIM)
        for v, btn in self._btns.items():
            btn.config(**(on if v == val else off))
        self._on_change()


# ─────────────────────────────────────────────────────────────────────────────
# Matplotlib helpers
# ─────────────────────────────────────────────────────────────────────────────

def _style_ax(ax, xlabel='', ylabel='', title=''):
    ax.set_facecolor(CANVAS)
    for sp in ax.spines.values():
        sp.set_color(BORDER)
    ax.tick_params(colors=DIM, labelsize=8)
    ax.xaxis.label.set_color(DIM)
    ax.yaxis.label.set_color(DIM)
    ax.set_xlabel(xlabel, fontsize=9)
    ax.set_ylabel(ylabel, fontsize=9)
    if title:
        ax.set_title(title, color=DIM, fontsize=9, pad=4)
    ax.grid(True, color=BORDER, alpha=0.4, linewidth=0.5)


def _stub(ax, msg='— coming soon —'):
    ax.text(0.5, 0.5, msg, color=DIM, fontsize=9,
            ha='center', va='center', transform=ax.transAxes, style='italic')


def _embed(fig, parent) -> FigureCanvasTkAgg:
    """Embed a matplotlib Figure in a Tk parent and pack to fill."""
    from matplotlib.backends.backend_tkagg import NavigationToolbar2Tk
    canvas = FigureCanvasTkAgg(fig, master=parent)
    toolbar_frame = tk.Frame(parent, bg=BG2)
    toolbar_frame.pack(fill='x', side='bottom')
    toolbar = NavigationToolbar2Tk(canvas, toolbar_frame)
    toolbar.config(bg=BG2)
    for child in toolbar.winfo_children():
        try:
            child.config(bg=BG2, fg=TEXT)
        except tk.TclError:
            pass
    toolbar.set_message = lambda msg: None
    toolbar.update()
    canvas.get_tk_widget().pack(fill='both', expand=True)
    canvas.draw()
    return canvas


# ─────────────────────────────────────────────────────────────────────────────
# ICI Window
# ─────────────────────────────────────────────────────────────────────────────

class ICIWindow(tk.Toplevel):
    """
    ICI analysis window — same maximised size as the main window.

        ICIWindow(parent, echem_df)
    """

    def __init__(self, parent: tk.Widget,
                 echem_df: Optional[pd.DataFrame] = None) -> None:
        super().__init__(parent)
        self.title('OperaXN — ICI Analysis')
        self.configure(bg=BG)
        self._maximise()

        self._df: Optional[pd.DataFrame] = None
        self._pulses: dict = {}
        self._ici_cache: dict = {}
        self._ax_pulse_twin = None
        self._ax_dv_sec = None
        self._ax_dv_twin = None
        self._updating = False
        self._last_cycle_phase: tuple = (None, None)

        # Regression-window overrides, resolved pulse > cycle > phase > bar defaults
        self._r1_pulse_overrides: dict = {}   # (cycle, phase, pulse_idx) -> (start_s, length_s)
        self._r1_cycle_overrides: dict = {}   # (cycle, phase)            -> (start_s, length_s)
        self._r1_phase_overrides: dict = {}   # phase                     -> (start_s, length_s)

        self._build_ui()

        if echem_df is not None and not echem_df.empty:
            self._load(echem_df)

    # ── sizing ─────────────────────────────────────────────────────────
    def _maximise(self):
        try:
            self.state('zoomed')
        except tk.TclError:
            try:
                self.attributes('-zoomed', True)
            except tk.TclError:
                w = self.winfo_screenwidth()
                h = self.winfo_screenheight()
                self.geometry(f'{w}x{h}+0+0')

    # ── layout ─────────────────────────────────────────────────────────
    def _build_ui(self):
        # ── Regression bar — packed from bottom first ──────────────────
        _separator(self).pack(fill='x', side='bottom')
        self.reg_bar = _RegressionBar(self, on_apply=self._on_apply,
                                       on_export=self._export_csv)
        self.reg_bar.pack(fill='x', side='bottom')

        # R/k axis controls live inline in the regression bar (no extra row),
        # so the figure areas keep their original size.
        self.rk_axis_bar = _RKAxisBar(self.reg_bar, on_change=self._on_rk_axis_changed)
        self.rk_axis_bar.pack(side='right', padx=_PAD_S)

        # ── Content area ───────────────────────────────────────────────
        content = tk.Frame(self, bg=BG)
        content.pack(fill='both', expand=True)

        # Left 2/3  |  Right 1/3
        left  = tk.Frame(content, bg=BG)
        right = tk.Frame(content, bg=BG)
        right.pack(side='right', fill='y')
        _separator(content, horizontal=False).pack(side='right', fill='y', padx=2)
        left.pack(side='left', fill='both', expand=True)

        # ── Left panel: top figure / selector strip / bottom figure ────
        left.grid_rowconfigure(0, weight=1)  # top figure
        left.grid_rowconfigure(1, weight=0)  # selector strip
        left.grid_rowconfigure(2, weight=1)  # bottom figure
        left.grid_columnconfigure(0, weight=1)

        # Top figure (Overview + Pulse zoom)
        top_cf = _canvas_frame(left)
        top_cf.grid(row=0, column=0, sticky='nsew',
                    padx=_PAD_S, pady=(_PAD_S, 2))
        self._fig_top = Figure(facecolor=BG, dpi=FIGURE_DPI)
        self._build_top_axes()
        self._canvas_top = _embed(self._fig_top, top_cf)

        # Selector strip
        strip_wrapper = tk.Frame(left, bg=BG2,
                                 highlightbackground=BORDER,
                                 highlightthickness=1)
        strip_wrapper.grid(row=1, column=0, sticky='ew',
                           padx=_PAD_S, pady=2)
        self.selector = _SelectorStrip(strip_wrapper,
                                       on_change=self._on_selection_change)
        self.selector.pack(fill='x')

        # Bottom figure (ICI fit + R²)
        bot_cf = _canvas_frame(left)
        bot_cf.grid(row=2, column=0, sticky='nsew',
                    padx=_PAD_S, pady=(2, _PAD_S))
        self._fig_bot = Figure(facecolor=BG, dpi=FIGURE_DPI)
        self._build_bot_axes()
        self._canvas_bot = _embed(self._fig_bot, bot_cf)

        # ── Right panel: R / k figures (4 stacked) ─────────────────────
        right_cf = _canvas_frame(right)
        right_cf.pack(fill='both', expand=True,
                      padx=_PAD_S, pady=_PAD_S)
        self._fig_right = Figure(figsize=(5.0, 10), facecolor=BG, dpi=FIGURE_DPI)
        self._build_right_axes()
        self._canvas_right = _embed(self._fig_right, right_cf)

    # ── axes setup ─────────────────────────────────────────────────────
    def _build_top_axes(self):
        gs = GridSpec(1, 2, figure=self._fig_top,
                      wspace=0.35,
                      left=0.10, right=0.90,
                      top=0.88, bottom=0.18)
        self.ax_overview = self._fig_top.add_subplot(gs[0, 0])
        self.ax_pulse    = self._fig_top.add_subplot(gs[0, 1])
        _style_ax(self.ax_overview, 't (h)', 'Voltage (V)', 'Overview')
        _style_ax(self.ax_pulse,    't (h)', 'Voltage (V)', 'Pulse zoom')

    def _build_bot_axes(self):
        gs = GridSpec(1, 2, figure=self._fig_bot,
                wspace=0.35,
                left=0.10, right=0.90,
                top=0.80, bottom=0.18)
        self.ax_dv = self._fig_bot.add_subplot(gs[0, 0])
        self.ax_r2 = self._fig_bot.add_subplot(gs[0, 1])
        _style_ax(self.ax_dv, '√Δt (s¹ᐟ²)', 'ΔV (V)', 'ICI fit')
        _style_ax(self.ax_r2, 'Pulse #',   'R²',     'R² vs Pulse')
        _stub(self.ax_dv); _stub(self.ax_r2)

    def _build_right_axes(self):
        gs = GridSpec(4, 1, figure=self._fig_right,
                      hspace=0.40,
                      left=0.14, right=0.97,
                      top=0.98, bottom=0.04)
        self.ax_r_chg  = self._fig_right.add_subplot(gs[0])
        self.ax_r_dis  = self._fig_right.add_subplot(gs[1])
        self.ax_k_chg  = self._fig_right.add_subplot(gs[2])
        self.ax_k_dis  = self._fig_right.add_subplot(gs[3])
        _style_ax(self.ax_r_chg,  'V (V)', 'R (Ω)', 'R – Charge')
        _style_ax(self.ax_r_dis,  'V (V)', 'R (Ω)', 'R – Discharge')
        _style_ax(self.ax_k_chg,  'V (V)', 'k',      'k – Charge')
        _style_ax(self.ax_k_dis,  'V (V)', 'k',      'k – Discharge')
        for ax in (self.ax_r_chg, self.ax_r_dis, self.ax_k_chg, self.ax_k_dis):
            if ax.has_data():
                ax.legend(fontsize=7, loc='best',
                          labelcolor=TEXT, facecolor=BG2, edgecolor=BORDER)
            else:
                _stub(ax, 'No data')

    # ── data loading ───────────────────────────────────────────────────
    def _load(self, echem_df: pd.DataFrame):
        self._df     = _prepare_df(echem_df)
        self._pulses = {}
        self._ici_cache = {}
        max_cycle = int(self._df[self._df['cycle'] > 0]['cycle'].max())
        self.selector.set_cycle_range(max_cycle)
        self._update_all()

    def _get_pulses(self, cycle: int, phase: str) -> list[dict]:
        key = (cycle, phase)
        if key not in self._pulses:
            if self._df is None:
                return []
            mask = (self._df['cycle'] == cycle) & (self._df['phase'] == phase)
            self._pulses[key] = _detect_pulses(
                self._df[mask], max_rest=float(self.reg_bar.max_rest_var.get()))
        return self._pulses[key]

    # ── plot: overview ─────────────────────────────────────────────────
    def _plot_overview(self, cycle, pulse_idx, phase):
        ax = self.ax_overview
        ax.cla()
        _style_ax(ax, 't (h)', 'Voltage (V)', 'Overview')
        if self._df is None:
            _stub(ax, 'No data loaded'); return

        df  = self._df
        t_h = df['t_s'].values / 3600.0
        v   = df['echem_data'].values

        if self.selector.show_all_var.get():
            for c in sorted(df[df['cycle'] > 0]['cycle'].unique()):
                m = df['cycle'] == c
                ax.plot(t_h[m], v[m], color=BORDER, lw=0.8, zorder=1)

        cyc = df['cycle'] == cycle
        for ph, col in (('charge', CHARGE_COLOR), ('discharge', DISCHARGE_COLOR)):
            m = cyc & (df['phase'] == ph)
            if m.any():
                ax.plot(t_h[m], v[m], color=col, lw=1.8, zorder=2,
                        label=ph.capitalize())

        pulses = self._get_pulses(cycle, phase)
        if 1 <= pulse_idx <= len(pulses):
            p  = pulses[pulse_idx - 1]
            t0 = p['pulse_start_t'] / 3600.0
            t1 = p['relax_end_t']   / 3600.0
            ax.axvspan(t0, t1, alpha=0.25, color=HIGHLIGHT_COLOR, zorder=3)
            ax.axvline(t0, color=HIGHLIGHT_COLOR, lw=1.0, ls='--', zorder=4)

        ax.legend(fontsize=7, loc='best',
                  labelcolor=TEXT, facecolor=BG2, edgecolor=BORDER)

    # ── plot: pulse zoom ───────────────────────────────────────────────
    def _plot_pulse_zoom(self, cycle, pulse_idx, phase):
        if self._ax_pulse_twin is not None:
            self._fig_top.delaxes(self._ax_pulse_twin)
            self._ax_pulse_twin = None

        ax = self.ax_pulse
        ax.cla()
        _style_ax(ax, 't (h)', 'Voltage (V)', 'Pulse zoom')

        if self._df is None:
            _stub(ax, 'No data loaded'); return

        pulses = self._get_pulses(cycle, phase)
        if not pulses:
            _stub(ax, f'No pulses found\n(cycle {cycle}, {phase})'); return

        pulse_idx = max(1, min(pulse_idx, len(pulses)))
        p    = pulses[pulse_idx - 1]
        mask = (self._df['cycle'] == cycle) & (self._df['phase'] == phase)
        seg  = self._df[mask]

        combined = pd.concat([seg[p['pulse_mask']], seg[p['relax_mask']]])
        if combined.empty:
            _stub(ax, 'Empty pulse segment'); return

        t_h = combined['t_s'].values / 3600.0
        v   = combined['echem_data'].values
        i_arr = combined['current'].fillna(0).values
        col = CHARGE_COLOR if phase == 'charge' else DISCHARGE_COLOR

        # V0 = voltage at end of active period (pyICI convention)
        pulse_seg = seg[p['pulse_mask']]
        relax_seg = seg[p['relax_mask']]
        t0_h = p['pulse_end_t'] / 3600.0

        ax.plot(t_h, v, color=col, lw=1.8, label='Voltage', zorder=3)

        # Shade rest period + V0 marker (matches pyICI)
        if not relax_seg.empty:
            ax.axvspan(t0_h, p['relax_end_t'] / 3600.0,
                       color=col, alpha=0.12, zorder=1)
        if not pulse_seg.empty:
            V0 = pulse_seg['echem_data'].iloc[-1]
            ax.plot(t0_h, V0, 'o', color='#51cf66', markersize=7,
                    label=f'V₀ = {V0:.3f} V', zorder=5)

        self._ax_pulse_twin = ax.twinx()
        ax2 = self._ax_pulse_twin
        ax2.plot(t_h, i_arr, color=CURRENT_COLOR, lw=1.2, ls='--',
                 label='Current', alpha=0.8, zorder=2)
        ax2.set_ylabel('Current (mA)', color=DIM, fontsize=9)
        ax2.tick_params(colors=DIM, labelsize=8)
        ax2.spines['right'].set_color(BORDER)
        for sp in ['top', 'bottom', 'left']:
            ax2.spines[sp].set_color(BORDER)
        ax2.set_facecolor('none')

        # Only include lines with real labels (avoids _child1 artifact)
        l1 = [l for l in ax.get_lines()  if not l.get_label().startswith('_')]
        l2 = [l for l in ax2.get_lines() if not l.get_label().startswith('_')]
        ax.legend(l1 + l2, [l.get_label() for l in l1 + l2],
                  fontsize=7, loc='best',
                  labelcolor=TEXT, facecolor=BG2, edgecolor=BORDER)
        ax.set_title(
            f'Cycle {cycle}  |  {phase.capitalize()}  |  '
            f'Pulse {pulse_idx}/{len(pulses)}',
            color=DIM, fontsize=9, pad=4,
        )

        # ── ICI analysis ───────────────────────────────────────────────────────────
    def _get_r1(self, cycle: int = None, phase: str = None, pulse_idx: int = None):
        """Resolve the regression window (start_s, length_s) for a pulse,
        falling back pulse -> cycle -> phase -> the bar's current defaults."""
        if cycle is not None and phase is not None and pulse_idx is not None:
            ov = self._r1_pulse_overrides.get((cycle, phase, pulse_idx))
            if ov is not None:
                return ov
        if cycle is not None and phase is not None:
            ov = self._r1_cycle_overrides.get((cycle, phase))
            if ov is not None:
                return ov
        if phase is not None:
            ov = self._r1_phase_overrides.get(phase)
            if ov is not None:
                return ov
        return self._r1_phase_overrides.get(phase, (0.5, 1.0))

    def _compute_ici(self, cycle: int, phase: str) -> list[dict]:
        key = (cycle, phase)
        if key not in self._ici_cache:
            pulses = self._get_pulses(cycle, phase)
            if not pulses or self._df is None:
                self._ici_cache[key] = []
            else:
                mask = (self._df['cycle'] == cycle) & (self._df['phase'] == phase)
                get_r1 = lambda idx: self._get_r1(cycle, phase, idx)
                self._ici_cache[key] = _compute_all_pulses(
                    self._df[mask], pulses, get_r1)
        return self._ici_cache[key]

    # ── plot: ICI fit ──────────────────────────────────────────────────────────
    def _plot_ici_fit(self, cycle: int, pulse_idx: int, phase: str):
        ax = self.ax_dv
        ax.cla()
        _style_ax(ax, '√Δt (√s)', 'ΔV (V)', 'ICI fit')

        results = self._compute_ici(cycle, phase)
        fit = next((r for r in results if r['pulse_idx'] == pulse_idx), None)

        if fit is None:
            _stub(ax, 'Insufficient rest data\nfor selected pulse')
            return

        col = CHARGE_COLOR if phase == 'charge' else DISCHARGE_COLOR
        ax.scatter(fit['sqrt_dt'], fit['delta_V'],
                   color=col, s=12, alpha=0.7, zorder=3, label='ΔV')

        r1s, r1l = self._get_r1(cycle, phase, pulse_idx)
        ax.axvspan(np.sqrt(r1s), np.sqrt(r1s + r1l),
                   alpha=0.12, color=ACCENT, zorder=1)

        ax.plot(fit['X_fit'], fit['y_fit'],
                color=ACCENT, lw=2, zorder=4,
                label=f'fit  R²={fit["r2"]:.3f}')

        ax.legend(fontsize=7, loc='best',
                  labelcolor=TEXT, facecolor=BG2, edgecolor=BORDER)
        if self._ax_dv_twin is not None:
            try:
                self._fig_bot.delaxes(self._ax_dv_twin)
            except Exception:
                pass
        self._ax_dv_twin = ax.twiny()
        xl = ax.get_xlim()
        twin = self._ax_dv_twin
        twin.set_xlim(xl)
        dt_max = xl[1] ** 2
        n_sq = int(np.floor(np.sqrt(dt_max)))
        dt_ticks = [i * i for i in range(n_sq + 1)]
        twin.set_xticks([np.sqrt(t) for t in dt_ticks])
        twin.set_xticklabels([str(t) for t in dt_ticks])
        twin.set_xlabel('Δt (s)', fontsize=8, color=DIM)
        twin.tick_params(colors=DIM, labelsize=7)
        for sp in twin.spines.values():
            sp.set_color(BORDER)
        twin.set_facecolor('none')

        ax.set_title(
            f'ICI fit  |  C{cycle}  {phase[:3]}  |  Pulse {pulse_idx}  '
            f'|  R={fit["R"]:.4f} Ω  k={fit["k"]:.4f} Ω·s⁻¹ᐟ²',
            color=DIM, fontsize=9, pad=4)

    # ── plot: R² vs pulse ──────────────────────────────────────────────────────
    def _plot_r2_panel(self, cycle: int, pulse_idx: int, phase: str, scope: str):
        ax = self.ax_r2
        ax.cla()
        _style_ax(ax, 'Pulse #', 'R²', 'R² vs Pulse')

        if self._df is None:
            _stub(ax, 'No data'); return

        datasets: list[tuple[list, str, str, float]] = []
        if scope == 'phase':
            col = CHARGE_COLOR if phase == 'charge' else DISCHARGE_COLOR
            datasets.append((self._compute_ici(cycle, phase), phase.capitalize(), col, 0.85))
        elif scope == 'cycle':
            datasets.append((self._compute_ici(cycle, 'charge'),    'Charge',    CHARGE_COLOR,    0.85))
            datasets.append((self._compute_ici(cycle, 'discharge'), 'Discharge', DISCHARGE_COLOR, 0.85))
        else:
            max_c = int(self._df[self._df['cycle'] > 0]['cycle'].max())
            for c in range(1, max_c + 1):
                alpha = 1.0 if c == cycle else 0.35   # same shading rule as the R/k panels
                for ph, col in (('charge', CHARGE_COLOR), ('discharge', DISCHARGE_COLOR)):
                    lbl = f'C{c} {ph[:3]}'
                    datasets.append((self._compute_ici(c, ph), lbl, col, alpha))

        for results, lbl, col, alpha in datasets:
            if not results:
                continue
            xs = [r['pulse_idx'] for r in results]
            ys = [r['r2']        for r in results]
            ax.scatter(xs, ys, color=col, s=18, alpha=alpha, label=lbl, zorder=3)

        # Star on selected pulse
        current_fits = self._compute_ici(cycle, phase)
        sel = next((r for r in current_fits if r['pulse_idx'] == pulse_idx), None)
        if sel and not np.isnan(sel['r2']):
            ax.scatter([pulse_idx], [sel['r2']],
                       color=HIGHLIGHT_COLOR, s=70, marker='*', zorder=5)

        if any(r for r, _, _, _ in datasets):
            ax.legend(fontsize=7, loc='best',
                      labelcolor=TEXT, facecolor=BG2, edgecolor=BORDER)

    # ── plot: R and k vs voltage / capacity / specific capacity ────────────────
    _XAXIS_LABELS = {
        'voltage':           'V (V)',
        'capacity':          'Capacity (mAh)',
        'specific_capacity': 'Specific Capacity (mAh/g)',
    }

    def _get_mass_mg(self) -> float:
        try:
            return float(self.rk_axis_bar.mass_var.get())
        except (ValueError, tk.TclError):
            return 0.0

    def _update_right_plots(self, cycle: int, phase: str, scope: str):
        xaxis   = self.rk_axis_bar.xaxis_var.get()
        mass_mg = self._get_mass_mg()
        xl      = self._XAXIS_LABELS[xaxis]

        for ax, yl, ttl in (
            (self.ax_r_chg, 'R (Ω)',    'R – Charge'),
            (self.ax_r_dis, 'R (Ω)',    'R – Discharge'),
            (self.ax_k_chg, 'k (Ω·s⁻¹ᐟ²)', 'k – Charge'),
            (self.ax_k_dis, 'k (Ω·s⁻¹ᐟ²)', 'k – Discharge'),
        ):
            ax.cla(); _style_ax(ax, xl, yl, ttl)

        if self._df is None:
            for ax in (self.ax_r_chg, self.ax_r_dis, self.ax_k_chg, self.ax_k_dis):
                _stub(ax)
            self._canvas_right.draw_idle()
            return

        if xaxis == 'specific_capacity' and mass_mg <= 0:
            for ax in (self.ax_r_chg, self.ax_r_dis, self.ax_k_chg, self.ax_k_dis):
                _stub(ax, 'Enter mass (mg) > 0')
            self._canvas_right.draw_idle()
            return

        max_c = int(self._df[self._df['cycle'] > 0]['cycle'].max())
        cycles = [cycle] if scope in ('phase', 'cycle') else list(range(1, max_c + 1))

        for c in cycles:
            alpha = 1.0 if c == cycle else 0.5
            lbl_s = f' C{c}' if len(cycles) > 1 else ''
            for ph, ax_r, ax_k, col in (
                ('charge',    self.ax_r_chg, self.ax_k_chg, CHARGE_COLOR),
                ('discharge', self.ax_r_dis, self.ax_k_dis, DISCHARGE_COLOR),
            ):
                res = self._compute_ici(c, ph)
                if not res:
                    continue
                if xaxis == 'voltage':
                    xs = np.array([r['V0'] for r in res])
                elif xaxis == 'capacity':
                    xs = np.array([r['capacity'] for r in res])
                else:
                    xs = np.array([r['capacity'] for r in res]) / (mass_mg / 1000.0)
                Rs   = np.array([r['R']     for r in res])
                ks   = np.array([r['k']     for r in res])
                R_e  = np.array([r['R_err'] for r in res])
                k_e  = np.array([r['k_err'] for r in res])
                lbl  = f'{ph.capitalize()}{lbl_s}'
                vR   = ~np.isnan(xs) & ~np.isnan(Rs)
                vk   = ~np.isnan(xs) & ~np.isnan(ks)
                if vR.any():
                    ax_r.errorbar(xs[vR], Rs[vR], yerr=R_e[vR],
                                  fmt='o', color=col, alpha=alpha,
                                  ms=5, lw=1, capsize=3, label=lbl)
                if vk.any():
                    ax_k.errorbar(xs[vk], ks[vk], yerr=k_e[vk],
                                  fmt='o', color=col, alpha=alpha,
                                  ms=5, lw=1, capsize=3, label=lbl)

        for ax in (self.ax_r_chg, self.ax_r_dis, self.ax_k_chg, self.ax_k_dis):
            if ax.get_lines() or ax.collections:
                ax.legend(fontsize=7, loc='best',
                          labelcolor=TEXT, facecolor=BG2, edgecolor=BORDER)
            else:
                _stub(ax, 'No data')

        self._canvas_right.draw_idle()

    # ── callbacks ──────────────────────────────────────────────────────────────
        
    def _on_selection_change(self):
        if getattr(self, '_updating', False):
            return
        self._updating = True
        try:
            cycle = self.selector.cycle_var.get()
            phase = self.selector.phase_var.get()
            pulses = self._get_pulses(cycle, phase)
            self.selector.set_pulse_range(len(pulses))
            if (cycle, phase) != self._last_cycle_phase:
                self._last_cycle_phase = (cycle, phase)
                self.selector.pulse_var.set(1)
            self._update_live_plots()
        finally:
            self._updating = False

    def _export_csv(self):
        if self._df is None:
            return
        directory = filedialog.askdirectory(title='Select export folder', parent=self)
        if not directory:
            return

        max_c   = int(self._df[self._df['cycle'] > 0]['cycle'].max())
        mass_mg = self._get_mass_mg()
        cols    = ['cycle', 'voltage (V)', 'capacity (mAh)', 'specific_capacity (mAh/g)',
                   'R (Ohm)', 'R_error (Ohm)',
                   'k (Ohm.s^-1/2)', 'k_error (Ohm.s^-1/2)', 'R2']

        for ph in ('charge', 'discharge'):
            rows = []
            for c in range(1, max_c + 1):
                for r in self._compute_ici(c, ph):
                    rows.append({
                        'cycle':                       c,
                        'voltage (V)':                 r['V0'],
                        'capacity (mAh)':               r['capacity'],
                        'specific_capacity (mAh/g)':     (r['capacity'] / (mass_mg / 1000.0)
                                                           if mass_mg > 0 else np.nan),
                        'R (Ohm)':              r['R'],
                        'R_error (Ohm)':        r['R_err'],
                        'k (Ohm.s^-1/2)':       r['k'],
                        'k_error (Ohm.s^-1/2)': r['k_err'],
                        'R2':                   r['r2'],
                    })
            out = pd.DataFrame(rows, columns=cols)
            out.to_csv(f'{directory}/ici_{ph}.csv', index=False)

        messagebox.showinfo(
            'Export complete',
            f'Saved ici_charge.csv and ici_discharge.csv to:\n{directory}',
            parent=self
        )

    def _on_rk_axis_changed(self, *_):
        if self._df is None:
            return
        cycle = self.selector.cycle_var.get()
        phase = self.selector.phase_var.get()
        scope = self.selector.scope_var.get()
        self._update_right_plots(cycle, phase, scope)

    def _on_apply(self, scope: str = 'pulse'):
        cycle = self.selector.cycle_var.get()
        phase = self.selector.phase_var.get()
        pulse = self.selector.pulse_var.get()
        val   = (float(self.reg_bar.start_var.get()),
                 float(self.reg_bar.length_var.get()))

        if scope == 'pulse':
            self._r1_pulse_overrides[(cycle, phase, pulse)] = val

        elif scope == 'cycle':
            self._r1_cycle_overrides[(cycle, phase)] = val
            # a cycle-wide value should win over any single-pulse overrides in it
            for key in list(self._r1_pulse_overrides):
                if key[0] == cycle and key[1] == phase:
                    del self._r1_pulse_overrides[key]

        elif scope == 'all':
            self._r1_phase_overrides[phase] = val
            # an all-cycles value should win over any cycle- or pulse-level
            # overrides previously set for this phase
            for key in list(self._r1_cycle_overrides):
                if key[1] == phase:
                    del self._r1_cycle_overrides[key]
            for key in list(self._r1_pulse_overrides):
                if key[1] == phase:
                    del self._r1_pulse_overrides[key]

        self._pulses.clear()
        self._ici_cache.clear()
        self._update_live_plots()

    def _update_live_plots(self):
        if self._df is None:
            return
        cycle = self.selector.cycle_var.get()
        pulse = self.selector.pulse_var.get()
        phase = self.selector.phase_var.get()
        scope = self.selector.scope_var.get()
        self._plot_overview(cycle, pulse, phase)
        self._plot_pulse_zoom(cycle, pulse, phase)
        self._fig_top.canvas.draw_idle()
        self._plot_ici_fit(cycle, pulse, phase)
        self._plot_r2_panel(cycle, pulse, phase, scope)
        self._canvas_bot.draw_idle()
        self._update_right_plots(cycle, phase, scope)

    def _update_all(self):
        self._update_live_plots()
