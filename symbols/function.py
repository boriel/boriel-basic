#!/usr/bin/env python
# -*- coding: utf-8 -*-
# vim: ts=4:et:sw=4:

# ----------------------------------------------------------------------
# Copyleft (K), Jose M. Rodriguez-Rosa (a.k.a. Boriel)
#
# This program is Free Software and is released under the terms of
#                    the GNU General License
# ----------------------------------------------------------------------

from api.constants import CLASS
from var import SymbolVAR
from paramlist import SymbolPARAMLIST


class SymbolFUNCTION(SymbolVAR):
    ''' This class expands VAR top denote Function delaations
    '''
    def __init__(self, varname, lineno, offset=None):
        SymbolVAR.__init__(self, varname, lineno, offset, class_=CLASS.function)
        self.callable = True

    @classmethod
    def fromVAR(cls, entry, paramlist=None):
        ''' Returns this a copy of var as a VARFUNCTION
        '''
        result = cls(entry.name, entry.lineno, entry.offset)
        result.copy_attr(entry)  # This will destroy children

        if paramlist is None:
            paramlist = SymbolPARAMLIST()
        result.params = paramlist  # Regenerate them

        return result

    @property
    def params(self):
        return self.children[0]

    @params.setter
    def params(self, value):
        assert isinstance(value, SymbolPARAMLIST)
        if self.children:
            self.children[0] = value
        else:
            self.children = [value]

    @property
    def body(self):
        return self.children[1:]

    def __repr__(self):
        return 'FUNC:{}'.format(self.name)