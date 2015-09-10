# vim: set expandtab sw=4 softtabstop=4 fileencoding=utf8 :
#
# Copyright 2015 Johan Ström
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

import collections

def resolve_keys(keys):
    """Expand keys to a list of tuples. For examples, please see GetterMixin
    or tests/test_ecollections.py"""
    if type(keys) == str:
        return [keys]

    if type(keys) == int:
        return [str(keys)]

    if type(keys) not in (tuple, list):
        raise Exception("Unknown keys format %s" % type(keys))

    if len(keys) == 0:
        raise Exception("Empty keys")

    # One string for each mutation will end up here
    res = []

    for part in keys:
        if part == None:
            continue

        if type(part) in (int, str):
            # Plain string/int, add to end of every known mutation
            if len(res) == 0:
                res.append(str(part))
            else:
                for n in range(len(res)):
                    res[n] += ':' + str(part)

        elif type(part) in (tuple, list):
            # More mutations
            if len(res) == 0:
                # First section of the key
                for variant in part:
                    if variant != None:
                        res.append(str(variant))
            else:
                # Subsequent section of the key(s)
                # For every existing mutation, create a clone for each new mutation,
                # and append the mutated part
                new = []
                for n in range(len(res)):
                    for m in range(len(part)):
                        if part[m] != None:
                            new.append(res[n] + ':' + part[m])
                res = new
        else:
            raise Exception("Unknown part type %s in keys" % str(part))

    return res

class GetterMixin(object):
    """ Mixin which assumes we have self.d as a dict or list"""

    def get(self, keys, default=None):
        """Locate a colon-delimited key from the YAML configuration
        dict, with options to try multiple keys.

        Parameter keys can be either a plain string, in which case that
        is the only key probed, or it can be a list of "items" to join into a key.
        Each item in the list can be either a plain string, or it can be a list itself,
        in which case it will be expanded to separate versions of the key to try.


        Examples:
            'section:option' will look for key 'section', which should be a dict
            with a key option. The value of that entry will be returned, if found.

            ('section', 'option') will do the exact same thing.

            (('section', 'fallback'), 'option') will first look at 'section:option', and if
            that is not found, it will try 'fallback:option'.

            ('root', ('section', 'fallback'), 'option') will look at
            'root:section:option', then 'root:fallback:option'.

            (('section', 'fallback'), 'option', ('a', 'b')) will look at
            'section:option:a', 'section:option:b', 'fallback:option:a', 'fallback:option:b'


        If no value for any key is found, the default returned.
        """
        keys = resolve_keys(keys)

        for key in keys:
            #print "Looking at ",key,
            data = traverse_dict_and_list(self.d, key, None)

            #print "found ",data
            if data != None:
                break

        if data == None:
            data = default

        if isinstance(data, str):
            # This is also a Sequence!
            return data
        elif isinstance(data, collections.Mapping):
            return EnhancedMapping(data)
        elif isinstance(data, collections.Sequence):
            return EnhancedSequence(data)

        return data

class EnhancedMapping(GetterMixin, collections.MutableMapping):
    """Wraps MutableMapping (dict) with 'get' decorator from GetterMixin"""
    def __init__(self, d):
        self.d = d

    def __getitem__(self, y):
        return self.d.__getitem__(y)

    def __setitem__(self, i, y):
        return self.d.__setitem__(i, y)

    def __delitem__(self, y):
        return self.d.__delitem__(y)

    def __iter__(self):
        return self.d.__iter__()

    def __len__(self):
        return self.d.__len__()

    def __repr__(self):
        return self.d.__repr__()

    def items(self):
        return self.d.items()

    def __eq__(self, other):
        return self.d.__eq__(other)


class EnhancedSequence(GetterMixin, collections.MutableSequence):
    """Wraps MutableSequence(list/tuple) with 'get' decorator from GetterMixin"""
    def __init__(self, d):
        self.d = d

    def __getitem__(self, y):
        return self.d.__getitem__(y)

    def __setitem__(self, i, y):
        return self.d.__setitem__(i, y)

    def insert(self, i, y):
        return self.d.insert(i, y)

    def __delitem__(self, y):
        return self.d.__delitem__(y)

    def __len__(self):
        return self.d.__len__()

    def __repr__(self):
        return self.d.__repr__()

    def __eq__(self, other):
        return self.d.__eq__(other)


# The following function is borrowed from https://github.com/saltstack/salt/blob/develop/salt/utils/__init__.py
#
#   Copyright 2014-2015 SaltStack Team
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.

DEFAULT_TARGET_DELIM = ':'

def traverse_dict_and_list(data, key, default, delimiter=DEFAULT_TARGET_DELIM):
    '''
    Traverse a dict or list using a colon-delimited (or otherwise delimited,
    using the 'delimiter' param) target string. The target 'foo:bar:0' will
    return data['foo']['bar'][0] if this value exists, and will otherwise
    return the dict in the default argument.
    Function will automatically determine the target type.
    The target 'foo:bar:0' will return data['foo']['bar'][0] if data like
    {'foo':{'bar':['baz']}} , if data like {'foo':{'bar':{'0':'baz'}}}
    then return data['foo']['bar']['0']
    '''
    for each in key.split(delimiter):
        if isinstance(data, list):
            try:
                idx = int(each)
            except ValueError:
                embed_match = False
                # Index was not numeric, lets look at any embedded dicts
                for embedded in (x for x in data if isinstance(x, dict)):
                    try:
                        data = embedded[each]
                        embed_match = True
                        break
                    except KeyError:
                        pass
                if not embed_match:
                    # No embedded dicts matched, return the default
                    return default
            else:
                try:
                    data = data[idx]
                except IndexError:
                    return default
        else:
            try:
                data = data[each]
            except (KeyError, TypeError):
                return default
    return data


