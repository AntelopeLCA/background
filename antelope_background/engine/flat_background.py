"""
class for storing static results of a tarjan ordering
"""

from scipy.sparse import csc_matrix, csr_matrix
from scipy.sparse.linalg import inv, factorized, spsolve
from scipy.sparse import eye
from scipy.io import savemat, loadmat

import os

from antelope import CONTEXT_STATUS_, comp_dir  # , num_dir
from antelope.models import UnallocatedExchange, Exchange
from .background_layer import BackgroundLayer, TermRef, ExchDef
from .background_engine import BackgroundEngine
from antelope_core import from_json, to_json


SUPPORTED_FILETYPES = ('.mat', )

_FLATTEN_AF = False


class NoLciDatabase(Exception):
    pass


def _iterate_a_matrix(a, y, threshold=1e-8, count=100, quiet=False, solver=None):
    if solver == 'spsolve':
        ima = eye(a.shape[0]) - a
        x = spsolve(ima, y)
        return csr_matrix(x).T
    y = csr_matrix(y)  # tested this with ecoinvent: convert to sparse: 280 ms; keep full: 4.5 sec
    total = csr_matrix(y.shape)
    if a is None:
        return total

    mycount = 0
    sumtotal = 0.0

    while mycount < count:
        total += y
        y = a.dot(y)
        inc = sum(abs(y).data)
        if inc == 0:
            if not quiet:
                print('exact result')
            break
        sumtotal += inc
        if inc / sumtotal < threshold:
            break
        mycount += 1
    if not quiet:
        print('completed %d iterations' % mycount)

    return total


def _unit_column_vector(dim, inx):
    return csr_matrix(((1,), ((inx,), (0,))), shape=(dim, 1))


def split_af(_af, _inds):
    """
    splits the input matrix into diagonal and off-diagonal portions, with the split being determined by _inds
    :param _af:
    :param _inds:
    :return:
    """
    _af = _af.tocoo()
    _r = _af.row
    _c = _af.col
    _d = _af.data
    _d_non = []
    _d_scc = []
    _shape = _af.shape
    for i in range(len(_d)):
        if _r[i] in _inds and _c[i] in _inds:
            _d_non.append(0)
            _d_scc.append(_d[i])
        else:
            _d_non.append(_d[i])
            _d_scc.append(0)
    _af_non = csc_matrix((_d_non, (_r, _c)), shape=_shape)
    _af_scc = csc_matrix((_d_scc, (_r, _c)), shape=_shape)
    assert (_af_non + _af_scc - _af).nnz == 0
    return _af_non, _af_scc


def _determine_scc_inds(ts):
    scc_inds = set()
    for _s in ts.nontrivial_sccs():
        if ts.is_background_scc(_s):
            continue
        for k in ts.scc(_s):
            scc_inds.add(ts.fg_dict(k.index))
    return scc_inds


def flatten(af, ad, bf, ts):
    """
    Accepts a fully populated background engine as argument

    :param af:
    :param ad:
    :param bf:
    :param ts:
    :return: af_flat, ad_flat, bf_flat
    """
    scc_inds = _determine_scc_inds(ts)

    non, scc = split_af(af, scc_inds)

    scc_inv = inv(eye(ts.pdim).tocsc() - scc)

    return non * scc_inv, ad * scc_inv, bf * scc_inv


ORDERING_SUFFIX = '.ordering.json.gz'


