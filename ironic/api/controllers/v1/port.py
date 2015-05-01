# Copyright 2013 UnitedStack Inc.
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

import datetime

from oslo_utils import uuidutils
import pecan
from pecan import rest
import wsme
from wsme import types as wtypes

from ironic.api.controllers import base
from ironic.api.controllers import link
from ironic.api.controllers.v1 import collection
from ironic.api.controllers.v1 import types
from ironic.api.controllers.v1 import utils as api_utils
from ironic.api import expose
from ironic.common import exception
from ironic.common.i18n import _
from ironic import objects

# TODO(mariojv) temporary imports for debugging
from ironic.openstack.common import log
LOG = log.getLogger(__name__)
import inspect
import traceback


class PortPatchType(types.JsonPatchType):

    @staticmethod
    def mandatory_attrs():
        return ['/address', '/node_uuid']


class Port(base.APIBase):
    """API representation of a port.

    This class enforces type checking and value constraints, and converts
    between the internal object model and the API representation of a port.
    """

    _node_uuid = None

    def _get_node_uuid(self):
        LOG.debug('getter for node_uuid called')
        return self._node_uuid

    def _set_node_uuid(self, value):
        LOG.debug('SETTING NODE UUID')
        LOG.debug('self: ' + str(self))
        if self.fields:
            LOG.debug('self as_dict: ' + str(self.as_dict()))
        if value and self._node_uuid != value:
            try:
                LOG.debug('CURRENT _node_uuid: ' + str(self._node_uuid))
                LOG.debug('TRYING TO SET TO value: ' + str(value))
                # FIXME(comstud): One should only allow UUID here, but
                # there seems to be a bug in that tests are passing an
                # ID. See bug #1301046 for more details.
                node = objects.Node.get(pecan.request.context, value)
                LOG.debug('NODE: ' + str(node))
                LOG.debug('NODE as_dict: ' + str(node.as_dict()))
                self._node_uuid = node.uuid
                # NOTE(lucasagomes): Create the node_id attribute on-the-fly
                #                    to satisfy the api -> rpc object
                #                    conversion.
                self.node_id = node.id
            except exception.NodeNotFound as e:
                # Change error code because 404 (NotFound) is inappropriate
                # response for a POST request to create a Port
                e.code = 400  # BadRequest
                raise e
        elif value == wtypes.Unset:
            LOG.debug('Value is unset. Unsetting node UUID.')
            self._node_uuid = wtypes.Unset

    uuid = types.uuid
    """Unique UUID for this port"""

    address = wsme.wsattr(types.macaddress, mandatory=True)
    """MAC Address for this port"""

    extra = {wtypes.text: types.jsontype}
    """This port's meta data"""

    node_uuid = wsme.wsproperty(types.uuid, _get_node_uuid, _set_node_uuid,
                                mandatory=True)
    """The UUID of the node this port belongs to"""

    links = wsme.wsattr([link.Link], readonly=True)
    """A list containing a self link and associated port links"""

    def __init__(self, **kwargs):
        LOG.debug('Creating Port... kwargs: ' + str(kwargs))
        LOG.debug('Trace below:')
        tb = traceback.extract_stack()
        formatted = traceback.format_list(tb)
        for line in formatted:
            LOG.debug(line)
        LOG.debug('self: ' + str(self))
        self.fields = []
        fields = list(objects.Port.fields)
        # NOTE(lucasagomes): node_uuid is not part of objects.Port.fields
        #                    because it's an API-only attribute
        fields.append('node_uuid')
        for field in fields:
            # Skip fields we do not expose.
            if not hasattr(self, field):
                continue
            self.fields.append(field)
            setattr(self, field, kwargs.get(field, wtypes.Unset))
        LOG.debug('self as_dict after modifying fields: ' + str(self.as_dict()))
        # NOTE(lucasagomes): node_id is an attribute created on-the-fly
        # by _set_node_uuid(), it needs to be present in the fields so
        # that as_dict() will contain node_id field when converting it
        # before saving it in the database.
        self.fields.append('node_id')
        LOG.debug('fields: ' + str(fields))
        LOG.debug('Calling setattr on node_uuid...')
        setattr(self, 'node_uuid', kwargs.get('node_id', wtypes.Unset))

    @staticmethod
    def _convert_with_links(port, url, expand=True):
        LOG.debug('calling _convert_with_links with port: ' + str(port.as_dict()))
        LOG.debug('expand: ' + str(expand))
        if not expand:
            port.unset_fields_except(['uuid', 'address'])
        # never expose the node_id attribute
        port.node_id = wtypes.Unset

        port.links = [link.Link.make_link('self', url,
                                          'ports', port.uuid),
                      link.Link.make_link('bookmark', url,
                                          'ports', port.uuid,
                                          bookmark=True)
                      ]

        LOG.debug('after convert_with_links: ' + str(port.as_dict()))
        return port

    @classmethod
    def convert_with_links(cls, rpc_port, expand=True):
        LOG.debug('Calling convert_with_links with rpc_port: ' + str(rpc_port.as_dict()))
        port = Port(**rpc_port.as_dict())
        return cls._convert_with_links(port, pecan.request.host_url, expand)

    @classmethod
    def sample(cls, expand=True):
        sample = cls(uuid='27e3153e-d5bf-4b7e-b517-fb518e17f34c',
                     address='fe:54:00:77:07:d9',
                     extra={'foo': 'bar'},
                     created_at=datetime.datetime.utcnow(),
                     updated_at=datetime.datetime.utcnow())
        # NOTE(lucasagomes): node_uuid getter() method look at the
        # _node_uuid variable
        sample._node_uuid = '7ae81bb3-dec3-4289-8d6c-da80bd8001ae'
        return cls._convert_with_links(sample, 'http://localhost:6385', expand)


