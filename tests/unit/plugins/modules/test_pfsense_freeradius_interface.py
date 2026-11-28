# Copyright: (c) 2026, Romain Tiennot
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

import os
import xml.etree.ElementTree as ET

from parameterized import parameterized

from ansible_collections.community.internal_test_tools.tests.unit.plugins.modules.utils import set_module_args
from ansible_collections.pfsensible.freeradius.plugins.modules import pfsense_freeradius_interface
# The test harness of pfsensible.core (its source tree: the built collection does not ship tests)
from ansible_collections.pfsensible.core.tests.unit.plugins.modules.pfsense_module import TestPFSenseModule


PACKAGE = "<package><name>freeradius3</name><internal_name>radiusd</internal_name></package>"
ENTRY = ("<config><varinterfaceip>{0}</varinterfaceip><varinterfaceport>{1}</varinterfaceport><varinterfacetype>{2}</varinterfacetype>"
         "<varinterfaceipversion>ipaddr</varinterfaceipversion><description></description></config>")
# Authentication and accounting on the local address, accounting declared as auth
INTERFACES = "<freeradiusinterfaces>{0}</freeradiusinterfaces>".format(
    ENTRY.format("127.0.0.1", "1812", "auth") + ENTRY.format("127.0.0.1", "1813", "auth"))
RESYNC = "freeradius_settings_resync();"


class TestPFSenseFreeRADIUSInterfaceModule(TestPFSenseModule):
    module = pfsense_freeradius_interface

    def setUp(self):
        super(TestPFSenseFreeRADIUSInterfaceModule, self).setUp()
        self.write_config(PACKAGE + INTERFACES)

    def run_module(self, changed=False, **params):
        with set_module_args(params):
            return self.changed(changed)

    def write_config(self, packages):
        with open(self.tmp_file, "w") as config:
            config.write("<pfsense><version>24.0</version><installedpackages>{0}</installedpackages></pfsense>".format(packages))

    def entries(self):
        return [{child.tag: child.text or "" for child in entry} for entry in ET.parse(self.tmp_file).findall("installedpackages/freeradiusinterfaces/config")]

    def test_change_type_and_repeat(self):
        result = self.run_module(changed=True, address="127.0.0.1", port=1813, type="acct", _ansible_diff=True)
        self.assertEqual(result["commands"], ["update freeradius_interface '127.0.0.1:1813' set type='acct'"])
        self.assertEqual(result["diff"]["before"]["varinterfacetype"], "auth")
        self.assertEqual([entry["varinterfacetype"] for entry in self.entries()], ["auth", "acct"])
        self.assertIn(RESYNC, self.phpshell.call_args[0][0])
        self.assertEqual(self.run_module(address="127.0.0.1", port=1813, type="acct")["commands"], [])

    def test_create_with_defaults(self):
        result = self.run_module(changed=True, address="*", port=1814)
        self.assertEqual(result["commands"], ["create freeradius_interface '*:1814', type='auth', ipversion='ipv4'"])
        self.assertEqual(self.entries()[2], dict(varinterfaceip="*", varinterfaceport="1814", varinterfacetype="auth", varinterfaceipversion="ipaddr"))
        self.assertIn(RESYNC, self.phpshell.call_args[0][0])

    def test_description_keeps_type(self):
        self.run_module(changed=True, address="127.0.0.1", port=1812, description="Local authentication")
        self.assertEqual(self.entries()[0]["varinterfacetype"], "auth")
        self.assertEqual(self.entries()[0]["description"], "Local authentication")

    def test_create_ipv6(self):
        self.run_module(changed=True, address="::1", port=1812, ipversion="ipv6", type="status")
        self.assertEqual(self.entries()[2], dict(varinterfaceip="::1", varinterfaceport="1812", varinterfacetype="status", varinterfaceipversion="ipv6addr"))

    def test_delete(self):
        result = self.run_module(changed=True, address="127.0.0.1", port=1813, state="absent")
        self.assertEqual(result["commands"], ["delete freeradius_interface '127.0.0.1:1813'"])
        self.assertEqual([entry["varinterfaceport"] for entry in self.entries()], ["1812"])
        self.assertIn(RESYNC, self.phpshell.call_args[0][0])
        self.run_module(address="127.0.0.1", port=1813, state="absent")

    def test_check_mode(self):
        self.run_module(changed=True, address="127.0.0.1", port=1813, type="acct", _ansible_check_mode=True)
        self.assertEqual([entry["varinterfacetype"] for entry in self.entries()], ["auth", "auth"])
        self.assertFalse(os.path.exists(self.backup_file))
        self.phpshell.assert_not_called()

    @parameterized.expand([
        ("address must not be empty", dict(address="", port=1812)),
        ("port must be between 1 and 65535", dict(address="127.0.0.1", port=0)),
        ("port must be between 1 and 65535", dict(address="127.0.0.1", port=65536)),
        ("address must be an IPv4 address", dict(address="::1", port=1812)),
        ("address must be an IPv6 address", dict(address="127.0.0.1", port=1812, ipversion="ipv6")),
        ("description may only contain", dict(address="127.0.0.1", port=1812, description="RADIUS <local>")),
    ])
    def test_invalid_option(self, msg, params):
        with set_module_args(params):
            self.assertIn(msg, self.failed()["msg"])
        self.assertFalse(os.path.exists(self.backup_file))

    @parameterized.expand([
        ("update", dict(type="acct")),
        ("delete", dict(state="absent")),
    ])
    def test_duplicate_entries(self, name, params):
        # The web GUI accepts a second entry on the same address and port: the module must not pick one of them
        self.write_config(PACKAGE + "<freeradiusinterfaces>{0}</freeradiusinterfaces>".format(
            ENTRY.format("127.0.0.1", "1813", "auth") + ENTRY.format("127.0.0.1", "1813", "status")))
        with set_module_args(dict(address="127.0.0.1", port=1813, **params)):
            self.assertEqual(self.failed()["msg"], "Found multiple entries for '127.0.0.1:1813'.")
        self.assertEqual([entry["varinterfacetype"] for entry in self.entries()], ["auth", "status"])
        self.assertFalse(os.path.exists(self.backup_file))
        self.phpshell.assert_not_called()

    def test_package_not_installed(self):
        self.write_config("")
        with set_module_args(dict(address="127.0.0.1", port=1813, type="acct")):
            self.assertIn("Unable to find package freeradius3", self.failed()["msg"])
