# vim: set expandtab sw=4 softtabstop=4 fileencoding=utf8 :
#
# Copyright 2014-2015 Johan Ström
#
# This python package is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

import re

RE_DEV_ID = re.compile('([A-F0-9][A-F0-9]\.[A-F0-9]{12})')
RE_DEV_ALIAS = re.compile('([A-Za-z0-9\-\_]+)')

RE_DEV_CHANNEL = re.compile('([A-F0-9][A-F0-9]\.[A-F0-9]{12})\.([0-9AB])')
RE_ALIAS_CHANNEL = re.compile('([A-Za-z0-9\-\_]+)\.([0-9AB])')

def owid_from_path(id_or_path):
    """Tries to interpret an 1-Wire ID from a string"""
    m = RE_DEV_ID.search(id_or_path)
    if not m:
        return None

    return str(m.group(1))


def is_owid(id_or_path):
    """Checks if the given id (or path) is a proper 1-Wire ID"""
    return RE_DEV_ID.match(id_or_path) != None

def is_valid_alias(alias):
    """Checks if the given string is a valid alias"""
    return RE_DEV_ALIAS.match(alias) != None

def parse_target(tgt):
    """Tries to resolve a id + channel from a "target" string, where
    the id and channel are dot delimited.
    """
    m = RE_DEV_CHANNEL.match(tgt)
    if m:
        dev_id = m.group(1)
        ch = m.group(2)
    else:
        # Try with alias regexp
        m = RE_ALIAS_CHANNEL.match(tgt)
        if m:
            dev_id = m.group(1)
            ch = m.group(2)
        else:
            # Try with only id
            dev_id = owid_from_path(tgt)
            ch = None

            # If that wasn't an ID, try as plain alias
            if dev_id == None and is_valid_alias(tgt):
                dev_id = tgt

    return (dev_id, ch)


