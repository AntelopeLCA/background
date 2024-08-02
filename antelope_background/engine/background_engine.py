"""
Tarjan's strongly connected components algorithm is recursive.  Python doesn't do well with deep recursion, so
we will re-implement the recursion as an iteration with a stack:
https://www.refactoring.com/catalog/replaceRecursionWithIteration.html

"""
import re  # for product_flows search

from collections import deque

import numpy as np
from scipy.sparse import csr_matrix  # , csc_matrix,

from antelope import comp_dir
from antelope.refs import ProcessRef
from antelope_core.contexts import NullContext

from .tarjan_stack import TarjanStack
from .product_flow import ProductFlow, NoMatchingReference
from .emission import Emission


class Marker:
    """
    Marker objects for interpreting the recursion queue
    """
    marker = None


class ParentMarker(Marker):
    """
    Used to mark the beginning of a new parent
    """
    marker = 'parent'


class RecurseMarker(Marker):
    """
    Used to mark the exchange that begins entry into recursion
    """
    marker = 'recurse'
    def __init__(self, term):
        self.term = term


class DequeError(Exception):
    """
    Something has gone wrong
    """
    pass


class RepeatAdjustment(Exception):
    pass


class TerminationError(Exception):
    """
    This indicates that an ambiguous termination was encountered, with no valid means to resolve the ambiguity
    """
    pass


class MatrixProto(object):
    """
    # Exchanges: parent = column; term = row;
    Value is modified to encode exchange direction: outputs must be negated at creation, inputs entered directly
    """
    def __init__(self, parent, value):
        assert isinstance(parent, ProductFlow)
        self._parent = parent
        self._value = value
        self._adjusted = False

    @property
    def parent(self):
        return self._parent

    @property
    def value(self):
        return self._value

    def adjust_val(self):
        if self._adjusted is False:
            self._value /= self.parent.inbound_ev
            self._adjusted = True
        else:
            raise RepeatAdjustment


class MatrixEntry(MatrixProto):
    def __init__(self, parent, term, value):
        assert isinstance(term, ProductFlow)
        super(MatrixEntry, self).__init__(parent, value)
        self._term = term

    @property
    def term(self):
        return self._term


class CutoffEntry(MatrixProto):
    """
    # Cutoffs: parent = column; emission = row of B includes direction information; value is entered unmodified
    """
    def __init__(self, parent, emission, value):
        assert isinstance(emission, Emission)
        super(CutoffEntry, self).__init__(parent, value)
        self._term = emission

    @property
    def emission(self):
        return self._term


class NoAllocation(Exception):
    pass


