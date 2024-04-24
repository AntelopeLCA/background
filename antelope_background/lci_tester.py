"""
LCI Tester

This module will enable a user to test a background engine against a known-good LCI repository.
The module uses a catalog with a resource that implements the exchange, index, and background
interfaces.  The module will construct a BackgroundEngine using the exchange and index interfaces
and provide a diagnostic background implementation. The user can then use the diagnostic
implementation to execute arbitrary background methods against both the existing and the new
resources, reporting similarities and differences.
"""

from antelope import BackgroundInterface
from math import isclose

from random import random

from .providers import TarjanBackground


class LciTester(BackgroundInterface):

    @classmethod
    def test_background_engine(cls, query, engine, rel_tol=1e-8, **kwargs):
        """
        This uses an existing, already-
        :param query:
        :param engine:
        :param rel_tol:
        :param kwargs:
        :return:
        """
        ref = '.'.join(['test', query.origin])
        engine.add_all_ref_products(**kwargs)
        tarjan = TarjanBackground(None, ref, engine=engine)
        bi = tarjan.make_interface('background')
        bi.setup_bm(engine.fg)
        return cls(query, bi, rel_tol=rel_tol)

    @classmethod
    def test_flat_background(cls, query, preferred=None, rel_tol=1e-8, **kwargs):
        """
        Supply a query for a known-good implementation of basic, index, exchange, background.  The tester
        will produce a new background from current code with supplied arguments and use it to instantiate an
        LciTester.
        :param query:
        :param preferred: preferred-process specification to pass to background engine
        :return:
        """
        ref = '.'.join(['test', query.origin])
        tarjan = TarjanBackground(None, ref=ref)
        bi = tarjan.make_interface('background')
        bi.setup_bm(query)
        bi.check_bg(prefer=preferred, **kwargs)
        return cls(query, bi, rel_tol=rel_tol)

    @property
    def origin(self):
        return self._query.origin

    def make_ref(self, entity):
        raise NotImplementedError

    def _perform_query(self, itype, attrname, exc, *args, **kwargs):
        """
        we just return both sets of responses to method-specific evaluators
        :param itype:
        :param attrname:
        :param exc:
        :param args:
        :param kwargs:
        :return:
        """
        good = getattr(self._query, attrname)(*args, **kwargs)
        test = getattr(self._bi, attrname)(*args, **kwargs)
        return good, test

    @staticmethod
    def _rx_key(rx):
        return rx.process.external_ref, rx.flow.external_ref, rx.direction

    @staticmethod
    def _exch_key(exch):
        return exch.flow.external_ref, exch.direction, tuple(exch.termination)

    def _test_ref_exchanges(self, s1, s2):
        """
        Tests qualitative equivalence of two sets of *reference* exchanges (process, flow, direction).
        :param s1:
        :param s2:
        :return:
        """
        set1 = {self._rx_key(s) for s in s1}
        set2 = {self._rx_key(s) for s in s2}
        d1 = set1.difference(set2)
        d2 = set2.difference(set1)
        if len(d1) + len(d2) == 0:
            print('PASS (%d)' % len(set1))
        else:
            print('FAIL (%d,%d / %d)' % (len(d1), len(d2), len(set1)))
        return d1, d2

    def _test_exchanges(self, s1, s2):
        """
        Tests qualitative equivalence of two sets of *depenedent* exchanges (flow, direction, termination).
        Returns two sets: those present only in s1, those present only in s2
        :param s1:
        :param s2:
        :return:
        """
        set1 = {self._exch_key(s) for s in s1}
        set2 = {self._exch_key(s) for s in s2}
        d1 = set1.difference(set2)
        d2 = set2.difference(set1)
        if len(d1) + len(d2) == 0:
            print('PASS (%d)' % len(set1))
        else:
            print('FAIL (%d,%d / %d)' % (len(d1), len(d2), len(set1)))
        return d1, d2

    def _test_exchange_values(self, s1, s2):
        """
        The exchanges are unordered, so it's nontrivial to test two sets of results against one another.
        We use the approach of mapping (flow.external_ref, direction, termination) to exchange value.
        This is a summary test that compares the two sets and returns the entries in s2 that do NOT match
        the entry in s1 (key error qualifies as nonmatch)
        Thus a return value of length 0 indicates a passed test.
        :param s1:
        :param s2:
        :return: a list of failed exchanges, expressed as 2-tuples: (bad_exch, good_val) or (bad_exch, None)
        """
        c = {self._exch_key(x): x.value for x in s1}
        fail = []
        for s in s2:
            try:
                v = c[self._exch_key(s)]
                if not isclose(v, s.value, rel_tol=self.rel_tol):
                    fail.append((s, v))
            except KeyError:
                fail.append((s, None))
        if len(fail) == 0:
            print('PASS (%d)' % len(c))
        else:
            print('FAIL (%d / %d)' % (len(fail), len(c)))
        return fail

    def __init__(self, query, test, rel_tol=1e-8):
        """
        Supply a "known-good" query that implements the background interface, and a "test object" that is a background
        implementation.

        The object will run the same query on both the query and the test and then compare the results.

        :param query:
        :param test:
        """
        self._query = query
        self._bi = test
        self.rel_tol = rel_tol

    @property
    def random_process(self):
        n = self._query.count('process')
        i = int(random() * n)
        return next(self._query.processes(offset=i, count=1))

    def foreground_flows(self, search=None, **kwargs):
        good, test = super(LciTester, self).foreground_flows(search=search, **kwargs)
        return self._test_ref_exchanges(good, test)

    def background_flows(self, search=None, **kwargs):
        good, test = super(LciTester, self).background_flows(search=search, **kwargs)
        return self._test_ref_exchanges(good, test)

    def consumers(self, process, ref_flow=None, **kwargs):
        good, test = super(LciTester, self).consumers(process, ref_flow=ref_flow, **kwargs)
        return self._test_ref_exchanges(good, test)

    def exterior_flows(self, direction=None, search=None, **kwargs):
        good, test = super(LciTester, self).exterior_flows(direction=direction, search=search, **kwargs)
        return self._test_exchanges(good, test)

    def lci(self, process, ref_flow=None, **kwargs):
        good, test = super(LciTester, self).lci(process, ref_flow=ref_flow, **kwargs)
        return self._test_exchange_values(good, test)
