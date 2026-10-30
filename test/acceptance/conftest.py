"""Every collected Gherkin scenario must have a concrete business driver."""
from pathlib import Path
import json
import re

import pytest
from pytest_bdd import given, when, then, parsers, scenarios

from .world import World

CONTRACTS=json.loads((Path(__file__).parent/'contracts.json').read_text(encoding='utf-8'))
BY_TITLE={case['title']:case for case in CONTRACTS.values()}


@pytest.fixture
def world(tmp_path, monkeypatch, request, qt_application_session):
    if request.node.get_closest_marker('windows') and __import__('os').name != 'nt':
        pytest.skip('BLOCKED: requires a real Windows host, not a frozen flag simulation')
    if request.node.get_closest_marker('packaged') or request.node.get_closest_marker('live'):
        from .external_cases import manifest
        manifest()
    instance=World(tmp_path, monkeypatch, qt_application_session,
                   real_process=bool(request.node.get_closest_marker('e2e')))
    request.node._acceptance_world=instance
    yield instance
    instance.close()


@given('独立的临时工作区和真实配置')
def isolated_workspace(world):
    assert world.source.is_file()


@when(parsers.re(r'执行业务操作 "(?P<title>[^"\n]+)"，变体为 "(?P<variant>.*)"'))
def perform_business_action(world, title, variant):
    contract=BY_TITLE[title]
    world.contract_id=next(key for key,value in CONTRACTS.items() if value is contract)
    world.contract=contract
    world.execute(contract['action'], variant)


@then(parsers.parse('应满足：{expected}'))
def validate_business_result(world, expected):
    assert expected==world.contract['expected']
    assert world.checks, 'An acceptance driver must produce observable business assertions'
    for label, actual, wanted in world.checks:
        value=actual() if callable(actual) and not isinstance(actual,type) else actual
        assert value==wanted, f'{label}: actual={value!r}, expected={wanted!r}'
    world.verified_assertions=len(world.checks)


def pytest_bdd_apply_tag(tag,function):
    if re.fullmatch(r'(WF|EDIT|RUN|CACHE|AI|SCH|PW|INT|PERSIST|CI|DIST)_\d{3}',tag):
        function.__contract_id__=tag
        return True


def pytest_configure(config):
    config._acceptance_results=[]


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item,call):
    outcome=yield
    report=outcome.get_result()
    contract_id=getattr(getattr(item,'obj',None),'__contract_id__',None)
    if not contract_id:return
    if report.when=='call' or (report.when=='setup' and report.skipped):
        world=getattr(item,'_acceptance_world',None)
        example=getattr(item,'callspec',None)
        variant=example.params.get('_pytest_bdd_example',{}).get('变体','default') if example else 'default'
        assertions=getattr(world,'verified_assertions',0)
        row={'id':contract_id,'variant':variant,'status':'passed' if report.passed else 'blocked' if report.skipped else 'failed',
             'binding':'bound','assertions':assertions,'kind':'business','nodeid':item.nodeid}
        if report.skipped:row['reason']=str(report.longrepr)
        if world and hasattr(world,'external_evidence'):row['external_evidence']=world.external_evidence
        item.config._acceptance_results.append(row)


def pytest_sessionfinish(session,exitstatus):
    output=session.config.getoption('--acceptance-report')
    if not output:return
    required=[]
    for item in session.items:
        contract_id=getattr(getattr(item,'obj',None),'__contract_id__',None)
        if not contract_id:continue
        example=getattr(item,'callspec',None)
        variant=example.params.get('_pytest_bdd_example',{}).get('变体','default') if example else 'default'
        required.append({'id':contract_id,'variant':variant})
    import os,subprocess
    source_ref=subprocess.check_output(['git','rev-parse','HEAD'],cwd=Path(__file__).parents[2],text=True).strip()
    data={'scope':'selected-cohort','source_ref':source_ref,'full_contract_cases':177,
          'required':required,'results':session.config._acceptance_results,
          'platforms':['windows' if os.name=='nt' else 'linux'],'required_platforms':[],
          'claims_live':any(item.get_closest_marker('live') for item in session.items),
          'live_evidence':[row['external_evidence'] for row in session.config._acceptance_results if 'external_evidence' in row]}
    path=Path(output);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
