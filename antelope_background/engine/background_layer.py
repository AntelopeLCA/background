from abc import ABC
from typing import Generator, Optional, Iterable
from collections import namedtuple

from antelope_core.contexts import Context


class TermRef(object):
    def __init__(self, flow_ref, direction, term_ref, scc_id=None):
        """

        :param flow_ref:
        :param direction: direction w.r.t. term
        :param term_ref:
        :param scc_id: None or 0 for singleton /emission; external_ref of a contained process for SCC
        """
        self._f = str(flow_ref)  # some flows were serialized with integer refs...
        self._d = {'Input': 0, 'Output': 1, 0: 0, 1: 1}[direction]
        # self._d = num_dir(direction)
        self._t = term_ref
        self._s = 0
        self.scc_id = scc_id

    @property
    def term_ref(self):
        return self._t

    @property
    def flow_ref(self):
        return self._f

    @property
    def direction(self):
        return ('Input', 'Output')[self._d]

    @property
    def scc_id(self):
        if self._s == 0:
            return []
        return self._s

    @scc_id.setter
    def scc_id(self, item):
        if item is None:
            self._s = 0
        else:
            self._s = item

    def __array__(self):
        return self.flow_ref, self._d, self.term_ref, self._s

    def __iter__(self):
        return iter(self.__array__())


"""
An ExchDef is a serialized exchange definition. It should contain:
.process = a string node ref
.flow = a string flow ref
.direction = a valid direction
.term = EITHER a string term_ref (interior flow) OR a tuple of strings (context) OR None (cutoff)
.value = float
"""
ExchDef = namedtuple('ExchDef', ('process', 'flow', 'direction', 'term', 'value'))


class BackgroundLayer(ABC):
    """
    the functions that are required by our background implementation
    """

    def map_contexts(self, index):
        """
        provide an index query that can resolve locally-cached context names to canonical contexts. the
        flat background will then create a map of local context to canonical context.

        :param index:
        :return:
        """
        raise NotImplementedError

    @property
    def fg(self) -> Generator[TermRef, None, None]:
        return NotImplemented

    @property
    def bg(self) -> Generator[TermRef, None, None]:
        return NotImplemented

    @property
    def ex(self) -> Generator[TermRef, None, None]:
        return NotImplemented

    def is_in_scc(self, process_ref: str, flow_ref: str) -> bool:
        raise NotImplementedError

    def is_in_background(self, process_ref: str, flow_ref: str) -> bool:
        raise NotImplementedError

    def foreground(self, process_ref: str, ref_flow: str, exterior=False) -> Generator[ExchDef, None, None]:
        raise NotImplementedError

    def consumers(self, process_ref: str, ref_flow: str) -> Generator[TermRef, None, None]:
        raise NotImplementedError

    def emitters(self, process_ref: str, ref_flow: str,
                 context: Optional[Context] = None) -> Generator[TermRef, None, None]:
        raise NotImplementedError

    def dependencies(self, process_ref: str, ref_flow: str) -> Generator[ExchDef, None, None]:
        raise NotImplementedError

    def exterior(self, process_ref: str, ref_flow: str) -> Generator[ExchDef, None, None]:
        raise NotImplementedError

    def ad(self, process_ref: str, ref_flow: str) -> Generator[ExchDef, None, None]:
        raise NotImplementedError

    def bf(self, process_ref: str, ref_flow: str) -> Generator[ExchDef, None, None]:
        raise NotImplementedError

    def lci(self, process_ref: str, ref_flow: str) -> Generator[ExchDef, None, None]:
        raise NotImplementedError

    def sys_lci(self, demand: Iterable) -> Generator[ExchDef, None, None]:
        raise NotImplementedError
