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

from oslo_config import cfg

from ironic.common import rpc
from ironic.objects import base
from ironic.objects import fields


CONF = cfg.CONF
CONF.import_opt('notification_priority', 'ironic.common.rpc')


@base.IronicObjectRegistry.register
class EventType(base.IronicObject):
    """Defines the event_type to be sent on the wire.

       An EventType must specify the object being acted on, a string describing
       the action being taken on the notification, and the phase of the action,
       if applicable.
    """
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'object': fields.StringField(nullable=False),
        'action': fields.StringField(nullable=False),
        'phase': fields.StringField(nullable=True)
    }

    def to_notification_event_type_field(self):
        s = 'baremetal.%s.%s' % (self.object, self.action)
        if self.obj_attr_is_set('phase') and self.phase is not None:
            s += '.%s' % self.phase
        return s


# NOTE(mariojv) This class will not be used directly and is just a base class
# for notifications, so we don't need to register it.
@base.IronicObjectRegistry.register_if(False)
class NotificationBase(base.IronicObject):
    """Base class for versioned notifications.

    Subclasses must define the "payload" field.
    """
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'priority': fields.NotificationPriorityField(),
        'event_type': fields.ObjectField('EventType'),
        'publisher': fields.ObjectField('NotificationPublisher')
    }

    # NOTE(mariojv) This may be a candidate for something oslo.messaging
    # implements instead of in ironic.
    def _should_notify(self):
        """Determine whether the notification should be sent.

           A notification is sent when the priority of the notification is
           greater than or equal to the priority specified in the
           configuration, in the increasing order of DEBUG, INFO, WARN, ERROR.

           :return: True if notification should be sent, False otherwise.
        """

        notify_priorities = {
            fields.NotificationPriority.DEBUG: 0,
            fields.NotificationPriority.INFO: 1,
            fields.NotificationPriority.WARN: 2,
            fields.NotificationPriority.ERROR: 3
        }
        if CONF.notification_priority is None:
            return False
        else:
            return (notify_priorities[self.priority] >=
                    notify_priorities[CONF.notification_priority])

    def _emit(self, context, event_type, publisher_id, payload):
        notifier = rpc.get_versioned_notifier(publisher_id)
        notify = getattr(notifier, self.priority)
        notify(context, event_type=event_type, payload=payload)

    def emit(self, context):
        """Send the notification."""
        assert self.payload.populated
        if self._should_notify():
            # NOTE(mariojv) By default, oslo_versionedobjects includes a list
            # of "changed fields" for the object in the output of
            # obj_to_primitive. This is unneeded since every field of the
            # object will look changed, since each payload is a newly created
            # object, so we drop the changes.
            self.payload.obj_reset_changes(recursive=False)

            self._emit(
                context,
                event_type=self.event_type.to_notification_event_type_field(),
                publisher_id='%s.%s' %
                             (self.publisher.service,
                              self.publisher.host),
                payload=self.payload.obj_to_primitive())


# NOTE(mariojv) This class will not be used directly and is just a base class
# for notifications, so we don't need to register it.
@base.IronicObjectRegistry.register_if(False)
class NotificationPayloadBase(base.IronicObject):
    """Base class for the payload of versioned notifications."""

    # SCHEMA defines how to populate the payload fields. It's an optional
    # attribute that subclasses may use to easily populate notifications with
    # data from other objects.
    # It is a dictionary where every key value pair has the following format:
    # <payload_field_name>: (<data_source_name>,
    #                        <field_of_the_data_source>)
    # The <payload_field_name> is the name where the data will be stored in the
    # payload object; this field has to be defined as a field of the payload.
    # The <data_source_name> shall refer to name of the parameter passed as
    # kwarg to the payload's populate_schema() call and this object will be
    # used as the source of the data. The <field_of_the_data_source> shall be
    # a valid field of the passed argument.
    # The SCHEMA needs to be applied with the populate_schema() call before the
    # notification can be emitted.
    # The value of the payload.<payload_field_name> field will be set by the
    # <data_source_name>.<field_of_the_data_source> field. The
    # <data_source_name> will not be part of the payload object internal or
    # external representation.
    # Payload fields that are not set by the SCHEMA can be filled in the same
    # way as in any versioned object.
    SCHEMA = {}
    # Version 1.0: Initial version
    VERSION = '1.0'

    def __init__(self, *args, **kwargs):
        super(NotificationPayloadBase, self).__init__(*args, **kwargs)
        # If SCHEMA is empty, the payload is already populated
        self.populated = not self.SCHEMA

    def populate_schema(self, **kwargs):
        """Populate the object based on the SCHEMA and the source objects

        :param kwargs: A dict contains the source object and the keys defined
                       in the SCHEMA
        """
        for key, (obj, field) in self.SCHEMA.items():
            source = kwargs[obj]
            if source.obj_attr_is_set(field):
                setattr(self, key, getattr(source, field))
        self.populated = True


@base.IronicObjectRegistry.register
class NotificationPublisher(base.IronicObject):
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'service': fields.StringField(nullable=False),
        'host': fields.StringField(nullable=False)
    }
