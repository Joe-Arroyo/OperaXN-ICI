"""
nexusgen - test.py

Usage:
  python test.py /path/to/file.nxs
  # Optional custom output dir:
  python test.py /path/to/file.nxs --outdir /path/to/extract

What it does:
  - Opens the given .nxs file
  - Extracts global_metadata (with subgroups like edf_metadata, synchrotron_metadata)
  - Extracts up to the first 5 scans (scan_0001...)
  - Extracts operando and standard electrochemistry data
  - Saves:
      * xrd 1D -> xrd_oned.csv
      * xrd 2D (if embedded) -> xrd_twod.npy
      * neutron banks (TOF & d) -> bank_*/.csv
      * operando echem -> operando_echem.csv
      * standard echem -> standard_echem_*.csv
      * scan metadata -> included in per-file summary.json
  - Writes a quick per-file summary.json and prints a short terminal summary
"""

import argparse
import json
import os
import re
from typing import Dict, Any, List

import h5py
import numpy as np
import pandas as pd


def is_scan_group(name: str) -> bool:
    return bool(re.fullmatch(r"scan_\d{4}", name))


def safe_attr(h5obj, key, default=None):
    try:
        if key in h5obj.attrs:
            v = h5obj.attrs[key]
            if isinstance(v, bytes):
                return v.decode("utf-8", errors="ignore")
            return v.tolist() if hasattr(v, "tolist") else v
    except Exception:
        pass
    return default


def safe_data(h5group, name: str):
    try:
        if name in h5group:
            return h5group[name][()]
    except Exception:
        pass
    return None


def decode_value(v):
    """Decode HDF5 value to JSON-serializable Python type."""
    if v is None:
        return None
    if isinstance(v, bytes):
        return v.decode("utf-8", errors="ignore")
    if isinstance(v, np.ndarray):
        if v.size == 1:
            item = v.item()
            if isinstance(item, bytes):
                return item.decode("utf-8", errors="ignore")
            return item
        if v.size <= 20:
            return v.tolist()
        return f"<array shape={v.shape}>"
    if isinstance(v, (np.integer, np.floating)):
        return v.item()
    return v


def ensure_dir(p: str):
    os.makedirs(p, exist_ok=True)


def write_csv(path: str, header: List[str], data: np.ndarray):
    pd.DataFrame(data, columns=header).to_csv(path, index=False)


def extract_global_metadata(h5file, summary: Dict[str, Any]):
    """Extract all global_metadata including subgroups (edf_metadata, synchrotron_metadata)."""
    if "global_metadata" not in h5file:
        summary["global_metadata"] = None
        return

    gm = h5file["global_metadata"]
    gm_out: Dict[str, Any] = {}

    # Extract root attributes
    gm_out["_attributes"] = {}
    for attr_name in gm.attrs.keys():
        gm_out["_attributes"][attr_name] = decode_value(gm.attrs[attr_name])

    # Extract subgroups (edf_metadata, synchrotron_metadata, etc.)
    for subgroup_name in gm.keys():
        subgroup = gm[subgroup_name]

        if isinstance(subgroup, h5py.Group):
            sg_out: Dict[str, Any] = {"_attributes": {}, "_datasets": {}}

            # Subgroup attributes
            for attr_name in subgroup.attrs.keys():
                sg_out["_attributes"][attr_name] = decode_value(subgroup.attrs[attr_name])

            # Subgroup datasets
            for ds_name in subgroup.keys():
                item = subgroup[ds_name]
                if isinstance(item, h5py.Dataset):
                    sg_out["_datasets"][ds_name] = decode_value(item[()])

            gm_out[subgroup_name] = sg_out

        elif isinstance(subgroup, h5py.Dataset):
            # Direct dataset under global_metadata
            if "_datasets" not in gm_out:
                gm_out["_datasets"] = {}
            gm_out["_datasets"][subgroup_name] = decode_value(subgroup[()])

    summary["global_metadata"] = gm_out


