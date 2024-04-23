"""
A routine to test the termination of all exchanges in a given database
"""
from antelope import NoReference
from antelope_core.archives import CheckTerms


class MissingAnchors(Exception):
    pass


def termination_test(query, prefer=None, strict=False):
    """

    :param query: a query that can implements inventory() and targets()
    :param prefer: a dict that maps flow external_refs to preferred providers
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
    missing = [af for af in ct.ambiguous_flows() if af.external_ref not in prefer.keys()]

    if len(missing) > 0:
        print('Found %d missing flows' % len(missing))
        for m in missing:
            print(m)
        if strict:
            raise MissingAnchors([m.external_ref for m in missing])
    return missing
