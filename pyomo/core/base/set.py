#  _________________________________________________________________________
#
#  Pyomo: Python Optimization Modeling Objects
#  Copyright (c) 2014 Sandia Corporation.
#  Under the terms of Contract DE-AC04-94AL85000 with Sandia Corporation,
#  the U.S. Government retains certain rights in this software.
#  This software is distributed under the BSD License.
#  _________________________________________________________________________

__all__ = ['Set', 'set_options', 'simple_set_rule', 'SetOf']

from sys import exc_info
import logging

from pyutilib.misc.misc import flatten_tuple

from pyomo.common.deprecation import deprecated
from pyomo.common.errors import DeveloperError
from pyomo.core.base.component import ComponentData
from pyomo.core.base.misc import sorted_robust

logger = logging.getLogger('pyomo.core')

def process_setarg(arg):
    """
    Process argument and return an associated set object.

    This method is used by IndexedComponent
    """
    if isinstance(arg,_SetData):
        # Argument is a non-indexed Set instance
        return arg
    elif isinstance(arg,IndexedSet):
        # Argument is an indexed Set instance
        raise TypeError("Cannot index a component with an indexed set")
    elif isinstance(arg,Component):
        # Argument is some other component
        raise TypeError("Cannot index a component with a non-set "
                        "component: %s" % (arg.name))
    else:
        try:
            #
            # If the argument has a set_options attribute, then use
            # it to initialize a set
            #
            options = getattr(arg,'set_options')
            options['initialize'] = arg
            return Set(**options)
        except:
            pass
    # Argument is assumed to be an initialization function
    return Set(initialize=arg)


@deprecated('The set_options decorator seems nonessential and is deprecated')
def set_options(**kwds):
    """
    This is a decorator for set initializer functions.  This
    decorator allows an arbitrary dictionary of values to passed
    through to the set constructor.

    Examples:
        @set_options(dimen=3)
        def B_index(model):
            return [(i,i+1,i*i) for i in model.A]

        @set_options(domain=Integers)
        def B_index(model):
            return range(10)
    """
    def decorator(func):
        func.set_options = kwds
        return func
    return decorator


def simple_set_rule( fn ):
    """
    This is a decorator that translates None into Set.End.
    This supports a simpler syntax in set rules, though these can be
    more difficult to debug when errors occur.

    Example:

    @simple_set_rule
    def A_rule(model, i, j):
        ...
    """

    def wrapper_function ( *args, **kwargs ):
        value = fn( *args, **kwargs )
        if value is None:
            return Set.End
        return value
    return wrapper_function

# What do sets do?
#
# ALL:
#   __contains__
#   __len__ (Note: None for all infinite sets)
#
# Note: FINITE implies DISCRETE. Infinite discrete sets cannot be iterated
#
# FINITE: ALL +
#   __iter__, __reversed__
#   add()
#   sorted(), ordered()
#
# ORDERED: FINITE +
#   __getitem__
#   next(), prev(), first(), last()
#   ord()
#
# When we do math, the least specific set dictates the API of the resulting set.



