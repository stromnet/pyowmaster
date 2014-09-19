# vim: set expandtab sw=4 softtabstop=4 fileencoding=utf8 :

import unittest

from pyowmaster import idFromPath

class PyOwmasterTest(unittest.TestCase):
    def testIdFromPath(self):
        self.assertEquals(idFromPath('10.CB310B000800'), '10.CB310B000800')
        self.assertEquals(idFromPath('/10.CB310B000800'), '10.CB310B000800')
        self.assertEquals(idFromPath('/uncached/10.CB310B000800'), '10.CB310B000800')
        self.assertEquals(idFromPath('/uncached/10.CB310B000800/temperature'), '10.CB310B000800')
        self.assertEquals(idFromPath('/uncached/alarm/10.CB310B000800'), '10.CB310B000800')

