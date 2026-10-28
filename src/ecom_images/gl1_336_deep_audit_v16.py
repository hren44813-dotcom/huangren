"""Reproducible source-level audit for GL1-336; not an engineering certification."""
from __future__ import annotations
import argparse, hashlib, json, re
from pathlib import Path
from typing import Any
EXPECTED_SCHEMA="16.0"
ALLOWED_CLAIM_STATUSES={"verified_local_file_integrity","confirmed_in_source_only","transcribed_not_independently_verified","catalog_declared_not_engineering_verified","catalog_declared_not_measured","prefix_ambiguous_pending_second_review","open_conflict","open_gap","inconclusive"}
def load_evidence(path:Path)->dict[str,Any]: return json.loads(path.read_text(encoding="utf-8"))
def validate_evidence(e:dict[str,Any])->dict[str,Any]:
 errors=[]; src=e.get("source",{}); fp=src.get("source_integrity",{}); loc=src.get("page_locator",{}); target=e.get("target",{})
 if e.get("version")!=EXPECTED_SCHEMA: errors.append("evidence version must be 16.0")
 if target.get("model")!="GL1-336": errors.append("scope must remain limited to GL1-336")
 if not re.fullmatch(r"[0-9a-f]{64}",str(fp.get("sha256",""))): errors.append("source SHA-256 is missing or invalid")
 if fp.get("size_bytes")!=173132513: errors.append("unexpected source file size")
 if fp.get("pdf_pages")!=195: errors.append("unexpected PDF page count")
 if loc.get("pdf_page_1based")!=37 or str(loc.get("printed_page_visible"))!="24": errors.append("target page locator changed unexpectedly")
 ids=set()
 for c in e.get("claims",[]):
  cid=c.get("claim_id")
  if not cid or cid in ids: errors.append(f"missing or duplicate claim id: {cid}")
  ids.add(cid)
  if c.get("pdf_page_1based")!=37: errors.append(f"claim {cid} is outside the single target page")
  if c.get("status") not in ALLOWED_CLAIM_STATUSES: errors.append(f"claim {cid} has an unapproved status")
  if c.get("independent_reviewer") is not None: errors.append(f"claim {cid} incorrectly names an independent reviewer")
  if c.get("status") in {"independently_verified","engineering_verified","physically_verified"}: errors.append(f"claim {cid} overstates verification")
 codes=e.get("catalog_variant_rows",[])
 if len(codes)!=12: errors.append("expected exactly 12 catalog part-code rows")
 if len({c.get("visual_transcription_candidate") for c in codes})!=12: errors.append("candidate part codes must be unique")
 for r in codes:
  if r.get("history_sku_binding") is not None: errors.append("catalog part code must not be silently bound to a shop SKU")
  if r.get("code_status")!="needs_second_person_and_BOM_confirmation": errors.append("part-code prefix ambiguity must remain open")
 conflicts={c.get("conflict_id"):c for c in e.get("conflicts",[])}
 for required in ("CON-001","CON-002","CON-003","CON-004","CON-005"):
  if required not in conflicts or conflicts[required].get("status")!="OPEN": errors.append(f"required conflict {required} must remain open")
 matrix=e.get("verification_matrix",{})
 for k in ("physical_product_identity","store_sku_binding","independent_engineer_review","manufacturer_confirmation","independent_measurement"):
  if matrix.get(k) not in {"not_verified","not_performed","not_obtained"}: errors.append(f"verification matrix overstates {k}")
 return {"ok":not errors,"version":EXPECTED_SCHEMA,"target_model":target.get("model"),"claims":len(e.get("claims",[])),"catalog_part_code_rows":len(codes),"open_conflicts":sorted(conflicts),"independent_engineering_verifications":0,"errors":errors}
def exact_model_occurrences(text:str,model:str="GL1-336")->list[str]:
 """Find exact model tokens; suffixes and longer codes must not match."""
 return re.findall(r"(?<![A-Z0-9.\-])"+re.escape(model.upper())+r"(?![A-Z0-9.\-])",text.upper())
