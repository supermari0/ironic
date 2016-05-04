# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""Base classes for our unit tests.

Allows overriding of config for use of fakes, and some black magic for
inline callbacks.

"""

import copy
import datetime
import os
import sys
import tempfile

import eventlet
eventlet.monkey_patch(os=False)
import fixtures
from oslo_config import cfg
from oslo_config import fixture as config_fixture
from oslo_log import log as logging
from oslo_serialization import jsonutils
import six
import testtools

from ironic.common import config as ironic_config
from ironic.common import context as ironic_context
from ironic.common import hash_ring
from ironic.objects import base as objects_base
from ironic.tests.unit import policy_fixture


CONF = cfg.CONF
CONF.import_opt('host', 'ironic.common.service')
logging.register_options(CONF)
logging.setup(CONF, 'ironic')


class ReplaceModule(fixtures.Fixture):
    """Replace a module with a fake module."""

    def __init__(self, name, new_value):
        self.name = name
        self.new_value = new_value

    def _restore(self, old_value):
        sys.modules[self.name] = old_value

    def setUp(self):
        super(ReplaceModule, self).setUp()
        old_value = sys.modules.get(self.name)
        sys.modules[self.name] = self.new_value
        self.addCleanup(self._restore, old_value)


class TestingException(Exception):
    pass


class TestCase(testtools.TestCase):
    """Test case base class for all unit tests."""

    def setUp(self):
        """Run before each test method to initialize test environment."""
        super(TestCase, self).setUp()
        self.context = ironic_context.get_admin_context()
        test_timeout = os.environ.get('OS_TEST_TIMEOUT', 0)
        try:
            test_timeout = int(test_timeout)
        except ValueError:
            # If timeout value is invalid do not set a timeout.
            test_timeout = 0
        if test_timeout > 0:
            self.useFixture(fixtures.Timeout(test_timeout, gentle=True))
        self.useFixture(fixtures.NestedTempfile())
        self.useFixture(fixtures.TempHomeDir())

        if (os.environ.get('OS_STDOUT_CAPTURE') == 'True' or
                os.environ.get('OS_STDOUT_CAPTURE') == '1'):
            stdout = self.useFixture(fixtures.StringStream('stdout')).stream
            self.useFixture(fixtures.MonkeyPatch('sys.stdout', stdout))
        if (os.environ.get('OS_STDERR_CAPTURE') == 'True' or
                os.environ.get('OS_STDERR_CAPTURE') == '1'):
            stderr = self.useFixture(fixtures.StringStream('stderr')).stream
            self.useFixture(fixtures.MonkeyPatch('sys.stderr', stderr))

        self.log_fixture = self.useFixture(fixtures.FakeLogger())
        self._set_config()
        # NOTE(danms): Make sure to reset us back to non-remote objects
        # for each test to avoid interactions. Also, backup the object
        # registry
        objects_base.IronicObject.indirection_api = None
        self._base_test_obj_backup = copy.copy(
            objects_base.IronicObjectRegistry.obj_classes())
        self.addCleanup(self._restore_obj_registry)

        self.addCleanup(self._clear_attrs)
        self.addCleanup(hash_ring.HashRingManager().reset)
        self.useFixture(fixtures.EnvironmentVariable('http_proxy'))
        self.policy = self.useFixture(policy_fixture.PolicyFixture())

    def _set_config(self):
        self.cfg_fixture = self.useFixture(config_fixture.Config(CONF))
        self.config(use_stderr=False,
                    fatal_exception_format_errors=True,
                    tempdir=tempfile.tempdir)
        self.set_defaults(host='fake-mini',
                          verbose=True)
        self.set_defaults(connection="sqlite://",
                          sqlite_synchronous=False,
                          group='database')
        ironic_config.parse_args([], default_config_files=[])

    def _restore_obj_registry(self):
        objects_base.IronicObjectRegistry._registry._obj_classes = (
            self._base_test_obj_backup)

    def _clear_attrs(self):
        # Delete attributes that don't start with _ so they don't pin
        # memory around unnecessarily for the duration of the test
        # suite
        for key in [k for k in self.__dict__.keys() if k[0] != '_']:
            del self.__dict__[key]

    def config(self, **kw):
        """Override config options for a test."""
        self.cfg_fixture.config(**kw)

    def set_defaults(self, **kw):
        """Set default values of config options."""
        group = kw.pop('group', None)
        for o, v in kw.items():
            self.cfg_fixture.set_default(o, v, group=group)

    def path_get(self, project_file=None):
        """Get the absolute path to a file. Used for testing the API.

        :param project_file: File whose path to return. Default: None.
        :returns: path to the specified file, or path to project root.
        """
        root = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                            '..',
                                            '..',
                                            )
                               )
        if project_file:
            return os.path.join(root, project_file)
        else:
            return root

    def assertJsonEqual(self, expected, observed):
        """Asserts that 2 complex data structures are json equivalent.

        Sorts internal data structures to avoid false mismatches.

        Because this is a recursive set of assertions, when failure
        happens we want to expose both the local failure and the
        global view of the 2 data structures being compared. So a
        MismatchError which includes the inner failure as the
        mismatch, and the passed in expected / observed as matchee /
        matcher is re-raised on a failure within the recursive loop.
        """
        if isinstance(expected, six.string_types):
            expected = jsonutils.loads(expected)
        if isinstance(observed, six.string_types):
            observed = jsonutils.loads(observed)

        def sort_key(x):
            if isinstance(x, (set, list)) or isinstance(x, datetime.datetime):
                return str(x)
            if isinstance(x, dict):
                items = ((sort_key(key), sort_key(value))
                         for key, value in x.items())
                return sorted(items)
            return x

        def inner(expected, observed):
            if isinstance(expected, dict) and isinstance(observed, dict):
                self.assertEqual(len(expected), len(observed))
                expected_keys = sorted(expected)
                observed_keys = sorted(observed)
                self.assertEqual(expected_keys, observed_keys)

                for key in list(six.iterkeys(expected)):
                    inner(expected[key], observed[key])
            elif (isinstance(expected, (list, tuple, set)) and
                  isinstance(observed, (list, tuple, set))):
                self.assertEqual(len(expected), len(observed))

                expected_values_iter = iter(sorted(expected, key=sort_key))
                observed_values_iter = iter(sorted(observed, key=sort_key))

                for i in range(len(expected)):
                    inner(next(expected_values_iter),
                          next(observed_values_iter))
            else:
                self.assertEqual(expected, observed)

        try:
            inner(expected, observed)
        except testtools.matchers.MismatchError as e:
            inner_mismatch = e.mismatch
            # inverting the observed / expected because testtools
            # error messages assume expected is second. Possibly makes
            # reading the error messages less confusing.
            raise testtools.matchers.MismatchError(
                observed, expected, inner_mismatch, verbose=True)
