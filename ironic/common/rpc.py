# Copyright 2014 Red Hat, Inc.
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

from oslo_config import cfg
import oslo_messaging as messaging

from ironic.common import context as ironic_context
from ironic.common import exception
from ironic.common.i18n import _
from ironic.objects import fields as ironic_fields


CONF = cfg.CONF
notification_opts = [
    cfg.StrOpt('notification_priority',
               choices=list(
                   ironic_fields.NotificationPriority.ALL).append(None),
               help=_('Specifies the minimum priority for which to send '
                      'notifications. A value of "None" indicates that no '
                      'notifications will be sent.'))
]
CONF.register_opts(notification_opts)

TRANSPORT = None
NOTIFICATION_TRANSPORT = None
METRICS_NOTIFIER = None
VERSIONED_NOTIFIER = None

ALLOWED_EXMODS = [
    exception.__name__,
]
EXTRA_EXMODS = []

# NOTE(lucasagomes): The ironic.openstack.common.rpc entries are for
# backwards compat with IceHouse rpc_backend configuration values.
TRANSPORT_ALIASES = {
    'ironic.openstack.common.rpc.impl_kombu': 'rabbit',
    'ironic.openstack.common.rpc.impl_qpid': 'qpid',
    'ironic.openstack.common.rpc.impl_zmq': 'zmq',
    'ironic.rpc.impl_kombu': 'rabbit',
    'ironic.rpc.impl_qpid': 'qpid',
    'ironic.rpc.impl_zmq': 'zmq',
}


def init(conf):
    global TRANSPORT, NOTIFICATION_TRANSPORT
    global METRICS_NOTIFIER, VERSIONED_NOTIFIER
    exmods = get_allowed_exmods()
    TRANSPORT = messaging.get_transport(conf,
                                        allowed_remote_exmods=exmods,
                                        aliases=TRANSPORT_ALIASES)
    NOTIFICATION_TRANSPORT = messaging.get_notification_transport(
        conf, allowed_remote_exmods=exmods, aliases=TRANSPORT_ALIASES)

    serializer = RequestContextSerializer(messaging.JsonPayloadSerializer())
    # Notifier used for sending metrics to Ceilometer
    METRICS_NOTIFIER = messaging.Notifier(TRANSPORT, serializer=serializer)

    if conf.notification_priority is None:
        VERSIONED_NOTIFIER = messaging.Notifier(NOTIFICATION_TRANSPORT,
                                                serializer=serializer,
                                                driver='noop')
    else:
        # TODO(mariojv) What is the default topic? Not sure if that's
        # necessary.
        VERSIONED_NOTIFIER = messaging.Notifier(NOTIFICATION_TRANSPORT,
                                                serializer=serializer,
                                                topic='notification')


def cleanup():
    global TRANSPORT, NOTIFICATION_TRANSPORT
    global METRICS_NOTIFIER, VERSIONED_NOTIFIER
    assert TRANSPORT is not None
    assert NOTIFICATION_TRANSPORT is not None
    assert METRICS_NOTIFIER is not None
    assert VERSIONED_NOTIFIER is not None
    TRANSPORT.cleanup()
    NOTIFICATION_TRANSPORT.cleanup()
    TRANSPORT = NOTIFICATION_TRANSPORT = None
    METRICS_NOTIFIER = VERSIONED_NOTIFIER = None


def set_defaults(control_exchange):
    messaging.set_transport_defaults(control_exchange)


def add_extra_exmods(*args):
    EXTRA_EXMODS.extend(args)


def clear_extra_exmods():
    del EXTRA_EXMODS[:]


def get_allowed_exmods():
    return ALLOWED_EXMODS + EXTRA_EXMODS


class RequestContextSerializer(messaging.Serializer):

    def __init__(self, base):
        self._base = base

    def serialize_entity(self, context, entity):
        if not self._base:
            return entity
        return self._base.serialize_entity(context, entity)

    def deserialize_entity(self, context, entity):
        if not self._base:
            return entity
        return self._base.deserialize_entity(context, entity)

    def serialize_context(self, context):
        return context.to_dict()

    def deserialize_context(self, context):
        return ironic_context.RequestContext.from_dict(context)


def get_transport_url(url_str=None):
    return messaging.TransportURL.parse(CONF, url_str, TRANSPORT_ALIASES)


def get_client(target, version_cap=None, serializer=None):
    assert TRANSPORT is not None
    serializer = RequestContextSerializer(serializer)
    return messaging.RPCClient(TRANSPORT,
                               target,
                               version_cap=version_cap,
                               serializer=serializer)


def get_server(target, endpoints, serializer=None):
    assert TRANSPORT is not None
    serializer = RequestContextSerializer(serializer)
    return messaging.get_rpc_server(TRANSPORT,
                                    target,
                                    endpoints,
                                    executor='eventlet',
                                    serializer=serializer)


def get_metrics_notifier(service=None, host=None, publisher_id=None):
    assert METRICS_NOTIFIER is not None
    if not publisher_id:
        publisher_id = "%s.%s" % (service, host or CONF.host)
    return METRICS_NOTIFIER.prepare(publisher_id=publisher_id)


def get_versioned_notifier(publisher_id=None):
    assert VERSIONED_NOTIFIER is not None
    return VERSIONED_NOTIFIER.prepare(publisher_id=publisher_id)