def extract_code_forms(text:str)->list[str]:
 """Return literal text-layer code forms without normalizing O to zero."""
 return sorted(set(re.findall(r"HC[O0]1-\d{5}",text)))
def sha256_file(path:Path)->str:
 h=hashlib.sha256()
 with path.open("rb") as f:
  for chunk in iter(lambda:f.read(1024*1024),b""): h.update(chunk)
 return h.hexdigest()
def audit_pdf(pdf_path:Path,e:dict[str,Any],out:Path)->dict[str,Any]:
 try: import fitz
 except ImportError as exc: raise RuntimeError("PyMuPDF is required: pip install 'PyMuPDF>=1.24,<2'") from exc
 src=e["source"];fp=src["source_integrity"];actual=sha256_file(pdf_path);size=pdf_path.stat().st_size
 if actual!=fp["sha256"] or size!=fp["size_bytes"]: raise ValueError("Source fingerprint mismatch; refusing to audit a different PDF.")
 d=fitz.open(pdf_path)
 if len(d)!=fp["pdf_pages"]: raise ValueError(f"PDF page count mismatch: expected {fp['pdf_pages']}, got {len(d)}")
 n=src["page_locator"]["pdf_page_1based"];p=d[n-1];text=p.get_text();hits=exact_model_occurrences(text,"GL1-336")
 if len(hits)<2 or "N.m" not in text or "1215" not in text: raise ValueError("Target page anchors GL1-336 / N.m / 1215 not all found.")
 out.mkdir(parents=True,exist_ok=True);crops=[]
 for item in src.get("derived_artifacts",[]):
  pix=p.get_pixmap(matrix=fitz.Matrix(1.4,1.4),clip=fitz.Rect(*item["crop_pdf_user_space"]),alpha=False);path=out/item["file"];pix.save(path);digest=sha256_file(path)
  crops.append({"file":item["file"],"sha256":digest,"reference_sha256":item["sha256"],"reference_hash_matches":digest==item["sha256"],"bytes":path.stat().st_size,"width_px":pix.width,"height_px":pix.height,"note":"Renderer-version differences may change PNG bytes; original PDF hash is the primary identity check."})
 (out/"page37_text_layer.txt").write_text(text,encoding="utf-8")
 result={"version":EXPECTED_SCHEMA,"source_sha256":actual,"source_size_bytes":size,"pdf_pages":len(d),"pdf_page_1based":n,"printed_page_visible":src["page_locator"]["printed_page_visible"],"exact_model_text_occurrences":len(hits),"catalog_torque_header_found":"N.m" in text,"catalog_material_label_found":"1215" in text,"text_layer_code_forms":extract_code_forms(text),"rendered_crops":crops,"source_revision_current":"unknown","physical_item_identity":"not_verified","engineering_parameters":"catalog_transcribed_not_independently_verified","store_sku_binding":"not_verified","warning":"Hash verifies the supplied bytes only; catalog transcription is not an engineering test."}
 (out/"gl1_336_pdf_audit_v16.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8");return result
def main(argv:list[str]|None=None)->int:
 p=argparse.ArgumentParser(description=__doc__);p.add_argument("pdf",type=Path);p.add_argument("--evidence",type=Path,default=Path("assets/gl1_336_deep_evidence_v16.json"));p.add_argument("--output-dir",type=Path,default=Path("build/gl1_336_v16"));a=p.parse_args(argv)
 e=load_evidence(a.evidence);v=validate_evidence(e)
 if not v["ok"]: print(json.dumps(v,ensure_ascii=False,indent=2));return 2
 r=audit_pdf(a.pdf,e,a.output_dir);print(json.dumps({"registry_validation":v,"pdf_audit":r},ensure_ascii=False,indent=2));return 0
if __name__=="__main__": raise SystemExit(main())