def extract_xrd(scan_grp, outdir_scan: str, s: Dict[str, Any]):
    if "xrd_data" not in scan_grp:
        return
    xrd = scan_grp["xrd_data"]

    # 1D data
    th = safe_data(xrd, "oned_2theta")
    inten = safe_data(xrd, "oned_intensity")
    if th is not None and inten is not None and len(th) == len(inten):
        write_csv(os.path.join(outdir_scan, "xrd_oned.csv"),
                  ["two_theta", "intensity"],
                  np.column_stack([th, inten]))
        s["xrd_oned_points"] = int(len(th))
        s["xrd_oned_source"] = safe_attr(xrd, "oned_source_file")

    # 2D data - check if embedded or external
    img = safe_data(xrd, "twod_image")
    is_embedded = safe_attr(xrd, "twod_embedded")
    source_file = safe_attr(xrd, "twod_source")

    if img is not None and is_embedded:
        # Embedded 2D data
        np.save(os.path.join(outdir_scan, "xrd_twod.npy"), img)
        s["xrd_twod_shape"] = list(img.shape)
        s["xrd_twod_stored"] = "embedded"
        s["xrd_twod_source"] = source_file
    elif source_file and is_embedded is False:
        # External reference (2D exists but not embedded)
        s["xrd_twod_stored"] = "external"
        s["xrd_twod_source"] = source_file

        is_hdf = safe_attr(xrd, "twod_is_hdf", False)
        is_edf = safe_attr(xrd, "twod_is_edf", False)
        if is_hdf:
            s["xrd_twod_format"] = "hdf"
        elif is_edf:
            s["xrd_twod_format"] = "edf"

    original_shape = safe_attr(xrd, "twod_original_shape")
    if original_shape is not None:
        s["xrd_twod_original_shape"] = list(original_shape) if hasattr(original_shape, '__iter__') else original_shape

    max_display = safe_attr(xrd, "twod_max_display_size")
    if max_display is not None:
        s["xrd_twod_max_display_size"] = max_display


def extract_neutron(scan_grp, outdir_scan: str, s: Dict[str, Any]):
    if "neutron_data" not in scan_grp:
        return
    ng = scan_grp["neutron_data"]
    s["neutron_start"] = safe_attr(ng, "start_time")
    s["neutron_end"] = safe_attr(ng, "end_time")
    s["neutron_banks"] = banks = []
    for name in ng.keys():
        if not name.startswith("bank_"):
            continue
        b = ng[name]
        info = {"bank": name}

        # TOF data
        tof = safe_data(b, "tof")
        tofi = safe_data(b, "tof_intensity")
        if tof is not None and tofi is not None and len(tof) == len(tofi):
            write_csv(os.path.join(outdir_scan, f"{name}_tof.csv"),
                      ["tof", "intensity"], np.column_stack([tof, tofi]))
            info["tof_points"] = int(len(tof))
            info["tof_source"] = safe_attr(b, "tof_source_file")

        # d-spacing data
        d = safe_data(b, "d_spacing")
        di = safe_data(b, "d_intensity")
        if d is not None and di is not None and len(d) == len(di):
            write_csv(os.path.join(outdir_scan, f"{name}_d.csv"),
                      ["d_spacing", "intensity"], np.column_stack([d, di]))
            info["d_points"] = int(len(d))
            info["d_source"] = safe_attr(b, "d_source_file")

        if len(info) > 1:
            banks.append(info)


def extract_metadata(scan_grp, s: Dict[str, Any]):
    if "metadata" not in scan_grp:
        return
    md = scan_grp["metadata"]
    md_out = {}

    # Timestamps
    for key in ["scan_timestamp", "midpoint_adjusted_timestamp", "voltage_timestamp"]:
        v = safe_data(md, key)
        if v is None:
            continue
        if isinstance(v, (bytes, np.bytes_)):
            v = v.decode("utf-8", errors="ignore")
        md_out[key] = v.tolist() if hasattr(v, "tolist") else v

    # Exposure time
    exp_time = safe_data(md, "exposure_time")
    if exp_time is not None:
        try:
            md_out["exposure_time"] = float(np.array(exp_time).squeeze())
        except Exception:
            md_out["exposure_time"] = exp_time

    # Voltage and current with units
    for key in ["voltage (V)", "current (mA)"]:
        v = safe_data(md, key)
        if v is not None:
            try:
                md_out[key] = float(np.array(v).squeeze())
            except Exception:
                md_out[key] = v

    if md_out:
        s["metadata"] = md_out


