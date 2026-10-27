"""历史商品参考知识库命令行（不把历史参考记录写入正式 SKU 表）。"""
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from ecom_images.database_v9 import DEFAULT_DB
from ecom_images.history_reference_v13 import initialize_history,import_reference,list_reference,history_integrity

def main(argv=None):
    p=argparse.ArgumentParser(description='历史商品结构参考库管理')
    p.add_argument('--database',type=Path,default=DEFAULT_DB)
    sub=p.add_subparsers(dest='action',required=True)
    sub.add_parser('init')
    imp=sub.add_parser('import'); imp.add_argument('--input',type=Path,default=ROOT/'assets/history/history_reference_v13.json');imp.add_argument('--dry-run',action='store_true')
    look=sub.add_parser('find');look.add_argument('--model',default='');look.add_argument('--category',default='');look.add_argument('--limit',type=int,default=100)
    sub.add_parser('check')
    a=p.parse_args(argv)
    try:
        if a.action=='init':initialize_history(a.database);result={'ok':True,'action':'init'}
        elif a.action=='import':result=import_reference(a.database,a.input.read_bytes(),dry_run=a.dry_run)
        elif a.action=='find':result=list_reference(a.database,text=a.model,category=a.category,limit=a.limit)
        else:result=history_integrity(a.database)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0 if not isinstance(result,dict) or result.get('ok',True) else 1
    except (OSError,ValueError,RuntimeError) as exc:
        print(f'操作失败：{exc}',file=sys.stderr);return 2
if __name__=='__main__':raise SystemExit(main())
