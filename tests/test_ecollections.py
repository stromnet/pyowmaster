# vim: set expandtab sw=4 softtabstop=4 fileencoding=utf8 :

import unittest

from pyowmaster.ecollections import *

class ResolveKeysTest(unittest.TestCase):
    def testSingleKey(self):
        self.assertEquals(resolve_keys('a:b'), ['a:b'])
        self.assertEquals(resolve_keys('a'), ['a'])
        self.assertEquals(resolve_keys(('a:b',)), ['a:b'])

    def testTupleKeys(self):
        self.assertEquals(resolve_keys(('a',)), ['a'])
        self.assertEquals(resolve_keys(('a', 'b')), ['a:b'])
        self.assertEquals(resolve_keys(('a', 'b:c', 'd')), ['a:b:c:d'])
        self.assertEquals(resolve_keys(['a', 'b:c', 'd']), ['a:b:c:d'])

    def testMultiKeys(self):
        self.assertEquals(resolve_keys((('a', 'b'),)), ['a', 'b'])
        self.assertEquals(resolve_keys((
            'x',
            ('a', 'b'),
            'c')),
            ['x:a:c', 'x:b:c'])

        self.assertEquals(resolve_keys((
            'x',
            ('a', 'b'),
            'c',
            ('1', '2'))),
            ['x:a:c:1', 'x:a:c:2',
             'x:b:c:1', 'x:b:c:2'])

        # A realistic use-case too..
        self.assertEquals(
            resolve_keys((('10.81239083289', 'DS18B20'), 'min_temp')),
            ['10.81239083289:min_temp', 'DS18B20:min_temp'])


class EnhancedMappingTest(unittest.TestCase):
    def testEmpty(self):
        d = EnhancedMapping({})
        self.assertEquals(len(d), 0)
        self.assertEquals(d.get('any'), None)
        self.assertEquals(d.get('0'), None)

    def testBasic(self):
        d = EnhancedMapping({'a':1, 'b': 2})
        self.assertEquals(len(d), 2)
        self.assertEquals(d.get('any'), None)
        self.assertEquals(d.get('a'), 1)
        self.assertEquals(d.get('b'), 2)

    def testNested(self):
        d = EnhancedMapping({'a':{'r':4}, 'b': [9,8,7]})
        self.assertEquals(len(d), 2)
        self.assertEquals(d.get('a'), {'r':4})

        # Ensure we get enhanced dicts in return
        self.assertIsInstance(d.get('a'), EnhancedMapping)
        self.assertEqual(d.get('b'), [9,8,7])

        # or sequecnes..
        self.assertIsInstance(d.get('b'), EnhancedSequence)
        self.assertEqual(d.get('b:0'), 9)

    def testFallbacks(self):
        d = EnhancedMapping({'a':{'r':4}, 'b': {'x':5, 'r':0}})
        self.assertEquals(d.get('a:r'), 4)
        self.assertEquals(d.get('a:x'), None)
        self.assertEquals(d.get('b:a'), None)
        self.assertEquals(d.get('a:x', 99), 99)
        self.assertEquals(d.get('b:a', 99), 99)
        self.assertEquals(d.get('b').get('a', 99), 99)
        self.assertEquals(d.get('b:x'), 5)
        self.assertEquals(d.get('b:r'), 0)
        self.assertEquals(d.get((('a','b'), 'x')), 5)
        self.assertEquals(d.get((('a','b'), 'r')), 4)


class EnhancedSequenceTest(unittest.TestCase):
    def testEmpty(self):
        d = EnhancedSequence([])
        self.assertEquals(len(d), 0)
        self.assertEquals(d.get('any'), None)
        self.assertEquals(d.get('0'), None)

    def testBasic(self):
        d = EnhancedSequence([1,2,3])
        self.assertEquals(len(d), 3)
        self.assertEquals(d.get('any'), None)
        self.assertEquals(d.get('0'), 1)
        self.assertEquals(d.get('1'), 2)

    def testNested(self):
        d = EnhancedSequence([1,{'a':2}, [3,4]])
        self.assertEquals(len(d), 3)
        self.assertEquals(d.get('0'), 1)
        self.assertEquals(d.get(0), 1)

        self.assertIsInstance(d.get('1'), EnhancedMapping)
        self.assertEqual(d.get('1'), {'a':2})
        self.assertEqual(d.get(1), {'a':2})

        self.assertEqual(d.get('1:a'), 2)

        self.assertIsInstance(d.get('2'), EnhancedSequence)
        self.assertEqual(d.get(2), [3,4])
        self.assertEqual(d.get('2'), [3,4])
        self.assertEqual(d.get('2:0'), 3)

    def testFallbacks(self):
        d = EnhancedSequence([1,{'a':2}, [3,4]])
        self.assertEquals(len(d), 3)
        self.assertEquals(d.get((('0', '1'),)), 1)

        self.assertEquals(d.get((('0', '1'),'a')), 2)
        self.assertEquals(d.get((('0', '2'), 1)), 4)
