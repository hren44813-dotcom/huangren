"""Strict, independently executable V14 evidence gate. Source locating != engineering verification."""
from __future__ import annotations
import csv
import io
import json
from pathlib import Path

HERE = Path(__file__).resolve().parents[2]
HISTORY = HERE / "assets/history/history_reference_v13.json"
SEED = HERE / "assets/history/evidence_seed_v14.json"
REQUIRED = {"id", "model", "record_type", "sku_code", "image_source", "drawing_source", "confirmed_by", "confirmed_at"}


def inspect(history: dict, seed: dict) -> dict:
    records = history["records"]
    assert history["meta"]["record_count"] == len(records) == 74, "V13 history data unexpectedly changed"
    by_id = {r["id"]: r for r in records}
    assert len(by_id) == len(records), "duplicate historical IDs"
    assert all(REQUIRED <= r.keys() for r in records)
    assert seed.get("version") == "14.0"
    sources = {s["source_id"]: s for s in seed["sources"]}
    claims = seed["claims"]
    assert len(sources) == len(seed["sources"]) and len({c["claim_id"] for c in claims}) == len(claims)
    for s in sources.values():
        assert s["source_type"] == "manufacturer_catalog"
        assert s["sha256"] is None or (len(s["sha256"]) == 64 and all(k in "0123456789abcdef" for k in s["sha256"]))
    ids = set()
    for c in claims:
        assert c["history_id"] in by_id, "orphan evidence claim"
        assert c["source_id"] in sources, "missing source"
        assert c["field"] == "model_exists", "catalog presence is NOT a material, dimension or torque verification"
        assert c["value"] == by_id[c["history_id"]]["model"], "model identity mismatch"
        assert type(c["page"]) is int and 1 <= c["page"] <= 10000
        assert c["excerpt"].strip()
        assert c["history_id"] not in ids, "duplicate page-claim attachment for same historical record"
        ids.add(c["history_id"])
    assert all(r.get("release_status") == "历史记录·未完成原件核验" for r in records), "release status drift"
    return {
        "history_records": len(records),
        "model_records": sum(r["record_type"] == "历史型号（SKU待绑定）" for r in records),
        "page_located_records": len(ids),
        "unlocated_records": len(records) - len(ids),
        "source_file_sha256_count": sum(bool(s.get("sha256")) for s in sources.values()),
        "independently_engineering_verified_count": 0,
        "commercial_sku_confirmed_count": sum(bool(r.get("sku_code")) for r in records),
        "records": records,
        "claims_by_id": {c["history_id"]: c for c in claims}
    }


def audit(root: Path = HERE) -> dict:
    history = json.loads((root / "assets/history/history_reference_v13.json").read_text(encoding="utf-8"))
    seed = json.loads((root / "assets/history/evidence_seed_v14.json").read_text(encoding="utf-8"))
    return inspect(history, seed)


def export_csv(report: dict) -> bytes:
    s = io.StringIO(newline="")
    writer = csv.writer(s)
    writer.writerow(["历史编号", "品类", "系列", "型号", "记录类型", "原PDF页码", "证据范围", "工程参数已核实", "商业SKU已确认"])
    for r in report["records"]:
        claim = report["claims_by_id"].get(r["id"])
        values = [r["id"], r["category"], r["series"], r["model"], r["record_type"],
                  claim["page"] if claim else "", "仅型号存在" if claim else "无原始文件页码", "否", "否"]
        # Harden CSV against spreadsheet formula injection.
        writer.writerow(["'" + x if isinstance(x,str) and x.lstrip().startswith(("=","+","-","@")) else x for x in values])
    return ("\ufeff" + s.getvalue()).encode("utf-8")


if __name__ == "__main__":
    output = audit()
    print(json.dumps({k: v for k,v in output.items() if k not in ("records", "claims_by_id")}, ensure_ascii=False, indent=2))
