# Changelog

## [Unreleased]

## June 27, 2026

### Fixed
- **Linux dialog buttons too small**: Added platform-conditional padding to buttons and widened dialog windows (`Upload Options`, `Select Data Source`, `Time Sorting Method`) on Linux.
- **Time Sorting dialog crash/loop on Linux**: Moved `TimeSortingDialog` creation to the main thread before spawning the file processing thread, resolving a Tkinter threading violation that caused the dialog to freeze or loop on Linux.
- **ICI analysis failing with Relative Time**: Fixed `_assign_time` in `capacity.py` to use the preserved `original_timestamp` column when available, maintaining sub-second echem timestamp precision that was being lost during HH:MM:SS conversion.
- **Code duplication in `capacity.py`**: Removed copy-pasted phase-assignment loop from `assign_cycles`; it now calls `classify_phases` internally.
- **Global matplotlib backend side effect**: Removed `matplotlib.use("TkAgg")` module-level call from `ici.py` that could interfere with the main window's backend setup on import.
- **No input validation before opening ICI/Capacity windows**: Added guards in `_on_ici_analysis` and `_open_capacity_window` to check that `echem_df` is not `None` and contains a `current` column before opening either window.
- **Stale ICI cache on data reload**: ICI window cache is now cleared when new data is loaded, preventing stale pulse detection and fit results from persisting across sessions.
- **`max_rest` hardcoded discrepancy**: `max_rest` pulse detection threshold is now user-configurable in the UI instead of being hardcoded to mismatched values (1800 s vs 300 s).
- **Apply scope bug**: Fixed bar live values leaking into pulses that were not explicitly overridden when using partial Apply.
- **Missing trailing newline in `capacity.py`**: Added newline at end of file.
- **Squashed noise commits**: Removed `nothing` / `Revert "nothing"` commits from git history before merge.

### Confirmed
- **Current sign convention**: Positive current = charge, negative = discharge — verified correct against echem data files.
- **`compute_capacity` uses `|I|`**: Intentional — both charge and discharge legs return positive capacity values.


## June 16, 2026

### Added
- **Regression window now specified in time, not points.** The Skip/Length point-count controls were replaced with `Start (s)` / `Length (s)`, defining the rest-period time window used for the ΔV vs √Δt fit (default: start at 0.5 s, length 1.0 s).
- **Scoped Apply controls** for the regression window — three buttons instead of one:
  - *Apply (this pulse)* — overrides only the currently selected pulse.
  - *Apply (all pulses)* — overrides every pulse in the current cycle, for the currently selected phase only.
  - *Apply (all cycles)* — overrides every pulse, every cycle, for the currently selected phase only.
  - Overrides resolve pulse → cycle → phase → global default, and applying a broader scope now clears any conflicting narrower override so the change is always immediately visible.
- **CSV export** of ICI results: a new "⬇ Export CSV" button writes two files (`ici_charge.csv`, `ici_discharge.csv`) covering every cycle, with columns `cycle, voltage (V), R (Ohm), R_error (Ohm), k (Ohm.s^-1/2), k_error (Ohm.s^-1/2), R2`. Export respects whatever regression-window overrides are currently active.

### Fixed
- Corrected the unit of the kinetic coefficient `k` from the previously mislabeled `Ω√s` to the dimensionally correct **Ω·s⁻¹ᐟ²** (ohms per √second), in the ICI fit plot title and the k vs Voltage panel labels.
- Fixed misalignment between the top (Overview/Pulse zoom) and bottom (ICI fit/R²) plot rows — both now share the same GridSpec margins so columns line up edge-to-edge.
- Enlarged the four stacked R/k vs Voltage plots by reclaiming unused GridSpec margin and reducing inter-plot spacing.
- Fixed the file-export dialog (and its confirmation popup) opening behind the ICI window by explicitly setting `parent=self`, so it now appears above the window that spawned it.
- R² vs Pulse panel ("All" scope) now shades points by cycle — full opacity for the currently selected cycle, dimmed for others — matching the shading already used in the R/k vs Voltage panels, instead of using a single flat color/alpha for every cycle.

### June 14, 2026

### Added
- **ICI Analysis window** (`🔬 ICI` button): opens a maximised window for Intermittent Current Interruption battery analysis.
- **Overview plot**: Voltage vs time for selected cycle, with charge/discharge phase colouring and pulse highlight (span + dashed line).
- **Pulse zoom plot**: Voltage + Current (twin y-axis) for the selected pulse and its relaxation period, with V₀ marker.
- **Cycle / Pulse / Phase selector strip**: navigate cycles and pulses with ◀▶ spinboxes and phase toggle (Charge / Discharge).
- **ICI fit plot** (ΔV vs √Δt): scatter of all rest data with linear regression line, regression window highlighted, R² in legend, R and k in title.
- **Secondary x-axis on ICI fit plot** showing Δt (s) with nonlinear tick placement (0, 1, 4, 9 … perfect squares) matching pyICI convention.
- **R² vs Pulse plot**: scatter of R² for all pulses in selected scope, with star marker on currently selected pulse and dynamic y-axis scaling.
- **R² scope toggle**: Phase / Cycle / All — controls which data appears in the R² and R/k plots.
- **R and k vs Voltage plots** (right panel): four stacked plots (R charge, R discharge, k charge, k discharge) with error bars from covariance propagation, always showing both phases regardless of selected phase.
- **Regression window controls**: Skip (pts) and Length (pts) spinboxes matching pyICI defaults (`r1_start=2`, `r1_length=10`); Apply clears cache and recomputes all fits.
- **NavigationToolbar2Tk** on all three figures for zoom/pan/home.
- **Show all cycles** checkbox in selector strip.

### Changed
- Pulse detection mirrors pyICI `assign_valid_pulses` exactly: exact zero current check (not threshold), `max_rest` filter (300 s) to exclude CV phase and inter-cycle rests.
- ICI fit regression mirrors pyICI math: V₀ = last active voltage, √Δt relative to first rest point, window `[r1_start : r1_start + r1_length]`, `R = -intercept / I_A`, `k = -slope / I_A` with covariance error propagation.
- Cycle navigator bounded to actual number of cycles in loaded data.
- Pulse navigator bounded to actual pulses in selected cycle/phase; resets to 1 when cycle or phase changes, preserves position when navigating within the same phase.
- Right panel packed before left panel so it always reserves its width.
- Toolbar coordinate message disabled to prevent hover-induced resize.


### June 06, 2026

### Added
- **Capacity Analysis window** (`📈 Capacity` button): opens a side-by-side view of Voltage vs Time and Capacity vs Voltage plots from the loaded electrochemical data.
- **Charge/discharge/rest classification**: automatically classifies electrochemical data by current sign (positive = charge, negative = discharge, zero = rest).
- **Cycle detection**: automatically counts and numbers cycles, where each cycle starts with a charge step followed by a discharge step.
- **Capacity calculation**: cumulative capacity (mAh) computed via trapezoidal integration of current over time, reset at the start of each half-cycle.
- **Sample mass input** in the Capacity window: enter mass in mg to plot specific capacity (mAh/g). When mass is 0, capacity is shown in mAh.
- **Cycle selection input** in the Capacity window: filter which cycles to display. Accepts `all`, a single number, comma-separated numbers (`1,3,5`), or ranges (`1-5`).
- **Cycle count indicator** in the Capacity window: shows the total number of detected cycles next to the cycle input.
- **Export buttons** in the Capacity window: export Voltage vs Time, Capacity vs Voltage, or both plots as PNG/PDF/SVG at 300 DPI.
- Time axis in Voltage vs Time plot displayed in hours.


