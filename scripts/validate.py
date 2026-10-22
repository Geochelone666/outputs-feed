#!/usr/bin/env python3
"""Validate feed.json and live-status.json against the published contract.

Stdlib only, so it runs in CI and in the external producer before it replaces files.
The rules mirror schema/*.schema.json plus checks a JSON Schema cannot express:
unique ids, and a guard against leaking private addresses or local paths into this
public repo.

Usage: python3 scripts/validate.py [REPO_DIR]
Exit status: 0 valid (warnings may be printed), 1 errors found.
"""
import json
import math
import re
import sys
from datetime import datetime
from pathlib import Path

# Things that must never appear in a public snapshot (see README "发布约定").
LEAK_PATTERNS = [
    (re.compile(r"\b10\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"), "private IPv4 (10/8)"),
    (re.compile(r"\b192\.168\.\d{1,3}\.\d{1,3}\b"), "private IPv4 (192.168/16)"),
    (re.compile(r"\b172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}\b"), "private IPv4 (172.16/12)"),
    (re.compile(r"\b100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}\b"),
     "CGNAT/Tailscale IPv4 (100.64/10)"),
    (re.compile(r"(/home/|/Users/|~/)[\w.-]+"), "local filesystem path"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "private key"),
    (re.compile(r"\b(ghp|gho|github_pat)_[A-Za-z0-9_]{20,}"), "GitHub token"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"), "API secret key"),
]

MEM_RE = re.compile(r"^\d+/\d+$")
LOAD_FAILED = object()


def parse_dt(value):
    """Return an aware datetime for an ISO 8601 string with timezone, else None."""
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo is not None else None


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool)
            and (not isinstance(v, float) or math.isfinite(v)))


def nonempty_str(v):
    return isinstance(v, str) and v.strip() != ""


def check_leaks(name, raw, errors):
    for rx, what in LEAK_PATTERNS:
        m = rx.search(raw)
        if m:
            errors.append(f"{name}: contains {what}: {m.group(0)!r}")


def validate_feed(data):
    errors = []
    if not isinstance(data, dict):
        return ["feed.json: top level must be an object"]
    if parse_dt(data.get("updated")) is None:
        errors.append("feed.json: 'updated' must be ISO 8601 with timezone")
    outputs = data.get("outputs")
    if not isinstance(outputs, list):
        errors.append("feed.json: 'outputs' must be an array")
        return errors
    seen = set()
    for i, o in enumerate(outputs):
        where = f"feed.json: outputs[{i}]"
        if not isinstance(o, dict):
            errors.append(f"{where} must be an object")
            continue
        for key in ("id", "project", "title", "type"):
            if not nonempty_str(o.get(key)):
                errors.append(f"{where}.{key} must be a non-empty string")
        if not isinstance(o.get("summary"), str):
            errors.append(f"{where}.summary must be a string")
        if parse_dt(o.get("ts")) is None:
            errors.append(f"{where}.ts must be ISO 8601 with timezone")
        url = o.get("url")
        if not (isinstance(url, str) and url.startswith("https://")):
            errors.append(f"{where}.url must be an https:// URL")
        oid = o.get("id")
        if isinstance(oid, str):
            if oid in seen:
                errors.append(f"{where}.id {oid!r} is duplicated")
            seen.add(oid)
    return errors


def validate_status(data):
    errors = []
    if not isinstance(data, dict):
        return ["live-status.json: top level must be an object"]
    if parse_dt(data.get("updated_utc")) is None:
        errors.append("live-status.json: 'updated_utc' must be ISO 8601 with timezone")
    else:
        off = parse_dt(data["updated_utc"]).utcoffset()
        if off is not None and off.total_seconds() != 0:
            errors.append("live-status.json: 'updated_utc' must be in UTC")
    vms = data.get("vms")
    if not isinstance(vms, list):
        errors.append("live-status.json: 'vms' must be an array")
        vms = []
    for i, vm in enumerate(vms):
        where = f"live-status.json: vms[{i}]"
        if not isinstance(vm, dict):
            errors.append(f"{where} must be an object")
            continue
        if not nonempty_str(vm.get("name")):
            errors.append(f"{where}.name must be a non-empty string")
        if not isinstance(vm.get("reachable"), bool):
            errors.append(f"{where}.reachable must be true/false")
        load = vm.get("load1")
        if load is not None and not (is_num(load) and load >= 0):
            errors.append(f"{where}.load1 must be a non-negative number or null")
        mem = vm.get("mem")
        if mem is not None:
            if not (isinstance(mem, str) and MEM_RE.match(mem)):
                errors.append(f"{where}.mem must look like 'used/total' or be null")
            else:
                used, total = (int(x) for x in mem.split("/"))
                if total == 0 or used > total:
                    errors.append(f"{where}.mem used/total is inconsistent: {mem}")
    cron = data.get("cron_count")
    if not (is_int(cron) and cron >= 0):
        errors.append("live-status.json: 'cron_count' must be a non-negative integer")
    outs = data.get("outputs")
    if not isinstance(outs, dict):
        errors.append("live-status.json: 'outputs' must be an object")
    else:
        for key in ("total", "public"):
            if not (is_int(outs.get(key)) and outs[key] >= 0):
                errors.append(f"live-status.json: outputs.{key} must be a non-negative integer")
        if is_int(outs.get("total")) and is_int(outs.get("public")) and outs["public"] > outs["total"]:
            errors.append("live-status.json: outputs.public exceeds outputs.total")
    shadow = data.get("shadow_last_run")
    if shadow is not None and parse_dt(shadow) is None:
        errors.append("live-status.json: 'shadow_last_run' must be ISO 8601 with timezone or null")
    return errors


def cross_warnings(feed, status):
    """Soft consistency checks; the two files are written independently."""
    warnings = []
    try:
        public = status["outputs"]["public"]
        n = len(feed["outputs"])
    except (KeyError, TypeError):
        return warnings
    if is_int(public) and public != n:
        warnings.append(f"live-status.json outputs.public={public} but feed.json lists {n} outputs")
    return warnings


def reject_constant(value):
    raise ValueError(f"non-standard numeric constant {value}")


def finite_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("numeric value exceeds finite float range")
    return number


def load(path, errors):
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as e:
        errors.append(f"{path.name}: cannot read: {e}")
        return LOAD_FAILED, ""
    try:
        return json.loads(raw, parse_constant=reject_constant, parse_float=finite_float), raw
    except ValueError as e:
        errors.append(f"{path.name}: invalid JSON: {e}")
        return LOAD_FAILED, raw


def validate_dir(root):
    root = Path(root)
    errors, warnings = [], []
    feed, _ = load(root / "feed.json", errors)
    status, _ = load(root / "live-status.json", errors)
    if feed is not LOAD_FAILED:
        errors += validate_feed(feed)
        # Scan decoded keys and values: JSON Unicode escapes must not hide a leak.
        check_leaks("feed.json", json.dumps(feed, ensure_ascii=False), errors)
    if status is not LOAD_FAILED:
        errors += validate_status(status)
        check_leaks("live-status.json", json.dumps(status, ensure_ascii=False), errors)
    if feed is not LOAD_FAILED and status is not LOAD_FAILED:
        warnings += cross_warnings(feed, status)
    return errors, warnings


def main(argv):
    root = argv[1] if len(argv) > 1 else Path(__file__).resolve().parents[1]
    errors, warnings = validate_dir(root)
    for w in warnings:
        print(f"warning: {w}")
    for e in errors:
        print(f"error: {e}")
    if errors:
        return 1
    print("feed.json and live-status.json are valid")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