def extract_operando_echem(h5file, outdir_root: str, summary: Dict[str, Any]):
    """Extract operando electrochemistry data."""
    if "operando_electrochemistry" not in h5file:
        summary["operando_echem_points"] = 0
        return

    e = h5file["operando_electrochemistry"]
    ts = safe_data(e, "timestamps")
    v = safe_data(e, "voltage (V)")
    i = safe_data(e, "current (mA)")

    def to1(x):
        if x is None:
            return None
        return np.array(x).reshape(-1)

    ts, v, i = to1(ts), to1(v), to1(i)
    summary["operando_echem_points"] = int(0 if ts is None else ts.shape[0])

    if ts is not None and v is not None and len(ts) == len(v):
        df = pd.DataFrame({"timestamp": ts.astype(str), "voltage_V": v})
        if i is not None and len(i) == len(ts):
            df["current_mA"] = i
        df.to_csv(os.path.join(outdir_root, "operando_echem.csv"), index=False)


def extract_standard_echem(h5file, outdir_root: str, summary: Dict[str, Any]):
    """Extract standard electrochemistry data files."""
    if "standard_electrochemistry" not in h5file:
        summary["standard_echem_files"] = 0
        return

    se = h5file["standard_electrochemistry"]
    num_files = safe_attr(se, "num_files", 0)
    summary["standard_echem_files"] = num_files

    extracted = []
    for file_name in se.keys():
        if not file_name.startswith("file_"):
            continue

        file_grp = se[file_name]
        source_file = safe_attr(file_grp, "source_file", file_name)

        ts = safe_data(file_grp, "timestamps")
        v = safe_data(file_grp, "voltage (V)")
        i = safe_data(file_grp, "current (mA)")

        def to1(x):
            if x is None:
                return None
            return np.array(x).reshape(-1)

        ts, v, i = to1(ts), to1(v), to1(i)

        if ts is not None and v is not None and len(ts) == len(v):
            df = pd.DataFrame({"timestamp": ts.astype(str), "voltage_V": v})
            if i is not None and len(i) == len(ts):
                df["current_mA"] = i

            output_name = f"standard_echem_{file_name}.csv"
            df.to_csv(os.path.join(outdir_root, output_name), index=False)

            extracted.append({
                "file": file_name,
                "source": source_file,
                "points": len(ts)
            })

    summary["standard_echem_extracted"] = extracted


def print_global_metadata_summary(gm: Dict[str, Any]):
    """Print a condensed summary of global metadata to terminal."""
    if gm is None:
        print("     global_metadata: not present")
        return

    print("     global_metadata:")

    # Root attributes
    attrs = gm.get("_attributes", {})
    if attrs:
        print(f"       root attributes: {len(attrs)} fields")
        for k in ["total_scans", "data_source", "generator", "generator_version",
                  "twod_included", "twod_max_display_size"]:
            if k in attrs:
                print(f"         {k}: {attrs[k]}")

    # Subgroups
    for key in gm:
        if key.startswith("_"):
            continue
        subgroup = gm[key]
        n_attrs = len(subgroup.get("_attributes", {}))
        n_datasets = len(subgroup.get("_datasets", {}))
        print(f"       {key}: {n_attrs} attrs, {n_datasets} datasets")

        # Show source file if available
        source = subgroup.get("_attributes", {}).get("source_file")
        if source:
            print(f"         source: {source}")


