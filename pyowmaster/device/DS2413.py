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
#
from pyowmaster.device.base import OwDevice
from pyowmaster.device.pio import *

def register(factory):
    factory.register("3A", DS2413)

CH_NAMES = ['A', 'B']
CH_IDS = {'A':0, 'B':1}

class DS2413(OwPIODevice):
    def __init__(self, ow, owid):
        super(DS2413, self).__init__(False, ow, owid)
        self.num_channels = 2

    def _ch_translate(self, ch):
        return CH_NAMES[ch]

    def _ch_translate_rev(self, ch):
        return CH_IDS[ch.upper()]

