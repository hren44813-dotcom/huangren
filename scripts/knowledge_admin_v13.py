"""CLI for initializing and auditing the V13 knowledge provenance schema."""
from __future__ import annotations
import argparse,json,sqlite3,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/"src"))
from ecom_images.database_v9 import DEFAULT_DB
from ecom_images.knowledge_schema_v13 import initialize_knowledge
from ecom_images.knowledge_v13 import add_model,register_source_file,list_models
from ecom_images.knowledge_audit_v13 import knowledge_audit,knowledge_summary


def main(argv: list[str]|None=None) -> int:
    """Parse one action, execute it and return a shell exit code."""
    parser=argparse.ArgumentParser(description="工业五金知识库 V13"); parser.add_argument("--database",type=Path,default=DEFAULT_DB)
    actions=parser.add_subparsers(dest="action",required=True)
    actions.add_parser("init",help="在现有商品档案数据库上增量创建知识库表")
    actions.add_parser("check",help="只读检查知识库、证据完整度和冲突")
    actions.add_parser("summary",help="查看知识库数量统计")
    model=actions.add_parser("add-model",help="登记制造商型号，不自动绑定店铺SKU")
    model.add_argument("--code",required=True); model.add_argument("--category",required=True)
    model.add_argument("--manufacturer",default=""); model.add_argument("--series",default="")
    source=actions.add_parser("register-source-file",help="计算本地文件SHA-256并登记元数据")
    source.add_argument("--file",type=Path,required=True); source.add_argument("--kind",required=True)
    source.add_argument("--authority",default="user_supplied"); source.add_argument("--storage-ref",default="")
    source.add_argument("--document-family",default=""); source.add_argument("--document-number",default="")
    source.add_argument("--revision",default=""); source.add_argument("--issue-date",default="")
    source.add_argument("--media-type",default=""); source.add_argument("--pages",type=int)
    listing=actions.add_parser("list-models",help="列出型号身份")
    listing.add_argument("--search",default=""); listing.add_argument("--limit",type=int,default=100)
    args=parser.parse_args(argv)
    try:
        if args.action=="init":
            initialize_knowledge(args.database); print("知识库 V13 初始化/结构检查完成；旧表与历史记录保留")
        elif args.action=="check":
            result={"summary":knowledge_summary(args.database),"audit":knowledge_audit(args.database)}
            print(json.dumps(result,ensure_ascii=False,indent=2)); return 0 if result["audit"]["ok"] else 2
        elif args.action=="summary": print(json.dumps(knowledge_summary(args.database),ensure_ascii=False,indent=2))
        elif args.action=="add-model":
            ident=add_model(args.database,model_code=args.code,category=args.category,manufacturer_name=args.manufacturer,series=args.series)
            print(json.dumps({"model_id":ident,"model_code":args.code},ensure_ascii=False))
        elif args.action=="register-source-file":
            ident=register_source_file(args.database,file_path=args.file,source_kind=args.kind,authority_level=args.authority,
                storage_ref=args.storage_ref,document_family=args.document_family,document_number=args.document_number,
                revision_label=args.revision,issue_date=args.issue_date,media_type=args.media_type,page_count=args.pages)
            print(json.dumps({"source_id":ident,"filename":args.file.name},ensure_ascii=False))
        elif args.action=="list-models": print(json.dumps(list_models(args.database,search=args.search,limit=args.limit),ensure_ascii=False,indent=2))
        return 0
    except (ValueError,RuntimeError,OSError,sqlite3.Error) as exc:
        print(f"知识库操作失败：{exc}",file=sys.stderr); return 1


if __name__=="__main__": raise SystemExit(main())
