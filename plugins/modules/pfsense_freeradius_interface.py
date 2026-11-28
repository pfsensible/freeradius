#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2026, Romain Tiennot
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

DOCUMENTATION = r"""
---
module: pfsense_freeradius_interface

short_description: Manage the interfaces FreeRADIUS listens on

version_added: "0.1.0"

description:
  - Manage the entries of Services > FreeRADIUS > Interfaces, what the FreeRADIUS package listens on.
  - An entry is found by its O(address) and O(port). The module fails when more than one entry has them, which the web GUI allows.
  - The freeradius3 package must be installed.
  - Omitted options preserve the settings of an existing entry. A new entry gets the defaults of the web GUI.
  - As the web GUI does, a change regenerates the package's configuration and restarts FreeRADIUS.

notes:
  - When the XMLRPC sync of the package is in V(auto) mode (see M(pfsensible.freeradius.pfsense_freeradius_sync)), a change reaches
    the High Availability peer with the next configuration sync, which saving the page in the web GUI starts, but the module does
    not. On an HA pair, start a sync after the changes, for example with M(pfsensible.core.pfsense_rewrite_config).

options:
  address:
    description:
      - IP address to listen on, or V(*) for all the addresses of O(ipversion).
      - The web GUI also requires an address configured on the firewall, or 127.0.0.1. The module does not check it.
    type: str
    required: true
  port:
    description: Port to listen on.
    type: int
    required: true
  type:
    description:
      - What the entry receives. V(auth) for authentication, V(acct) for accounting.
      - V(auth) for a new entry when omitted.
    type: str
    choices: [auth, acct, proxy, detail, status, coa]
  ipversion:
    description:
      - IP version of O(address).
      - V(ipv4) for a new entry when omitted.
    type: str
    choices: [ipv4, ipv6]
  description:
    description: Description of the entry. Letters, digits, spaces and C(_,.;:+=()-) only.
    type: str
  state:
    description: State in which to leave the entry.
    type: str
    choices: [present, absent]
    default: present

author: Romain Tiennot (@RomainTie)
"""

EXAMPLES = r"""
- name: Listen for accounting on the local address
  pfsensible.freeradius.pfsense_freeradius_interface:
    address: 127.0.0.1
    port: 1813
    type: acct

- name: Stop listening on port 1814
  pfsensible.freeradius.pfsense_freeradius_interface:
    address: "*"
    port: 1814
    state: absent
"""

RETURN = r"""
commands:
    description: Pseudo-CLI commands describing configuration changes.
    returned: always
    type: list
    elements: str
    sample: ["update freeradius_interface '127.0.0.1:1813' set type='acct'"]
"""

import re

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.pfsensible.core.plugins.module_utils.module_base import PFSenseModuleBase

FREERADIUS_INTERFACE_ARGUMENT_SPEC = dict(
    address=dict(type="str", required=True),
    port=dict(type="int", required=True),
    type=dict(type="str", choices=["auth", "acct", "proxy", "detail", "status", "coa"]),
    ipversion=dict(type="str", choices=["ipv4", "ipv6"]),
    description=dict(type="str"),
    state=dict(type="str", choices=["present", "absent"], default="present"),
)

# The values of the web GUI for ipversion
IPVERSIONS = dict(ipv4="ipaddr", ipv6="ipv6addr")
# The defaults of the web GUI for a new entry
DEFAULTS = dict(varinterfacetype="auth", varinterfaceipversion="ipaddr")
# freeradius_validate_interfaces() of the package
DESCRIPTION_RE = re.compile(r"^[a-zA-Z0-9 _,.;:+=()-]*$")
# The fields of an entry, by option
FIELDS = dict(type="varinterfacetype", ipversion="varinterfaceipversion", description="description")

# What the package runs when its Interfaces page is saved or an entry deleted
FREERADIUS_INTERFACE_PHP_COMMAND = """
require_once("/usr/local/pkg/freeradius.inc");
freeradius_settings_resync();
"""


