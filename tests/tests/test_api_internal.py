#!/usr/bin/python
# Copyright 2016 Mender Software AS
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        https://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.
from common import api_client_int, api_client_mgmt, \
                   mongo, clean_db, \
                   mongo_devauth, clean_db_devauth, \
                   do_create_devices
import bravado
import pytest
import json
import tenantadm

class TestInternalApiTenantCreate:
    def test_create_ok(self, api_client_int, clean_db):
        _, r = api_client_int.create_tenant('foobar')
        assert r.status_code == 201

        assert 'deviceadm-foobar' in clean_db.database_names()
        assert 'migration_info' in clean_db['deviceadm-foobar'].collection_names()

    def test_create_twice(self, api_client_int, clean_db):
        _, r = api_client_int.create_tenant('foobar')
        assert r.status_code == 201

        # creating once more should not fail
        _, r = api_client_int.create_tenant('foobar')
        assert r.status_code == 201

    def test_create_empty(self, api_client_int):
        try:
            _, r = api_client_int.create_tenant('')
        except bravado.exception.HTTPError as e:
            assert e.response.status_code == 400


@pytest.fixture(scope="function")
def init_authsets(clean_db, clean_db_devauth, api_client_mgmt):
    """
        Create a couple auth sets in various states, including 'preauthorized'.
        The fixture is specific to testing internal PUT /devices/{id}/status.
        Some common funcs are reused, but existing common fixtures don't fit the bill.
    """
    return do_init_authsets(api_client_mgmt)

TENANTS = ['tenant1', 'tenant2']
@pytest.fixture(scope="function")
def init_authsets_mt(clean_db, clean_db_devauth, api_client_mgmt):
    """
        Create a couple auth sets in various states, including 'preauthorized', in a MT context (2 tenants).
        The fixture is specific to testing internal PUT /devices/{id}/status.
    """
    tenant_authsets = {}
    with tenantadm.fake_tenantadm():
        for t in TENANTS:
            tenant_authsets[t] = do_init_authsets(api_client_mgmt, t)

    return tenant_authsets

def do_init_authsets(api_client_mgmt, tenant_id=None):
    auth=None
    if tenant_id is not None:
        auth = api_client_mgmt.make_user_auth("user", tenant_id)

    # create 5 auth sets in 'pending' state
    count = 5
    do_create_devices(tenant_id, count)
    devs = api_client_mgmt.get_all_devices(auth=auth)
    assert len(devs) == count

    # using deviceadm's api, change up some statuses
    api_client_mgmt.change_status(devs[0].id, 'accepted', auth)
    api_client_mgmt.change_status(devs[3].id, 'rejected', auth)

    # add a preauthorized device
    identity = json.dumps({"mac": "preauth-mac"})
    api_client_mgmt.preauthorize(identity, 'preauth-key', auth)

    devs = api_client_mgmt.get_all_devices(auth=auth)
    assert len(devs) == count + 1
    return devs

class TestInternalApiPutDeviceStatusBase:
    def _do_test_ok(self, api_client_int, api_client_mgmt, init_authsets, auth=None):
        """
            Tests the happy path.
        """

        # find the preauthorized device and accept
        preauth = [d for d in init_authsets if d.status == 'preauthorized']
        assert len(preauth) == 1
        preauth = preauth[0]

        api_client_int.change_status(preauth.id, 'accepted', auth)

        # assert that the preauth device is now accepted
        devs = api_client_mgmt.get_all_devices(auth=auth)
        accepted = [d for d in devs if d.id == preauth.id and d.status == 'accepted']
        assert len(accepted) == 1

    def _do_test_invalid_init_status(self, status, api_client_int, api_client_mgmt, init_authsets, auth=None):
        """
            Tests an invalid transition, i.e. 'not preauthorized' -> 'accepted'.
        """
        existing = [d for d in init_authsets if d.status == status]
        existing = existing[0]

        try:
            api_client_int.change_status(existing.id, 'accepted', auth)
        except bravado.exception.HTTPError as e:
            assert e.response.status_code == 409

    def _do_test_invalid_dest_status(self, dest_status, api_client_int, api_client_mgmt, init_authsets, auth=None):
        """
            Tests an invalid destination status, i.e. 'not accepted'.
        """
        preauth = [d for d in init_authsets if d.status == 'preauthorized']
        preauth = preauth[0]

        try:
            api_client_int.change_status(preauth.id, dest_status, auth)
        except bravado.exception.HTTPError as e:
            assert e.response.status_code == 400


