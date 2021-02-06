# background
Background LCI implementation including Tarjan Ordering.

This is kept as a separate repo because it is the only place `numpy/scipy` is required.  The 
idea is to enable people to run LCI/A computations without having the background data on their 
machine or having to perform matrix construction and inversion (i.e. only using foreground 
computations, like GaBi does).

## Partial Ordering
The default implementation performs an ordering of the LCI database using Tarjan's algorithm 
for detecting strongly-connected components (see [Partial Ordering of Life Cycle Inventory 
Databases](https://doi.org/10.1007/s11367-015-0972-x))

It performs the ordering, and then builds and stores a static LCI database (A and B matrices).  
This code is a bit convoluted, but it works.

#### (Muttered question from the audience)

No, it isn't tested. Tests have been performed (and passed).

#### (indistinct grumbling)

I know. I'm sorry.

## Installing

Installation should be straightforward-- `lxml` is required here to access a local copy of ecoinvent.

    user@host$ pip install antelope_background lxml

### Setting up a catalog with ecoinvent data

    >>> from antelope_core import LcCatalog
    >>> from antelope_core.data_sources.ecoinvent import EcoinventConfig
    >>> cat = LcCatalog('/home/user/my_catalog')
    Loading JSON data from /home/b/my_catalog/reference-quantities.json:
    local.qdb: /home/b/my_catalog/reference-quantities.json
    local.qdb: /data/GitHub/lca-tools/lcatools/qdb/data/elcd_reference_quantities.json
    25 new quantity entities added (25 total)
    6 new flow entities added (6 total)
     
    >>> ec = EcoinventConfig('/path/to/ecoinvent')
    >>> for res in ec.make_resources('local.ecoinvent.3.7.1.cutoff'):
            cat.add_resource(res)
     
    >>> cat.show_interfaces()
    local.ecoinvent.3.7.1.cutoff [basic, exchange]
    local.qdb [basic, index, quantity]
     
    >>>

When the background is installed, new interface methods are available for catalog queries. In
order to access them, the background matrix must be constructed, which is done through
traversal of the LCI network using Tarjan's algorithm.  This is triggered automatically
any time you request a background interface method.  But it can also be triggered explicitly:


    >>> q = cat.query('local.ecoinvent.3.7.1.cutoff')
    >>> q.check_bg()
    ... # several minutes pass 
     Loaded 17400 processes (t=158.06 s)
     Loaded 17495 processes (t=158.69 s)
    20 new quantity entities added (20 total)
    5333 new flow entities added (5333 total)
    17495 new process entities added (17495 total)
    ...
    Creating flat background
    ...
     True
     
    >>> cat.show_interfaces()
    local.ecoinvent.3.7.1.cutoff [basic, exchange]
    local.ecoinvent.3.7.1.cutoff.index.20210205 [background, basic, index]
    local.qdb [basic, index, quantity]
     
    >>>

The `check_bg()` route is slow because it requires indexing the database and traversing all exchanges,
both of which require loading all XML files.  Fortunately, if the two steps are done during 
the same python session, then the inventory remains in memory and each file only has to be 
loaded once. 

Once the background matrix and index are created, the XML files do not need to be individually 
loaded except to access details about a specific process.  

Now that the background interface exists, background queries can be conducted.

# Contributing

Please do!
