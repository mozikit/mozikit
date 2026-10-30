"""Fail on missing business drivers or drift between features and the catalog."""
import json
from pathlib import Path

from gherkin.parser import Parser

from . import external_cases, execution_cases, integration_cases, workflow_cases

ROOT=Path(__file__).parent


def test_every_contract_has_exactly_one_business_binding():
    contracts=json.loads((ROOT/'contracts.json').read_text(encoding='utf-8'))
    drivers=[module.DRIVERS for module in (external_cases,execution_cases,integration_cases,workflow_cases)]
    assert len(contracts)==89
    assert sum(len(case['variants']) for case in contracts.values())==177
    for identifier,case in contracts.items():
        assert sum(case['action'] in mapping for mapping in drivers)==1,identifier


def test_features_and_catalog_have_identical_ids_titles_expectations_and_variants():
    contracts=json.loads((ROOT/'contracts.json').read_text(encoding='utf-8'))
    found={}
    for path in (ROOT/'features').glob('*.feature'):
        document=Parser().parse(path.read_text(encoding='utf-8'))
        for child in document['feature']['children']:
            scenario=child.get('scenario')
            if not scenario:continue
            identifier=next(tag['name'][1:] for tag in scenario['tags'] if tag['name'][1:] in contracts)
            assert identifier not in found
            case=contracts[identifier]
            assert scenario['name']==case['title']
            assert scenario['steps'][-1]['text']=='应满足：'+case['expected']
            variants=[row['cells'][0]['value'] for example in scenario['examples'] for row in example['tableBody']]
            assert variants==case['variants'] if variants else case['variants']==['default']
            found[identifier]=path.name
    assert found.keys()==contracts.keys()
