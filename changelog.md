# Changelog

## [Unreleased]

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
