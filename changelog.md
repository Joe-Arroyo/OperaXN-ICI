# Changelog

## [Unreleased]

June 06, 2026

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
