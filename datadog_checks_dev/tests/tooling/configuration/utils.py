# (C) Datadog, Inc. 2019
# All rights reserved
# Licensed under a 3-clause BSD style license (see LICENSE)
from textwrap import dedent

from datadog_checks.dev.tooling.configuration import ConfigSpec
from datadog_checks.dev.tooling.configuration.consumers import ExampleConsumer


def get_spec(text, **kwargs):
    kwargs.setdefault('source', 'test')
    return ConfigSpec(normalize_yaml(text), **kwargs)


def get_example_consumer(text, **kwargs):
    spec = get_spec(text, **kwargs)
    spec.load()
    return ExampleConsumer(spec.data)


def normalize_yaml(text):
    return dedent(text).lstrip()
