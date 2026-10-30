"""Missing evidence and a newer failed CI attempt must never authorize a release."""
from copy import deepcopy

import pytest

from tools.check_acceptance import complete
from tools.check_coverage import CLI,CORE,evaluate
from tools.check_release_checks import ready


def test_release_requires_both_platforms_latest_attempt_for_exact_sha():
    sha='a'*40
    runs=[{'id':1,'run_attempt':1,'name':name,'head_sha':sha,'status':'completed','conclusion':'success'}
          for name in ['Test (Linux)','Test (Windows)']]
    assert ready(runs,sha)
    assert not ready(runs,'b'*40)
    assert not ready(runs[:1],sha)
    retry={**runs[1],'run_attempt':2,'conclusion':'failure'}
    assert not ready([*runs,retry],sha)
    assert not ready([*runs,{**retry,'id':2,'status':'in_progress','conclusion':None}],sha)


@pytest.mark.parametrize('fault',['module','branches','empty'])
def test_coverage_cannot_pass_without_measured_source_or_branches(fault):
    data={'files':{name:{'summary':{'covered_lines':100,'num_statements':100,
        'covered_branches':100,'num_branches':100}} for name in (*CLI,*CORE)}}
    assert all(row['passed'] for row in evaluate(data))
    if fault=='module':del data['files'][CORE[0]]
    elif fault=='branches':del data['files'][CLI[0]]['summary']['num_branches']
    else:
        for row in data['files'].values():row['summary'].update(num_statements=0,num_branches=0)
    with pytest.raises(ValueError):evaluate(data)


def test_business_evidence_cannot_hide_skips_or_missing_platforms():
    data={'required':[{'id':'one'},{'id':'two'}],'results':[
        {'id':identifier,'status':'passed','binding':'bound','assertions':3,'kind':'business'}
        for identifier in ['one','two']]}
    assert complete(data)
    data['results'][1]['status']='blocked'
    assert not complete(data)
    data['results'].pop()
    assert not complete(data)
    data['required'].pop()
    assert complete(data)
    data.update(required_platforms=['windows'],platforms=['linux'])
    assert not complete(data)
