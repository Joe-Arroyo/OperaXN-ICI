"""
NXS_Generator - test.py

Usage:
  python test.py /path/to/file.nxs
  # Optional custom output dir:
  python test.py /path/to/file.nxs --outdir /path/to/extract

What it does:
  - Opens the given .nxs file
  - Extracts global_metadata (instrument_settings, beamline_settings)
  - Extracts up to the first 5 scans (scan_0001...)
  - Saves:
      * xrd 1D -> xrd_oned.csv
      * xrd 2D (if embedded) -> xrd_twod.npy
      * neutron banks (TOF & d) -> bank_*/.csv
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
    """Extract all global_metadata including instrument_settings and beamline_settings."""
    if "global_metadata" not in h5file:
        summary["global_metadata"] = None
        return

    gm = h5file["global_metadata"]
    gm_out: Dict[str, Any] = {}

    # Extract root attributes
    gm_out["_attributes"] = {}
    for attr_name in gm.attrs.keys():
        gm_out["_attributes"][attr_name] = decode_value(gm.attrs[attr_name])

    # Extract subgroups (instrument_settings, beamline_settings, etc.)
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
    th = safe_data(xrd, "oned_2theta")
    inten = safe_data(xrd, "oned_intensity")
    if th is not None and inten is not None and len(th) == len(inten):
        write_csv(os.path.join(outdir_scan, "xrd_oned.csv"),
                  ["two_theta", "intensity"],
                  np.column_stack([th, inten]))
        s["xrd_oned_points"] = int(len(th))

    img = safe_data(xrd, "twod_image")
    if img is not None:
        np.save(os.path.join(outdir_scan, "xrd_twod.npy"), img)
        s["xrd_twod_shape"] = list(img.shape)
        s["xrd_twod_stored"] = "embedded"
    else:
        if safe_attr(xrd, "twod_is_hdf", False):
            s["xrd_twod_stored"] = "external_hdf"
            s["xrd_twod_source_file"] = safe_attr(xrd, "twod_source_file")


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
        tof = safe_data(b, "tof")
        tofi = safe_data(b, "tof_intensity")
        if tof is not None and tofi is not None and len(tof) == len(tofi):
            write_csv(os.path.join(outdir_scan, f"{name}_tof.csv"),
                      ["tof", "intensity"], np.column_stack([tof, tofi]))
            info["tof_points"] = int(len(tof))
        d = safe_data(b, "d_spacing")
        di = safe_data(b, "d_intensity")
        if d is not None and di is not None and len(d) == len(di):
            write_csv(os.path.join(outdir_scan, f"{name}_d.csv"),
                      ["d_spacing", "intensity"], np.column_stack([d, di]))
            info["d_points"] = int(len(d))
        if len(info) > 1:
            banks.append(info)


def extract_metadata(scan_grp, s: Dict[str, Any]):
    if "metadata" not in scan_grp:
        return
    md = scan_grp["metadata"]
    md_out = {}
    for key in ["scan_timestamp", "midpoint_adjusted_timestamp", "voltage_timestamp", "exposure_time"]:
        v = safe_data(md, key)
        if v is None:
            continue
        if isinstance(v, (bytes, np.bytes_)):
            v = v.decode("utf-8", errors="ignore")
        md_out[key] = v.tolist() if hasattr(v, "tolist") else v
    for key in ["voltage", "current"]:
        v = safe_data(md, key)
        if v is not None:
            try:
                md_out[key] = float(np.array(v).squeeze())
            except Exception:
                md_out[key] = v
    if md_out:
        s["metadata"] = md_out


def extract_echem_global(h5file, outdir_root: str, summary: Dict[str, Any]):
    if "electrochemistry" not in h5file:
        return
    e = h5file["electrochemistry"]
    ts = safe_data(e, "timestamps")
    v = safe_data(e, "voltage")
    i = safe_data(e, "current")

    def to1(x):
        if x is None:
            return None
        return np.array(x).reshape(-1)

    ts, v, i = to1(ts), to1(v), to1(i)
    summary["echem_points"] = int(0 if ts is None else ts.shape[0])
    if ts is not None and v is not None and len(ts) == len(v):
        df = pd.DataFrame({"timestamp": ts.astype(str), "voltage": v})
        if i is not None and len(i) == len(ts):
            df["current"] = i
        df.to_csv(os.path.join(outdir_root, "echem_timeseries.csv"), index=False)


def print_global_metadata_summary(gm: Dict[str, Any]):
    """Print a condensed summary of global metadata to terminal."""
    if gm is None:
        print("     global_metadata: not present")
        return

    print("     global_metadata:")

    # Root attributes
    attrs = gm.get("_attributes", {})
    if attrs:
        print(f"       attributes: {len(attrs)} fields")
        for k in ["total_scans", "data_source", "generator", "generator_version"]:
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
        # Global echem
        extract_echem_global(f, file_root, summary)

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

    for s in summary["scans"]:
        bits = [s["scan_group"]]
        if "xrd_oned_points" in s:
            bits.append(f"1D={s['xrd_oned_points']}pts")
        if s.get("xrd_twod_stored") == "embedded":
            bits.append(f"2D={s.get('xrd_twod_shape')}")
        elif s.get("xrd_twod_stored") == "external_hdf":
            bits.append("2D=external(HDF)")
        md = s.get("metadata", {})
        if "voltage" in md:
            bits.append(f"V={md['voltage']}")
        if "current" in md:
            bits.append(f"I={md['current']}")
        print("     - " + " | ".join(bits))


if __name__ == "__main__":
    main()
