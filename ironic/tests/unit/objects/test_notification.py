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

import mock

from ironic.objects import base
from ironic.objects import fields
from ironic.objects import notification
from ironic.tests import base as test_base


class TestNotificationBase(test_base.TestCase):

    @base.IronicObjectRegistry.register_if(False)
    class TestObject(base.IronicObject):
        VERSION = '1.0'
        fields = {
            'fake_field_1': fields.StringField(),
            'fake_field_2': fields.IntegerField()
        }

    @base.IronicObjectRegistry.register_if(False)
    class TestNotificationPayload(notification.NotificationPayloadBase):
        VERSION = '1.0'

        SCHEMA = {
            'fake_field_1': ('test_obj', 'fake_field_1'),
            'fake_field_2': ('test_obj', 'fake_field_2')
        }

        fields = {
            'fake_field_1': fields.StringField(),
            'fake_field_2': fields.IntegerField(),
            'an_extra_field': fields.StringField(nullable=False),
            'an_optional_field': fields.IntegerField(nullable=True)
        }

        def populate_schema(self, test_obj):
            super(TestNotificationBase.TestNotificationPayload,
                  self).populate_schema(test_obj=test_obj)

    @base.IronicObjectRegistry.register_if(False)
    class TestNotificationPayloadEmptySchema(
            notification.NotificationPayloadBase):
        VERSION = '1.0'

        fields = {
            'fake_field': fields.StringField()
        }

    @base.IronicObjectRegistry.register_if(False)
    class TestNotification(notification.NotificationBase):
        VERSION = '1.0'
        fields = {
            'payload': fields.ObjectField('TestNotificationPayload')
        }

    @base.IronicObjectRegistry.register_if(False)
    class TestNotificationEmptySchema(notification.NotificationBase):
        VERSION = '1.0'
        fields = {
            'payload': fields.ObjectField('TestNotificationPayloadEmptySchema')
        }

    def setUp(self):
        super(TestNotificationBase, self).setUp()
        self.fake_obj = self.TestObject(fake_field_1='fake1', fake_field_2=2)

    def _verify_notification(self, mock_notifier, mock_context,
                             expected_event_type, expected_payload,
                             expected_publisher, notif_level):
        mock_notifier.prepare.assert_called_once_with(
            publisher_id=expected_publisher)
        # Handler actually sending out the notification depends on the
        # notification priority
        mock_notify = getattr(mock_notifier.prepare.return_value, notif_level)
        self.assertTrue(mock_notify.called)
        self.assertEqual(mock_notify.call_args[0][0], mock_context)
        self.assertEqual(mock_notify.call_args[1]['event_type'],
                         expected_event_type)
        actual_payload = mock_notify.call_args[1]['payload']
        self.assertJsonEqual(expected_payload, actual_payload)

    @mock.patch('ironic.common.rpc.VERSIONED_NOTIFIER')
    def test_emit_notification(self, mock_notifier):
        self.config(notification_priority='debug')
        payload = self.TestNotificationPayload(an_extra_field='extra',
                                               an_optional_field=1)
        payload.populate_schema(test_obj=self.fake_obj)
        notif = self.TestNotification(
            event_type=notification.EventType(
                object='test_object', action='test', phase='start'),
            priority=fields.NotificationPriority.DEBUG,
            publisher=notification.NotificationPublisher(
                service='ironic-conductor',
                host='host'),
            payload=payload)

        mock_context = mock.Mock()
        notif.emit(mock_context)

        self._verify_notification(
            mock_notifier,
            mock_context,
            expected_event_type='baremetal.test_object.test.start',
            expected_payload={
                'ironic_object.name': 'TestNotificationPayload',
                'ironic_object.data': {
                    'fake_field_1': 'fake1',
                    'fake_field_2': 2,
                    'an_extra_field': 'extra',
                    'an_optional_field': 1
                },
                'ironic_object.version': '1.0',
                'ironic_object.namespace': 'ironic'},
            expected_publisher='ironic-conductor.host',
            notif_level=fields.NotificationPriority.DEBUG)

    @mock.patch('ironic.common.rpc.VERSIONED_NOTIFIER')
    def test_no_emit_priority_too_low(self, mock_notifier):
        # Make sure notification doesn't emit when configured notification
        # priority < config priority
        self.config(notification_priority='warn')
        payload = self.TestNotificationPayload(an_extra_field='extra',
                                               an_optional_field=1)
        payload.populate_schema(test_obj=self.fake_obj)
        notif = self.TestNotification(
            event_type=notification.EventType(
                object='test_object', action='test', phase='start'),
            priority=fields.NotificationPriority.DEBUG,
            publisher=notification.NotificationPublisher(
                service='ironic-conductor',
                host='host'),
            payload=payload)

        mock_context = mock.Mock()
        notif.emit(mock_context)

        self.assertFalse(mock_notifier.called)

    @mock.patch('ironic.common.rpc.VERSIONED_NOTIFIER')
    def test_no_emit_notifs_disabled(self, mock_notifier):
        # Make sure notifications aren't emitted when notification_priority
        # isn't defined, indicating notifications should be disabled
        # NOTE(mariojv) "None" is the default today, but this is here just to
        # be explicit in case that changes.
        self.config(notification_priority=None)
        payload = self.TestNotificationPayload(an_extra_field='extra',
                                               an_optional_field=1)
        payload.populate_schema(test_obj=self.fake_obj)
        notif = self.TestNotification(
            event_type=notification.EventType(
                object='test_object', action='test', phase='start'),
            priority=fields.NotificationPriority.DEBUG,
            publisher=notification.NotificationPublisher(
                service='ironic-conductor',
                host='host'),
            payload=payload)

        mock_context = mock.Mock()
        notif.emit(mock_context)

        self.assertFalse(mock_notifier.called)

    @mock.patch('ironic.common.rpc.VERSIONED_NOTIFIER')
    def test_no_emit_schema_not_populated(self, mock_notifier):
        self.config(notification_priority='debug')
        payload = self.TestNotificationPayload(an_extra_field='extra',
                                               an_optional_field=1)
        notif = self.TestNotification(
            event_type=notification.EventType(
                object='test_object', action='test', phase='start'),
            priority=fields.NotificationPriority.DEBUG,
            publisher=notification.NotificationPublisher(
                service='ironic-conductor',
                host='host'),
            payload=payload)

        mock_context = mock.Mock()
        self.assertRaises(AssertionError, notif.emit, mock_context)
        self.assertFalse(mock_notifier.called)

    @mock.patch('ironic.common.rpc.VERSIONED_NOTIFIER')
    def test_emit_notification_empty_schema(self, mock_notifier):
        self.config(notification_priority='debug')
        payload = self.TestNotificationPayloadEmptySchema(fake_field='123')
        notif = self.TestNotificationEmptySchema(
            event_type=notification.EventType(
                object='test_object', action='test', phase='fail'),
            priority=fields.NotificationPriority.ERROR,
            publisher=notification.NotificationPublisher(
                service='ironic-conductor',
                host='host'),
            payload=payload)

        mock_context = mock.Mock()
        notif.emit(mock_context)

        self._verify_notification(
            mock_notifier,
            mock_context,
            expected_event_type='baremetal.test_object.test.fail',
            expected_payload={
                'ironic_object.name': 'TestNotificationPayloadEmptySchema',
                'ironic_object.data': {
                    'fake_field': '123',
                },
                'ironic_object.version': '1.0',
                'ironic_object.namespace': 'ironic'},
            expected_publisher='ironic-conductor.host',
            notif_level=fields.NotificationPriority.ERROR)