# A trivial class that we can use to test if an object is a "legitimate"
# set (either SimpleSet, or a member of an IndexedSet)
class _SetData(ComponentData):
    """The base for all objects that can be used as a component indexing set.

    Derived versions of this class can be used as the Index for any
    IndexedComponent (including IndexedSet)."""
    __slots__ = tuple()

    def __contains__(self, idx):
        raise DeveloperError("Derived set class (%s) failed to "
                             "implement __contains__" % (type(self).__name__,))

    def __len__(self):
        return None

    def is_finite(self):
        """Return True if this is a finite discrete (iterable) Set"""
        return False

    def __eq__(self, other):
        if self is other:
            return True
        if isinstance(other, _SetData):
            other_is_finite = other.is_finite()
        else:
            other_is_finite = True
            try:
                other = set(other)
            except:
                pass
        if self.is_finite():
            if not other_is_finite:
                return False
            if len(self) != len(other):
                return False
            for x in self:
                if x not in other:
                    return False
            return True
        elif other_is_finite:
            return False
        return self.ranges() == other.ranges()

    def isdisjoint(self, other):
        # For efficiency, if the other is not a Set, we will try converting
        # it to a Python set() for efficient lookup.
        if isinstance(other, _SetData):
            other_is_finite = other.is_finite()
        else:
            other_is_finite = True
            try:
                other = set(other)
            except:
                pass
        if self.is_finite():
            for x in self:
                if x in other:
                    return False
            return True
        elif other_is_finite:
            for x in other:
                if x in self:
                    return False
            return True
        else:
            all(r.isdisjoint(s) for r in self.ranges() for s in other.ranges())

    def issubset(self, other):
        if isinstance(other, _SetData):
            other_is_finite = other.is_finite()
        else:
            other_is_finite = True
            try:
                other = set(other)
            except:
                pass
        if self.is_finite():
            for x in self:
                if x not in other:
                    return False
            return True
        elif other_is_finite:
            return False
        else:
            for r in self.ranges():
                if not any( r.issubset(s) for s in other.ranges() ):
                    return False
            return True

    def issuperset(self, other):
        # For efficiency, if the other is not a Set, we will try converting
        # it to a Python set() for efficient lookup.
        if isinstance(other, _SetData):
            other_is_finite = other.is_finite()
        else:
            other_is_finite = True
            try:
                other = set(other)
            except:
                pass
        if other_is_finite:
            for x in other:
                if x not in self:
                    return False
            return True
        elif self.is_finite():
            return False
        else:
            for r in self.ranges():
                if not any( s.issubset(r) for s in other.ranges() ):
                    return False
            return True

    def union(self, *args):
        """
        Return the union of this set with one or more sets.
        """
        tmp = self
        for arg in args:
            tmp = _SetUnion(tmp, arg)
        return tmp

    def intersection(self, *args):
        """
        Return the intersection of this set with one or more sets
        """
        tmp = self
        for arg in args:
            tmp = _SetIntersection(tmp, arg)
        return tmp

    def difference(self, *args):
        """
        Return the difference between this set with one or more sets
        """
        tmp = self
        for arg in args:
            tmp = _SetDifference(tmp, arg)
        return tmp

    def symmetric_difference(self, *args):
        """
        Return the symmetric difference of this set with one or more sets
        """
        tmp = self
        for arg in args:
            tmp = _SetSymmetricDifference(tmp, arg)
        return tmp

    def cross(self, *args):
        """
        Return the cross-product between this set and one or more sets
        """
        tmp = self
        for arg in args:
            tmp = _SetProduct(tmp, arg)
        return tmp

    # <= is equivalent to issubset
    # >= is equivalent to issuperset
    # |  is equivalent to union
    # &  is equivalent to intersection
    # -  is equivalent to difference
    # ^  is equivalent to symmetric_difference
    # *  is equivalent to cross

    __le__  = issubset
    __ge__  = issuperset
    __or__  = union
    __and__ = intersection
    __sub__ = difference
    __xor__ = symmetric_difference
    __mul__ = cross

    def __lt__(self,other):
        """
        Return True if the set is a strict subset of 'other'

        TODO: verify that this is more efficient than an explicit implimentation.
        """
        return self <= other and not self == other

    def __gt__(self,other):
        """
        Return True if the set is a strict superset of 'other'

        TODO: verify that this is more efficient than an explicit implimentation.
        """
        return self >= other and not self == other


class _InfiniteSet(_SetData):
    __slots__ = ('_ranges',)

    def __init__(self, *ranges):
        for r in ranges:
            if not isinstance(r, _InfiniteRange):
                raise TypeError(
                    "Arguments to _InfiniteSet must be _InfiniteRange objects")
        self._ranges = ranges

    def __contains__(self, val):
        for r in self._ranges:
            if val in r:
                return True
        return False

    def ranges(self):
        return self._ranges


class _FiniteSetMixin(object):
    __slots__ = ()

    def __reversed__(self):
        return reversed(self.__iter__())

    def is_finite(self):
        """Return True if this is a finite discrete (iterable) Set"""
        return True

    def sorted(self):
        return sorted_robust(self)

    def ordered(self):
        return self.sorted()



class _FiniteSetData(_SetData, _FiniteSetMixin):
    """A general unordered iterable Set"""
    __slots__ = ('_values', '_domain')

    def __init__(self, component, domain=None):
        super(_FiniteSetData, self).__init__(component)
        self._values = set()
        if domain is None:
            self._domain = Any
        else:
            self._domain = domain

    def __contains__(self, item):
        """
        Return True if the set contains a given value.
        """
        return item in self._values

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        """
        Return the number of elements in the set.
        """
        # Note tha the sorted status has no bearing on the number of items,
        # so there is no reason to check if the data is correctly sorted
        return len(self._values)

    def data(self):
        return tuple(self._values)

    def add(self, value):
        if self._domain is not None and value not in self._domain:
            raise ValueError("Cannot add value %s to set %s.\n"
                             "\tThe value is not in the Set's domain"
                             % (value, self.name,))
        value = flatten_tuple(value)
        try:
            if value in self._values:
                logger.warning(
                    "Element %s already exists in set %s; no action taken"
                    % (value, self.name))
            self._values.add(value)
        except:
            exc = exc_info()
            raise TypeError("Unable to insert '%s' into set %s:\n\t%s: %s"
                            % (value, self.name, exc[0].__name__, exc[1]))


