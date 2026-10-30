"""Require the latest Linux and Windows workflow attempts for the exact SHA."""
import argparse
import json
from pathlib import Path

REQUIRED=('Test (Linux)','Test (Windows)')


def ready(document,sha):
    runs=document.get('workflow_runs',[]) if isinstance(document,dict) else document
    for name in REQUIRED:
        matching=[run for run in runs if run.get('name')==name and run.get('head_sha')==sha]
        if not matching:return False
        latest=max(matching,key=lambda run:(run.get('id',0),run.get('run_attempt',0)))
        if latest.get('status')!='completed' or latest.get('conclusion')!='success':return False
    return True


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report',type=Path);parser.add_argument('sha')
    args=parser.parse_args()
    result=ready(json.loads(args.report.read_text(encoding='utf-8')),args.sha)
    print('success' if result else 'missing-or-not-green')
    return 0 if result else 1


if __name__=='__main__':raise SystemExit(main())
