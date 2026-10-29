import logging

import pytest
import yaml

from iact3 import util
from iact3.exceptions import Iact3Exception, InvalidActionError


def test_exit_and_program_name(monkeypatch, caplog):
    with caplog.at_level(logging.ERROR), pytest.raises(SystemExit) as error:
        util.exit_with_code(7, 'failed')
    assert error.value.code == 7
    assert 'failed' in caplog.text
    with pytest.raises(SystemExit) as error:
        util.exit_with_code(0)
    assert error.value.code == 0
    monkeypatch.setenv('ALIBABA_CLOUD_IACT3_COMPAT_MODE', ' compat ')
    assert util.get_program_name() == 'compat iact3'
    monkeypatch.delenv('ALIBABA_CLOUD_IACT3_COMPAT_MODE')
    assert util.get_program_name('custom') == 'custom'


def test_make_dir_and_tokens(tmp_path):
    path = tmp_path / 'a' / 'b'
    util.make_dir(str(path))
    util.make_dir(str(path))
    with pytest.raises(OSError):
        util.make_dir(str(path), ignore_exists=False)
    assert util.pascal_to_snake('StackName') == 'stack_name'
    assert util.generate_client_token_ex('prefix', 'suffix').startswith('prefix_')
    assert len(util.generate_client_token_ex('x' * 80, 'suffix')) == 64
    assert util.generate_client_token_ex('', 'suffix').endswith('_suffix')


@pytest.mark.parametrize('source,expected', [
    ('!Ref Name', {'Ref': 'Name'}),
    ('!Sub ["${Name}", {Name: value}]', {'Fn::Sub': ['${Name}', {'Name': 'value'}]}),
    ('!Join {a: b}', {'Fn::Join': {'a': 'b'}}),
    ('!GetAtt Resource.Output', {'Fn::GetAtt': ['Resource', 'Output']}),
    ('!GetAtt Resource.Nested.Output', {'Fn::GetAtt': ['Resource.Nested', 'Output']}),
    ('!GetAtt Resource.Nested.Outputs.Address', {'Fn::GetAtt': ['Resource.Nested', 'Outputs.Address']}),
    ('!GetAtt [Resource, Output]', {'Fn::GetAtt': ['Resource', 'Output']}),
])
def test_ros_yaml_tags(source, expected):
    assert yaml.load(source, Loader=util.CustomSafeLoader) == expected


def test_invalid_getatt_is_rejected():
    with pytest.raises(ValueError, match='Resolve !GetAtt error'):
        yaml.load('!GetAtt Resource', Loader=util.CustomSafeLoader)


def test_rank_instance_types_prefers_entry_then_small_secondary():
    values = ['ecs.g7.4xlarge', 'ecs.c7.large', 'ecs.t5.large', 'ecs.t6.micro', 'ecs.other.small']
    assert util.rank_cheapest_instance_types(values) == [
        'ecs.t6.micro', 'ecs.t5.large', 'ecs.c7.large', 'ecs.other.small', 'ecs.g7.4xlarge']
    assert util.pick_cheapest_instance_type(values) == 'ecs.t6.micro'
    assert util.pick_cheapest_instance_type([]) is None
    assert util.rank_cheapest_instance_types([]) == []


def test_sort_database_classes_by_spec_ratio_and_zone():
    values = ['mysql.x8.small.2c', 'mysql.n1.micro.2c', 'mysql.n1.micro.1c', 'mysql.n2.micro.1c']
    assert util.sort_cheapest_db_instance_classes(values) == [
        'mysql.n1.micro.1c', 'mysql.n1.micro.2c', 'mysql.n2.micro.1c', 'mysql.x8.small.2c']
    assert util.sort_cheapest_db_instance_classes([]) == []
    assert util.sort_cheapest_db_instance_classes(None) is None


def test_price_ranking_handles_unknown_formats_and_hyphenated_families():
    values = ['unknown', 'ecs.t6-large', 'ecs.c7-small', 'ecs.mystery.micro']
    ranked = util.rank_cheapest_instance_types(values)
    assert ranked[0] == 'ecs.t6-large'
    assert ranked[1] == 'ecs.c7-small'
    assert set(ranked) == set(values)
    assert ranked.index('ecs.mystery.micro') < ranked.index('unknown')
    assert util.sort_cheapest_db_instance_classes(['unknown', 'mysql.n1.micro.1c']) == [
        'mysql.n1.micro.1c', 'unknown']


def test_exception_metadata():
    error = Iact3Exception('failed', code='Custom')
    assert error.message == 'failed' and error.code == 'Custom'
    error = InvalidActionError('action')
    assert error.expression == 'action' and error.code == 'Iact3Exception'