class BackgroundEngine(object):
    """
    Class for converting a collection of linked processes into a coherent technology matrix.
    """
    def __init__(self, query, quiet=True, preferred=None):
        """
        Construct an ordered background matrix from a query that implements basic, index and exchange.
        Required routes:
         B query.get() <- for all processes and flows
         I query.count('process')
         I query.processes() <- complete
         I flow.targets()
         B process.references()
         B process.reference(ref_flow)
         E process.inventory(ref_flow)

         process.__getitem__() <-- SpatialScope (only used in rare cases)

        :param query:
        :param quiet:
        :param preferred: a dict mapping flow external refs to their preferred processes (by external ref).
        The special entry None should map to a list of process external_refs that should be preferred whenever they
        are found (in the order of preference)
        """
        self.fg = query
        self._preferred_processes = {None: []}  # use to resolve termination errors. dict of flow_ref -> process
        if preferred:
            self._preferred_processes.update(preferred)
        self.missing_references = []
        self._quiet = quiet
        self._lowlinks = dict()  # dict mapping product_flow key to lowlink (int) -- which is key into TarjanStack.sccs

        self.tstack = TarjanStack()  # ordering of sccs

        # hold exchanges before updating component graph
        self._interior_incoming = []  # terminated entries -> added to the component graph
        self._cutoff_incoming = []  # entries with no termination -> emissions

        # _interior_incoming entries get sorted into:
        self._interior = []  # MatrixEntries whose parent (column) is background - A*
        self._foreground = []  # MatrixEntries whose parent is upstream of the background - Af + Ad
        self._bg_emission = []  # CutoffEntries whose parent is background - B*
        self._cutoff = []  # CutoffEntries whose parent is foreground - Bf

        self._product_flows = dict()  # maps product_flow.key to index-- being position in _pf_index
        self._pf_index = []  # maps index to product_flow in order added

        self._a_matrix = None  # includes only interior exchanges -- dependencies in _interior
        self._b_matrix = None  # SciPy.csc_matrix for bg only

        self._all_added = False

        self._r_stack = deque()  # recursion stack
        self._p_stack = list()  # recursion parents

        self._emissions = dict()  # maps emission key to index
        self._ef_index = []  # maps index to emission

    def _print(self, *args):
        if not self._quiet:
            print(*args)

    @property
    def lci_db(self):
        return self._a_matrix, self._b_matrix

    @property
    def mdim(self):
        return len(self._emissions)

    @property
    def emissions(self):
        return self._ef_index

    def index(self, product_flow):
        return self._product_flows[product_flow.key]

    def product_flow(self, index):
        return self._pf_index[index]

    def _lowlink(self, product_flow):
        return self._lowlinks[product_flow.key]

    def _add_product_flow(self, pf):
        self._product_flows[pf.key] = pf.index
        self._set_lowlink(pf, pf.index)
        self._pf_index.append(pf)
        self.tstack.add_to_stack(pf)

    def _rm_product_flow_children(self, bad_pf):
        """
        Used only to back-out the links in-progress when a TerminationError is encountered.
        This needs desperately to be tested. U
        :param bad_pf:
        :return:
        """
        self._r_stack.clear()
        while len(self._interior_incoming) > 0:
            pf = self.tstack.pop_from_stack()
            self._print('!!!removing %s' % pf)
            while 1:
                z = self._pf_index.pop()
                self._lowlinks.pop(z.key)
                self._product_flows.pop(z.key)
                if z is pf:
                    break
                self._print('--!removing %s' % z)
            while self._interior_incoming and self._interior_incoming[-1].parent is pf:
                self._interior_incoming.pop()
            while self._cutoff_incoming and self._cutoff_incoming[-1].parent is pf:
                self._cutoff_incoming.pop()
            if pf is bad_pf:
                break

    def _set_lowlink(self, pf, lowlink):
        """
        Sets lowlink to be the lower of the existing lowlink or the supplied lowlink
        :param pf:
        :param lowlink:
        :return:
        """
        if pf.key in self._lowlinks:
            existing = self._lowlinks[pf.key]
            self._lowlinks[pf.key] = min(existing, lowlink)
        else:
            self._lowlinks[pf.key] = lowlink

    def check_product_flow(self, flow, termination):
        """
        returns the product flow if it exists, or None if it doesn't
        :param flow:
        :param termination: the process whose reference flow is flow
        :return:
        """
        if termination is None:
            raise ValueError('Must supply a termination')
        k = (flow.external_ref, termination.external_ref)
        if k in self._product_flows:
            return self.product_flow(self._product_flows[k])
        else:
            return None

    def _create_product_flow(self, flow, term):
        """

        :param flow: actual flow or flow ref
        :param term: actual process or process ref
        :return:
        """
        index = len(self._pf_index)
        # term = self.fg.get(termination.external_ref)  # turn it into a catalog ref
        try:
            pf = ProductFlow(index, flow, term)
        except NoMatchingReference:
            print('### !!! NO MATCHING REFERENCE !!! ###')  # fix this if it comes up again
            if (term.external_ref, flow.external_ref) not in self.missing_references:
                self.missing_references.append((term.external_ref, flow.external_ref))
            return None
        self._add_product_flow(pf)
        return pf

    def _add_emission(self, flow, direction, context):
        cx = context or NullContext
        key = (flow.external_ref, direction, cx)
        if key in self._emissions:
            return self._ef_index[self._emissions[key]]
        else:
            index = len(self._ef_index)
            ef = Emission(index, flow, direction, cx)
            self._emissions[ef.key] = index
            self._ef_index.append(ef)
            return ef

    def terminate(self, exch, strategy) -> ProcessRef | None:
        """
        Find the ProductFlow that terminates a given exchange.  If an exchange has an explicit termination, use it.
        Else if flow / direction / term are already seen, use it.
        Else if flow is found in list of preferred providers, use designated provider (None -> cutoff)
        lastly, ask archive for valid targets. If this list has length != 1, defer to designated strategy or raise error
        :param exch:
        :param strategy:
        :return:
        """
        if isinstance(exch.termination, str):
            return self.fg.get(exch.termination)
        else:
            if (exch.flow.external_ref, exch.direction, exch.termination) in self._emissions:
                return None
            if exch.flow.external_ref in self._preferred_processes:
                term = self._preferred_processes[exch.flow.external_ref]
                if term is None:
                    return None
                if not hasattr(term, 'entity_type'):
                    term = self.fg.get(term)
                if term.entity_type != 'process':
                    raise TypeError('%s: Bad preferred provider %s' % (exch.flow.external_ref, term))
                return term

            terms = [t for t in self.fg.targets(exch.flow, direction=exch.direction)]
            if len(terms) == 0:
                return None
            elif len(terms) == 1:
                term = terms[0]
            else:
                t_map = {t.external_ref: t for t in terms}
                pref = self._preferred_processes[None]
                for p in pref:
                    if p in t_map:
                        return t_map[p]
                if strategy == 'abort':
                    print('flow: %s\nAmbiguous termination found for %s: %s' % (exch.flow.external_ref,
                                                                                exch.direction, exch.flow))
                    raise TerminationError
                elif strategy == 'first':
                    term = terms[0]
                elif strategy == 'last':
                    term = terms[-1]
                elif strategy == 'cutoff':
                    return None
                elif strategy == 'mix':
                    raise NotImplementedError('MIX not presently supported (for some reason)')
                    # return self.fg.mix(exch.flow, exch.direction)
                else:
                    raise KeyError('Unknown multi-termination strategy %s' % strategy)
            return term  # targets() returns refs- no need to get again

    @staticmethod
    def construct_sparse(nums, nrows, ncols):
        """

        :param nums:
        :param nrows:
        :param ncols:
        :return:
        """
        if len(nums) == 0:
            return csr_matrix((nrows, ncols))
        else:
            try:
                return csr_matrix((nums[:, 2], (nums[:, 0], nums[:, 1])), shape=(nrows, ncols))
            except IndexError:
                print('nrows: %s  ncols: %s' % (nrows, ncols))
                print(nums)
                raise

    def _construct_b_matrix(self):
        """
        b matrix only includes emissions from background + downstream processes.
        [foreground processes LCI will have to be computed the foreground way]
        :return:
        """
        if self._b_matrix is not None:
            raise ValueError('B matrix already specified!')
        num_bg = np.array([[co.emission.index, self.tstack.bg_dict(co.parent.index), co.value]
                           for co in self._bg_emission])
        self._b_matrix = self.construct_sparse(num_bg, self.mdim, self.tstack.ndim)

    def _pad_b_matrix(self):
        print('Growing B matrix from %d to %d rows' % (self._b_matrix.shape[0], self.mdim))
        bx_coo = self._b_matrix.tocoo()
        self._b_matrix = csr_matrix((bx_coo.data, (bx_coo.row, bx_coo.col)),
                                    shape=(self.mdim, self.tstack.ndim))

    def _construct_a_matrix(self):
        ndim = self.tstack.ndim
        num_bg = np.array([[self.tstack.bg_dict(i.term.index), self.tstack.bg_dict(i.parent.index), i.value]
                           for i in self._interior])
        self._a_matrix = self.construct_sparse(num_bg, ndim, ndim)

    '''required for create_flat_background
    '''
    def foreground_flows(self, search=None, outputs=True):
        for k in self.tstack.foreground_flows(outputs=outputs):
            if search is None:
                yield k
            else:
                if bool(re.search(search, str(k), flags=re.IGNORECASE)):
                    yield k

    def background_flows(self, search=None):
        for k in self.tstack.background_flows():
            if search is None:
                yield k
            else:
                if bool(re.search(search, str(k), flags=re.IGNORECASE)):
                    yield k

    '''
    def foreground_dependencies(self, product_flow):
        for fg in self._foreground:
            if fg.parent.index == product_flow.index:
                yield fg

    def foreground_emissions(self, product_flow):
        for co in self._cutoff:
            if co.parent.index == product_flow.index:
                yield co
    ''' # cut to here

    def foreground(self, pf):
        """
        Computes a list of indices for foreground nodes that are downstream of the named pf (inclusive).
        :param pf: ProductFlow OR ProductFlow.index
        :return: ordered list of product flows
        """
        if isinstance(pf, int):
            pf = self.product_flow(pf)
        if self.is_in_background(pf):
            return []
        return self.tstack.foreground(pf)

    def is_in_background(self, pf):
        """
        Tells whether a Product Flow OR index is part of the background SCC.
        :param pf: product_flow OR product_flow.index
        :return: bool
        """
        return self.tstack.is_background(pf)

    def make_foreground(self, product_flow=None):
        """
        make af, ad, bf for a given list of product flows, or entire if input list is omitted.
        :param product_flow: a single ProductFlow to generate the foreground. If omitted, generate entire foreground.
         if the product_flow is itself in the background, create a foreground model based on its inventory.
        :return: af, ad, bf sparse csc_matrixes

        Not dealing with cutoffs because they are out-of-band here. cutoffs belong to the Big Foreground, not to the
        little archive Foregrounds.  A background database with cutoffs will properly situate the cutoffs in the B
        matrix, where they are treated equivalently.
        """
        af_exch = []
        ad_exch = []
        fg_cutoff = []
        if product_flow is None:
            pdim = self.tstack.pdim

            def fg_dict(x):
                return self.tstack.fg_dict(x)

            bf_exch = self._cutoff
            if self.tstack.pdim == 0:
                return None, None, None
            for fg in self._foreground:
                if self.is_in_background(fg.term.index):
                    ad_exch.append(fg)
                else:
                    af_exch.append(fg)
        else:
            if self.is_in_background(product_flow):
                _af = self.construct_sparse([], 1, 1)
                bg_index = self.tstack.bg_dict(product_flow.index)
                _ad = self._a_matrix[:, bg_index]
                _bf = self._b_matrix[:, bg_index]
                return _af, _ad, _bf

            product_flows = self.foreground(product_flow)
            pdim = len(product_flows)
            bf_exch = []
            _fg_dict = dict((pf.index, n) for n, pf in enumerate(product_flows))

            def fg_dict(x):
                return _fg_dict[x]

            for fg in self._foreground:
                if fg.parent.index in _fg_dict:
                    if self.is_in_background(fg.term.index):
                        ad_exch.append(fg)
                    elif fg.term.index in _fg_dict:
                        af_exch.append(fg)
                    else:
                        fg_cutoff.append(fg)
            for co in self._cutoff:
                if co.parent.index in _fg_dict:
                    bf_exch.append(co)

        num_af = np.array([[fg_dict(i.term.index), fg_dict(i.parent.index), i.value] for i in af_exch])
        num_ad = np.array([[self.tstack.bg_dict(i.term.index), fg_dict(i.parent.index), i.value] for i in ad_exch])
        num_bf = np.array([[co.emission.index, fg_dict(co.parent.index), co.value] for co in bf_exch])
        ndim = self.tstack.ndim
        _af = self.construct_sparse(num_af, pdim, pdim)
        _ad = self.construct_sparse(num_ad, ndim, pdim)
        _bf = self.construct_sparse(num_bf, self.mdim, pdim)
        if len(fg_cutoff) > 0:
            for co in fg_cutoff:
                # this should never happen
                print('Losing FG Cutoff %s' % co)
        return _af, _ad, _bf

    def _update_component_graph(self):
        self.tstack.add_to_graph(self._interior_incoming)  # background should be brought up to date
        while len(self._interior_incoming) > 0:
            k = self._interior_incoming.pop()
            k.adjust_val()
            if self.is_in_background(k.parent.index):
                self._interior.append(k)
            else:
                self._foreground.append(k)

        while len(self._cutoff_incoming) > 0:
            k = self._cutoff_incoming.pop()
            k.adjust_val()
            if self.is_in_background(k.parent.index):
                self._bg_emission.append(k)
            else:
                self._cutoff.append(k)

        # if self.tstack.background is None:
        #     return

        if self._a_matrix is None:
            self._construct_a_matrix()
            self._construct_b_matrix()

        if self.mdim > self._b_matrix.shape[0]:
            self._pad_b_matrix()

        for k in self.missing_references:
            print('Missing reference (term:%s;flow:%s)' % k)
        self.missing_references = []

        # self.make_foreground()

    def add_all_ref_products(self, multi_term='abort', default_allocation=None):
        """

        :param multi_term:
        :param default_allocation:
        The list-of-2-tuples is tested in UsLciEcospoldTest; the legacy list-of-processes is tested in UsLciOlcaTest
        :return:
        """
        if self._all_added:
            return
        for p in self.fg.processes(count=self.fg.count('process')):
            for x in p.references():
                j = self.check_product_flow(x.flow, p)
                if j is None:
                    self._add_ref_product_deque(x.flow, p, multi_term, default_allocation)
        self._update_component_graph()
        self._all_added = True

    def add_ref_product(self, flow, term, multi_term='abort', default_allocation=None):
        """
        Here we are adding a reference product - column of the A + B matrix.  The termination must be supplied.
        :param flow: a product flow
        :param term: a process that includes the product flow among its reference exchanges (input OR output).
        :param multi_term: ['first'] specify how to handle ambiguous terminations.  Possible answers are:
         'cutoff' - call the flow a cutoff and ignore it
         'mix' - create a new "market" process that mixes the inputs
         'first' - take the first match (alphabetically by process name)
         'last' - take the last match (alphabetically by process name)
         'abort' - the default- do not allow a nondeterministic termination
        :param default_allocation: an LcQuantity to use for allocation if unallocated processes are encountered
        :return:
        """
        j = self.check_product_flow(flow, term)

        if j is None:
            j = self._add_ref_product_deque(flow, term, multi_term, default_allocation)

            self._update_component_graph()
        return j

    '''
    def _add_ref_product(self, flow, term, multi_term, default_allocation):
        j = self._create_product_flow(flow, term)
        if j is None:
            # _create_product_flow already prints a MissingReference message
            return
        try:
            self._traverse_term_exchanges(j, multi_term, default_allocation)
        except TerminationError:
            self._rm_product_flow_children(j)
            print('Termination Error: process %s: ref_flow %s, ' % (j.process.external_ref, j.flow.external_ref))

            raise

        return j

    def _traverse_term_exchanges(self, parent, multi_term, default_allocation):
        """
        Implements the Tarjan traversal
        :param parent: a ProductFlow
        :param default_allocation:
        :return:
        """
        rx = parent.process.reference(parent.flow)

        """ # this could never happen
        if not rx.is_reference:
            print('### Nonreference RX found!\nterm: %s\nflow: %s\next_id: %s' % (rx.process,
                                                                                  rx.flow,
                                                                                  rx.process.external_ref))
            rx = parent.process.reference()
            print('    using ref %s\n' % rx)
        """

        exchs = parent.process.inventory(ref_flow=rx)  # allocated exchanges

        for exch in exchs:
            if exch.is_reference:  # in parent.process.reference_entity:
                # we're done with the exchange
                raise TypeError('Reference exchange encountered in bg inventory %s' % exch)
            val = pval = exch.value  # allocated exchange

            # for interior flows-- enforce normative direction
            if exch.direction == 'Output':
                pval *= -1

            if val is None or val == 0:
                # don't add zero entries (or descendants) to sparse matrix
                continue
            if exch.flow == rx.flow and exch.direction == comp_dir(rx.direction) and\
                    val == 1.0 and exch.type == 'cutoff':
                # skip pass-thru flows
                print('Skipping pass-thru exchange: %s' % exch)
                continue

            # normal non-reference exchange. Either a dependency (if interior) or a cutoff (if exterior).
            term = self.terminate(exch, multi_term)
            if term is None:
                # cutoff -- add the exchange value to the exterior matrix
                emission = self._add_emission(exch.flow, exch.direction, exch.termination)  # check, create, and add
                self.add_cutoff(parent, emission, val)
                continue

            # so it's interior-- does it exist already?
            i = self.check_product_flow(exch.flow, term)
            if i is None:
                i = self._add_ref_product(exch.flow, term, multi_term, default_allocation)

                if i is None:
                    print('Cutting off at Parent process: %s\n%s -X- %s\n' % (parent.process.external_ref,
                                                                              exch.flow.name,
                                                                              term))
                    continue
                # carry back lowlink, if lower
                self._set_lowlink(parent, self._lowlink(i))
            elif self.tstack.check_stack(i):
                # visited and currently on stack - carry back index if lower
                self._set_lowlink(parent, self.index(i))
            else:
                # visited, not on stack- nothing to do
                pass
            # add the exchange value to the interior matrix
            self.add_interior(parent, i, pval)

        # name an SCC if we've found one
        if self._lowlink(parent) == self.index(parent):
            self.tstack.label_scc(self.index(parent), parent.key)
    '''

    def _add_ref_product_deque(self, flow, term, multi_term, default_allocation):
        if len(self._r_stack) != 0:
            raise DequeError('Recursion stack is not empty')
        j = self._create_product_flow(flow, term)
        if j is None:
            # _create_product_flow already prints a MissingReference message
            return

        self._dq_put_node_on_stack(j)

        while len(self._r_stack) > 0:
            try:
                self._dq_handle_stack(multi_term, default_allocation)
            except TerminationError:
                self._rm_product_flow_children(j)
                print('Termination Error: process %s: ref_flow %s, ' % (j.process.external_ref, j.flow.external_ref))

                raise

        return j

    def _dq_put_node_on_stack(self, parent):
        """
        The theory here is that we use both ends of the stack to keep track of what we are doing.
        The left-hand end is the recursion stack- we push things onto it as we traverse the graph
        the right-hand end is the parent stack- we use it to keep track of the parent nodes we have
        processed.  I suspect this will be equal to tstack._stack but I don't feel like investigating.

        When we push a new node onto the stack- we put the node on the right, and a marker object on the left.
        then we stack the exchanges on top of the marker object.
        When we have cleared the stack back to the marker object, we know we're done with the node.

        :param parent:
        :return:
        """
        self._r_stack.appendleft(ParentMarker())
        self._r_stack.append(parent)

        rx = parent.process.reference(parent.flow)
        exchs = parent.process.inventory(ref_flow=rx)  # allocated exchanges

        self._r_stack.extendleft(list(exchs))

    def _dq_handle_stack(self, multi_term, default_allocation):
        obj = self._r_stack[0]
        parent = self._r_stack[-1]

        if isinstance(obj, ParentMarker):
            """
            # we have exhausted a parent node's exchanges and arrived back at the node-- we check to see if we've
            discovered an SCC
            """
            # we have completed this parent node
            self._r_stack.popleft()  # the recursion marker
            parent = self._r_stack.pop()  # the parent node
            # name an SCC if we've found one
            if self._lowlink(parent) == self.index(parent):
                self.tstack.label_scc(self.index(parent), parent.key)
            # and we're done
            return

        elif isinstance(obj, RecurseMarker):
            """
            # we have completed recursion-- 
            The exchange that triggered recursion is next on the stack and we need to handle the parent's lowlink
            """
            # carry back lowlink, if lower
            marker = self._r_stack.popleft()
            i = marker.term
            self._set_lowlink(parent, self._lowlink(i))

            ''' # add interior
            '''
            exch = self._r_stack.popleft()

            pval = exch.value  # allocated exchange

            # for interior flows-- enforce normative direction
            if exch.direction == 'Output':
                pval *= -1

            self.add_interior(parent, i, pval)
            # and we're done
            return

        else:
            """
            # obj is an exchange
            We are in the middle of recursion, progressing through a child node's exchanges.  We proceed depending
            on each exchange's characteristics -- 
             - exterior--- is a recursive base case
             - interior, novel--- we must recurse
             - interior, on tarjan stack--- no recursion necessary but we have to update lowlink
             - interior, not on tarjan stack--- nothing to do
            """
            exch = self._r_stack[0]

            if exch.is_reference:  # in parent.process.reference_entity:
                raise TypeError('Reference exchange encountered in bg inventory %s' % exch)

            val = exch.value  # allocated exchange value

            if val is None or val == 0:
                # don't add zero entries (or descendants) to sparse matrix
                self._r_stack.popleft()
                return

            if exch.flow == parent.flow and exch.direction == comp_dir(parent.direction) and\
                    val == 1.0 and exch.type == 'cutoff':
                # skip pass-thru flows
                print('Skipping pass-thru exchange: %s' % exch)
                self._r_stack.popleft()
                return

            # normal non-reference exchange. Either a dependency (if interior) or a cutoff (if exterior).
            term = self.terminate(exch, multi_term)

            if term is None:
                # cutoff -- add the exchange value to the exterior matrix
                exch = self._r_stack.popleft()  # finished with this exchange
                emission = self._add_emission(exch.flow, exch.direction, exch.termination)  # check, create, and add
                self.add_cutoff(parent, emission, val)

            else:
                # interior exchange
                i = self.check_product_flow(exch.flow, term)

                if i is None:
                    # no product flow exists
                    i = self._create_product_flow(exch.flow, term)
                    if i is None:
                        # MissingReference cutoff
                        print('Cutting off at Parent process: %s\n%s -X- %s\n' % (parent.process.external_ref,
                                                                                  exch.flow.name,
                                                                                  term))
                        # we recourse to the cutoff procedure
                        exch = self._r_stack.popleft()  # finished with this exchange
                        emission = self._add_emission(exch.flow, exch.direction,
                                                      None)  # check, create, and add
                        self.add_cutoff(parent, emission, val)
                        return

                    # we leave the exchange on the stack, and recurse into the target node
                    self._r_stack.appendleft(RecurseMarker(i))
                    self._dq_put_node_on_stack(i)
                    return

                elif self.tstack.check_stack(i):
                    # visited and currently on stack - carry back index if lower
                    self._set_lowlink(parent, self.index(i))

                else:
                    # visited, not on stack- nothing to do with lowlink
                    pass

                self._r_stack.popleft()

                if exch.direction == 'Output':
                    val *= -1

                self.add_interior(parent, i, val)

    def add_cutoff(self, parent, emission, val):
        """
        Create an exchange for a cutoff flow (incl. elementary flows)
        :param parent: product flow- B matrix column
        :param emission: emission - B matrix row
        :param val: raw exchange value
        """
        self._cutoff_incoming.append(CutoffEntry(parent, emission, val))

    def add_interior(self, parent, term, val):
        """
        Enforces the convention that interior exchanges are inputs; reference flows are outputs; symmetrically to
        inbound_ev determination in ProductFlow constructore

        :param parent: product flow - A matrix column
        :param term: product flow - A matrix row
        :param val: raw (direction-adjusted) exchange value
        :return:
        """
        if parent is term:
            self._print('self-dependency detected! %s' % parent.process)
            parent.adjust_ev(val)
        else:
            self._interior_incoming.append(MatrixEntry(parent, term, val))
