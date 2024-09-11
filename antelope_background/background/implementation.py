from antelope_core.implementations import BackgroundImplementation, CoreConfigureImplementation
from antelope import check_direction, comp_dir
from antelope.models import ExteriorFlow
from antelope_core.exchanges import ExchangeValue  # these should be ExchangeRefs?
from antelope_core.contexts import Context
from antelope_core.archives import ArchiveError
from antelope_core.implementations.quantity import QuantityConversionError, NoFactorsFound, CO2QuantityConversion
from antelope_core.lcia_results import LciaResult

from scipy.sparse import csr_matrix


class InvalidRefFlow(Exception):
    pass


class TarjanBackgroundImplementation(BackgroundImplementation):
    """
    This is the class that does the background interfacing work for partially-ordered databases.  The plumbing is
    pretty complicated so it deserves some explanation.

    The MRO for this is:
    (antelope_background.background.implementation.TarjanBackgroundImplementation,
    lcatools.implementations.background.BackgroundImplementation,
    lcatools.implementations.basic.BasicImplementation,
    lcatools.interfaces.ibackground.BackgroundInterface,
    lcatools.interfaces.abstract_query.AbstractQuery,
    object)

    So ultimately this is a query object that implements the background interface.

    The __init__ comes from the BasicImplementation, which requires an archive as first argument.  In the default
    BackgroundImplementation, this archive is used to generally provide all the entity data.  However, in the Tarjan
    background this is just a container for the FlatBackground lci calculator.  For that engine to work, it needs the
    catalog query that is provided in setup_bm().  This is baked in at BackgroundInterface

    the FlatBackground provides all necessary information-- which boils down to external_refs that can be
    looked up via the catalog / client code.

    The BackgroundImplementation subclasses BasicImplementation and adds an _index attribute.  This index is used for
    creating the flat background and also for accessing contexts when generating elementary exchanges.

    The necessary conditions to CREATE a flat Tarjan Background are: a valid [invertible] database with complete working
    index and inventory implementations. This flat background then gets serialized using a numpy [matlab] format, along
    with a separate index file as json.

    The necessary conditions to RESTORE a flat Tarjan Background are the serialization created above, and an index
    implementation for retrieving entities and contexts.
    """

    """
    basic implementation overrides
    """
    def __getitem__(self, item):
        return self._fetch(item)

    '''
    def _fetch(self, external_ref, **kwargs):
        return self._index.get(external_ref, **kwargs)

    '''
    def _fetch(self, external_ref, **kwargs):
        """
        we always get from the index implementation because we don't want to load every object just to refer to it
        :param external_ref:
        :param kwargs:
        :return:
        """
        ix_e = next(self._index._iface('index')).get(external_ref, **kwargs)
        return ix_e.make_ref(self._index)

    def get_canonical(self, quantity_ref):
        return self._index.get_canonical(quantity_ref)

    """
    background implementation
    """
    def __init__(self, *args, **kwargs):
        super(TarjanBackgroundImplementation, self).__init__(*args, **kwargs)

        self._flat = None

    def check_bg(self, reset=False, **kwargs):
        if self._flat is None or reset:
            if reset:
                self._archive.reset()
            if hasattr(self._archive, 'create_flat_background'):
                self._flat = self._archive.create_flat_background(self._index, **kwargs)
            else:
                raise ArchiveError('No create_flat_background: %s' % self._archive)  # how would we ever get here?
                # self._flat = FlatBackground.from_index(self._index, **kwargs)
        return True

    def _check_ref(self, arg, opt_arg):
        """
        Do argument handling.  Valid argument patterns:
        _check_ref(exchange) -> require is_reference, use process_ref and flow_ref
        _check_ref(process, <anything>) -> obtain process.reference(<anything>) and fall back to above
        :param arg:
        :param opt_arg:
        :return: two strings which are valid external refs: process_ref, flow_ref
        """
        self.check_bg()
        try:
            if isinstance(arg, str):
                process_ref = arg
                flow_ref = self.get(process_ref).reference(opt_arg).flow.external_ref
            elif hasattr(arg, 'entity_type'):
                if arg.entity_type == 'process':
                    process_ref = arg.external_ref
                    flow_ref = arg.reference(opt_arg).flow.external_ref
                elif arg.entity_type == 'exchange':
                    if not arg.is_reference:
                        raise ValueError('Exchange argument must be reference exchange')
                    process_ref = arg.process.external_ref
                    flow_ref = arg.flow.external_ref
                else:
                    raise TypeError('Cannot handle entity type %s (%s)' % (arg, arg.entity_type))
            else:
                raise TypeError('Unable to interpret input arg %s' % arg)
            return process_ref, flow_ref
        except StopIteration:
            raise InvalidRefFlow('process: %s\nref flow: %s' % (arg, opt_arg))

    '''
    def _product_flow_from_term_ref(self, tr):
        p = self[tr.term_ref]
        f = self[tr.flow_ref]
        return ProductFlow(self.origin, f, tr.direction, p, tr.scc_id)
    '''

    def _exchange_from_term_ref(self, tr):
        p = self[tr.term_ref]
        return p.reference(tr.flow_ref)

    def foreground_flows(self, search=None, **kwargs):
        self.check_bg()
        for fg in self._flat.fg:
            yield self._exchange_from_term_ref(fg)

    def background_flows(self, search=None, **kwargs):
        self.check_bg()
        for bg in self._flat.bg:
            yield self._exchange_from_term_ref(bg)

    def exterior_flows(self, search=None, **kwargs):
        self.check_bg()
        for ex in self._flat.ex:
            c = self._flat.context_map.get(ex.term_ref)
            f = self[ex.flow_ref]
            yield ExteriorFlow.from_background(f, comp_dir(ex.direction), c)  # serialization is opposite sense from API spec

    def is_in_scc(self, process, ref_flow=None, **kwargs):
        process, ref_flow = self._check_ref(process, ref_flow)
        return self._flat.is_in_scc(process, ref_flow)

    def is_in_background(self, process, ref_flow=None, **kwargs):
        process, ref_flow = self._check_ref(process, ref_flow)
        return self._flat.is_in_background(process, ref_flow)

    def foreground(self, process, ref_flow=None, exterior=False, **kwargs):
        process, ref_flow = self._check_ref(process, ref_flow)
        # parse args-- if exterior is True, force cutoffs and emissions to true
        # if exterior:
        #     cutoffs = emissions = exterior
        # else:  # otherwise, if user specifies either cutoffs or emissions, exterior is flipped to True
        #     exterior |= bool(cutoffs or emissions)
        for x in self._flat.foreground(process, ref_flow, exterior=exterior):
            # to filter cutoffs vs emissions, first need to detect if x is an exterior exchange-- which we don't know how to do just yet
            yield ExchangeValue(self[x.process], self[x.flow], x.direction, termination=x.term, value=x.value)

    def _direct_exchanges(self, process_ref, flow_ref, x_iter, corr=False):
        """
        This expects an iterable of ExchDefs, which are clearly redundant (only used for this)
        :param process_ref:
        :param flow_ref:
        :param x_iter:
        :return:
        """
        node = self[process_ref]
        inv_rx = bool(node.reference_value(flow_ref) < 0) and corr
        for x in x_iter:
            if inv_rx:
                dirn = comp_dir(x.direction)
                val = x.value * -1
            else:
                dirn = x.direction
                val = x.value
            yield ExchangeValue(node, self[x.flow], dirn, termination=x.term, value=val)

    def consumers(self, process, ref_flow=None, **kwargs):
        process, ref_flow = self._check_ref(process, ref_flow)
        for x in self._flat.consumers(process, ref_flow):
            yield self._exchange_from_term_ref(x)

    def emitters(self, flow, direction=None, context=None, **kwargs):
        """
        :param flow:
        :param direction: [None]
        :param context: should be canonical, if provided
        :param kwargs:
        :return:
        """
        self.check_bg()
        if direction is not None:
            direction = check_direction(direction)
        for x in self._flat.emitters(flow, direction, context):
            yield self._exchange_from_term_ref(x)

    def product_models(self, **kwargs):
        for fgf in self.foreground_flows(**kwargs):
            try:
                next(self.consumers(fgf.process, fgf.flow))
            except StopIteration:
                yield fgf

    def dependencies(self, process, ref_flow=None, **kwargs):
        process, ref_flow = self._check_ref(process, ref_flow)
        for x in self._direct_exchanges(process, ref_flow, self._flat.dependencies(process, ref_flow), corr=True):
            yield x

    def emissions(self, process, ref_flow=None, **kwargs):
        for x in self._exterior(process, ref_flow=ref_flow):
            if isinstance(x.termination, Context):
                if x.termination.elementary:
                    yield x

    def cutoffs(self, process, ref_flow=None, **kwargs):
        for x in self._exterior(process, ref_flow=ref_flow):
            if isinstance(x.termination, Context):
                if x.termination.elementary:
                    continue
            yield x

    def _exterior(self, process, ref_flow=None):
        process, ref_flow = self._check_ref(process, ref_flow)
        for x in self._direct_exchanges(process, ref_flow, self._flat.exterior(process, ref_flow)):
            yield x

    def ad(self, process, ref_flow=None, **kwargs):
        process, ref_flow = self._check_ref(process, ref_flow)
        for x in self._direct_exchanges(process, ref_flow, self._flat.ad(process, ref_flow), corr=True):
            yield x

    def bf(self, process, ref_flow=None, **kwargs):
        process, ref_flow = self._check_ref(process, ref_flow)
        for x in self._direct_exchanges(process, ref_flow, self._flat.bf(process, ref_flow)):
            yield x

    def lci(self, process, ref_flow=None, **kwargs):
        process, ref_flow = self._check_ref(process, ref_flow)
        for x in self._direct_exchanges(process, ref_flow, self._flat.lci(process, ref_flow, **kwargs)):
            yield x

    def sys_lci(self, demand, **kwargs):
        self.check_bg()
        node = None
        for x in self._flat.sys_lci(demand):
            if node is None:
                node = self[x.process]
            yield ExchangeValue(node, self[x.flow], x.direction, termination=x.term, value=x.value)

    def _get_quantity_conversion(self, q_ref, ex):
        f = self[ex.flow_ref]
        loc = f.locale
        cx = self._flat.context_map.get(ex.term_ref)
        qr = f.lookup_cf(q_ref, cx, loc)
        if isinstance(qr, QuantityConversionError):
            try:
                qr = qr.repair(f)
            except NoFactorsFound:
                pass
        if f.quell_co2:
            return CO2QuantityConversion.copy(qr)
        return qr

    def _add_lcia_component(self, res, term, node_weight, m_index, dense_qcs):
        key = term.term_ref, term.flow_ref
        comp = self[term.term_ref]
        sub_res = LciaResult(res.quantity)
        sub_res.add_component(term.term_ref, comp)
        dense_exch_defs = self._flat.generate_ems_by_index(term.term_ref, term.flow_ref, m_index)
        for i, x in enumerate(self._direct_exchanges(comp, term.flow_ref, dense_exch_defs)):
            sub_res.add_score(comp.external_ref, x, dense_qcs[i])
        res.add_summary(key, comp, node_weight, sub_res)

    def _add_lcia_summary(self, res, term, node_weight, unit_score):
        key = term.term_ref, term.flow_ref
        comp = self[term.term_ref]
        res.add_summary(key, comp, node_weight, unit_score)

    def deep_lcia(self, process, quantity_ref, ref_flow=None, detailed=False, **kwargs):
        process, ref_flow = self._check_ref(process, ref_flow)
        q_ref = self.get_canonical(quantity_ref)
        qcs = [self._get_quantity_conversion(q_ref, ex) for ex in self._flat.ex]
        char_vector = csr_matrix([k.value for k in qcs])
        _, nzc = char_vector.nonzero()
        dense_qcs = [qcs[k] for k in nzc]
        sf, s = self._flat.unit_scores(char_vector)
        xf, x = self._flat.activity_levels(process, ref_flow)

        res = LciaResult(q_ref)
        for i in range(self._flat.pdim):
            if xf[0, i] != 0:
                if sf[0, i] != 0:
                    term = self._flat.fg[i]
                    if detailed:
                        self._add_lcia_component(res, term, xf[0, i], nzc, dense_qcs)
                    else:
                        self._add_lcia_summary(res, term, xf[0, i], sf[0, i])

        for i in range(self._flat.ndim):
            if x[0, i] != 0:
                if s[0, i] != 0:
                    term = self._flat.bg[i]
                    if detailed:
                        self._add_lcia_component(res, term, x[0, i], nzc, dense_qcs)
                    else:
                        self._add_lcia_summary(res, term, x[0, i], s[0, i])

        return res


class TarjanConfigureImplementation(CoreConfigureImplementation):
    _config_options = ('prefer_provider',)

    def prefer_provider(self, flow_ref, process_ref=None):
        self._archive.prefer(flow_ref, process_ref)


