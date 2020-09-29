# background
Background LCI implementation including Tarjan Ordering.

This is kept as a separate repo because it is the only place `numpy/scipy` is required.  The idea is to enable people to run LCI/A computations without having the background data on their machine or having to perform matrix construction and inversion (i.e. only using foreground computations, like GaBi does).

## Partial Ordering
The default implementation performs an ordering of the LCI database using Tarjan's algorithm for detecting strongly-connected components (see [Partial Ordering of Life Cycle Inventory Databases](https://doi.org/10.1007/s11367-015-0972-x))

It performs the ordering, and then builds and stores a static LCI database (A and B matrices).  This code is crusty, but it works.
