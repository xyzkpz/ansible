#!/usr/bin/python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2016 Red Hat, Inc.
#
# This file is part of Ansible
#
# Ansible is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Ansible is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Ansible.  If not, see <http://www.gnu.org/licenses/>.
#

ANSIBLE_METADATA = {'metadata_version': '1.0',
                    'status': ['preview'],
                    'supported_by': 'community'}


DOCUMENTATION = '''
---
module: ovirt_quotas
short_description: Module to manage datacenter quotas in oVirt
version_added: "2.3"
author: "Ondra Machacek (@machacekondra)"
description:
    - "Module to manage datacenter quotas in oVirt"
options:
    name:
        description:
            - "Name of the the quota to manage."
        required: true
    state:
        description:
            - "Should the quota be present/absent."
        choices: ['present', 'absent']
        default: present
    datacenter:
        description:
            - "Name of the datacenter where quota should be managed."
        required: true
    description:
        description:
            - "Description of the the quota to manage."
    cluster_threshold:
        description:
            - "Cluster threshold(soft limit) defined in percentage (0-100)."
    cluster_grace:
        description:
            - "Cluster grace(hard limit) defined in percentage (1-100)."
    storage_threshold:
        description:
            - "Storage threshold(soft limit) defined in percentage (0-100)."
    storage_grace:
        description:
            - "Storage grace(hard limit) defined in percentage (1-100)."
    clusters:
        description:
            - "List of dictionary of cluster limits, which is valid to specific cluster."
            - "If cluster isn't spefied it's valid to all clusters in system:"
            - "C(cluster) - Name of the cluster."
            - "C(memory) - Memory limit (in GiB)."
            - "C(cpu) - CPU limit."
    storages:
        description:
            - "List of dictionary of storage limits, which is valid to specific storage."
            - "If storage isn't spefied it's valid to all storages in system:"
            - "C(storage) - Name of the storage."
            - "C(size) - Size limit (in GiB)."
extends_documentation_fragment: ovirt
'''

EXAMPLES = '''
# Examples don't contain auth parameter for simplicity,
# look at ovirt_auth module to see how to reuse authentication:

# Add cluster quota to cluster cluster1 with memory limit 20GiB and CPU limit to 10:
ovirt_quotas:
    name: quota1
    datacenter: dcX
    clusters:
        - name: cluster1
          memory: 20
          cpu: 10

# Add cluster quota to all clusters with memory limit 30GiB and CPU limit to 15:
ovirt_quotas:
    name: quota2
    datacenter: dcX
    clusters:
        - memory: 30
          cpu: 15

# Add storage quota to storage data1 with size limit to 100GiB
ovirt_quotas:
    name: quota3
    datacenter: dcX
    storage_grace: 40
    storage_threshold: 60
    storages:
        - name: data1
          size: 100

# Remove quota quota1 (Note the quota must not be assigned to any VM/disk):
ovirt_quotas:
    state: absent
    datacenter: dcX
    name: quota1
'''

RETURN = '''
id:
    description: ID of the quota which is managed
    returned: On success if quota is found.
    type: str
    sample: 7de90f31-222c-436c-a1ca-7e655bd5b60c
quota:
    description: "Dictionary of all the quota attributes. Quota attributes can be found on your oVirt instance
                  at following url: https://ovirt.example.com/ovirt-engine/api/model#types/quota."
    returned: On success if quota is found.
'''

try:
    import ovirtsdk4.types as otypes
except ImportError:
    pass

import traceback

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.ovirt import (
    BaseModule,
    check_sdk,
    create_connection,
    equal,
    get_link_name,
    ovirt_full_argument_spec,
    search_by_name,
)


