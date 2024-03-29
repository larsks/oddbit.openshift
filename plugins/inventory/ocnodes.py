from ansible.errors import AnsibleParserError
from ansible.plugins.inventory import BaseInventoryPlugin, Cacheable, Constructable

import openshift_client as oc

DOCUMENTATION = r"""
name: ocnodes
plugin_type: inventory
short_description: Inventory of openshift nodes
extends_documentation_fragment:
    - constructed
options:
    plugin:
        type: str
        description: Name of the plugin
        required: true
        choices: ['oddbit.openshift.ocnodes']
    group:
        type: str
        description: Add nodes to named group
        required: false
    group_vars:
        type: dict
        description: Arbitrary group variables
        required: false
"""


class InventoryModule(BaseInventoryPlugin, Constructable, Cacheable):
    NAME = "ocnodes"

    def __init__(self):
        super(InventoryModule, self).__init__()

    def verify_file(self, path: str):
        if super(InventoryModule, self).verify_file(path):
            return path.endswith("openshift.yaml")
        return False

    def _set_variables(self, hostvars):
        strict = self.get_option("strict")

        for host in hostvars:
            for varname, varvalue in hostvars[host].items():
                self.inventory.set_variable(host, varname, varvalue)

            # create composite vars
            self._set_composite_vars(
                self.get_option("compose"), hostvars[host], host, strict=strict
            )

            # constructed groups based on conditionals
            self._add_host_to_composed_groups(
                self.get_option("groups"), hostvars[host], host, strict=strict
            )

            # constructed keyed_groups
            self._add_host_to_keyed_groups(
                self.get_option("keyed_groups"), hostvars[host], host, strict=strict
            )

    def _create_node_variables(self, name, node):
        hostvars = {}

        roles = [
            label.split("/")[1]
            for label in node.model.metadata.labels
            if label.startswith("node-role.kubernetes.io")
        ]

        hostvars["node_roles"] = roles
        hostvars["node_labels"] = node.model.metadata.labels
        hostvars["node_annotations"] = node.model.metadata.annotations
        hostvars["node_info"] = node.model.status.nodeInfo
        hostvars["node_addresses"] = node.model.status.addresses
        hostvars["node_ready"] = next(
            (
                condition["status"] == "True"
                for condition in node.model.status.conditions
                if condition["type"] == "Ready"
            ),
            False,
        )

        return hostvars

    def parse(self, inventory, loader, path, cache: bool = True):
        super(InventoryModule, self).parse(inventory, loader, path, cache)
        self._read_config_data(path)

        group_name = None
        if self.has_option("group"):
            group_name = self.get_option("group")
            if group_name:
                self.inventory.add_group(group_name)
                if self.has_option("group_vars"):
                    for name, value in self.get_option("group_vars").items():
                        self.inventory.set_variable(group_name, name, value)

        nodes = oc.selector("nodes").objects()
        hostvars = {}
        for node in nodes:
            name = node.model.metadata.name
            self.inventory.add_host(name, group=group_name)

            if "addresses" in node.model.status:
                try:
                    address = next(
                        addr["address"]
                        for addr in node.model.status.addresses
                        if addr["type"] == "InternalIP"
                    )
                    self.inventory.set_variable(name, "ansible_host", address)
                except StopIteration:
                    pass

            hostvars[name] = self._create_node_variables(name, node)

        self._set_variables(hostvars)