def main():
    ap = argparse.ArgumentParser(description="Extract first 5 scans from a single NXS file.")
    ap.add_argument("nxs_file", help="Path to a .nxs file")
    ap.add_argument("--outdir", help="Output directory (default: <file_stem>_extract)")
    args = ap.parse_args()

    nxs_path = os.path.abspath(args.nxs_file)
    if not os.path.isfile(nxs_path):
        raise SystemExit(f"File not found: {nxs_path}")

    outdir = args.outdir or (os.path.splitext(os.path.basename(nxs_path))[0] + "_extract")
    outdir = os.path.abspath(outdir)
    os.makedirs(outdir, exist_ok=True)

    summary: Dict[str, Any] = {
        "file": os.path.basename(nxs_path),
        "total_scans_seen": 0,
        "scans_processed": 0,
        "global_metadata": None,
        "scans": []
    }

    with h5py.File(nxs_path, "r") as f:
        # Extract global metadata first
        extract_global_metadata(f, summary)

        # Figure out first 5 scans
        scan_names = [k for k in f.keys() if is_scan_group(k)]
        scan_names.sort(key=lambda n: int(n.split("_")[1]))
        summary["total_scans_seen"] = len(scan_names)
        scan_names = scan_names[:5]
        summary["scans_processed"] = len(scan_names)

        # Per-file root
        file_root = outdir

        # Extract electrochemistry data
        extract_operando_echem(f, file_root, summary)
        extract_standard_echem(f, file_root, summary)

        # Process scans
        for scan_name in scan_names:
            scan_grp = f[scan_name]
            scan_num = int(scan_name.split("_")[1])
            scan_out = os.path.join(file_root, f"scan_{scan_num:04d}")
            ensure_dir(scan_out)

            s: Dict[str, Any] = {
                "scan_group": scan_name,
                "attrs": {
                    "NX_class": safe_attr(scan_grp, "NX_class"),
                    "scan_number": safe_attr(scan_grp, "scan_number", scan_num),
                }
            }

            extract_xrd(scan_grp, scan_out, s)
            extract_neutron(scan_grp, scan_out, s)
            extract_metadata(scan_grp, s)
            summary["scans"].append(s)

        # Write summary.json
        with open(os.path.join(file_root, "summary.json"), "w", encoding="utf-8") as fh:
            json.dump(summary, fh, indent=2, default=str)

    # Terminal summary
    print(f"[OK] {os.path.basename(nxs_path)} -> {outdir}")
    print(f"     scans processed: {summary['scans_processed']} / total in file: {summary['total_scans_seen']}")

    # Print global metadata summary
    print_global_metadata_summary(summary.get("global_metadata"))

    # Print electrochemistry summary
    if summary.get("operando_echem_points", 0) > 0:
        print(f"     operando electrochemistry: {summary['operando_echem_points']} points")

    if summary.get("standard_echem_files", 0) > 0:
        print(f"     standard electrochemistry: {summary['standard_echem_files']} files")
        for item in summary.get("standard_echem_extracted", []):
            print(f"       - {item['source']}: {item['points']} points")

    # Print scan details
    for s in summary["scans"]:
        bits = [s["scan_group"]]

        # XRD info
        if "xrd_oned_points" in s:
            bits.append(f"1D={s['xrd_oned_points']}pts")
        if s.get("xrd_twod_stored") == "embedded":
            shape_str = f"2D={s.get('xrd_twod_shape')}"
            if "xrd_twod_original_shape" in s and s["xrd_twod_original_shape"] != s.get("xrd_twod_shape"):
                shape_str += f" (original={s['xrd_twod_original_shape']})"
            bits.append(shape_str)
        elif s.get("xrd_twod_stored") == "external":
            fmt = s.get("xrd_twod_format", "unknown")
            bits.append(f"2D=external({fmt})")

        # Metadata
        md = s.get("metadata", {})
        if "voltage (V)" in md:
            bits.append(f"V={md['voltage (V)']}")
        if "current (mA)" in md:
            bits.append(f"I={md['current (mA)']}")
        if "exposure_time" in md:
            bits.append(f"exp={md['exposure_time']}s")

        # Neutron banks
        banks = s.get("neutron_banks", [])
        if banks:
            bits.append(f"neutron={len(banks)}banks")

        print("     - " + " | ".join(bits))


if __name__ == "__main__":
    main()