class PFSenseFreeRADIUSInterfaceModule(PFSenseModuleBase):
    """ module managing the interfaces of the FreeRADIUS package """

    ##############################
    # unit tests
    #
    # Must be class method for unit test usage
    @staticmethod
    def get_argument_spec():
        """ return argument spec """
        return FREERADIUS_INTERFACE_ARGUMENT_SPEC

    def __init__(self, module, pfsense=None):
        super(PFSenseFreeRADIUSInterfaceModule, self).__init__(
            module, pfsense, package="freeradius3", name="pfsense_freeradius_interface", root="freeradiusinterfaces", node="config",
            create_root=True, update_php=FREERADIUS_INTERFACE_PHP_COMMAND,
        )

    ##############################
    # params processing
    #
    def _find_entry(self):
        """ the entry with the address and port of the task """
        found = [elt for elt in self.elements
                 if elt.findtext("varinterfaceip") == self.params["address"] and elt.findtext("varinterfaceport") == str(self.params["port"])]
        # The web GUI does not check that an address and port are unique
        if len(found) > 1:
            self.module.fail_json(msg="Found multiple entries for {0}.".format(self._get_obj_name()))
        return found[0] if found else None

    def _validate_params(self):
        """ do the checks of the web GUI """
        params = self.params
        if params["state"] == "absent":
            return

        if not params["address"]:
            self.module.fail_json(msg="address must not be empty")
        if not 1 <= params["port"] <= 65535:
            self.module.fail_json(msg="port must be between 1 and 65535")
        if params.get("description") and not DESCRIPTION_RE.match(params["description"]):
            self.module.fail_json(msg="description may only contain letters, digits, spaces and _,.;:+=()-")

        if params["address"] != "*":
            ipversion = params.get("ipversion")
            if ipversion is None:
                entry = self._find_entry()
                stored = entry.findtext("varinterfaceipversion") if entry is not None else None
                ipversion = "ipv6" if stored == "ipv6addr" else "ipv4"
            if ipversion == "ipv4" and not self.pfsense.is_ipv4_address(params["address"]):
                self.module.fail_json(msg="address must be an IPv4 address, as ipversion is ipv4")
            if ipversion == "ipv6" and not self.pfsense.is_ipv6_address(params["address"]):
                self.module.fail_json(msg="address must be an IPv6 address, as ipversion is ipv6")

    def _params_to_obj(self):
        """ return a dict from module params """
        params = self.params
        obj = dict(varinterfaceip=params["address"], varinterfaceport=str(params["port"]))
        if params["state"] == "present":
            self.target_elt = self._find_entry()
            if self.target_elt is None:
                obj.update(DEFAULTS)
            if params.get("type") is not None:
                obj["varinterfacetype"] = params["type"]
            if params.get("ipversion") is not None:
                obj["varinterfaceipversion"] = IPVERSIONS[params["ipversion"]]
            if params.get("description") is not None:
                obj["description"] = params["description"]
        return obj

    ##############################
    # XML processing
    #
    def _find_target(self):
        """ find the XML target_elt """
        return self._find_entry()

    ##############################
    # Logging
    #
    def _get_obj_name(self):
        """ return obj's name """
        return "'{0}:{1}'".format(self.params["address"], self.params["port"])

    @staticmethod
    def _view(values):
        """ the options of an entry's fields, as the task gives them """
        view = dict()
        for option, field in FIELDS.items():
            if values.get(field) is not None:
                view[option] = values[field]
        if view.get("ipversion") is not None:
            view["ipversion"] = "ipv6" if view["ipversion"] == "ipv6addr" else "ipv4"
        return view

    def _log_fields(self, before=None):
        """ generate pseudo-CLI command fields parameters """
        after = self._view(self.diff["after"] if before is not None else self.obj)
        if before is None:
            return "".join(self.format_cli_field(after, option) for option in FIELDS)
        before = self._view(before)
        values = ""
        for option in FIELDS:
            values += self.format_updated_cli_field(after, before, option, add_comma=(values), log_none=False)
        return values


def main():
    module = AnsibleModule(
        argument_spec=FREERADIUS_INTERFACE_ARGUMENT_SPEC,
        supports_check_mode=True)

    pfmodule = PFSenseFreeRADIUSInterfaceModule(module)
    # Pass params for testing framework
    pfmodule.run(module.params)
    pfmodule.commit_changes()


if __name__ == "__main__":
    main()
