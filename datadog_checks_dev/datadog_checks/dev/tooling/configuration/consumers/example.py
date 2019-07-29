# (C) Datadog, Inc. 2019
# All rights reserved
# Licensed under a 3-clause BSD style license (see LICENSE)
from collections import OrderedDict

import yaml
from six import StringIO

from ..utils import default_option_example

DESCRIPTION_LINE_LENGTH_LIMIT = 120


class OptionWriter(object):
    def __init__(self):
        self.writer = StringIO()
        self.errors = []

    def write(self, *strings):
        for s in strings:
            self.writer.write(s)

    def new_error(self, s):
        self.errors.append(s)

    @property
    def contents(self):
        return self.writer.getvalue()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.writer.close()


def construct_yaml(obj):
    return yaml.safe_dump(obj, default_flow_style=False, sort_keys=False)


def value_type_string(value):
    value_type = value['type']
    if value_type == 'object':
        return 'mapping'
    elif value_type == 'array':
        item_type = value['items']['type']
        if item_type == 'object':
            return 'list of mappings'
        elif item_type == 'array':
            return 'list of lists'
        else:
            return 'list of {}s'.format(item_type)
    else:
        return value_type


def write_option(option, writer, indent='', start_list=False):
    option_name = option['name']
    if 'value' in option:
        value = option['value']
        required = option['required']
        writer.write(
            indent, '## ', option_name, ' - ', value_type_string(value), ' - ', 'required' if required else 'optional'
        )

        example = value.get('example')
        if not required:
            example_type = type(example)
            if example_type is bool:
                writer.write(' - default: ', 'true' if example else 'false')
            elif example_type in (int, float):
                writer.write(' - default: ', str(example))
            elif example_type is str:
                if example != default_option_example(option_name):
                    writer.write(' - default: ', example)

        writer.write('\n')

        for line in option['description'].splitlines():
            if line:
                line = '{}## {}'.format(indent, line)
                if len(line) > DESCRIPTION_LINE_LENGTH_LIMIT:
                    extra_characters = len(line) - DESCRIPTION_LINE_LENGTH_LIMIT
                    writer.new_error(
                        'Description line length of option `{}` was over the limit by {} character{}'.format(
                            option_name, extra_characters, 's' if extra_characters > 1 else ''
                        )
                    )
                writer.write(line)
            else:
                writer.write(indent, '##')

            writer.write('\n')

        writer.write(indent, '#\n')

        if start_list:
            option_yaml = construct_yaml([{option_name: example}])
            indent = indent[:-2]
        else:
            option_yaml = construct_yaml({option_name: example})

        for line in option_yaml.splitlines():
            writer.write(indent)
            if not required:
                writer.write('# ')

            writer.write(line, '\n')
    else:
        for line in option['description'].splitlines():
            if line:
                line = '{}## {}'.format(indent, line)
                if len(line) > DESCRIPTION_LINE_LENGTH_LIMIT:
                    extra_characters = len(line) - DESCRIPTION_LINE_LENGTH_LIMIT
                    writer.new_error(
                        'Description line length of section `{}` was over the limit by {} character{}'.format(
                            option_name, extra_characters, 's' if extra_characters > 1 else ''
                        )
                    )
                writer.write(line)
            else:
                writer.write(indent, '##')

            writer.write('\n')

        writer.write(indent, '#\n')

        if 'options' in option:
            multiple = option['multiple']
            options = option['options']
            next_indent = indent + '    '
            writer.write(indent, option_name, ':', '\n')
            if options:
                for i, opt in enumerate(options):
                    writer.write('\n')
                    if i == 0 and multiple:
                        if opt['required']:
                            write_option(opt, writer, next_indent, start_list=True)
                        else:
                            writer.write(next_indent[:-2], '-\n')
                            write_option(opt, writer, next_indent)
                    else:
                        write_option(opt, writer, next_indent)
            elif multiple:
                writer.write('\n', next_indent[:-2], '- {}\n')

        # For sections that prefer to document everything in the description, like `logs`
        else:
            # raise Exception('ooooooooo')
            example = option.get('example', [] if option.get('multiple', False) else {})
            option_yaml = construct_yaml({option_name: example})
            for line in option_yaml.splitlines():
                writer.write(indent, '# ', line, '\n')


class ExampleConsumer(object):
    def __init__(self, spec):
        self.spec = spec

    def render(self):
        files = OrderedDict()

        for file in self.spec['files']:
            with OptionWriter() as writer:
                options = file['options']
                num_options = len(options)
                for i, option in enumerate(options, 1):
                    write_option(option, writer)

                    # No new line necessary after the last option
                    if i != num_options:
                        writer.write('\n')

                files[file['example_name']] = (writer.contents, writer.errors)

        return files