class FlatBackground(BackgroundLayer):
    """
    Static, ordered background stored in an easily serializable way
    """
    @classmethod
    def from_query(cls, query, quiet=True, preferred=None, **kwargs):
        """
        :param query: an index + exchange interface with operable processes(), terminate(), get() and inventory()
        :param quiet: passed to cls
        :param preferred: a preferred-provider dict as specified in BackgroundEngine init
        :param kwargs: passed to add_all_ref_products()
        :return:
        """
        be = BackgroundEngine(query, preferred=preferred)
        be.add_all_ref_products(**kwargs)
        flat = cls.from_background_engine(be, quiet=quiet)
        flat.map_contexts(query)
        return flat

    @classmethod
    def from_background_engine(cls, be, **kwargs):
        af, ad, bf = be.make_foreground()

        if _FLATTEN_AF:
            af, ad, bf = flatten(af, ad, bf, be.tstack)

        _map_nontrivial_sccs = {k: be.product_flow(k).process.external_ref for k in be.tstack.nontrivial_sccs()}

        def _make_term_ref(pf):
            try:
                _scc_id = _map_nontrivial_sccs[be.tstack.scc_id(pf)]
            except KeyError:
                _scc_id = 0
            return pf.flow.external_ref, pf.direction, pf.process.external_ref, _scc_id

        def _make_term_ext(em):
            """
            Here we decide to store contexts as '; '-concatenated strings -- which we must do bc it is serializable

            gets undone in map_context when we figure out which term_ref corresponds to which [canonical] context

            Note also the directionality here: comp_dir(em.direction)  em is coming from the BackgroundEngine so it
            is an Emission type, which is created from an exterior exchange using its native flow and direction [w/r/t
            the parent].  We take direction w.r.t. the context so the declaration is self-consistent, but that is not
            really sensible. But it's serialized. Thus we take comp-dir.

            Not investigated: whether problems arise when an exchange with a non-complementary context is used
            as the source for a BackgroundEngine emission, the BackgroundEngine is flattened, serialized to .mat, and
            deserialized for computation.  Not sure what the problem would be, but we should probably test it.
            [LciaResult negates value when it detects a conflicting exchange-context pairing.]

            :param em:
            :return:
            """
            ''' # <<< master
            try:
                comp = em.compartment[-1]
            except IndexError:
                comp = None
            return em.flow.external_ref, comp_dir(em.direction), comp, 0
            >>>>>>> preferred_product
            '''
            return em.flow.external_ref, comp_dir(em.direction), '; '.join(em.context.as_list()), 0  # serialize

        return cls([_make_term_ref(x) for x in be.foreground_flows(outputs=False)],
                   [_make_term_ref(x) for x in be.background_flows()],
                   [_make_term_ext(x) for x in be.emissions],
                   af, ad, bf,
                   lci_db=be.lci_db,
                   **kwargs)

    @classmethod
    def from_file(cls, file, **kwargs):
        ext = os.path.splitext(file)[1]
        if ext == '.mat':
            return cls.from_matfile(file, **kwargs)
        elif ext == '.hdf':
            return cls.from_hdf5(file, **kwargs)
        else:
            raise ValueError('Unsupported file type %s' % ext)

    @classmethod
    def from_hdf5(cls, fle, quiet=True):
        raise NotImplementedError

    @classmethod
    def from_matfile(cls, file, quiet=True):
        d = loadmat(file)
        if 'A' in d:
            lci_db = (d['A'].tocsr(), d['B'].tocsr())
        else:
            lci_db = None

        try:
            ordr = from_json(file + ORDERING_SUFFIX)
        except FileNotFoundError:  # legacy
            ordr = from_json(file + '.index.json.gz')

        '''
        def _unpack_term_ref(arr):
            _xt = arr[3][0]
            if len(_xt) == 1:
                _xt = _xt[0]
            return arr[0][0], arr[1][0][0], arr[2][0], _xt
        
        return cls((_unpack_term_ref(f) for f in d['foreground']),
                   (_unpack_term_ref(f) for f in d['background']),
                   (_unpack_term_ref(f) for f in d['exterior']),
                   d['Af'].tocsr(), d['Ad'].tocsr(), d['Bf'].tocsr(),
                   lci_db=lci_db,
                   quiet=quiet)
        '''
        return cls(ordr['foreground'], ordr['background'], ordr['exterior'],
                   d['Af'].tocsr(), d['Ad'].tocsr(), d['Bf'].tocsr(),
                   lci_db=lci_db,
                   quiet=quiet)

    context_map = None

    def map_contexts(self, index):
        self.context_map = dict()
        for k in self._ex:
            if k.term_ref not in self.context_map:
                term = tuple(k.term_ref.split('; '))  # de-serialize
                naive_context = index.get_context(term)
                canonical_context = index._tm[naive_context]  # not sure about this
                self.context_map[k.term_ref] = canonical_context

    def __init__(self, foreground, background, exterior, af, ad, bf, lci_db=None, quiet=True):
        """

        :param foreground: iterable of foreground Product Flows as TermRef params
        :param background: iterable of background Product Flows as TermRef params
        :param exterior: iterable of Exterior flows as TermRef params
        :param af: sparse, flattened Af
        :param ad: sparse, flattened Ad
        :param bf: sparse, flattened Bf
        :param lci_db: [None] optional (A, B) 2-tuple
        :param quiet: [True] does nothing for now
        """
        self._fg = tuple([TermRef(*f) for f in foreground])
        self._bg = tuple([TermRef(*x) for x in background])
        self._ex = tuple([TermRef(*x) for x in exterior])

        self._af = af
        self._ad = ad
        self._bf = bf

        if lci_db is None:
            self._A = None
            self._B = None
        else:
            self._A = lci_db[0].tocsr()
            self._B = lci_db[1].tocsr()

        self._lu = None  # store LU decomposition

        self._fg_index = {(k.term_ref, k.flow_ref): i for i, k in enumerate(self._fg)}
        self._bg_index = {(k.term_ref, k.flow_ref): i for i, k in enumerate(self._bg)}
        self._ex_index = {(k.term_ref, k.flow_ref, k.direction): i for i, k in enumerate(self._ex)}

        self._quiet = quiet

    def index_of(self, term_ref, flow_ref):
        key = (term_ref, flow_ref)
        if key in self._fg_index:
            return self._fg_index[key]
        elif key in self._bg_index:
            return self._bg_index[key]
        else:
            raise KeyError('Unknown termination %s, %s' % key)

    @property
    def _complete(self):
        return self._A is not None and self._B is not None

    @property
    def ndim(self):
        return len(self._bg)

    @property
    def pdim(self):
        return len(self._fg)

    @property
    def mdim(self):
        return len(self._ex)

    @property
    def fg(self):
        return self._fg

    @property
    def bg(self):
        return self._bg

    @property
    def ex(self):
        return self._ex

    def is_in_scc(self, process, ref_flow):
        if self.is_in_background(process, ref_flow):
            tr = self._bg[self._bg_index[(process, ref_flow)]]
        else:
            tr = self._fg[self._fg_index[(process, ref_flow)]]
        return len(tr.scc_id) > 0

    def is_in_background(self, process, ref_flow):
        return (process, ref_flow) in self._bg_index

    def foreground(self, process, ref_flow, traverse=False, exterior=False):
        """
        Most of the way toward making exchanges. yields a sequence of 5-tuples defining terminated exchanges.

        NOTE: traverse=True differs from the prior implementation because the old BackgroundEngine returned an Af
        matrix and the foreground routine generated one exchange per matrix entry.

        In contrast, the current implementation traverses the foreground and creates one exchange per traversal link.
        If a fragment references the same subfragment multiple times, this will result in redundant entries for the
        same fragment.  At the moment this is by design but it may be undesirable.

        An easy solution would be to keep a log of nonzero Af indices and 'continue' if one is encountered.
        :param process:
        :param ref_flow:
        :param traverse: [False] if True, generate one exchange for every traversal link. Default is to create one
        exchange for every matrix entry.  traverse=True will produce duplicate exchanges in cases where sub-fragments
        are traversed multiple times.
        :param exterior: [False] return entries for exterior flows
        :return:
        """
        if _FLATTEN_AF is False and traverse is True:
            print('Warning: traversal of foreground SCC will never terminate')

        index = self._fg_index[process, ref_flow]
        yield ExchDef(process, ref_flow, self._fg[index].direction, None, 1.0)

        cols_seen = set()
        cols_seen.add(index)

        q = [index]
        while len(q) > 0:
            current = q.pop(0)
            node = self._fg[current]
            fg_deps = self._af[:, current]
            rows, cols = fg_deps.nonzero()
            for i in range(len(rows)):
                assert cols[i] == 0  # 1-column slice
                if _FLATTEN_AF:
                    assert rows[i] > current  # well-ordered and flattened
                if rows[i] in cols_seen:
                    if traverse:
                        q.append(rows[i])  # allow fragment to be traversed multiple times
                else:
                    cols_seen.add(rows[i])
                    q.append(rows[i])
                term = self._fg[rows[i]]
                dat = fg_deps.data[i]
                if dat < 0:
                    dat *= -1
                    dirn = term.direction  # comp directions w.r.t. parent node
                else:
                    dirn = comp_dir(term.direction)  # comp directions w.r.t. parent node
                yield ExchDef(node.term_ref, term.flow_ref, dirn, term.term_ref, dat)

            bg_deps = self._ad[:, current]
            for dep in self._generate_exch_defs(node.term_ref, bg_deps, self._bg):
                yield dep

            if exterior:
                ems = self._bf[:, current]
                for ext in self._generate_em_defs(node.term_ref, ems):
                    yield ext

    @staticmethod
    def _generate_exch_defs(node_ref, data_vec, enumeration):
        rows, cols = data_vec.nonzero()
        assert all(cols == 0)
        for i in range(len(rows)):
            term = enumeration[rows[i]]
            dat = data_vec.data[i]
            if dat < 0:
                dat *= -1
                dirn = term.direction
            else:
                dirn = comp_dir(term.direction)
            yield ExchDef(node_ref, term.flow_ref, dirn, term.term_ref, dat)

    def _generate_em_defs(self, node_ref, data_vec):
        """
        Emissions have a natural direction which should not be changed.
        :param node_ref:
        :param data_vec:
        :return:
        """
        rows, cols = data_vec.nonzero()
        assert all(cols == 0)
        for i in range(len(rows)):
            term = self._ex[rows[i]]
            dat = data_vec.data[i]
            dirn = comp_dir(term.direction)
            if CONTEXT_STATUS_ == 'compat':
                _term = None
            else:
                _term = self.context_map.get(term.term_ref)
            yield ExchDef(node_ref, term.flow_ref, dirn, _term, dat)

    def generate_ems_by_index(self, process, ref_flow, m_index):
        if self.is_in_background(process, ref_flow):
            index = self._bg_index[process, ref_flow]
            ems = self._B[:, index]
        else:
            index = self._fg_index[process, ref_flow]
            ems = self._bf[:, index]

        for i in m_index:
            term = self._ex[i]
            dat = ems[i, 0]
            dirn = comp_dir(term.direction)
            cx = self.context_map.get(term.term_ref)
            yield ExchDef(process, term.flow_ref, dirn, cx, dat)

    def consumers(self, process, ref_flow):
        idx = self.index_of(process, ref_flow)
        if self.is_in_background(process, ref_flow):
            for i in self._ad[idx, :].nonzero()[1]:
                yield self._fg[i]
            for i in self._A[idx, :].nonzero()[1]:
                yield self._bg[i]
        else:
            for i in self._af[idx, :].nonzero()[1]:
                yield self._fg[i]

    def emitters(self, flow_ref, direction, context=None):
        """
        We have to test whether our serialized context matches the canonical one that was submitted. we also want to
        internalize context serialization (search term: '; ')
        :param flow_ref:
        :param direction:
        :param context: (canonical, "of query")
        :return:
        """
        yielded = set()
        for idx, ex in enumerate(self.ex):  # termination, flow_ref, direction
            if ex.flow_ref != flow_ref:
                continue
            if direction:
                if ex.direction != direction:
                    continue
            if context:
                if self.context_map.get(ex.term_ref) != context:
                    continue
            # found an eligible external flow
            for i in self._bf[idx, :].nonzero()[1]:
                yielded.add(self._fg[i])
            for i in self._B[idx, :].nonzero()[1]:
                yielded.add(self._bg[i])
        for rx in yielded:
            yield rx

    def dependencies(self, process, ref_flow):
        if self.is_in_background(process, ref_flow):
            index = self._bg_index[process, ref_flow]
            fg_deps = csr_matrix([])
            bg_deps = self._A[:, index]
        else:
            index = self._fg_index[process, ref_flow]
            fg_deps = self._af[:, index]
            bg_deps = self._ad[:, index]

        for x in self._generate_exch_defs(process, fg_deps, self._fg):
            yield x

        for x in self._generate_exch_defs(process, bg_deps, self._bg):
            yield x

    def exterior(self, process, ref_flow):
        if self.is_in_background(process, ref_flow):
            index = self._bg_index[process, ref_flow]
            ems = self._B[:, index]
        else:
            index = self._fg_index[process, ref_flow]
            ems = self._bf[:, index]

        for x in self._generate_em_defs(process, ems):
            yield x

    def _x_tilde(self, process, ref_flow, quiet=True, **kwargs):
        index = self._fg_index[process, ref_flow]
        return _iterate_a_matrix(self._af, _unit_column_vector(self.pdim, index), quiet=quiet, **kwargs)

    def ad(self, process, ref_flow, **kwargs):
        if self.is_in_background(process, ref_flow):
            for x in self.dependencies(process, ref_flow):
                yield x
        else:
            ad_tilde = self._ad.dot(self._x_tilde(process, ref_flow, **kwargs))
            for x in self._generate_exch_defs(process, ad_tilde, self._bg):
                yield x

    def bf(self, process, ref_flow, **kwargs):
        if self.is_in_background(process, ref_flow):
            for x in self.exterior(process, ref_flow):
                yield x
        else:
            bf_tilde = self._bf.dot(self._x_tilde(process, ref_flow, **kwargs))
            for x in self._generate_em_defs(process, bf_tilde):
                yield x

    def _compute_bg_lci(self, ad, solver=None, **kwargs):
        if solver == 'factorize':
            if self._lu is None:
                ima = eye(self._A.shape[0]) - self._A
                self._lu = factorized(ima.tocsc())
        if self._lu is None:
            bx = _iterate_a_matrix(self._A, ad, solver=solver, **kwargs)
        else:
            bx = csr_matrix(self._lu(ad.toarray().flatten())).T
        return self._B.dot(bx)

    def _compute_lci(self, process, ref_flow, **kwargs):
        if self.is_in_background(process, ref_flow):
            if not self._complete:
                raise NoLciDatabase
            ad = _unit_column_vector(self.ndim, self._bg_index[process, ref_flow])
            bx = self._compute_bg_lci(ad, **kwargs)
            return bx
        else:
            x_tilde = self._x_tilde(process, ref_flow, **kwargs)
            ad_tilde = self._ad.dot(x_tilde)
            bf_tilde = self._bf.dot(x_tilde)
            if self._complete:
                bx = self._compute_bg_lci(ad_tilde, **kwargs)
                return bx + bf_tilde
            else:
                return bf_tilde

    def lci(self, process, ref_flow, **kwargs):
        for x in self._generate_em_defs(process,
                                        self._compute_lci(process, ref_flow, **kwargs)):
            yield x

    @staticmethod
    def _check_dirn(term_ref, exch):
        if comp_dir(exch.direction) == term_ref.direction:
            return 1
        return -1

    def sys_lci(self, demand, quiet=None, **kwargs):
        """

        :param demand: an iterable of exchanges, each of which must be mapped to a foreground, interior, or exterior
        TermRef. The exchanges can either be proper exchanges, or ExchangeRefs, or UnallocatedExchange or
        AllocatedExchange models
        :param quiet: whether to silence debugging info
        :return:
        """
        node_ref = None

        fg_ind = []
        fg_val = []
        bg_ind = []
        bg_val = []
        ex_ind = []
        ex_val = []

        missed = []

        for exch in demand:

            if isinstance(exch, Exchange):  # the model
                x = exch
            else:
                x = UnallocatedExchange.from_inv(exch)

            if node_ref is None:  # just take the first one
                node_ref = x.process
            if x.type == 'context':
                missed.append(ExchDef(x.process, x.flow.external_ref, x.direction,
                                      tuple(x.context), x.value))
            elif x.termination is None:
                missed.append(ExchDef(x.process, x.flow.external_ref, x.direction, None, x.value))
            else:
                key = (x.termination, x.flow.external_ref)
                if key in self._fg_index:
                    ind = self._fg_index[key]
                    fg_ind.append(ind)
                    fg_val.append(x.value * self._check_dirn(self._fg[ind], x))
                elif key in self._bg_index:
                    ind = self._bg_index[key]
                    bg_ind.append(ind)
                    bg_val.append(x.value * self._check_dirn(self._bg[ind], x))
                else:
                    xd = ExchDef(x.process, key[1], x.direction, key[0], x.value)
                    if not quiet:
                        print('missed %s-%s-%s-%s-%s' % xd)
                    missed.append(xd)

        # compute ad_tilde  # csr_matrix(((1,), ((inx,), (0,))), shape=(dim, 1))
        x_dmd = csr_matrix((fg_val, (fg_ind, [0]*len(fg_ind))), shape=(self.pdim, 1))
        x_tilde = _iterate_a_matrix(self._af, x_dmd, quiet=True, **kwargs)
        ad_tilde = self._ad.dot(x_tilde).todense()
        bf_tilde = self._bf.dot(x_tilde).todense()

        # consolidate bg dependencies
        for i in range(len(bg_ind)):
            ad_tilde[bg_ind[i]] += bg_val[i]

        # compute b
        bx = self._compute_bg_lci(ad_tilde, quiet=quiet, **kwargs) + bf_tilde

        # consolidate direct emissions
        for i in range(len(ex_ind)):
            bx[ex_ind[i]] += ex_val[i]

        for x in self._generate_em_defs(node_ref, csr_matrix(bx)):
            yield x

        for x in missed:  #
            yield x

    def unit_scores(self, char_vector):
        """
        Returns the unit impact scores based on the supplied characterization vector
        :param char_vector:
        :return: sf, s -- unit scores for foreground and background
        """
        sf = char_vector * self._bf
        s = char_vector * self._B
        return sf, s

    def activity_levels(self, process, ref_flow, **kwargs):
        """
        Returns the background activity levels resulting from a unit of the designated process.

        :param process:
        :param ref_flow:
        :return: (xf, x) the foreground and background activity levels
        """
        if self.is_in_background(process, ref_flow):
            ad = _unit_column_vector(self.ndim, self._bg_index[process, ref_flow])
            xf = csr_matrix((1, self.pdim))
            x = _iterate_a_matrix(self._A, ad, **kwargs)
            return xf, x.transpose()
        else:
            xf = self._x_tilde(process, ref_flow, **kwargs)
            ad_tilde = self._ad.dot(xf)
            x = _iterate_a_matrix(self._A, ad_tilde, **kwargs)
            return xf.transpose(), x.transpose()

    def _write_ordering(self, filename):
        if not filename.endswith(ORDERING_SUFFIX):
            filename += ORDERING_SUFFIX

        ordr = {'foreground': [tuple(f) for f in self._fg],
                'background': [tuple(f) for f in self._bg],
                'exterior': [tuple(f) for f in self._ex]}
        to_json(ordr, filename, gzip=True)

    def _write_mat(self, filename, complete=True):
        d = {'Af': csr_matrix((self.pdim, self.pdim)) if self._af is None else self._af,
             'Ad': csr_matrix((self.ndim, self.pdim)) if self._ad is None else self._ad,
             'Bf': csr_matrix((self.mdim, self.pdim)) if self._bf is None else self._bf}
        if complete and self._complete:
            d['A'] = self._A
            d['B'] = self._B
        savemat(filename, d)

    def write_to_file(self, filename, complete=True):
        if filename.endswith(ORDERING_SUFFIX):
            filename = filename[:-len(ORDERING_SUFFIX)]
        filetype = os.path.splitext(filename)[1]
        if filetype not in SUPPORTED_FILETYPES:
            raise ValueError('Unsupported file type %s' % filetype)
        if filetype == '.mat':
            self._write_mat(filename, complete=complete)
        else:
            raise ValueError('Unsupported file type %s' % filetype)
        self._write_ordering(filename)