class _OrderedSetMixin(_FiniteSetMixin):
    __slots__ = ()

    def first(self):
        return self[1]

    def last(self):
        return self[len(self)]

    def next(self, item, step=1):
        """
        Return the next item in the set.

        The default behavior is to return the very next element. The `step`
        option can specify how many steps are taken to get the next element.

        If the search item is not in the Set, or the next element is beyond
        the end of the set, then an IndexError is raised.
        """
        position = self.ord(item)
        return self[position+step]

    def nextw(self, item, step=1):
        """
        Return the next item in the set with wrapping if necessary.

        The default behavior is to return the very next element. The `step`
        option can specify how many steps are taken to get the next element.
        If the next element is past the end of the Set, the search wraps back
        to the beginning of the Set.

        If the search item is not in the Set an IndexError is raised.
        """
        position = self.ord(item)
        return self[(position+step-1) % len(self) + 1]

    def prev(self, item, step=1):
        """Return the previous item in the set.

        The default behavior is to return the immediately previous
        element. The `step` option can specify how many steps are taken
        to get the previous element.

        If the search item is not in the Set, or the previous element is
        before the beginning of the set, then an IndexError is raised.
        """
        return self.next(item, -step)

    def prevw(self, item, step=1):
        """Return the previous item in the set with wrapping if necessary.

        The default behavior is to return the immediately
        previouselement. The `step` option can specify how many steps
        are taken to get the previous element. If the previous element
        is past the end of the Set, the search wraps back to the end of
        the Set.

        If the search item is not in the Set an IndexError is raised.
        """
        return self.nextw(item, -step)


class _OrderedSetData(_FiniteSetData, _OrderedSetMixin):
    """
    This class defines the data for an ordered set.

    Constructor Arguments:
        component   The Set object that owns this data.

    Public Class Attributes:
    """

    __slots__ = ('_is_sorted','_ordered_values')
    _InsertionOrder = 1
    _Sorted = 2
    _SortNeeded = 3
    _DataOK = set([_InsertionOrder, _Sorted])


    def __init__(self, component):
        super(_OrderedSetData, self).__init__(component)
        self._values = {}
        self._ordered_values = []
        self._is_sorted = None

    def __iter__(self):
        """
        Return an iterator for the set.
        """
        if self._is_sorted not in self._DataOK:
            self._sort()
        return iter(self._ordered_values)

    def data(self):
        if self._is_sorted not in self._DataOK:
            self._sort()
        return tuple(self._ordered_values)

    def add(self, value):
        # Note tha the sorted status has no bearing on insertion,
        # so there is no reason to check if the data is correctly sorted
        if self._domain is not None and value not in self._domain:
            raise ValueError("Cannot add value %s to set %s.\n"
                             "\tThe value is not in the Set's domain"
                             % (value, self.name,))
        value = flatten_tuple(value)
        try:
            if value in self._values:
                logger.warning(
                    "Element %s already exists in set %s; no action taken"
                    % (value, self.name))
            else:
                self._values[value] = len(self._values)
                self._ordered_values.append(value)
                if self._is_sorted == self._Sorted:
                    self._is_sorted = self._SortNeeded
        except:
            exc = exc_info()
            raise TypeError("Unable to insert '%s' into set %s:\n\t%s: %s"
                            % (value, self.name, exc[0].__name__, exc[1]))

    def __getitem__(self, item):
        """
        Return the specified member of the set.

        The public Set API is 1-based, even though the
        internal _lookup and _values are (pythonically) 0-based.
        """
        if self._is_sorted not in self._DataOK:
            self._sort()
        if item >= 1:
            if item > len(self):
                raise IndexError("Cannot index a Set past the last element")
            return self._ordered_values[item-1]
        elif item < 0:
            if len(self)+item < 0:
                raise IndexError("Cannot index a Set before the first element")
            return self._ordered_values[item]
        else:
            raise IndexError("Valid index values for sets are 1 .. len(set) or -1 .. -len(set)")

    def ord(self, item):
        """
        Return the position index of the input value.

        Note that Pyomo Set objects have positions starting at 1 (not 0).

        If the search item is not in the Set, then an IndexError is raised.
        """
        if self._is_sorted not in self._DataOK:
            self._sort()
        try:
            return self._values[item] + 1
        except KeyError:
            raise IndexError(
                "Cannot identify position of %s in Set %s: item not in Set"
                % (item, self.name))

    def ordered(self):
        return self.data()

    def sorted(self):
        data = self.data()
        if self._is_sorted == self._Sorted:
            return data
        else:
            return sorted_robust(data)

    def _sort(self):
        if self._is_sorted is None:
            self._is_sorted = self.parent_component().ordering(self)
        if self._is_sorted == self._SortNeeded:
            self._ordered_values = sorted_robust(self._ordered_values)
            self._values = dict((j, i) for i, j in enumerate(self._ordered_values))
            self._is_sorted = self._Sorted

