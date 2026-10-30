"""A declared cohort passes only with bound, observable business evidence."""
import argparse
import json
from pathlib import Path


def complete(document):
    required=document.get('required',[])
    if not required:return False
    rows={(row['id'],row.get('variant','default')):row for row in document.get('results',[])}
    for item in required:
        key=(item['id'],item.get('variant','default'))
        row=rows.get(key,{})
        if row.get('status')!='passed' or row.get('binding')!='bound' or row.get('assertions',0)<1 or row.get('kind')!='business':return False
    if not set(document.get('required_platforms',[]))<=set(document.get('platforms',[])):return False
    if document.get('claims_live') and not document.get('live_evidence'):return False
    return True


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('report',type=Path)
    args=parser.parse_args();data=json.loads(args.report.read_text(encoding='utf-8'))
    passed=complete(data);print('passed' if passed else 'incomplete-or-failed')
    return 0 if passed else 1


if __name__=='__main__':raise SystemExit(main())
