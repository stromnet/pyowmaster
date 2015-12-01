# vim: set expandtab sw=4 softtabstop=4 fileencoding=utf8 :

import unittest

from pyowmaster.owidutil import *

class OwIdUtilTest(unittest.TestCase):
    def test_owid_from_path(self):
        self.assertEquals(owid_from_path('10.CB310B000800'), '10.CB310B000800')
        self.assertEquals(owid_from_path('/10.CB310B000800'), '10.CB310B000800')
        self.assertEquals(owid_from_path('/uncached/10.CB310B000800'), '10.CB310B000800')
        self.assertEquals(owid_from_path('/uncached/10.CB310B000800/temperature'), '10.CB310B000800')
        self.assertEquals(owid_from_path('/uncached/alarm/10.CB310B000800'), '10.CB310B000800')

    def test_is_owid(self):
        self.assertTrue(is_owid('10.CB310B000800'))
        self.assertFalse(is_owid('/10.CB310B000800'))
        self.assertFalse(is_owid('/uncached/10.CB310B000800'))
#        self.assertFalse(is_owid('10.CB310B000800.0'))

    def test_parse_target(self):

        self.assertEquals(parse_target('10.CB310B000800.0'), ('10.CB310B000800', '0'))
        self.assertEquals(parse_target('10.CB310B000800.A'), ('10.CB310B000800', 'A'))
        self.assertEquals(parse_target('10CB310B000800.A'), ('10CB310B000800', 'A'))
        self.assertEquals(parse_target('10.CB310B000800'), ('10.CB310B000800', None))
        self.assertEquals(parse_target('F0.0BD2C6D4CC6D.port.1'), ('F0.0BD2C6D4CC6D', 'port.1'))
        self.assertEquals(parse_target('F0.0BD2C6D4CC6D.port.2'), ('F0.0BD2C6D4CC6D', 'port.2'))
        self.assertEquals(parse_target('somedev'), ('somedev', None))
        self.assertEquals(parse_target('somedev.A'), ('somedev', 'A'))
        self.assertEquals(parse_target('/Invalid/name/.A'), (None, None))
