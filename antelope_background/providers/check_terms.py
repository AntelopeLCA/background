"""
A routine to test the termination of all exchanges in a given database
"""
from antelope import NoReference
from antelope_core.archives import CheckTerms


class AmbiguousAnchors(Exception):
    pass


def termination_test(query, prefer=None, strict=False):
    """
    A utility that tests a query with an optional preferred-provider dictionary.
    Runs CheckTerms() on the query.
    Returns a list of all distinct flows whose terminations are ambiguous (after the preferred provider
    specification)

    :param query: a query that can implements inventory() and targets()
    :param prefer: a dict that maps flow external_refs to preferred providers
    :param strict: [False] if True, raise exception for ambiguous terminations
    """
    if prefer is None:
        prefer = dict()

    # first, validate preferred-providers
    for k, v in prefer.items():
        if v is None or v == []:
            continue
        try:
            query.get(v).reference(k)
        except NoReference:
            raise ValueError('Bad preferred provider %s for flow %s' % (v, k))

    ct = CheckTerms(query)
    ambiguous = [af for af in ct.ambiguous_flows() if af.external_ref not in prefer.keys()]

    if len(ambiguous) > 0:
        print('Found %d ambiguous flows' % len(ambiguous))
        for m in ambiguous:
            print(m)
        if strict:
            raise AmbiguousAnchors([m.external_ref for m in ambiguous])
    return ambiguous
