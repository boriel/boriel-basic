#!/usr/bin/env python
# -*- coding: utf-8 -*-
# vim: ts=4:et:sw=4:

# ----------------------------------------------------------------------
# Copyleft (K), Jose M. Rodriguez-Rosa (a.k.a. Boriel)
#
# This program is Free Software and is released under the terms of
#                    the GNU General License
# ----------------------------------------------------------------------

__all__ = [
    'ID_CLASSES', 'DEPRECATED_SUFFIXES', 'ID_TYPES',
    'TYPE_NAMES', 'NAME_TYPES', 'TYPE_SIZES', 'SUFFIX_TYPE',
    'PTR_TYPE'
]

# -------------------------------------------------
# Global constants
# -------------------------------------------------

# ----------------------------------------------------------------------
# Identifier Class (variable, function, label, array)
# ----------------------------------------------------------------------
ID_CLASSES = (
    'var',  # A scalar variable
    'function',  # A function or subroutine
    'label',  # A Label (usually used for GOTO or @label operator)
    'array'  # An array variable (A collection of values of the same type)
)

# ----------------------------------------------------------------------
# Deprecated suffixes for variable names, such as "a$"
# ----------------------------------------------------------------------
DEPRECATED_SUFFIXES = ('$', '%', '&')

# ----------------------------------------------------------------------
# Identifier type
# i8 = Integer, 8 bits
# u8 = Unsigned, 8 bits and so on
# ----------------------------------------------------------------------
ID_TYPES = ('i8', 'u8', 'i16', 'u16', 'i32', 'u32', 'fixed', 'float', 'string')
TYPE_NAMES = {
    'byte': 'i8', 'ubyte': 'u8', 'integer': 'i16', 'uinteger': 'u16',
    'long': 'i32', 'ulong': 'u32', 'fixed': 'fixed', 'float': 'float',
    'string': 'string'
}

# The reverse of above
NAME_TYPES = dict([(TYPE_NAMES[x], x) for x in TYPE_NAMES.keys()])

TYPE_SIZES = {
    'i8': 1, 'u8': 1, 'i16': 2, 'u16': 2, 'i32': 4, 'u32': 4,
    'fixed': 4, 'float': 5, 'string': 2, None: 0
}

# Maps suffix to types
SUFFIX_TYPE = {'$': 'string', '%': 'i16', '&': 'i32'}

# Platform dependant. This is the default (Z80).
PTR_TYPE = 'u16'

# ----------------------------------------------------------------------
# Internal constants. Don't touch unless you know what are you doing
# ----------------------------------------------------------------------
MIN_STRSLICE_IDX = 0      # Min. string slicing position
MAX_STRSLICE_IDX = 65534  # Max. string slicing position