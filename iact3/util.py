import logging
import os
import re
import sys
import uuid
import yaml

LOG = logging.getLogger(__name__)


FIRST_CAP_RE = re.compile("(.)([A-Z][a-z]+)")
ALL_CAP_RE = re.compile("([a-z0-9])([A-Z])")


def exit_with_code(code, msg=""):
    if msg:
        LOG.error(msg)
    sys.exit(code)


def make_dir(path, ignore_exists=True):
    path = os.path.abspath(path)
    if ignore_exists and os.path.isdir(path):
        return
    os.makedirs(path)


def pascal_to_snake(pascal):
    sub = ALL_CAP_RE.sub(r"\1_\2", pascal)
    return ALL_CAP_RE.sub(r"\1_\2", sub).lower()


def generate_client_token_ex(prefix: str, suffix: str):
    if prefix:
        t = [prefix]
    else:
        t = []
    t.append(str(uuid.uuid1())[:-13])
    t.append(suffix)
    r = '_'.join(t)
    if len(r) > 64:
        r = r[:64]
    return r


ROS_FUNCTION_NAMES = {
    "MergeMap", "Sub", "Base64Decode", "Indent", "Base64", "If", "EachMemberIn", "FormatTime", "Length",
    "Not", "Replace", "Min", "Equals", "Test", "Split", "Join", "ListMerge", "Or", "ResourceFacade",
    "SelectMapList", "MergeMapToList", "Select", "Calculate", "FindInMap", "MarketplaceImage", "GetAZs",
    "Any", "Contains", "Add", "Str", "GetAtt", "Base64Encode", "GetStackOutput", "TransformNamespace", "Jq",
    "Max", "MemberListToMap", "Index", "Cidr", "GetJsonValue", "Ref", "And", "Avg", "MatchPattern", "Sub"
}


class CustomSafeLoader(yaml.SafeLoader):
    pass


def make_constructor(fun_name):
    if fun_name == 'Ref':
        tag_name = fun_name
    else:
        tag_name = 'Fn::{}'.format(fun_name)

    if fun_name == 'GetAtt':
        def get_attribute_constructor(loader, node):
            if isinstance(node, yaml.ScalarNode):
                value = loader.construct_scalar(node)
                try:
                    split_value = value.split('.')
                    if len(split_value) == 2:
                        resource, attribute = split_value
                    elif len(split_value) >= 3:
                        if split_value[-2] == 'Outputs':
                            resource = '.'.join(split_value[:-2])
                            attribute = '.'.join(split_value[-2:])
                        else:
                            resource = '.'.join(split_value[:-1])
                            attribute = split_value[-1]
                    else:
                        raise ValueError
                    return {tag_name: [resource, attribute]}
                except ValueError:
                    raise ValueError('Resolve !GetAtt error. Value: {}'.format(value))
            elif isinstance(node, yaml.SequenceNode):
                values = loader.construct_sequence(node)
                return {tag_name: values}
            else:
                value = loader.construct_object(node)
                return {tag_name: value}
        return get_attribute_constructor

    def constructor(loader, node):
        if isinstance(node, yaml.nodes.ScalarNode):
            value = loader.construct_scalar(node)
        elif isinstance(node, yaml.nodes.SequenceNode):
            value = loader.construct_sequence(node)
        elif isinstance(node, yaml.nodes.MappingNode):
            value = loader.construct_mapping(node)
        else:
            value = loader.construct_object(node)
        return {tag_name: value}

    return constructor


for f in ROS_FUNCTION_NAMES:
    CustomSafeLoader.add_constructor(f'!{f}', make_constructor(f))
