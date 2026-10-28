"""CLI for the V13 document import, search and integrity audit."""
from __future__ import annotations
import argparse,json,sqlite3,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/"src"))
from ecom_images.database_v9 import DEFAULT_DB
from ecom_images.knowledge_schema_v13 import initialize_knowledge
from ecom_images.knowledge_ingest_v13 import (
    audit_document_store,import_document,initialize_ingestion,knowledge_document_summary,search_knowledge,search_models,
)

def main(argv:list[str]|None=None)->int:
    parser=argparse.ArgumentParser(description="工业五金知识库 V13：文件导入、解析、型号与参数检索")
    parser.add_argument("--database",type=Path,default=DEFAULT_DB)
    actions=parser.add_subparsers(dest="action",required=True)
    actions.add_parser("init",help="初始化 V13 知识库与增量文档检索表")
    imp=actions.add_parser("import-file",help="导入并索引一个本地文件")
    imp.add_argument("--file",type=Path,required=True)
    imp.add_argument("--kind",choices=["manufacturer_document","supplier_document","purchase_record","physical_photo","lab_report","platform_export","internal_note","other"],default="other")
    imp.add_argument("--authority",choices=["unverified","user_supplied","manufacturer_controlled","independent_test","system_export"],default="user_supplied")
    imp.add_argument("--document-family",default=""); imp.add_argument("--document-number",default="")
    imp.add_argument("--revision",default=""); imp.add_argument("--issue-date",default="")
    search=actions.add_parser("search",help="检索原始资料、型号、SKU 自由文本及已有参数主张")
    search.add_argument("--query",default=""); search.add_argument("--model",default=""); search.add_argument("--attribute",default="")
    search.add_argument("--limit",type=int,default=50)
    models=actions.add_parser("search-models",help="仅检索已登记的制造商型号")
    models.add_argument("--query",default=""); models.add_argument("--limit",type=int,default=100)
    actions.add_parser("summary",help="查看索引统计")
    actions.add_parser("audit",help="只读检查源文件指纹与索引完整性")
    args=parser.parse_args(argv)
    try:
        if args.action=="init":
            initialize_knowledge(args.database); initialize_ingestion(args.database)
            print(json.dumps({"ok":True,"message":"V13 知识库及文档检索表已初始化/检查","summary":knowledge_document_summary(args.database)},ensure_ascii=False,indent=2))
        elif args.action=="import-file":
            result=import_document(args.database,file_path=args.file,source_kind=args.kind,authority_level=args.authority,
                document_family=args.document_family,document_number=args.document_number,
                revision_label=args.revision,issue_date=args.issue_date)
            print(json.dumps(result,ensure_ascii=False,indent=2))
        elif args.action=="search":
            print(json.dumps(search_knowledge(args.database,query=args.query,model_code=args.model,
                attribute=args.attribute,limit=args.limit),ensure_ascii=False,indent=2))
        elif args.action=="search-models":
            print(json.dumps(search_models(args.database,query=args.query,limit=args.limit),ensure_ascii=False,indent=2))
        elif args.action=="summary":
            print(json.dumps(knowledge_document_summary(args.database),ensure_ascii=False,indent=2))
        elif args.action=="audit":
            result=audit_document_store(args.database); print(json.dumps(result,ensure_ascii=False,indent=2))
            return 0 if result["ok"] else 2
        return 0
    except (ValueError,RuntimeError,OSError,sqlite3.Error) as exc:
        print(f"知识库文档操作失败：{exc}",file=sys.stderr); return 1

if __name__=="__main__": raise SystemExit(main())
