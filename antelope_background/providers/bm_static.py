"""
LcArchive subclass that supports rich background computations by providing a FlatBackground implementation.
"""

import os
import time
from abc import ABC

from antelope_core.archives import LcArchive, InterfaceError
from ..engine.flat_background import FlatBackground, SUPPORTED_FILETYPES, ORDERING_SUFFIX
from ..background.implementation import TarjanBackgroundImplementation, TarjanConfigureImplementation
from .check_terms import termination_test


def _ref(obj):
    if obj is None:
        return obj
    if hasattr(obj, 'external_ref'):
        return obj.external_ref
    return str(obj)


class TarjanBackground(LcArchive, ABC):

    def __init__(self, source, save_after=False, engine=None, **kwargs):
        self._save_after = save_after
        self._prefer = {None: []}
        if source:
            if source.endswith(ORDERING_SUFFIX):
                source = source[:-len(ORDERING_SUFFIX)]  # prevent us from trying to instantiate from the ordering file

            filetype = os.path.splitext(source)[1]
            if filetype not in SUPPORTED_FILETYPES:
                raise ValueError('Unsupported filetype %s' % filetype)
        else:
            self._save_after = False

        '''
        if not source.endswith(self._filetype):
            source += self._filetype
        '''

        super(TarjanBackground, self).__init__(source, **kwargs)

        if source and os.path.exists(source):  # flat background already stored
            self._flat = FlatBackground.from_file(source)
        elif engine is not None:
            self._flat = FlatBackground.from_background_engine(engine)
        else:
            self._flat = None

    def prefer(self, flow, process):
        """
        Supply a reference flow (or external ref) and the preferred provider process (or external ref)
        If a process is to be preferred for *all* its flows, specify 'None' as the flow.

        :param flow: a reference flow (or external ref) or None
        :param process: a preferred process (or external ref)
        :return:
        """
        if flow is None:
            self._prefer[None].append(_ref(process))
        else:
            self._prefer[_ref(flow)] = _ref(process)

    def test_archive(self, query, strict=True):
        return termination_test(query, self._prefer, strict=strict)

    def make_interface(self, iface, privacy=None):
        if iface == 'background':
            return TarjanBackgroundImplementation(self)
        elif iface == 'configure':
            return TarjanConfigureImplementation(self)
        else:
            raise InterfaceError(iface)

    def _make_prefer_dict(self, prefer_arg, update=False):
        prefer_dict = {k: v for k, v in self._prefer.items()}
        if prefer_arg is not None:
            if isinstance(prefer_arg, dict):
                for k, v in prefer_arg.items():
                    if k is None:
                        prefer_dict[None].extend(_ref(z) for z in v)
                    else:
                        prefer_dict[_ref(k)] = _ref(v)
            elif hasattr(prefer_arg, '__iter__'):
                try:
                    for k, v in prefer_arg:
                        if k is None:
                            prefer_dict[None].extend(_ref(z) for z in v)
                        else:
                            prefer_dict[_ref(k)] = _ref(v)
                except ValueError:  # too many values to unpack
                    prefer_dict[None].extend(_ref(z) for z in prefer_arg)
            else:
                raise TypeError('Unable to parse preferred-provider specification')
        if update:
            self._prefer = prefer_dict
        return prefer_dict

    def create_flat_background(self, query, save_after=None, prefer=None, **kwargs):
        """
        Create an ordered background, save it, and instantiate it as a flat background
        :param query: interface to use for the engine
        :param save_after: trigger save-after (note: does not override init value)
        :param prefer: specify preferred providers.  Because I am so sloppy, this routine has been written to accept
         all kinds of possible formats for input:
         dict: { flow_ref: process* } un-terminated flow-ref prefers named process
           *- could be entity_type=process or external_ref of a process
         iterable of 2-tuples: [(flow_ref, process_ref), ...] .. un-terminated flow prefers named process
           *- for both of these, either flows or external_refs of flows can be passed as keys
           *- to prefer a process regardless of reference flow, use None as the flow_ref
         iterable of entries:
                 Because I am so sloppy, this routine has been written to accept all kinds of possible formats for input:
         dict: { flow_ref: process* } un-terminated flow-ref prefers named process
           *- could be entity_type=process or external_ref of a process
         iterable of 2-tuples: [(flow_ref, process_ref), ...] .. un-terminated flow prefers named process
           *- for both of these, either flows or external_refs of flows can be passed as keys
           *- to prefer a process regardless of reference flow, use None as the flow_ref
         list of processes: [process, ...] .. list of processes to prefer if an ambiguous match is encountered (legacy)
           * equivalent to a list of [(None, process), ...]

        :return:
        """
        if self._flat is None:
            prefer_dict = self._make_prefer_dict(prefer)
            print('Creating flat background')
            start = time.time()
            self._flat = FlatBackground.from_query(query, preferred=prefer_dict, **kwargs)
            self._add_name(query.origin, self.source, rewrite=True)
            print('Completed in %.3g sec' % (time.time() - start))
            if save_after or self._save_after:
                self.write_to_file()  # otherwise, the user / catalog must explicitly request it
        else:
            self._flat.map_contexts(query)
        return self._flat

    def reset(self):
        self._flat = None

    def write_to_file(self, filename=None, gzip=False, complete=True, domesticate=None, **kwargs):
        """

        :param filename:
        :param gzip: not used
        :param complete:
        :param domesticate: not used
        :param kwargs:
        :return:
        """
        if filename is None:
            filename = self.source
        self._flat.write_to_file(filename, complete=complete, **kwargs)