class TestInternalApiPutDeviceStatus(TestInternalApiPutDeviceStatusBase):
    def test_ok(self, api_client_int, api_client_mgmt, init_authsets):
        self._do_test_ok(api_client_int, api_client_mgmt, init_authsets)

    def test_invalid_init_status_pending(self, api_client_int, api_client_mgmt, init_authsets):
        self._do_test_invalid_init_status('pending', api_client_int, api_client_mgmt, init_authsets)

    def test_invalid_init_status_accepted(self, api_client_int, api_client_mgmt, init_authsets):
        self._do_test_invalid_init_status('accepted', api_client_int, api_client_mgmt, init_authsets)

    def test_invalid_init_status_rejected(self, api_client_int, api_client_mgmt, init_authsets):
        self._do_test_invalid_init_status('rejected', api_client_int, api_client_mgmt, init_authsets)

    def test_invalid_dest_status_rejected(self, api_client_int, api_client_mgmt, init_authsets):
        self._do_test_invalid_dest_status('rejected', api_client_int, api_client_mgmt, init_authsets)

    def test_invalid_dest_status_accepted(self, api_client_int, api_client_mgmt, init_authsets):
        self._do_test_invalid_dest_status('accepted', api_client_int, api_client_mgmt, init_authsets)

    def test_invalid_dest_status_pending(self, api_client_int, api_client_mgmt, init_authsets):
        self._do_test_invalid_dest_status('pending', api_client_int, api_client_mgmt, init_authsets)

    def test_invalid_dest_status_bogus(self, api_client_int, api_client_mgmt, init_authsets):
        self._do_test_invalid_dest_status('bogus', api_client_int, api_client_mgmt, init_authsets)


class TestInternalApiPutDeviceStatusMultitenant(TestInternalApiPutDeviceStatusBase):
    @pytest.mark.parametrize("tenant_id", ["tenant1", "tenant2"])
    def test_ok(self, api_client_int, api_client_mgmt, init_authsets_mt, tenant_id):
        auth = api_client_mgmt.make_user_auth("user", tenant_id)
        self._do_test_ok(api_client_int, api_client_mgmt, init_authsets_mt[tenant_id], auth)

    @pytest.mark.parametrize("tenant_id", ["tenant1", "tenant2"])
    def test_invalid_init_status_pending(self, api_client_int, api_client_mgmt, init_authsets_mt, tenant_id):
        auth = api_client_mgmt.make_user_auth("user", tenant_id)
        self._do_test_invalid_init_status('pending', api_client_int, api_client_mgmt, init_authsets_mt[tenant_id], auth)

    @pytest.mark.parametrize("tenant_id", ["tenant1", "tenant2"])
    def test_invalid_init_status_accepted(self, api_client_int, api_client_mgmt, init_authsets_mt, tenant_id):
        auth = api_client_mgmt.make_user_auth("user", tenant_id)
        self._do_test_invalid_init_status('accepted', api_client_int, api_client_mgmt, init_authsets_mt[tenant_id], auth)

    @pytest.mark.parametrize("tenant_id", ["tenant1", "tenant2"])
    def test_invalid_init_status_rejected(self, api_client_int, api_client_mgmt, init_authsets_mt, tenant_id):
        auth = api_client_mgmt.make_user_auth("user", tenant_id)
        self._do_test_invalid_init_status('rejected', api_client_int, api_client_mgmt, init_authsets_mt[tenant_id], auth)

    @pytest.mark.parametrize("tenant_id", ["tenant1", "tenant2"])
    def test_invalid_dest_status_rejected(self, api_client_int, api_client_mgmt, init_authsets_mt, tenant_id):
        auth = api_client_mgmt.make_user_auth("user", tenant_id)
        self._do_test_invalid_dest_status('rejected', api_client_int, api_client_mgmt, init_authsets_mt[tenant_id], auth)

    @pytest.mark.parametrize("tenant_id", ["tenant1", "tenant2"])
    def test_invalid_dest_status_accepted(self, api_client_int, api_client_mgmt, init_authsets_mt, tenant_id):
        auth = api_client_mgmt.make_user_auth("user", tenant_id)
        self._do_test_invalid_dest_status('accepted', api_client_int, api_client_mgmt, init_authsets_mt[tenant_id], auth)

    @pytest.mark.parametrize("tenant_id", ["tenant1", "tenant2"])
    def test_invalid_dest_status_pending(self, api_client_int, api_client_mgmt, init_authsets_mt, tenant_id):
        auth = api_client_mgmt.make_user_auth("user", tenant_id)
        self._do_test_invalid_dest_status('pending', api_client_int, api_client_mgmt, init_authsets_mt[tenant_id], auth)

    @pytest.mark.parametrize("tenant_id", ["tenant1", "tenant2"])
    def test_invalid_dest_status_bogus(self, api_client_int, api_client_mgmt, init_authsets_mt, tenant_id):
        auth = api_client_mgmt.make_user_auth("user", tenant_id)
        self._do_test_invalid_dest_status('bogus', api_client_int, api_client_mgmt, init_authsets_mt[tenant_id], auth)
