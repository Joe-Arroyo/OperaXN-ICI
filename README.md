# OperaXN

**OPERAndo X-ray and Neutron diffraction data visualisation tool**

**OperaXN** is a Python-based desktop application for correlating, visualising and analysing *operando* diffraction data collected by laboratory XRD, synchrotron XRD or neutron diffraction sources. It also includes **Nexus Generator**, a companion tool for generating standardised NeXus (`.nxs`) files from raw electrochemical and diffraction data to facilitate easy data sharing in machine-readable formats.

## Features

### OperaXN
- Automated time-correlation of electrochemical (voltage and current) and diffraction datasets
- Simultaneous visualisation of X-ray (1D and 2D) and neutron diffraction data with electrochemical cycling
- Interactive GUI with scan navigation and visualisation controls
- Export publication-quality figures (PNG, PDF, SVG)
- Generate animated GIFs
- Currently supports `.dat`, `.xy`, `.edf`, `.hdf`, `.nxs`, `.txt`, and `.zip` files

### Nexus Generator
- Build Nexus files from raw diffraction and electrochemistry data
- Supports synchrotron, in-house, and neutron data types
- Embeds instrument metadata and time-correlated scan data
- Produces files compliant with the Nexus standard for seamless data sharing
  
## Installation

### From source

```bash
git clone https://github.com/matthewarlopowell/OperaXN.git
cd OperaXN
pip install .
```

### For development

```bash
pip install -e .
```

## Usage

### Launch OperaXN

```bash
operaxn
```

### Launch Nexus Generator

```bash
nexusgen
```

### Command line options

```bash
operaxn --help          # Show all options
operaxn --debug         # Enable debug logging
operaxn --check-deps    # Verify dependencies
```

## Time correlation

OperaXN correlates diffraction scans with electrochemistry data by timestamp. Two modes are available (selected at load time):

- **Absolute** — scan timestamps are matched directly to echem timestamps via nearest-neighbour lookup.
- **Relative** — both datasets are zeroed to their respective first timestamps and correlated by elapsed time. Useful when diffraction and echem clocks are not synchronised.

## Preferred data formats

### In-House

**1D data** (`.dat`) — whitespace-delimited columns with a `#` comment header containing a `Date` field in ISO 8601 format (e.g. `2023-04-19T10:30:00`) for time-correlation:

```
tth(°)    Intensity(a.u.)    Sigma_I(a.u.)
```

**2D data** (`.edf`) — raw 2D detector images in ESRF Data Format. Must include `Date` and `WaveLength` fields in the EDF header.

One file per scan, stored in a single directory. 1D and 2D files are paired by matching `Date` timestamps.

### Synchrotron

Synchrotron data is grouped by scan ID extracted from filenames. `.nxs` metadata files are required; `.xy` and `.hdf` are optional depending on whether 1D, 2D, or both are available.

**Metadata** (`.nxs`) — NeXus files providing `start_time` and `end_time` timestamps for time-correlation. The midpoint of each scan is used for echem matching.

**1D data** (`.xy`) — headerless, whitespace-delimited two-column data:

```
tth(°)    Intensity(a.u.)
```

**2D data** (`.hdf`) — 2D detector images stored in HDF5 format.

All file types are stored within a single parent directory (subdirectories are traversed). Files are matched by scan ID extracted from filenames.

### Neutron

**Logbook** (`.txt`) — ISIS instrument logbook, tab-delimited with ≥8 columns per row. Column 0 is a 5–7 digit scan ID; two columns contain start and end timestamps in `Day Mon DD HH:MM:SS YYYY` format (e.g. `Mon Jul 15 22:43:31 2024`). The midpoint of each scan is used for echem matching.

**TOF and d-spacing data** (`.dat`) — Mantid-exported files with a `#` comment header, three whitespace-delimited columns per bank:

```
# Time-of-flight         Y                 E
```

```
# d-Spacing              Y                 E
```

Files follow the naming convention `SCANID-BANK-0.dat` (TOF) and `SCANID-BANK-d-0.dat` (d-spacing), where SCANID is a 5–7 digit number and BANK is a single digit (1–5). POLARIS-format names (`POLSCANID-b_BANK.dat`) are also supported. All files are stored in a single directory alongside the logbook.

### Echem

Electrochemistry data as tab-delimited `.txt` with a header row and the following columns:

```
Timestamp    Voltage    Current
```

Column detection is keyword-based — headers containing `time`/`date`, `voltage`/`ecell`/`ewe`/`v/`, and `current`/`i/` are recognised automatically. If no header is detected, columns default to time, voltage, current in that order.

Timestamps must be absolute (e.g. `01/02/2024 10:30:00`) and are parsed day-first.

## Dependencies

- Python >= 3.9
- NumPy >= 1.20.0
- Pandas >= 2.0.0
- Matplotlib >= 3.4.0
- h5py >= 3.0.0
- Fabio >= 0.14.0
- OpenPyXL >= 3.0.0
- PSutil >= 5.8.0
- ImageIO >= 2.9.0

## Project Structure

```
OperaXN/
  bin/
    operaxn/       # Main visualisation application
    nexusgen/      # Nexus file generator
  examples/        # Example datasets
  pyproject.toml
  requirements.txt
```

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.

## AI Usage
This project was developed with the assistance of Claude (Anthropic).