class PortCollection(collection.Collection):
    """API representation of a collection of ports."""

    ports = [Port]
    """A list containing ports objects"""

    def __init__(self, **kwargs):
        self._type = 'ports'

    @staticmethod
    def convert_with_links(rpc_ports, limit, url=None, expand=False, **kwargs):
        collection = PortCollection()
        collection.ports = [Port.convert_with_links(p, expand)
                            for p in rpc_ports]
        collection.next = collection.get_next(limit, url=url, **kwargs)
        return collection

    @classmethod
    def sample(cls):
        sample = cls()
        sample.ports = [Port.sample(expand=False)]
        return sample


class PortsController(rest.RestController):
    """REST controller for Ports."""

    from_nodes = False
    """A flag to indicate if the requests to this controller are coming
    from the top-level resource Nodes."""

    _custom_actions = {
        'detail': ['GET'],
    }

    def _get_ports_collection(self, node_ident, address, marker, limit,
                              sort_key, sort_dir, expand=False,
                              resource_url=None):
        # TODO(mariojv) This is just for debugging
        frame = inspect.currentframe()
        args, _, _, values = inspect.getargvalues(frame)
        LOG.debug('function name "%s"' % inspect.getframeinfo(frame)[2])
        for i in args:
            LOG.debug("    %s = %s" % (i, values[i]))

        if self.from_nodes and not node_ident:
            raise exception.MissingParameterValue(_(
                  "Node identifier not specified."))

        limit = api_utils.validate_limit(limit)
        sort_dir = api_utils.validate_sort_dir(sort_dir)

        marker_obj = None
        if marker:
            marker_obj = objects.Port.get_by_uuid(pecan.request.context,
                                                  marker)
            LOG.debug('market_obj: ' + str(marker_obj))

        if node_ident:
            # FIXME(comstud): Since all we need is the node ID, we can
            #                 make this more efficient by only querying
            #                 for that column. This will get cleaned up
            #                 as we move to the object interface.
            node = api_utils.get_rpc_node(node_ident)
            LOG.debug('node: ' + str(node.as_dict()))
            ports = objects.Port.list_by_node_id(pecan.request.context,
                                                 node.id, limit, marker_obj,
                                                 sort_key=sort_key,
                                                 sort_dir=sort_dir)
            LOG.debug('ports in _get_ports_collection: ' + str(ports.as_dict()))

        elif address:
            ports = self._get_ports_by_address(address)
        else:
            ports = objects.Port.list(pecan.request.context, limit,
                                      marker_obj, sort_key=sort_key,
                                      sort_dir=sort_dir)

        return PortCollection.convert_with_links(ports, limit,
                                                 url=resource_url,
                                                 expand=expand,
                                                 sort_key=sort_key,
                                                 sort_dir=sort_dir)

    def _get_ports_by_address(self, address):
        """Retrieve a port by its address.

        :param address: MAC address of a port, to get the port which has
                        this MAC address.
        :returns: a list with the port, or an empty list if no port is found.

        """
        try:
            port = objects.Port.get_by_address(pecan.request.context, address)
            return [port]
        except exception.PortNotFound:
            return []

    @expose.expose(PortCollection, types.uuid_or_name, types.uuid,
                         types.macaddress, types.uuid, int, wtypes.text,
                         wtypes.text)
    def get_all(self, node=None, node_uuid=None, address=None, marker=None,
                limit=None, sort_key='id', sort_dir='asc'):
        """Retrieve a list of ports.

        Note that the 'node_uuid' interface is deprecated in favour
        of the 'node' interface

        :param node: UUID or name of a node, to get only ports for that
                           node.
        :param node_uuid: UUID of a node, to get only ports for that
                           node.
        :param address: MAC address of a port, to get the port which has
                        this MAC address.
        :param marker: pagination marker for large data sets.
        :param limit: maximum number of resources to return in a single result.
        :param sort_key: column to sort results by. Default: id.
        :param sort_dir: direction to sort. "asc" or "desc". Default: asc.
        """
        LOG.debug('calling get_all')
        # TODO(mariojv) This is just for debugging
        frame = inspect.currentframe()
        args, _, _, values = inspect.getargvalues(frame)
        LOG.debug('function name "%s"' % inspect.getframeinfo(frame)[2])
        for i in args:
            LOG.debug("    %s = %s" % (i, values[i]))

        if not node_uuid and node:
            LOG.debug('node: ' + str(node))
            # We're invoking this interface using positional notation, or
            # explicitly using 'node'.  Try and determine which one.
            # Make sure only one interface, node or node_uuid is used
            if (not api_utils.allow_node_logical_names() and
                not uuidutils.is_uuid_like(node)):
                raise exception.NotAcceptable()

        return self._get_ports_collection(node_uuid or node, address, marker,
                                          limit, sort_key, sort_dir)

    @expose.expose(PortCollection, types.uuid_or_name, types.uuid,
                         types.macaddress, types.uuid, int, wtypes.text,
                         wtypes.text)
    def detail(self, node=None, node_uuid=None, address=None, marker=None,
               limit=None, sort_key='id', sort_dir='asc'):
        """Retrieve a list of ports with detail.

        Note that the 'node_uuid' interface is deprecated in favour
        of the 'node' interface

        :param node: UUID or name of a node, to get only ports for that
                     node.
        :param node_uuid: UUID of a node, to get only ports for that
                          node.
        :param address: MAC address of a port, to get the port which has
                        this MAC address.
        :param marker: pagination marker for large data sets.
        :param limit: maximum number of resources to return in a single result.
        :param sort_key: column to sort results by. Default: id.
        :param sort_dir: direction to sort. "asc" or "desc". Default: asc.
        """
        LOG.debug('calling detail')
        # TODO(mariojv) This is just for debugging
        frame = inspect.currentframe()
        args, _, _, values = inspect.getargvalues(frame)
        LOG.debug('function name "%s"' % inspect.getframeinfo(frame)[2])
        for i in args:
            LOG.debug("    %s = %s" % (i, values[i]))

        if not node_uuid and node:
            # We're invoking this interface using positional notation, or
            # explicitly using 'node'.  Try and determine which one.
            # Make sure only one interface, node or node_uuid is used
            LOG.debug('node: ' + str(node))
            if (not api_utils.allow_node_logical_names() and
                not uuidutils.is_uuid_like(node)):
                raise exception.NotAcceptable()

        # NOTE(lucasagomes): /detail should only work against collections
        parent = pecan.request.path.split('/')[:-1][-1]
        if parent != "ports":
            raise exception.HTTPNotFound

        expand = True
        resource_url = '/'.join(['ports', 'detail'])
        return self._get_ports_collection(node_uuid or node, address, marker,
                                          limit, sort_key, sort_dir, expand,
                                          resource_url)

    @expose.expose(Port, types.uuid)
    def get_one(self, port_uuid):
        """Retrieve information about the given port.

        :param port_uuid: UUID of a port.
        """
        LOG.debug('calling get_one')
        LOG.debug('port_uuid: ' + str(port_uuid))
        if self.from_nodes:
            raise exception.OperationNotPermitted
        rpc_port = objects.Port.get_by_uuid(pecan.request.context, port_uuid)
        LOG.debug('rpc port as_dict: ' + str(rpc_port.as_dict()))
        return Port.convert_with_links(rpc_port)

    @expose.expose(Port, body=Port, status_code=201)
    def post(self, port):
        """Create a new port.

        :param port: a port within the request body.
        """
        LOG.debug('POST! Creating new port in post() fn')
        LOG.debug('port argument: ' + str(port))
        LOG.debug('port as_dict: ' + str(port.as_dict()))
        if self.from_nodes:
            raise exception.OperationNotPermitted

        new_port = objects.Port(pecan.request.context,
                                **port.as_dict())
        LOG.debug('new port: ' + str(new_port.as_dict()))
        new_port.create()
        LOG.debug('new port created')
        # Set the HTTP Location Header
        pecan.response.location = link.build_url('ports', new_port.uuid)
        LOG.debug('calling convert with links')
        return Port.convert_with_links(new_port)

    @wsme.validate(types.uuid, [PortPatchType])
    @expose.expose(Port, types.uuid, body=[PortPatchType])
    def patch(self, port_uuid, patch):
        """Update an existing port.

        :param port_uuid: UUID of a port.
        :param patch: a json PATCH document to apply to this port.
        """
        LOG.debug('patching port')
        LOG.debug('port_uuid: ' + str(port_uuid))
        if self.from_nodes:
            raise exception.OperationNotPermitted

        rpc_port = objects.Port.get_by_uuid(pecan.request.context, port_uuid)
        try:
            port_dict = rpc_port.as_dict()
            LOG.debug('rpc port_dict: ' + str(port_dict))
            # NOTE(lucasagomes):
            # 1) Remove node_id because it's an internal value and
            #    not present in the API object
            # 2) Add node_uuid
            port_dict['node_uuid'] = port_dict.pop('node_id', None)
            LOG.debug('port_dict after removing node id: ' + str(port_dict))
            port = Port(**api_utils.apply_jsonpatch(port_dict, patch))
            LOG.debug('port after applying patch: ' + str(port.as_dict()))
        except api_utils.JSONPATCH_EXCEPTIONS as e:
            raise exception.PatchError(patch=patch, reason=e)

        # Update only the fields that have changed
        for field in objects.Port.fields:
            try:
                patch_val = getattr(port, field)
            except AttributeError:
                # Ignore fields that aren't exposed in the API
                continue
            if patch_val == wtypes.Unset:
                patch_val = None
            if rpc_port[field] != patch_val:
                rpc_port[field] = patch_val
        LOG.debug('rpc port after changing fields: ' + str(rpc_port.as_dict()))
        rpc_node = objects.Node.get_by_id(pecan.request.context,
                                          rpc_port.node_id)
        LOG.debug('rpc_node: ' + str(rpc_node.as_dict()))
        topic = pecan.request.rpcapi.get_topic_for(rpc_node)

        LOG.debug('WARNING did not remove rpc_node.node_id before updating')
        new_port = pecan.request.rpcapi.update_port(
                                        pecan.request.context, rpc_port, topic)
        LOG.debug('new port: ' + str(new_port))
        return Port.convert_with_links(new_port)

    @expose.expose(None, types.uuid, status_code=204)
    def delete(self, port_uuid):
        """Delete a port.

        :param port_uuid: UUID of a port.
        """
        LOG.debug('deleting port: ' + str(port_uuid))
        if self.from_nodes:
            raise exception.OperationNotPermitted
        rpc_port = objects.Port.get_by_uuid(pecan.request.context,
                                            port_uuid)
        LOG.debug('rpc_port: ' + str(rpc_port.as_dict()))
        rpc_node = objects.Node.get_by_id(pecan.request.context,
                                          rpc_port.node_id)
        LOG.debug('rpc_node: ' + str(rpc_node.as_dict()))
        topic = pecan.request.rpcapi.get_topic_for(rpc_node)
        pecan.request.rpcapi.destroy_port(pecan.request.context,
                                          rpc_port, topic)
