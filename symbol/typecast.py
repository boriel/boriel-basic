#!/usr/bin/python
# -*- coding: utf-8 -*-
# vim: ts=4:et:sw=4:

# ----------------------------------------------------------------------
# Copyleft (K), Jose M. Rodriguez-Rosa (a.k.a. Boriel)
#
# This program is Free Software and is released under the terms of
#                    the GNU General License
# ----------------------------------------------------------------------

from symbol import Symbol
from number import Number
from gl import optemps



class TypeCast(Symbol):
    ''' Defines a typecast operation.
    '''
    def __init__(self, lineno, new_type, node):
        Symbol.__init__(self, new_type, 'CAST')
        self.t = optemps.new_t()
        self._type = new_type
        self.lineno = lineno
        self.node = node


    @classmethod
    def create(cls, lineno, new_type, node):
        ''' Creates a node containing the type cast of
        the given one. If new_type == node.type, then
        nothing is done, and the same node is
        returned.
    
        Returns None on failure (and calls syntax_error)
        '''
        if node is None:
            return None
    
        if new_type == node._type:
            return node
    
        if node._type == 'string':
            syntax_error(lineno, 'Cannot convert string to a value. Use VAL() function')
            return None
    
        if new_type == 'string':
            syntax_error(lineno, 'Cannot convert value to string. Use STR() function')
            return None
    
        if is_const(node.symbol):
            node = node.symbol.expr
    
        if not is_number(node):
            return cls(lineno, new_type, node)
    
        # It's a number. So let's convert it directly
        if node.token != 'NUMBER':
            if node._class == 'const':
                node = Number(node.lineno, node.value, node._type)
    
        if new_type not in ('i8', 'u8', 'i16', 'u16', 'i32', 'u32'): # not an integer
            node.value = float(node.value)
        else: # It's an integer
            new_val = int(node.value) & ((1 << (8 * TYPE_SIZES[new_type])) - 1) # Mask it
    
            if node.value >= 0 and new_val != node.value:
                warning_conversion_lose_digits(node.symbol.lineno)
                node.value = new_val
            elif node.value < 0 and (1 << (TYPE_SIZES[new_type] * 8)) + node.value != new_val:
                warning_conversion_lose_digits(node.symbol.lineno)
                node.value = new_val - (1 << (TYPE_SIZES[new_type] * 8))
    
        node._type = new_type
        node.t = node.value
    
        return node
    
    
