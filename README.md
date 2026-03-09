# OperaXN

**OPERAndo X-ray and Neutron diffraction data visualisation tool**

OperaXN is a Python-based desktop application for correlating, visualising and analysing *operando* diffraction data collected by laboratory XRD, synchrotron XRD or neutron diffraction sources. It also includes **nexusgen**, a companion tool for generating standardised NeXus (`.nxs`) files from raw electrochemical and diffraction data to facilitate easy data sharing in machine-readable formats.

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

### Launch the visualiser

```bash
operaxn
```

### Launch the NeXus file generator

```bash
nexusgen
```

### Command line options

```bash
operaxn --help          # Show all options
operaxn --debug         # Enable debug logging
operaxn --check-deps    # Verify dependencies
```

## Preferred data formats

### In-House

**1D data** (`.dat`) - whitespace-delimited columns with a `#` comment header containing a `Date` field for time-correlation:

```
tth(°)    Intensity(a.u.)    Sigma_I(a.u.)
```

**2D data** (`.edf`) - raw 2D detector images in ESRF Data Format. Must include `Date` and `WaveLength` fields in the EDF header.

One file per scan, stored in a single directory. Files are sorted by name to determine scan order (eg: 20231204_1_00446_azimAvg.dat, 20231204_1_00398.edf).

### Synchrotron

Synchrotron data requires three file types grouped by scan ID:

**Metadata** (`.nxs`) - NeXus files containing `start_time` and `end_time` fields (under `entry1/`) used for time-correlation with electrochemistry data.

**1D data** (`.xy`) - headerless, whitespace-delimited two-column data:

```
tth(°)    Intensity(a.u.)
```

**2D data** (`.hdf`) - 2D detector images stored in HDF5 format (under `entry/data/data`).

All three file types are stored in subdirectories within a single parent directory. Files are matched by scan ID extracted from filenames (eg: i11-1-85000.nxs,  i11-1-85000_integration_tth_0000_HM28.xy, pixium_85000.hdf).

### Neutron

**Logbook** (`.txt`) - tab-delimited logbook file containing scan IDs (5–7 digit) with start and end timestamps for time-correlation. Timestamps are in `Day Mon DD HH:MM:SS YYYY` format.

**TOF and d-spacing data** (`.dat`) - Mantid-exported files with a `#` comment header, three whitespace-delimited columns per bank:

```
# Time-of-flight         Y                 E
```

```
# d-Spacing              Y                 E
```

Files follow the naming convention `SCAN-BANK_ID-0.dat` (TOF) and `SCAN-BANK_ID-d-0.dat` (d-spacing). All banks and scans are stored in a single directory alongside the logbook.

### Echem

Electrochemistry data as `.xlsx` or `.txt` with the following columns and absolute timestamps:

```
Absolute    Elapsed    Current [A]    Voltage [V]
```

Absolute timestamps are required for time-correlation with diffraction scans.

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
