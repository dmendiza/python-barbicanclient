# Copyright (c) 2015 Red Hat Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import logging

from barbicanclient import base


LOG = logging.getLogger(__name__)


class VersionManager(base.BaseEntityManager):
    """Entity Manager for versions"""

    def __init__(self, api):
        super(VersionManager, self).__init__(api, '')

    def list_versions(self):
        """List versions"""
        LOG.debug('Listing versions supported by the server')
        response = self._api.get('/')
        # do different responses depending on output
        versions = response['versions']
        if 'values' in versions:
            # pre-microversions, return "values"
            return versions['values']
        else:
            return versions
