"""Gate statements and branches separately; missing measured modules fail closed."""
import argparse
import json
from pathlib import Path

CLI=('src/cli.py','src/cli_parity.py')
CORE=('src/core/workflow_lifecycle.py','src/core/execution_snapshots.py',
      'src/core/playwright_runtime.py','src/core/config_transactions.py')


def measure(document,modules):
    files={name.replace('\\','/'):value for name,value in document.get('files',{}).items()}
    totals=dict(lines=0,statements=0,branches=0,total_branches=0)
    for module in modules:
        matches=[value for name,value in files.items() if name==module or name.endswith('/'+module)]
        if len(matches)!=1:raise ValueError('Missing or ambiguous measured module: '+module)
        summary=matches[0]['summary']
        if 'num_branches' not in summary:raise ValueError('Branch measurement is required')
        totals['lines']+=summary['covered_lines'];totals['statements']+=summary['num_statements']
        totals['branches']+=summary['covered_branches'];totals['total_branches']+=summary['num_branches']
    if not totals['statements'] or not totals['total_branches']:raise ValueError('Empty coverage cannot pass')
    return 100*totals['lines']/totals['statements'],100*totals['branches']/totals['total_branches']


def evaluate(document,core=True):
    result=[]
    for label,modules,lines,branches in [('CLI',CLI,85,75)]+([('core',CORE,90,85)] if core else []):
        actual_lines,actual_branches=measure(document,modules)
        result.append({'group':label,'statements':actual_lines,'branches':actual_branches,
                       'passed':actual_lines>=lines and actual_branches>=branches})
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report',type=Path);parser.add_argument('--cli-only',action='store_true')
    args=parser.parse_args()
    try: result=evaluate(json.loads(args.report.read_text(encoding='utf-8')),not args.cli_only)
    except (OSError,ValueError,KeyError) as exc:parser.exit(1,str(exc)+'\n')
    print(json.dumps(result,indent=2))
    return 0 if all(row['passed'] for row in result) else 1


if __name__=='__main__':raise SystemExit(main())