class QuotasModule(BaseModule):

    def build_entity(self):
        return otypes.Quota(
            description=self._module.params['description'],
            name=self._module.params['name'],
            storage_hard_limit_pct=self._module.params.get('storage_grace'),
            storage_soft_limit_pct=self._module.params.get('storage_threshold'),
            cluster_hard_limit_pct=self._module.params.get('cluster_grace'),
            cluster_soft_limit_pct=self._module.params.get('cluster_threshold'),
        )

    def update_storage_limits(self, entity):
        new_limits = {}
        for storage in self._module.params.get('storages'):
            new_limits[storage.get('name', '')] = {
                'size': storage.get('size'),
            }

        old_limits = {}
        sd_limit_service = self._service.service(entity.id).quota_storage_limits_service()
        for limit in sd_limit_service.list():
            storage = get_link_name(self._connection, limit.storage_domain) if limit.storage_domain else ''
            old_limits[storage] = {
                'size': limit.limit,
            }
            sd_limit_service.service(limit.id).remove()

        return new_limits == old_limits

    def update_cluster_limits(self, entity):
        new_limits = {}
        for cluster in self._module.params.get('clusters'):
            new_limits[cluster.get('name', '')] = {
                'cpu': cluster.get('cpu'),
                'memory': float(cluster.get('memory')),
            }

        old_limits = {}
        cl_limit_service = self._service.service(entity.id).quota_cluster_limits_service()
        for limit in cl_limit_service.list():
            cluster = get_link_name(self._connection, limit.cluster) if limit.cluster else ''
            old_limits[cluster] = {
                'cpu': limit.vcpu_limit,
                'memory': limit.memory_limit,
            }
            cl_limit_service.service(limit.id).remove()

        return new_limits == old_limits

    def update_check(self, entity):
        # -- FIXME --
        # Note that we here always remove all cluster/storage limits, because
        # it's not currently possible to update them and then re-create the limits
        # appropriatelly, this shouldn't have any side-effects, but it's not considered
        # as a correct approach.
        # This feature is tracked here: https://bugzilla.redhat.com/show_bug.cgi?id=1398576
        #

        return (
            self.update_storage_limits(entity) and
            self.update_cluster_limits(entity) and
            equal(self._module.params.get('description'), entity.description) and
            equal(self._module.params.get('storage_grace'), entity.storage_hard_limit_pct) and
            equal(self._module.params.get('storage_threshold'), entity.storage_soft_limit_pct) and
            equal(self._module.params.get('cluster_grace'), entity.cluster_hard_limit_pct) and
            equal(self._module.params.get('cluster_threshold'), entity.cluster_soft_limit_pct)
        )


def main():
    argument_spec = ovirt_full_argument_spec(
        state=dict(
            choices=['present', 'absent'],
            default='present',
        ),
        name=dict(required=True),
        datacenter=dict(required=True),
        description=dict(default=None),
        cluster_threshold=dict(default=None, type='int', aliases=['cluster_soft_limit']),
        cluster_grace=dict(default=None, type='int', aliases=['cluster_hard_limit']),
        storage_threshold=dict(default=None, type='int', aliases=['storage_soft_limit']),
        storage_grace=dict(default=None, type='int', aliases=['storage_hard_limit']),
        clusters=dict(default=[], type='list'),
        storages=dict(default=[], type='list'),
    )
    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
    )
    check_sdk(module)

    try:
        auth = module.params.pop('auth')
        connection = create_connection(auth)
        datacenters_service = connection.system_service().data_centers_service()
        dc_name = module.params['datacenter']
        dc_id = getattr(search_by_name(datacenters_service, dc_name), 'id', None)
        if dc_id is None:
            raise Exception("Datacenter '%s' was not found." % dc_name)

        quotas_service = datacenters_service.service(dc_id).quotas_service()
        quotas_module = QuotasModule(
            connection=connection,
            module=module,
            service=quotas_service,
        )

        state = module.params['state']
        if state == 'present':
            ret = quotas_module.create()

            # Manage cluster limits:
            cl_limit_service = quotas_service.service(ret['id']).quota_cluster_limits_service()
            for cluster in module.params.get('clusters'):
                cl_limit_service.add(
                    limit=otypes.QuotaClusterLimit(
                        memory_limit=float(cluster.get('memory')),
                        vcpu_limit=cluster.get('cpu'),
                        cluster=search_by_name(
                            connection.system_service().clusters_service(),
                            cluster.get('name')
                        ),
                    ),
                )

            # Manage storage limits:
            sd_limit_service = quotas_service.service(ret['id']).quota_storage_limits_service()
            for storage in module.params.get('storages'):
                sd_limit_service.add(
                    limit=otypes.QuotaStorageLimit(
                        limit=storage.get('size'),
                        storage_domain=search_by_name(
                            connection.system_service().storage_domains_service(),
                            storage.get('name')
                        ),
                    )
                )

        elif state == 'absent':
            ret = quotas_module.remove()

        module.exit_json(**ret)
    except Exception as e:
        module.fail_json(msg=str(e), exception=traceback.format_exc())
    finally:
        connection.close(logout=auth.get('token') is None)


if __name__ == "__main__":
    main()
