# (C) Datadog, Inc. 2018-2019
# All rights reserved
# Licensed under a 3-clause BSD style license (see LICENSE)
from collections import namedtuple
from time import time as timestamp

import requests

from datadog_checks.base import ConfigurationError, OpenMetricsBaseCheck, is_affirmative

from .errors import ApiUnreachable
from .metrics import METRIC_MAP

try:
    from json import JSONDecodeError
except ImportError:
    from simplejson import JSONDecodeError

Api = namedtuple('Api', ('check_health', 'check_leader'))


class Vault(OpenMetricsBaseCheck):
    DEFAULT_METRIC_LIMIT = 0
    CHECK_NAME = 'vault'
    DEFAULT_API_VERSION = '1'
    EVENT_LEADER_CHANGE = 'vault.leader_change'
    SERVICE_CHECK_CONNECT = 'vault.can_connect'
    SERVICE_CHECK_UNSEALED = 'vault.unsealed'
    SERVICE_CHECK_INITIALIZED = 'vault.initialized'
    API_METHODS = ('check_health', 'check_leader')

    HTTP_CONFIG_REMAPPER = {
        'ssl_verify': {'name': 'tls_verify'},
        'ssl_cert': {'name': 'tls_cert'},
        'ssl_private_key': {'name': 'tls_private_key'},
        'ssl_ca_cert': {'name': 'tls_ca_cert'},
        'ssl_ignore_warning': {'name': 'tls_ignore_warning'},
    }

    # Expected HTTP Error codes for /sys/health endpoint
    # https://www.vaultproject.io/api/system/health.html
    SYS_HEALTH_DEFAULT_CODES = {
        200,  # initialized, unsealed, and active
        429,  # unsealed and standby
        472,  # data recovery mode replication secondary and active
        473,  # performance standby
        501,  # not initialized
        503,  # sealed
    }

    SYS_LEADER_DEFAULT_CODES = {503}  # sealed

    def __init__(self, name, init_config, instances):
        super(Vault, self).__init__(
            name,
            init_config,
            instances,
            default_instances={self.CHECK_NAME: {'namespace': self.CHECK_NAME, 'metrics': [METRIC_MAP]}},
            default_namespace=self.CHECK_NAME,
        )

        self._api_url = self.instance.get('api_url', '')
        self._client_token = self.instance.get('client_token')
        self._client_token_path = self.instance.get('client_token_path')
        self._tags = self.instance.get('tags', [])

        # Keep track of the previous cluster leader to detect changes
        self._previous_leader = None
        self._detect_leader = is_affirmative(self.instance.get('detect_leader', False))

        # Determine the appropriate methods later
        self._api = None

        # Only collect OpenMetrics if we are given tokens
        self._scraper_config = None

        self.check_initializations.append(self.parse_config)

    def check(self, _):
        # raise Exception(self._client_token)
        tags = list(self._tags)

        # We access the version of the Vault API corresponding to the instance's `api_url`
        self._api.check_leader(tags)
        self._api.check_health(tags)

        if self._client_token:
            try:
                self.process(self._scraper_config)
            except Exception as e:
                if self._client_token_path and str(e).startswith('403 Client Error: Forbidden for url'):
                    self.log.error('Permission denied, refreshing the client token...')
                    self.renew_client_token()
                    return

                raise

        self.service_check(self.SERVICE_CHECK_CONNECT, self.OK, tags=tags)

    def check_leader_v1(self, tags):
        url = self._api_url + '/sys/leader'
        leader_data = self.access_api(url, tags, ignore_status_codes=self.SYS_LEADER_DEFAULT_CODES)
        errors = leader_data.get('errors')
        if errors:
            error_msg = ';'.join(errors)
            self.log.error('Unable to fetch leader data from vault. Reason: %s', error_msg)
            return

        is_leader = is_affirmative(leader_data.get('is_self'))
        tags.append('is_leader:{}'.format('true' if is_leader else 'false'))

        self.gauge('vault.is_leader', int(is_leader), tags=tags)

        current_leader = leader_data.get('leader_address')
        if self._detect_leader and current_leader:
            if self._previous_leader is not None and current_leader != self._previous_leader:
                self.event(
                    {
                        'timestamp': timestamp(),
                        'event_type': self.EVENT_LEADER_CHANGE,
                        'msg_title': 'Leader change',
                        'msg_text': 'Leader changed from `{}` to `{}`.'.format(self._previous_leader, current_leader),
                        'alert_type': 'info',
                        'source_type_name': self.CHECK_NAME,
                        'host': self.hostname,
                        'tags': tags,
                    }
                )
            self._previous_leader = current_leader

    def check_health_v1(self, tags):
        url = self._api_url + '/sys/health'
        health_data = self.access_api(url, tags, ignore_status_codes=self.SYS_HEALTH_DEFAULT_CODES)

        cluster_name = health_data.get('cluster_name')
        if cluster_name:
            tags.append('cluster_name:{}'.format(cluster_name))

        vault_version = health_data.get('version')
        if vault_version:
            tags.append('vault_version:{}'.format(vault_version))

        unsealed = not is_affirmative(health_data.get('sealed'))
        if unsealed:
            self.service_check(self.SERVICE_CHECK_UNSEALED, self.OK, tags=tags)
        else:
            self.service_check(self.SERVICE_CHECK_UNSEALED, self.CRITICAL, tags=tags)

        initialized = is_affirmative(health_data.get('initialized'))
        if initialized:
            self.service_check(self.SERVICE_CHECK_INITIALIZED, self.OK, tags=tags)
        else:
            self.service_check(self.SERVICE_CHECK_INITIALIZED, self.CRITICAL, tags=tags)

    def access_api(self, url, tags, ignore_status_codes=None):
        if ignore_status_codes is None:
            ignore_status_codes = []

        try:
            response = self.http.get(url)
            status_code = response.status_code
            if status_code >= 400 and status_code not in ignore_status_codes:
                msg = 'The Vault endpoint `{}` returned {}'.format(url, status_code)
                self.service_check(self.SERVICE_CHECK_CONNECT, self.CRITICAL, message=msg, tags=tags)
                raise ApiUnreachable(msg)
            json_data = response.json()
        except JSONDecodeError:
            msg = 'The Vault endpoint `{}` returned invalid json data.'.format(url)
            self.service_check(self.SERVICE_CHECK_CONNECT, self.CRITICAL, message=msg, tags=tags)
            raise ApiUnreachable(msg)
        except requests.exceptions.Timeout:
            msg = 'Vault endpoint `{}` timed out after {} seconds'.format(url, self.http.options['timeout'][0])
            self.service_check(self.SERVICE_CHECK_CONNECT, self.CRITICAL, message=msg, tags=tags)
            raise ApiUnreachable(msg)
        except (requests.exceptions.RequestException, requests.exceptions.ConnectionError):
            msg = 'Error accessing Vault endpoint `{}`'.format(url)
            self.service_check(self.SERVICE_CHECK_CONNECT, self.CRITICAL, message=msg, tags=tags)
            raise ApiUnreachable(msg)

        return json_data

    def parse_config(self):
        if not self._api_url:
            raise ConfigurationError('Vault setting `api_url` is required')

        api_version = self._api_url[-1]
        if api_version not in ('1',):
            self.log.warning(
                'Unknown Vault API version `%s`, using version `%s`', api_version, self.DEFAULT_API_VERSION
            )
            api_version = self.DEFAULT_API_VERSION
            self._api_url = self._api_url[:-1] + api_version

        methods = {method: getattr(self, '{}_v{}'.format(method, api_version)) for method in self.API_METHODS}
        self._api = Api(**methods)

        if self._client_token_path:
            self.renew_client_token()

        if self._client_token:
            instance = self.instance.copy()
            instance['prometheus_url'] = '{}/sys/metrics?format=prometheus'.format(self._api_url)
            self._scraper_config = self.create_scraper_configuration(instance)
            self.set_client_token(self._client_token)

    def set_client_token(self, client_token):
        self._client_token = client_token
        self.http.options['headers']['X-Vault-Token'] = client_token

    def renew_client_token(self):
        with open(self._client_token_path, 'rb') as f:
            self.set_client_token(f.read().decode('utf-8'))

    def poll(self, scraper_config, headers=None):
        if self._client_token:
            headers = {'X-Vault-Token': self._client_token}

        return super(Vault, self).poll(scraper_config, headers=headers)

    def get_scraper_config(self, instance):
        # This validation is called during `__init__` but we don't need it
        pass
