# coding=utf-8
#
# This file is part of Hypothesis, which may be found at
# https://github.com/HypothesisWorks/hypothesis/
#
# Most of this work is copyright (C) 2013-2019 David R. MacIver
# (david@drmaciver.com), but it contains contributions by others. See
# CONTRIBUTING.rst for a full list of people who may hold copyright, and
# consult the git log if you need to determine who owns an individual
# contribution.
#
# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at https://mozilla.org/MPL/2.0/.
#
# END HEADER

from __future__ import absolute_import, division, print_function

import attr

from hypothesis.errors import Flaky
from hypothesis.internal.compat import hbytes, hrange
from hypothesis.internal.conjecture.data import DataObserver, Status


@attr.s()
class TreeNode(object):
    bits = attr.ib(default=attr.Factory(list))
    values = attr.ib(default=attr.Factory(list))
    transition = attr.ib(default=None)

    def split_at(self, i):
        child = TreeNode(
            bits=self.bits[i + 1 :],
            values=self.values[i + 1 :],
            transition=self.transition,
        )
        key = self.values[i]
        del self.values[i:]
        del self.bits[i + 1 :]
        assert len(self.values) == i
        assert len(self.bits) == i + 1
        self.transition = {key: child}


class DataTree(object):
    """Tracks the tree structure of a collection of ConjectureData
    objects, for use in ConjectureRunner."""

    def __init__(self, cap):
        self.cap = cap
        self.root = TreeNode()

    @property
    def is_exhausted(self):
        """Returns True if every possible node is dead and thus the language
        described must have been fully explored."""
        return False

    def generate_novel_prefix(self, random):
        """Generate a short random string that (after rewriting) is not
        a prefix of any buffer previously added to the tree."""
        return hbytes()

    def rewrite(self, buffer):
        """Use previously seen ConjectureData objects to return a tuple of
        the rewritten buffer and the status we would get from running that
        buffer with the test function. If the status cannot be predicted
        from the existing values it will be None."""
        return (buffer, None)

    def simulate_test_function(self, data):
        pass

    def new_observer(self):
        return TreeRecordingObserver(self)


def _is_simple_mask(mask):
    """A simple mask is ``(2 ** n - 1)`` for some ``n``, so it has the effect
    of keeping the lowest ``n`` bits and discarding the rest.

    A mask in this form can produce any integer between 0 and the mask itself
    (inclusive), and the total number of these values is ``(mask + 1)``.
    """
    return (mask & (mask + 1)) == 0


class TreeRecordingObserver(DataObserver):
    def __init__(self, tree):
        self.__tree = tree
        self.__current_node = tree.root
        self.__index_in_current_node = 0

    def draw_bits(self, n_bits, forced, value):
        i = self.__index_in_current_node
        self.__index_in_current_node += 1
        node = self.__current_node

        if i < len(node.bits):
            if n_bits != node.bits[i]:
                self.__inconsistent_generation()
        else:
            assert node.transition is None
            node.bits.append(n_bits)
        assert i < len(node.bits)
        if i < len(node.values):
            if value != node.values[i]:
                node.split_at(i)
                assert i == len(node.values)
                new_node = TreeNode()
                node.transition[value] = new_node
                self.__current_node = new_node
                self.__index_in_current_node = 0
        elif node.transition is None:
            node.values.append(value)
        else:
            try:
                self.__current_node = node.transition[value]
            except KeyError:
                self.__current_node = node.transition.setdefault(value, TreeNode())
            except TypeError:
                assert (
                    isinstance(node.transition, Status)
                    and node.transition != Status.OVERRUN
                )
                self.__inconsistent_generation()
            self.__index_in_current_node = 0

    def __inconsistent_generation(self):
        raise Flaky(
            "Inconsistent data generation! Data generation behaved differently "
            "between different runs. Is your data generation depending on external "
            "state?"
        )

    def conclude_test(self, status, interesting_origin):
        """Says that ``status`` occurred at node ``node``. This updates the
        node if necessary and checks for consistency."""
        if status == Status.OVERRUN:
            return
        i = self.__index_in_current_node
        node = self.__current_node

        if i < len(node.values) or isinstance(node.transition, dict):
            self.__inconsistent_generation()

        if node.transition is not None:
            if node.transition != status:
                raise Flaky(
                    "Inconsistent test results! Test case was %s on first run but %s on second"
                    % (existing.status.name, status)
                )
        else:
            node.transition = status
