#!/usr/bin/python
# -*- coding: utf-8 -*-
# vim: ts=4:et:sw=4:

# ----------------------------------------------------------------------
# Copyleft (K), Jose M. Rodriguez-Rosa (a.k.a. Boriel)
#
# This program is Free Software and is released under the terms of
#                    the GNU General License
# ----------------------------------------------------------------------

import ply.yacc as yacc
from options import OPTIONS

from zxblex import tokens
import zxblex
import zxbpplex

from ast import Ast
from symbol import Symbol
from backend import Quad, OpcodesTemps, REQUIRES

# PI Constant
# PI = 3.1415927 is ZX Spectrum PI representation
# But a better one is 3.141592654
import math
from math import pi as PI
import sys


# Output stream
ERROR_output = sys.stderr

DEFAULT_TYPE = 'float'
DEFAULT_IMPLICIT_TYPE = 'auto' # Use 'auto' for smart type guessing
DEFAULT_MAX_SYNTAX_ERRORS = 20

FILENAME = ''    # name of current file being parsed

# ----------------------------------------------------------------------
# Number of parser (both syntatic & semantic) errors found. If not 0
# at the end, no asm output will be emitted.
# ----------------------------------------------------------------------
has_errors = 0 # Number of errors
has_warnings = 0 # Number of warnings

# ----------------------------------------------------------------------
# Identifier type
# i8 = Integer, 8 bits
# u8 = Unsigned, 8 bits and so on
# ----------------------------------------------------------------------
ID_TYPES = ('i8', 'u8', 'i16', 'u16', 'i32', 'u32', 'fixed', 'float', 'string')
TYPE_NAMES = { 'byte': 'i8', 'ubyte': 'u8', 'integer': 'i16', 'uinteger': 'u16', 'long': 'i32',
            'ulong': 'u32', 'fixed': 'fixed', 'float': 'float', 'string': 'string'}

NAME_TYPES = dict([(TYPE_NAMES[x], x) for x in TYPE_NAMES.keys()]) # The reverse of above

TYPE_SIZES = {'i8': 1, 'u8': 1, 'i16': 2, 'u16': 2, 'i32': 4, 'u32': 4,
             'fixed': 4, 'float': 5, 'string': 2, None: 0 }

# Deprecated suffixes for variable names, such as "a$"
DEPRECATED_SUFFIXES = ('$', '%', '&')

# ----------------------------------------------------------------------
# Identifier Class (variable, function, label, array)
# ----------------------------------------------------------------------
ID_CLASSES = ('var', 'function', 'label', 'array')

# ----------------------------------------------------------------------
# Internal constants. Don't touch unless you know what are you doing
# ----------------------------------------------------------------------

MIN_STRSLICE_IDX = 0     # Min. string slicing position
MAX_STRSLICE_IDX = 65535 # Max. string slicing position


# ----------------------------------------------------------------------
# Compilation flags
#
# optimization -- Optimization level. Use -O flag to change.
# case_insensitive -- Whether user identifiers are case insensitive
#                          or not
# array_base -- Default array lower bound
# param_byref --Default paramameter passing. TRUE => By Reference
# ----------------------------------------------------------------------
OPTIONS.add_option_if_not_defined('optimization', int, 0)
OPTIONS.add_option_if_not_defined('case_insensitive', bool, False)
OPTIONS.add_option_if_not_defined('array_base', int, 0)
OPTIONS.add_option_if_not_defined('byref', bool, False)
OPTIONS.add_option_if_not_defined('max_syntax_errors', int, DEFAULT_MAX_SYNTAX_ERRORS)
OPTIONS.add_option_if_not_defined('string_base', int, 0)


# ----------------------------------------------------------------------
# PUSH / POP loops for taking into account which nested-loop level
# the parser is in. Each element of the list must be a t-uple. And
# each t-uple must have at least one element (a string), which contains
# which kind of loop the parser is in: e.g. 'FOR', 'WHILE', or 'DO'.
# Nested loops are appended at the end, and popped out on loop exit.
# ----------------------------------------------------------------------
LOOPS = []

# ----------------------------------------------------------------------
# Each new scope push the current LOOPS state and reset LOOPS. Upon
# scope exit, the previous LOOPS is restored and popped out of the
# META_LOOPS stack.
# ----------------------------------------------------------------------
META_LOOPS = []

# ----------------------------------------------------------------------
# Function level entry ID in which ambit we are in. If the list
# is empty, we are at global scope
# ----------------------------------------------------------------------
FUNCTION_LEVEL = []

# ----------------------------------------------------------------------
# Function calls pending to check
# Each scope pushes (prepends) an empty list
# ----------------------------------------------------------------------
FUNCTION_CALLS = []

# ----------------------------------------------------------------------
# Initialization routines to be called automatically at program start
# ----------------------------------------------------------------------
INITS = set([])

# ----------------------------------------------------------------------
# Defined user labels. They all are prepended _label_. Line numbers 10,
# 20, 30... are in the form: __label_10, __label_20, __label_30...
# ----------------------------------------------------------------------
LABELS = {}


# ----------------------------------------------------------------------
# True if we're in the middle of a LET sentence. False otherwise.
# ----------------------------------------------------------------------
LET_ASSIGNEMENT = False

# ----------------------------------------------------------------------
# True if PRINT sentence has been used.
# ----------------------------------------------------------------------
PRINT_IS_USED = False


# ----------------------------------------------------------------------
# Symbol table. Each id level will push a new symbol table
# ----------------------------------------------------------------------
class SymbolTable(object):
    ''' Implements a symbol table
    '''
    def __init__(self):
        ''' Initializes the S.T.
        '''
        self.table = [{}] # New levels will push dictionaries
        self.mangle = ''  # Prefix for local variables
        self.mangles = [] # Mangles stack
        self.size = 0     # Size (in bytes) of variables
        self.caseins = [{}] # Case insensitive identifiers


    def get_id_entry(self, id, scope = None):
        ''' Returns the ID entry stored in self.table, starting
        by the first one. Returns None if not found.

        If scope is not None, only the given scope is searched.
        '''
        if id[-1] in DEPRECATED_SUFFIXES:
            id = id[:-1] # Remove it

        idL = id.lower()

        if scope is not None:
            if len(self.table) > scope:
                if id in self.table[scope].keys():
                    return self.table[scope][id]

                if idL in self.caseins[scope].keys():
                    return self.caseins[scope][idL]

            return None

        for i in range(len(self.table)):
            try:
                self.table[i][id]
                return self.table[i][id]
            except KeyError:
                pass

            try:
                self.caseins[i][idL]
                return self.caseins[i][idL]
            except KeyError:
                pass

        return None


    def declare_id(self, id, lineno):
        ''' Check there is no 'id' already declared in the current scope, and
            creates and returns it. Otherwise, returns None,
            and the caller function raises the syntax/semantic error.
        '''
        id2 = id
        if id2[-1] in DEPRECATED_SUFFIXES:
            id2 = id2[:-1] # Remove it

        # Try-except is faster than IN
        try:
            self.table[0][id2] # Checks if already declared
            return None
        except KeyError:
            pass

        try:
            self.caseins[0][id2.lower()] # Checks for case insensitive
            return None
        except KeyError:
            pass

        entry = self.table[0][id2] = SymbolID(id, lineno)
        entry.callable = None  # True for function, strings or arrays. False for any other
        entry.forwarded = False # True for a function header
        entry._mangled = '%s_%s' % (self.mangle, entry.id) # Mangled name
        entry.caseins = OPTIONS.case_insensitive.value

        if entry.caseins:
            self.caseins[0][id2.lower()] = entry

        return entry


    def create_id(self, id, lineno):
        ''' Check there is no 'id' already declared in the current scope.
        If it does exists raises an error. Otherwise creates and returns it.
        '''
        result = self.declare_id(id, lineno)
        if result is None:
            if id not in self.table[0].keys(): # is it case insensitive?
                id = id.lower()

            syntax_error(lineno, 'Duplicated identifier "%s" (previous one at %s:%i)' %
                (id, self.table[0][id].filename, self.table[0][id].lineno))

        return result


    def get_or_create(self, id, lineno, scope = None):
        ''' Returns the ID entry if stored in self.table,
        otherwise, creates a new one.
        '''
        entry = self.get_id_entry(id, scope)
        if entry is not None:
            return entry

        return self.create_id(id, lineno)


    def check_declared(self, id, lineno, _classname = 'variable'):
        ''' Checks if the given id is already defined in any scope
            or raises a Syntax Error.

            Note: _classname is not the class attribute, but the name of
            the class as it would appear on compiler messages.
        '''
        result = self.get_id_entry(id)
        if result is None or not result.declared:
            syntax_error(lineno, 'Undeclared %s "%s"' % (_classname, id))
            return None

        return result


    def check_class(self, id, _class, lineno, scope = None):
        ''' Check the id is either undefined or defined as a
        the given class.
        '''
        if _class not in ID_CLASSES:
            syntax_error(lineno, 'INTERNAL ERROR: Invalid class "%s". Please contact the autor(s).' % _class)

        entry = self.get_id_entry(id, scope)
        if entry is None or entry._class is None:
            return True

        if entry._class != _class:
            if entry._class == 'array':
                a1 = 'n'
            else:
                a1 = ''

            if _class == 'array':
                a2 = 'n'
            else:
                a2 = ''

            syntax_error(lineno, "identifier '%s' is a%s %s, not a%s %s" % (id, a1, entry._class, a2, _class))
            return False

        return True


    def start_function_body(self, funcname):
        ''' Start a new variable ambit.
        '''
        global LOOPS

        self.mangles.append(self.mangle)
        self.mangle = '%s_%s' % (self.mangle, funcname)
        self.table.insert(0, {})   # Prepends new symbol table
        self.caseins.insert(0, {}) # Prepends caseins dictionary
        META_LOOPS.append(LOOPS)
        LOOPS = []


    def end_function_body(self):
        ''' Ends a function body and pops old symbol table.
        '''
        global LOOPS


        def entry_size(entry): 
            ''' For local variables and params, returns the real variable or local array size in bytes
            '''
            if entry.scope == 'global' or entry.alias is not None: # aliases and global variables = 0
                return 0

            result = entry.size
            if (entry._class != 'array'):
                return result

            for bound in entry.bounds.next:
                result *= (bound.symbol.upper - bound.symbol.lower + 1)

            result += 1 + 2 * len(entry.bounds.next) # Bytes for the array header

            return result


        def sortentries(entries):
            ''' Sort in-place entries according to it sizes in ascending order
            '''
            for i in range(len(entries)):
                tmp = entries[i]
                size = entry_size(tmp)
                I = i

                for j in range(i + 1, len(entries)):
                    tmp1 = entries[j]
                    size1 = entry_size(tmp1)
                    if size > size1:
                        tmp = tmp1
                        size = size1
                        I = j

                entries[I], entries[i] = entries[i], entries[I]

        self.offset = 0
        entries = self.table[0].values()
        sortentries(entries)

        for entry in entries: # Symbols of the current level
            if entry._class is None:
                self.move_to_global_scope(entry.id)

            if entry._class == 'function': continue

            if entry._class == 'var' and entry.scope == 'local': # Local variables offset
                if entry.alias is not None: # Is it an alias of another declared variable?
                    if entry.offset is None:
                        entry.offset = entry.alias.offset
                    else:
                        entry.offset = entry.alias.offset - entry.offset
                else:
                    self.offset += entry_size(entry)
                    entry.offset = self.offset

            if entry._class == 'array' and entry.scope == 'local':
                entry.offset = entry_size(entry) + self.offset
                self.offset = entry.offset


        self.mangle = self.mangles.pop()
        self.table.pop(0)
        self.caseins.pop(0)
        LOOPS = META_LOOPS.pop()

        return self.offset


    def move_to_global_scope(self, id):
        ''' If the given id is in the current scope, and there is more than 1 scope,
        move the current id to the global scope and make it global. Labels need
        this.
        '''
        if id in self.table[0].keys() and len(self.table) > 1: # In the current scope and more than 1 scope?
            self.table[-1][id] = self.table[0][id]
            self.table[-1][id].offset = None
            self.table[-1][id].scope = 'global'
            del self.table[0][id] # Removes it from the current scope


    def make_static(self, id):
        ''' The given ID in the current scope is changed to 'global', but the variable remains in the
        current scope, if it's a 'global private' variable: A variable private to a function
        scope, but whose contents are not in the stack, but in the global variable area.
        These are called 'static variables' in C.

        A copy of the instance, but mangled, is also allocated in the global symbol table.
        '''
        entry = self.table[0][id]
        entry.scope = 'global'
        self.table[-1][entry._mangled] = entry


    def make_id(self, id, lineno, scope = None):
        ''' Checks whether the id exist or not.
        If it exist, returns it, otherwise, create it.
        Scope is related to which scope to search in the SYMBOL TABLE. If scope
        is None, all of them (from inner to outer) will be searched.
        '''
        return self.get_or_create(id, lineno, scope)


    def make_var(self, id, lineno, default_type = None, scope = None):
        ''' Checks whether the id exist or not.
        If it exists, it must be a variable (not a function, array, constant, or label)
        '''
        if not self.check_class(id, 'var', lineno, scope):
            return None

        entry = self.get_or_create(id, lineno, scope)

        if entry.declared == True:
            return entry

        entry._class = 'var' # Make it a variable
        entry.callable = False

        if entry._mangled[-1] == '$': # A string variable?
            entry._type = 'string' # Ok. We know it's a string
            entry._mangled = entry._mangled[:-1]
            entry.id = entry.id[:-1]
        elif entry._mangled[-1] == '%': # An integer variable
            entry._type = 'i16' # Ok. We know it's a 16 bit signed integer
            entry._mangled = entry._mangled[:-1]
            entry.id = entry.id[:-1]

        if entry._type == 'string' and entry.scope == 'global':
            entry.t = entry._mangled
        else:
            entry.t = optemps.new_t()

        if entry._type is None: # First time used?
            if default_type is None:
                default_type = DEFAULT_TYPE
                warning(lineno, "Variable '%s' declared as '%s'" % (id, default_type))

            entry._type = default_type # Default type is unknown

        entry.scope = 'local' if len(self.table) > 1 else 'global'

        return entry


    def get_id_or_make_var(self, id, lineno, default_type = None, scope = None):
        ''' Returns the id if already created. Otherwise, create a var
        '''
        result = self.get_id_entry(id)
        if result is not None:
            return result

        return self.make_var(id, lineno, default_type, scope)


    def make_vardecl(self, id, lineno, _type, default_value = None, kind = 'variable'):
        ''' Like the above, but checks that entry.declared is False.
        Otherwise raises an error.

        Parameter default_value specifies specifies an initalized
        variable, if set.
        '''
        entry = self.make_var(id, lineno, _type._type, scope = 0)
        if entry is None:
            return None

        if entry.declared:
            if entry.scope == 'parameter':
                syntax_error(lineno, "%s '%s' already declared as a parameter at %s:%i" % (kind, id, entry.filename, entry.lineno))
            else:
                syntax_error(lineno, "%s '%s' already declared at %s:%i" % (kind, id, entry.filename, entry.lineno))
            return None

        entry.declared = True

        if entry._type != _type._type:
            if not _type.symbol.implicit:
                syntax_error(lineno, "%s suffix for '%s' is for type '%s' but declared as '%s'" % (kind, id, entry._type, _type._type))
                return None

            _type.symbol.implicit = False
            _type._type = entry._type

        if _type.symbol.implicit:
            warning_implicit_type(lineno, id, entry._type)

        if default_value is not None and entry._type != default_value._type:
            if is_number(default_value):
                default_value = make_typecast(entry._type, default_value)
                if default_value is None:
                    return None
            else:
                syntax_error(lineno, "%s '%s' declared as '%s' but initialized with a '%s' value" % (kind, id, entry._type, default_value._type))
                return None

        if default_value is not None:
            default_value = default_value.value

        entry.default_value = default_value

        if len(self.table) > 1:
            entry.scope = 'local'

            if entry._type == 'string':
                entry.t = optemps.new_t()

        if entry.scope == 'global' and entry._type == 'string':
            entry.t = entry._mangled

        return entry


    def make_constdecl(self, id, lineno, _type, default_value):
        entry = self.create_id(id, lineno)

        if entry is None:
            return

        entry = self.make_vardecl(id, lineno, _type, default_value, 'constant')

        if entry is None:
            return

        entry._class = 'const'
        entry.value = entry.t = default_value.value

        return entry


    def make_label(self, id, lineno):
        ''' Unlike variables, labels are always global.
        '''
        _id = str(id)

        if not self.check_class(_id, 'label', lineno):
            return None

        entry = self.get_id_entry(_id) # Must not exist, or, if created, have _class = None or Function and declared = False
        if entry is None:
            entry = self.create_id(_id, lineno)

        entry._class = 'label'
        entry._type = None # Labels does not have type

        if _id[0] == '.':
            _id = _id[1:]
            entry._mangled = '%s' % _id # Mangled name. Labels are just the label, 'cause it starts with '.'
        else:
            entry._mangled = '__LABEL__%s' % entry.id # Mangled name. Labels are __LABEL__

        entry.is_line_number = isinstance(id, int)
        self.move_to_global_scope(_id)

        return entry


    def make_labeldecl(self, id, lineno):
        entry = self.make_label(id, lineno)
        if entry is None:
            return None

        if entry.declared:
            if entry.is_line_number:
                syntax_error(lineno, "Duplicated line number '%s'. Previous was at %i" % (entry.id, entry.lineno))
            else:
                syntax_error(lineno, "Label '%s' already declared at line %i" % (id, entry.lineno))
            return None

        entry.declared = True
        entry._type = 'u16'

        return entry


    def make_paramdecl(self, id, lineno, _type = 'float'):
        ''' Like the above, but checks for parameters. Check if entry.declared is False.
        Otherwise raises an error.
        '''
        entry = self.make_var(id, lineno, _type, scope = 0)

        if entry.declared:
            syntax_error(lineno, "Parameter '%s' already declared at %s:%i" % (id, entry.filename, entry.lineno))
            return None

        entry.declared = True
        entry._type = _type
        entry.scope = 'parameter'

        if entry._type == 'string':
            entry.t = optemps.new_t()

        return entry


    def make_arraydecl(self, id, lineno, _type, bounds, default_value = None):
        ''' Like the above, but declares an array. It checks that entry.declared is False.
        Otherwise raises an error.
        '''
        entry = self.make_var(id, lineno, default_type = _type._type, scope = 0)
        if entry is None:
            return None

        if not entry.declared:
            if entry.callable:
                syntax_error(lineno, "Array '%s' must be declared before use. First used at line %i" % (id, entry.lineno))
                return None
        else:
            if entry.scope == 'parameter':
                syntax_error(lineno, "variable '%s' already declared as a parameter at line %i" % (id, entry.lineno))
            else:
                syntax_error(lineno, "variable '%s' already declared at line %i" % (id, entry.lineno))
            return None

        if entry._type != _type._type:
            if not _type.symbol.implicit:
                syntax_error(lineno, "Array suffix for '%s' is for type '%s' but declared as '%s'" % (entry.id, entry._type, _type._type))
                return None

            _type.symbol.implicit = False
            _type._type = entry._type

        if _type.symbol.implicit:
            warning_implicit_type(lineno, id)

        entry.declared = True
        entry._class = 'array'
        entry._type = _type._type
        entry.bounds = bounds
        entry.count = bounds.symbol.count # Number of bounds
        entry.total_size = bounds.size * TYPE_SIZES[entry._type]
        entry.default_value = default_value
        entry.callable = True

        return entry


    def make_func(self, id, lineno):
        ''' Checks whether the id exist or not (error if exists).
        And creates the entry at the symbol table.
        '''
        if not self.check_class(id, 'function', lineno):
            entry = self.get_id_entry(id) # Must not exist, or, if created, hav _class = None or Function and declared = False
            an = 'an' if entry._class.lower()[0] in 'aeio' else 'a'
            syntax_error(lineno, "'%s' already declared as %s %s at %i" % (id, an, entry._class, entry.lineno))
            return None

        entry = self.get_id_entry(id) # Must not exist, or, if created, hav _class = None or Function and declared = False
        if entry is not None:
            if entry.declared and not entry.forwarded:
                syntax_error(lineno, "Duplicate function name '%s', previously defined at %i" % (id, entry.lineno))
                return None

            if entry.callable == False:
                syntax_error_not_array_nor_func(lineno, id)
                return None
        else:
            entry = self.create_id(id, lineno)

        if not entry.forwarded:
            entry._type = None  # Function return type must be set later unless a deprecated suffix used
        else:
            old_type = entry._type # Remembers the old type
            old_params_size = entry.params_size

        if entry._mangled[-1] == '$': # A string variable?
            entry._type = 'string' # Ok. We know it's a string
            entry._mangled = entry._mangled[:-1]
            entry.id = entry.id[:-1]
        elif entry._mangled[-1] == '%': # An integer variable
            entry._type = 'i16' # Ok. We know it's a 16 bit signed integer
            entry._mangled = entry._mangled[:-1]
            entry.id = entry.id[:-1]

        if entry.forwarded:
            if entry._type is not None:
                if entry._type != old_type:
                    syntax_error_func_type_mismatch(lineno, entry)
            else:
                entry._type = old_type  

        entry._class = 'function'
        entry._mangled = '_%s' % entry.id # Mangled name (functions always has _name as mangled)
        entry.callable = True
        entry.locals_size = 0 # Size of local variables
        entry.local_symbol_table = {}

        if not entry.forwarded:
            entry.params_size = 0 # Size of parametres
        else:
            entry.params_size = old_params_size # Size of parametres

        return entry


    def make_callable(self, id, lineno):
        ''' Creates a func/array/string call. Checks if id is callable or not.
        '''
        entry = self.get_or_create(id, lineno)
        if entry.callable == False: # Is it NOT callable?
            if entry._type != 'string':
                syntax_error_not_array_nor_func(lineno, id)
                return None
            else:
                # Ok, it is a string slice if it has 0 or 1 parameters
                return entry

        entry._mangled = '_%s' % entry.id # Mangled name (functions always has _name as mangled)
        entry.callable = True
        return entry


    def check_labels(self):
        ''' Checks if all the labels has been declared
        '''
        for entry in self.table[0].values():
            if entry._class == 'label':
                self.check_declared(entry.id, entry.lineno, 'label')


    def check_classes(self, scope = -1):
        ''' Check if pending identifiers are defined or not. If not,
        returns a syntax error. If no scope is given, the current
        one is checked.
        '''
        for entry in self.table[scope].values():
            if entry._class is None:
                syntax_error(entry.lineno, "Unknown identifier '%s'" % entry.id)


    @property
    def vars(self):
        ''' Returns symbol instances corresponding to variables
        of the current scope.
        '''
        return [x for x in self.table[0].values() if x._class == 'var']


    @property
    def arrays(self):
        ''' Returns symbol instances corresponding to arrays
        of the current scope.
        '''
        return [x for x in self.table[0].values() if x._class == 'array']


    @property
    def functions(self):
        ''' Returns symbol instances corresponding to functions
        of the current scope.
        '''
        return [x for x in self.table[0].values() if x._class == 'function']


    @property
    def aliases(self):
        ''' Returns symbol instances corresponding to aliased vars.
        '''
        return [x for x in self.table[0].values() if x.is_aliased]


    def __getitem__(self, level):
        ''' Returns the SYMBOL TABLE for the given scope (0 = global)
        '''
        return self.table[level]




SYMBOL_TABLE = SymbolTable()


# ----------------------------------------------------------------------
# Abstract Syntax Tree class
# ----------------------------------------------------------------------
class Tree(Ast):
    ''' Adds some methods for easier coding...
    '''
    def __get_value(self):
        return self.symbol.value

    def __set_value(self, value):
        self.symbol.value = value

    value = property(__get_value, __set_value)


    @property
    def token(self):
        return self.symbol.token


    @property
    def text(self):
        return self.symbol.text


    @property
    def lineno(self):
        return self.symbol.lineno # Only for some symbols, lookout!


    @property
    def _class(self):
        if hasattr(self.symbol, '_class'):
            return self.symbol._class

        return None


    def __get_t(self):
        return self.symbol.t

    def __set_t(self, value):
        self.symbol.t = value

    t = property(__get_t, __set_t)


    def __get_type(self):
        return self.symbol._type

    def __set_type(self, _type):
        self.symbol._type = _type

    _type = property(__get_type, __set_type)


    @property
    def size(self):
        return self.symbol.size



# ----------------------------------------------------------------------
# Symbol objects
# ----------------------------------------------------------------------
class SymbolID(Symbol):
    ''' Defines an ID (Identifier) symbol.
    '''
    def __init__(self, value, lineno, offset = None):
        global SYMBOL_TABLE

        Symbol.__init__(self, value, 'ID')
        self.id = value
        self.filename = FILENAME    # In which file was first used
        self.lineno = lineno        # In which line was first used
        self._class = None
        self._mangled = '_%s' % value # This value will be overriden later
        self.t = self._mangled
        self.declared = False # if declared (DIM var AS <type>) this must be True
        self._type = None # Unknown type
        self.offset = offset # For local variables, offset from top of the stack
        self.default_value = None # If defined, variable will be initialized with this value (Arrays = List of Bytes)
        self.scope = 'global' # One of 'global', 'parameter', 'local'
        self.byref = False    # By default, it's a global var
        self.default_value = None # For variables, this is the default initalized value
        self.__kind = None  # If not None, it should be one of 'function' or 'sub'
        self.addr = None    # If not None, the address of this symbol (string)
        self.alias = None    # If not None, this var is an alias of another
        self.aliased_by = [] # Which variables are an alias of this one
        self.referenced_by = []    # Which objects do use this one (e.g. sentences using this variable)
        self.references = []    # Objects referenced by this one (e.g. variables used in this sentence)
        self.accessed = False    # Where this object has been accessed (if false it might be not compiled, since it is useless)
        self.caseins = OPTIONS.case_insensitive.value # Whether this ID is case insensitive or not

    @property
    def size(self):
        return TYPE_SIZES[self._type]

    def set_kind(self, value, lineno):
        if self.__kind is not None and self.__kind != value:
            q = 'SUB' if self.__kind == 'function' else 'FUNCTION'
            syntax_error(lineno, "'%s' is a %s, not a %s" % (self.id, self.__kind.upper(), q))
            return

        self.__kind = value


    @property
    def kind(self):
        return self.__kind


    def add_alias(self, entry):
        ''' Adds id to the current list 'aliased_by'
        '''
        self.aliased_by.append(entry)


    def make_alias(self, entry):
        ''' Make this variable an alias of another one
        '''
        entry.add_alias(self)
        self.alias = entry
        self.scope = entry.scope # Even local declared aliases can be "global" (static)
        self.byref = entry.byref
        self.offset = entry.offset
        self.addr = entry.addr


    @property
    def is_aliased(self):
        ''' Return if this symbol is aliased by another
        '''
        return len(self.aliased_by) > 0



class SymbolNUMBER(Symbol):
    ''' Defines an NUMBER symbol.
    '''
    def __init__(self, value, _type = None, lineno = None):
        if lineno is None:
            raise ValueError # This should be changed to another exception

        Symbol.__init__(self, value, 'NUMBER')

        if int(value) == value:
            value = int(value)

        self.value = value

        if _type is not None:
            self._type = _type

        elif isinstance(value, float):
            if -32768.0 < value < 32767:
                self._type = 'fixed'
            else:
                self._type = 'float'

        elif isinstance(value, int):
            if 0 <= value < 256:
                self._type = 'u8'
            elif -128 <= value < 128:
                self._type = 'i8'
            elif 0 <= value < 65536:
                self._type = 'u16'
            elif -32768 <= value < 32768:
                self._type = 'i16'
            elif value < 0:
                self._type = 'i32'
            else:
                self._type = 'u32'

        self.t = value
        self.lineno = lineno


class SymbolSTRING(Symbol):
    ''' Defines a string constant.
    '''
    def __init__(self, value, lineno):
        Symbol.__init__(self, value, 'STRING')
        self._type = 'string'
        self.lineno = lineno
        self.t = value


class SymbolASM(Symbol):
    ''' Defines an ASM sentence
    '''
    def __init__(self, asm, lineno):
        Symbol.__init__(self, asm, 'ASM')
        self.lineno = lineno


class SymbolSTRSLICE(Symbol):
    ''' Defines a string slice
    '''
    def __init__(self, lineno):
        Symbol.__init__(self, None, 'STRSLICE')
        self.lineno = lineno
        self._type = 'string'
        self.t = optemps.new_t()


class SymbolBINARY(Symbol):
    ''' Defines a BINARY EXPRESSION e.g. (a + b)
        Only the operator (e.g. 'PLUS') is stored.
    '''
    def __init__(self, oper, lineno):
        Symbol.__init__(self, oper, 'BINARY')
        self.left = None # Must be set by make_binary
        self.right = None
        self.t = optemps.new_t()
        self.lineno = lineno


class SymbolUNARY(Symbol):
    ''' Defines an UNARY EXPRESSION e.g. (a + b)
        Only the operator (e.g. 'PLUS') is stored.
    '''
    def __init__(self, oper, lineno):
        Symbol.__init__(self, oper, 'UNARY')
        self.left = None # Must be set by make_unary
        self.t = optemps.new_t()
        self.lineno = lineno


class SymbolSENTENCE(Symbol):
    ''' Defines a BASIC SENTENCE object. e.g. 'BORDER'.
    '''
    def __init__(self, sentence):
        Symbol.__init__(self, None, sentence)
        self.args = None # Must be set o an array of args. by make_sentence


class SymbolBLOCK(Symbol):
    ''' Defines a block of code.
    '''
    def __init__(self):
        Symbol.__init__(self, None, 'BLOCK')


class SymbolTYPECAST(Symbol):
    ''' Defines a typecast operation.
    '''
    def __init__(self, new_type):
        Symbol.__init__(self, new_type, 'CAST')
        self.t = optemps.new_t()
        self._type = new_type


class SymbolTYPE(Symbol):
    ''' Defines a type definition.
    '''
    def __init__(self, _type, lineno, implicit = False):
        ''' Implicit = True if this type has been
        "inferred" by default, or by the expression surrounding
        the ID.
        '''
        Symbol.__init__(self, _type, 'TYPE')
        self._type = _type
        self.size = TYPE_SIZES[self._type]
        self.lineno = lineno
        self.implicit = implicit


class SymbolVARDECL(Symbol):
    ''' Defines a Variable declaration
    '''
    def __init__(self, symbol):
        Symbol.__init__(self, symbol._mangled, 'VARDECL')
        self._type = symbol._type
        self.size = symbol.size
        self.entry = symbol

    @property
    def default_value(self):
        return self.entry.default_value


class SymbolARRAYDECL(Symbol):
    ''' Defines an Array declaration
    '''
    def __init__(self, symbol):
        Symbol.__init__(self, symbol._mangled, 'ARRAYDECL')
        self._type = symbol._type
        self.size = symbol.total_size # Total array cell + index size
        self.entry = symbol
        self.bounds = symbol.bounds


class SymbolFUNCDECL(Symbol):
    ''' Defines a Function declaration
    '''
    def __init__(self, symbol):
        Symbol.__init__(self, symbol._mangled, 'FUNCDECL')
        self.fname = symbol.id
        self._mangled = symbol._mangled
        self.entry = symbol # Symbol table entry

    def __get_locals_size(self):
        return self.entry.locals_size

    def __set_locals_size(self, value):
        self.entry.locals_size = value

    locals_size = property(__get_locals_size, __set_locals_size)

    def __get_type(self):
        return self.entry._type

    def __set_type(self, value):
        self.entry._type = value

    _type = property(__get_type, __set_type)

    @property
    def size(self):
        return TYPE_SIZES[self._type]


class SymbolPARAMDECL(Symbol):
    ''' Defines a parameter declaration
    '''
    def __init__(self, symbol, _type):
        Symbol.__init__(self, symbol._mangled, 'PARAMDECL')
        self.entry = symbol
        self.__size = TYPE_SIZES[self._type]
        self.__size = self.__size + (self.__size % 2) # Make it even-sized (Float and Byte)
        self.byref = OPTIONS.byref.value    # By default all params By value (false)
        self.offset = None  # Set by PARAMLIST, contains positive offset from top of the stack

    @property
    def _type(self):
        return self.entry._type

    @property
    def size(self):
        if self.byref:
            return TYPE_SIZES['u16']

        return self.__size


class SymbolPARAMLIST(Symbol):
    ''' Defines a list of parameters definitions in a function header
    '''
    def __init__(self):
        Symbol.__init__(self, None, 'PARAMLIST')
        self.size = 0   # Will contain the sum of all the params size (byte params counts as 2 bytes)
        self.count = 0    # Counter of number of params


class SymbolARGUMENT(Symbol):
    ''' Defines an argument in a function call
    '''
    def __init__(self, lineno, byref = False):
        ''' Initializes the argument data. Byref must be set
        to True if this Argument is passed by reference.
        '''
        Symbol.__init__(self, None, 'ARGUMENT')
        self.lineno = lineno
        self.byref = byref

    @property
    def _type(self):
        return self.arg._type

    @property
    def size(self):
        return TYPE_SIZES[self._type]

    @property
    def arg(self):
        return self.this.next[0].symbol # The argument itself (SymbolID, SymbolBINARY, etc...)

    @property
    def t(self):
        return self.arg.t

    @property
    def _mangled(self):
        return self.arg._mangled

    def typecast(self, _type):
        ''' Apply type casting to the argument expression.
        Returns True on success.
        '''
        self.this.next[0] = make_typecast(_type, self.this.next[0])

        return self.this.next[0] is not None


class SymbolARGLIST(Symbol):
    ''' Defines a list of arguments in a function call
    '''
    def __init__(self):
        Symbol.__init__(self, None, 'ARGLIST')
        self.count = 0 # Number of params

    def __getitem__(self, range):
        return self.this.next[range]


class SymbolCALL(Symbol):
    ''' Defines a list of arguments in a function call/array access/string
    '''
    def __init__(self, lineno, symbol, name = 'FUNCCALL'):
        Symbol.__init__(self, symbol._mangled, name) # Func. call / array access
        self.entry = symbol
        self.t = optemps.new_t()
        self.lineno = lineno

    @property
    def _type(self):
        return self.entry._type

    @property
    def size(self):
        return TYPE_SIZES[self._type]

    @property
    def args(self):
        return self.this.next[0].symbol


class SymbolCONST(Symbol):
    ''' Defines a constant expression (not numerical, e.g. a Label or an @label)
    '''
    def __init__(self, lineno, expr):
        Symbol.__init__(self, None, 'CONST')
        self.expr = expr
        self.lineno = lineno

    @property
    def _type(self):
        return self.expr._type


class SymbolBOUND(Symbol):
    ''' Defines an array bound
    '''
    def __init__(self, lower, upper):
        Symbol.__init__(self, None, 'BOUND')
        self.lower = lower
        self.upper = upper
        self.size = upper - lower + 1


class SymbolBOUNDLIST(Symbol):
    ''' Defines a bound list for an array
    '''
    def __init__(self):
        Symbol.__init__(self, None, 'BOUNDLIST')
        self.size = 0  # Total number of array cells
        self.count = 0 # Number of bounds


class SymbolArrayAccess(SymbolCALL):
    ''' Defines an array access. It's pretty much like a function call
    (e.g. A(1, 2) could be an array access or a function call, depending on
    context). So we derive this class from SymbolCall

    Initializing this with SymbolArrayAccess(symbol, ARRAYLOAD) will
    make the returned expression to be loaded into the stack (by default
    it only returns the pointer address to the element)
    '''
    def __init__(self, lineno, symbol, access = 'ARRAYACCESS', offset = None):
        SymbolCALL.__init__(self, lineno, symbol, access)
        self.offset = offset

    @property
    def scope(self):
        return self.entry.scope

    @property
    def _mangled(self):
        return self.entry._mangled



# ----------------------------------------------------------------------
# Function for checking some arguments
# ----------------------------------------------------------------------
def is_number(*p):
    ''' Returns True if ALL of the arguments are AST nodes
    containing NUMBER constants
    '''
    try:
        for i in p:
            if i.token != 'NUMBER' and (i.token != 'ID' or i._class != 'const'):
                return False

        return True
    except:
        pass

    return False


def is_id(*p):
    ''' Returns True if ALL of the arguments are AST nodes
    containing ID
    '''
    try:
        for i in p:
            if i.token != 'ID':
                return False

        return True
    except:
        pass

    return False


def is_integer(*p):
    try:
        for i in p:
            if i._type not in ('i8', 'u8', 'i16', 'u16', 'i32', 'u32'):
                return False

        return True

    except:
        pass

    return False



def is_unsigned(*p):
    ''' Returns false unles all types in p are unsigned
    '''
    try:
        for i in p:
            if i._type not in ('u8', 'u16', 'u32'):
                return False

        return True

    except:
        pass

    return False



def is_signed(*p):
    ''' Returns false unles all types in p are signed
    '''
    try:
        for i in p:
            if i._type not in ('float', 'fixed', 'i8', 'i16', 'i32'):
                return False

        return True

    except:
        pass

    return False


def is_numeric(*p):
    try:
        for i in p:
            if i._type == 'string':
                return False

        return True

    except:
        pass

    return False


def is_string(*p):
    try:
        for i in p:
            if i.token != 'STRING':
                return False

        return True

    except:
        pass

    return False


def is_const(*p):
    ''' True if all the given nodes are
    constant expressions.'''
    try:
        for i in p:
            if i.token != 'CONST':
                return False

        return True

    except:
        pass

    return False


def is_type(_type, *p):
    ''' True if all args have the same type
    '''
    try:
        for i in p:
            if i._type != _type:
                return False

        return True

    except:
        pass

    return False


def is_dynamic(*p):
    ''' True if all args are dynamic (e.g. Strings, dynamic arrays, etc)
    '''
    try:
        for i in p:
            if i.scope == 'global' and i._type not in ('string'):
                return False

        return True

    except:
        pass

    return False



def common_type(a, b):
    ''' Returns a type which is common for both a and b types.
    Returns None if no common types allowed.
    '''
    if a is None or b is None:
        return None

    if a._type == b._type:    # Both types are the same?
        return a._type        # Returns it

    if a._type is None and b._type is None:
        return DEFAULT_TYPE

    if a._type is None:
        return b._type

    if b._type is None:
        return a._type

    types = (a._type, b._type)

    if 'float' in types:
        return 'float'

    if 'fixed' in types:
        return 'fixed'

    if 'string' in types:
        return 'string'

    result = a._type if TYPE_SIZES[a._type] > TYPE_SIZES[b._type] else b._type

    if not is_unsigned(a, b):
        result = 'i' + result[1:]

    return result


def check_call_arguments(lineno, id, args):
    ''' Checks every argument in a function call against a function.
        Returns True on success.
    '''
    entry = SYMBOL_TABLE.check_declared(id, lineno, 'function')
    if entry is None:
        return False

    if not SYMBOL_TABLE.check_class(id, 'function', lineno):
        return False

    if not hasattr(entry, 'params'):
        return False

    if args.symbol.count != entry.params.symbol.count:
        c = 's' if entry.params.symbol.count != 1 else ''
        syntax_error(lineno, "Function '%s' takes %i parameter%s, not %i" % (id, entry.params.symbol.count, c, len(args.next)))
        return False

    for arg, param in zip(args.next, entry.params.next):
        if arg._type != param._type:
            if not arg.symbol.typecast(param._type):
                return False

        if param.symbol.byref:
            if not isinstance(arg.symbol.arg, SymbolID):
                syntax_error(lineno, "Expected a variable name, not an expression (parameter By Reference)")
                return False

            if arg.symbol.arg._class not in ('var', 'array'):
                syntax_error(lineno, "Expected a variable or array name (parameter By Reference)")
                return False

            arg.symbol.byref = True

    return True


def check_pending_calls():
    ''' Calls the above function for each pending call of the current
    ambit level
    '''
    result = True

    # Check for functions defined after calls (parametres, etc)
    for id, params, lineno in FUNCTION_CALLS:
        result = result and check_call_arguments(lineno, id, params)

    return result


def check_pending_labels(ast):
    ''' Iteratively traverses the ast looking for ID with no class set,
    marks them as labels, and check they've been declared.

    This way we avoid stack overflow for high linenumbered listings.
    '''
    result = True

    pending = [ast]

    while pending != []:
        ast = pending.pop()

        if ast is None:
            continue

        for x in ast.next:
            pending += [x]

        if ast.token != 'ID' or (ast.token == 'ID' and ast._class is not None):
            continue

        tmp =  SYMBOL_TABLE.get_id_entry(ast.symbol.id)
        if tmp is None or tmp._class is None:
            syntax_error(ast.symbol.lineno, 'Undeclared identifier "%s"' % ast.symbol.id)
        else:
            ast.symbol = tmp 

        result = result and tmp is not None

    return result



def check_type(lineno, type_list, arg):
    ''' Check arg's type is one in type_list, otherwise,
    raises an error.
    '''
    if not isinstance(type_list, list):
        type_list = [type_list]

    if arg._type in type_list:
        return True

    if len(type_list) == 1:
        syntax_error(lineno, "Wrong expression type '%s'. Expected '%s'" % (arg._type, type_list[0]))
    else:
        syntax_error(lineno, "Wrong expression type '%s'. Expected one of '%s'" % (arg._type, tuple(type_list)))

    return False



# ----------------------------------------------------------------------
# Function to make AST nodes
# ----------------------------------------------------------------------
def make_binary(lineno, oper, a, b, func, _type = None):
    ''' Creates a binary node for a binary operation
        'func' parameter is a lambda function
    '''
    if is_number(a, b): # Try constant-folding
        return Tree.makenode(SymbolNUMBER(func(a.value, b.value), _type = _type, lineno = lineno))

    # Check for constant non-nummeric operations
    c_type = common_type(a, b)
    if c_type: # there must be a commont type for a and b
        if is_const(a, b) and is_type(c_type, a, b):
            a.symbol.expr = Tree.makenode(SymbolBINARY(oper, lineno = lineno), a.symbol.expr, b.symbol.expr)
            a.symbol.expr._type = c_type
            return a
    
        if is_const(a) and is_number(b) and is_type(c_type, a):
            a.symbol.expr = Tree.makenode(SymbolBINARY(oper, lineno = lineno), a.symbol.expr, make_typecast(c_type, b))
            a.symbol.expr._type = c_type
            return a
    
        if is_const(b) and is_number(a) and is_type(c_type, b):
            b.symbol.expr = Tree.makenode(SymbolBINARY(oper, lineno = lineno), make_typecast(c_type, a), b.symbol.expr)
            b.symbol.expr._type = c_type
            return b

    if oper in ('BNOT', 'BAND', 'BOR', 'BXOR',
                'NOT', 'AND', 'OR', 'XOR',
                'MINUS', 'MULT', 'DIV', 'SHL', 'SHR') and not is_numeric(a, b):
        syntax_error(lineno, 'Operator %s cannot be used with STRINGS' % oper)
        return None

    if is_string(a, b): # Are they STRING Constants?
        if oper == 'PLUS':
            return Tree.makenode(SymbolSTRING(func(a.text, b.text), lineno))
        else:
            return Tree.makenode(SymbolNUMBER(int(func(a.text, b.text)), _type = 'u8', lineno = lineno)) # Convert to u8 (Boolean result)

    c_type = common_type(a, b)

    if oper in ('BNOT', 'BAND', 'BOR', 'BXOR'):
        if c_type in ('fixed', 'float'):
            c_type = 'i32'

    if oper not in ('SHR', 'SHL'):
        a = make_typecast(c_type, a)
        b = make_typecast(c_type, b)

    result = Tree.makenode(SymbolBINARY(oper, lineno = lineno), a, b)
    result.left = a
    result.right = b

    if _type is not None:
        result._type = _type
    elif oper in ('LT', 'GT', 'EQ', 'LE', 'GE', 'NE', 'AND', 'OR', 'XOR', 'NOT'):
        result._type = 'u8' # Boolean type
    else:
        result._type = c_type

    return result


def make_unary(lineno, oper, a, func = None, _type = None, _class = SymbolNUMBER):
    ''' Creates a node for a unary operation
        'func' parameter is a lambda function
        _type is the resulting type (by default, the
        same as the argument).
        For example, for LEN (str$), result type is 'u16'
        and arg type is 'string'

        _class = class of the returning node (SymbolNUMBER by default)
    '''
    if func is not None:
        if is_number(a): # Try constant-folding
            return Tree.makenode(_class(func(a.value), lineno = lineno))
        elif is_string(a):
            return Tree.makenode(_class(func(a.text), lineno = lineno))

    if _type is None:
        _type = a._type

    if oper == 'MINUS':
        if not is_signed(SymbolTYPE(_type, lineno)):
            _type = 'i' + _type[1:]
            a = make_typecast(_type, a)
    elif oper == 'NOT':
        _type = 'u8'

    result = Tree.makenode(SymbolUNARY(oper, lineno = lineno), a)
    result.left = a
    result._type = _type

    return result


def make_constexpr(lineno, expr):
    result = Tree.makenode(SymbolCONST(lineno, expr))

    return result


def make_strslice(lineno, s, lower, upper):
    ''' Creates a node for a string slice. S is the string expression Tree.
    Lower and upper are the bounds, if lower & upper are constants, and
    s is also constant, s, then a string constant is returned.

    If lower > upper, an empty string is returned.
    '''
    check_type(lineno, 'string', s)
    lo = up = None
    base = Tree.makenode(SymbolNUMBER(OPTIONS.string_base.value, lineno = lineno))

    lower = make_typecast('u16', make_binary(lineno, 'MINUS', lower, base, lambda x, y: x - y))
    upper = make_typecast('u16', make_binary(lineno, 'MINUS', upper, base, lambda x, y: x - y))

    if is_number(lower):
        lo = lower.value

        if lo < MIN_STRSLICE_IDX:
            lower.value = lo = MIN_STRSLICE_IDX

    if is_number(upper):
        up = upper.value

        if up > MAX_STRSLICE_IDX:
            upper.value = up = MAX_STRSLICE_IDX

    if is_number(lower, upper):
        if lo > up:
            return Tree.makenode(SymbolSTRING('', lineno))

        if s.token == 'STRING': # A constant string? Recalculate it now
            up += 1
            st = s.t.ljust(up) # Procrustean filled (right) /***/ This behaviour must be checked against Sinclair BASIC
            return Tree.makenode(SymbolSTRING(st[lo:up], lineno))

        # a$(0 TO INF.) = a$
        if lo == MIN_STRSLICE_IDX and up == MAX_STRSLICE_IDX:
            return s

    return Tree.makenode(SymbolSTRSLICE(lineno), s, lower, upper)


def make_sentence(sentence, *args):
    ''' Creates a node for a basic sentence.
    '''
    result = Tree.makenode(SymbolSENTENCE(sentence), *args)
    result.args = list(args)

    return result


def make_asm_sentence(asm, lineno):
    ''' Creates a node for an ASM inline sentence
    '''
    result = Tree.makenode(SymbolASM(asm, lineno))
    return result


def make_block(*args):
    ''' Creates a chain of code blocks.
    '''
    args = [x for x in args if x is not None]
    if len(args) == 0:
        return None

    if args[0].token == 'BLOCK':
        args = args[0].next + args[1:]

    if args[-1].token == 'BLOCK':
        args = args[:-1] + args[-1].next

    return Tree.makenode(SymbolBLOCK(), *tuple(args))


def make_typecast(new_type, node):
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
        syntax_error(node.symbol.lineno, 'Cannot convert string to a value. Use VAL() function')
        return None

    if new_type == 'string':
        syntax_error(node.symbol.lineno, 'Cannot convert value to string. Use STR() function')
        return None

    if is_const(node.symbol):
        node = node.symbol.expr

    if not is_number(node):
        return Tree.makenode(SymbolTYPECAST(new_type), node)

    # It's a number. So let's convert it directly
    if node.token != 'NUMBER':
        if node._class == 'const':
            node = Tree.makenode(SymbolNUMBER(node.value, node._type, node.lineno))

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


def make_var_declaration(symbol):
    ''' This will return a node with the symbol as a variable.
    '''
    return Tree.makenode(SymbolVARDECL(symbol))


def make_array_declaration(symbol):
    ''' This will return a node with the symbol as an array.
    '''
    return Tree.makenode(SymbolARRAYDECL(symbol))


def make_func_declaration(func_name, lineno):
    ''' This will return a node with the symbol as a function.
    '''
    symbol = SYMBOL_TABLE.make_func(func_name, lineno)
    if symbol is None:
        return

    symbol.declared = True

    return Tree.makenode(SymbolFUNCDECL(symbol))


def make_arg_list(node, *args):
    ''' This will return a node with an argument_list.
    '''
    if node is None:
        node = Tree.makenode(SymbolARGLIST())

    if node.token != 'ARGLIST':
        return make_arg_list(None, node, *args)

    for i in args:
        node.next.append(i)
        node.symbol.count += 1

    return node


def make_argument(expr, lineno):
    ''' Creates a Tree node containing an ARGUMENT
    '''
    node = SymbolARGUMENT(lineno)

    return Tree.makenode(node, expr)


def make_param_list(node, *args):
    ''' This will return a node with a param_list
    (declared in a function declaration)
    '''
    if node is None:
        node = Tree.makenode(SymbolPARAMLIST())

    if node.token != 'PARAMLIST':
        return make_param_list(None, node, *args)

    for i in args:
        if i is None: continue

        node.next.append(i)
        if i.symbol.offset is None:
            i.symbol.offset = node.symbol.size
            i.symbol.entry.offset = i.symbol.offset
            node.symbol.size += i.size
            node.symbol.count += 1

    return node


def make_proc_call(id, lineno, params, TOKEN = 'CALL'):
    ''' This will return an AST node for a function/procedure call.
    '''
    entry = SYMBOL_TABLE.make_callable(id, lineno)
    if entry._class is None:
        entry._class = 'function'

    entry.accessed = True
    SYMBOL_TABLE.check_class(id, 'function', lineno)

    if entry.declared:
        check_call_arguments(lineno, id, params)
    else:
        SYMBOL_TABLE.move_to_global_scope(id) # All functions goes to global scope (no nested functions)
        FUNCTION_CALLS.append((id, params, lineno,))

    return Tree.makenode(SymbolCALL(lineno, entry, TOKEN), params)


def make_array_access(id, lineno, arglist, access = 'ARRAYACCESS'):
    ''' Creates an array access. A(x1, x2, ..., xn)
    '''
    check = SYMBOL_TABLE.check_class(id, 'array', lineno)
    if not check:
        return None

    variable = SYMBOL_TABLE.check_declared(id, lineno, 'array')
    if variable is None:
        return None

    if variable.count != len(arglist.next):
        syntax_error(lineno, "Array '%s' has %i dimensions, not %i" % (variable.id, variable.count, len(arglist.next)))
        return None

    offset = 0

    # Now we must typecast each argument to a u16 (POINTER) type
    for i, b in zip(arglist.next, variable.bounds.next):
        lower_bound = Tree.makenode(SymbolNUMBER(b.symbol.lower, _type = 'u16', lineno = lineno))
        i.next[0] = make_binary(lineno, 'MINUS', make_typecast('u16', i.next[0]), lower_bound, lambda x, y: x - y, _type = 'u16')

        if is_number(i.next[0]):
            val = i.next[0].value
            if val < 0 or val > (b.symbol.upper - b.symbol.lower):
                warning(lineno, "Array '%s' subscript out of range" % id)

            if offset is not None:
                offset = offset * (b.symbol.upper + 1 - b.symbol.lower) + val
        else:
            offset = None

    if offset is not None:
        offset *= TYPE_SIZES[variable._type]

    return (variable, Tree.makenode(SymbolArrayAccess(lineno, variable, access, offset = offset), arglist), offset)


def make_call(id, lineno, params):
    ''' This will return an AST node for a function call/array access.
    '''
    entry = SYMBOL_TABLE.make_callable(id, lineno)
    if entry is None:
        return None

    if entry._class == 'array': # An already declared array
        arr = make_array_access(id, lineno, params, 'ARRAYLOAD')
        if arr is not None:
            offset = arr[2]
            arr = arr[1]

            if offset is not None:
                offset = make_typecast('u16', Tree.makenode(SymbolNUMBER(offset, lineno = lineno)))

            arr.next.append(offset)

        return arr

    elif entry._class == 'var': # An already declared/used string var
        if params.symbol.count > 1:
            syntax_error_not_array_nor_func(lineno, id)
            return None

        entry = SYMBOL_TABLE.get_id_or_make_var(id, lineno)
        if entry is None:
            return None

        if params.symbol.count == 1:
            return make_strslice(lineno, Tree.makenode(entry), params.next[0].next[0], params.next[0].next[0])

        entry.accessed = True
        return Tree.makenode(entry)


    return make_proc_call(id, lineno, params, 'FUNCCALL')


def make_param_decl(id, lineno, typedef):
    ''' A param decl is like a var decl, in the current scope (local variable).
    This will check that no ID with this name is alredy declared, an declares it.
    '''
    entry = SYMBOL_TABLE.make_paramdecl(id, lineno, typedef._type)
    if entry is None:
        return None

    entry._class = 'var'

    return Tree.makenode(SymbolPARAMDECL(entry, typedef._type))


def make_type(typename, lineno, implicit = False):
    ''' Creates a type declaration symbol stored in a AST
    '''
    typename = TYPE_NAMES[typename.lower()]
    return Tree.makenode(SymbolTYPE(typename, lineno, implicit))


def make_bound(lower, upper, lineno):
    ''' Creates an array bound
    '''
    if not is_number(lower, upper):
        syntax_error(lineno, 'Array bounds must be constants')
        return None

    lower.value = int(lower.value)
    upper.value = int(upper.value)

    if lower.value < 0:
        syntax_error(lineno, 'Array bounds must be greater than 0')
        return None

    if lower.value > upper.value:
        syntax_error(lineno, 'Lower array bound must be less or equal to upper one')
        return None

    return Tree.makenode(SymbolBOUND(lower.value, upper.value))


def make_bound_list(node, *args):
    ''' Creates an array BOUND LIST.
    '''
    if node is None:
        return make_bound_list(Tree.makenode(SymbolBOUNDLIST()), *args)

    if node.token != 'BOUNDLIST':
        return make_bound_list(None, node, *args)

    for i in args:
        node.next.append(i)

    node.symbol.count = len(node.next)
    node.symbol.size = 1

    for i in node.next:
        node.symbol.size *= i.size

    return node


def make_label(id, lineno):
    ''' Creates a label entry. Returns None on error.
    '''
    label = SYMBOL_TABLE.make_labeldecl(id, lineno)

    if label is not None:
        result = make_sentence('LABEL', Tree.makenode(label))
    else:
        result = None

    return result


# ----------------------------------------------------------------------
# Operators precedence
# ----------------------------------------------------------------------
precedence = (
    ('left', 'OR'),
    ('left', 'AND'),
    ('left', 'XOR'),
    ('left', 'BOR'),
    ('left', 'BAND'),
    ('left', 'BXOR'),
    ('right', 'NOT'),
    ('right', 'BNOT'),
    ('left', 'LT', 'GT', 'EQ', 'LE', 'GE', 'NE'),
    ('left', 'SHR', 'SHL'),
    ('left', 'PLUS', 'MINUS'),
    ('left', 'MOD'),
    ('left', 'MUL', 'DIV'),
    ('right', 'UMINUS'),
    ('right', 'POW'),
)


# ----------------------------------------------------------------------
# Grammar rules
# ----------------------------------------------------------------------

def p_start(p):
    ''' start : program
    '''
    global ast, data_ast

    user_data = make_label('.ZXBASIC_USER_DATA', 0)
    user_data_end = make_label('.ZXBASIC_USER_DATA_LEN', 0)

    if PRINT_IS_USED:
        zxbpplex.ID_TABLE.define('___PRINT_IS_USED___', 1)

    if zxblex.IN_STATE:
        p.type = 'NEWLINE'
        p_error(p)
        sys.exit(1)

    ast = p[0] = p[1]
    __end = make_sentence('END', Tree.makenode(SymbolNUMBER(0, lineno = p.lexer.lineno)))

    if ast is not None:
        ast.next.append(__end)
    else:
        ast = __end

    SYMBOL_TABLE.check_labels()
    SYMBOL_TABLE.check_classes()

    if has_errors:
        return

    if not check_pending_labels(ast):
        return

    if not check_pending_calls():
        return

    data_ast = make_sentence('BLOCK', user_data)

    # Appends variable declarations at the end.
    for var in SYMBOL_TABLE.vars:
        data_ast.next.append(make_var_declaration(var))

    # Appends arrays declarations at the end.
    for var in SYMBOL_TABLE.arrays:
        data_ast.next.append(make_array_declaration(var))



def p_program_program_line(p):
    ''' program : program_line
    '''
    p[0] = p[1]


def p_program(p):
    ''' program : program program_line
    '''
    if OPTIONS.enableBreak.value:
        lineno = p.lexer.lineno
        tmp = make_sentence('CHKBREAK', Tree.makenode(SymbolNUMBER(lineno, 'u16', lineno)))
        p[0] = make_block(p[1], p[2], tmp)
    else:
        p[0] = make_block(p[1], p[2])


def p_program_line_(p):
    ''' program_line : statement
                | var_decl
                | preproc_line
                | label_line
    '''
    p[0] = p[1]


def p_program_line_label(p):
    ''' label_line : LABEL statement
                   | LABEL var_decl
    '''
    p[0] = make_block(make_label(p[1], p.lineno(1)), p[2])


def p_program_line_label2(p):
    ''' program_line : ID CO NEWLINE
    '''
    p[0] = make_label(p[1], p.lineno(1))


def p_var_decl(p):
    ''' var_decl : DIM idlist typedef NEWLINE
                 | DIM idlist typedef CO
    '''
    for vardata in p[2]:
        entry = SYMBOL_TABLE.make_vardecl(vardata[0], vardata[1], p[3])

    p[0] = None # Variable declarations are made at the end of parsing


def p_var_decl_at(p):
    ''' var_decl : DIM idlist typedef AT expr CO
                 | DIM idlist typedef AT expr NEWLINE
    '''
    p[0] = None

    if len(p[2]) != 1:
        syntax_error(p.lineno(1), 'Only one variable at a time can be declared this way')
        return

    idlist = p[2][0]
    entry = SYMBOL_TABLE.make_vardecl(idlist[0], idlist[1], p[3])
    if entry is None:
        return

    if p[5].token == 'UNARY' and p[5].text == 'ADDRESS': # Must be an ID
        if p[5].next[0].token == 'ID':
            entry.make_alias(p[5].next[0].symbol)
        elif p[5].next[0].token == 'ARRAYACCESS':
            if p[5].next[0].symbol.offset is None:
                syntax_error(p.lineno(4), 'Address is not constant. Only constant subscripts are allowed')
                return

            entry.make_alias(p[5].next[0].symbol.entry)
            entry.offset = p[5].next[0].symbol.offset
        else:
            syntax_error(p.lineno(4), 'Only address of identifiers are allowed')
            return

    elif not is_number(p[5]):
        syntax_error(p.lineno(4), 'Address must be a numeric constant expression')
        return
    else:
        entry.addr = str(make_typecast('u16', p[5]).value)
        if entry.scope == 'local':
            SYMBOL_TABLE.make_static(entry.id)


def p_var_decl_ini(p):
    ''' var_decl : DIM idlist typedef EQ expr NEWLINE
                 | DIM idlist typedef EQ expr CO
                 | CONST idlist typedef EQ expr NEWLINE
                 | CONST idlist typedef EQ expr CO
    '''
    p[0] = None
    if len(p[2]) != 1:
        syntax_error(p.lineno(1), "Initialized variables must be declared one by one.")
        return

    if not is_number(p[5]):
        syntax_error_not_constant(p.lineno(1))
        return

    defval = make_typecast(p[3]._type, p[5])

    if p[1] == 'DIM':
        entry = SYMBOL_TABLE.make_vardecl(p[2][0][0], p[2][0][1], p[3], default_value = defval)
    else:
        entry = SYMBOL_TABLE.make_constdecl(p[2][0][0], p[2][0][1], p[3], default_value = defval)


def p_idlist_id(p):
    ''' idlist : ID
    '''
    p[0] = [(p[1], p.lineno(1))]


def p_idlist_idlist_id(p):
    ''' idlist : idlist COMMA ID
    '''
    p[0] = p[1] + [(p[3], p.lineno(3))]


def p_arr_decl(p):
    ''' var_decl : DIM ID LP bound_list RP typedef NEWLINE
                 | DIM ID LP bound_list RP typedef CO
    '''
    entry = SYMBOL_TABLE.make_arraydecl(p[2], p.lineno(2), p[6], p[4])
    p[0] = None


def p_arr_decl_initialized(p):
    ''' var_decl : DIM ID LP bound_list RP typedef RIGHTARROW const_vector NEWLINE
                 | DIM ID LP bound_list RP typedef RIGHTARROW const_vector CO
                 | DIM ID LP bound_list RP typedef EQ const_vector NEWLINE
                 | DIM ID LP bound_list RP typedef EQ const_vector CO
    '''
    def check_bound(boundlist, remaining):
        ''' Checks if constant vector bounds matches the array one
        '''
        if boundlist == []: # Returns on empty list
            if not isinstance(remaining, list):
                return True        # It's OK :-)

            syntax_error(p.lineno(9), 'Unexpected extra vector dimensions. It should be %i' % len(remaining))

        if not isinstance(remaining, list):
            syntax_error(p.lineno(9), 'Mismatched vector size. Missing %i extra dimension(s)' % len(boundlist))
            return False

        if len(remaining) != boundlist[0].size:
            syntax_error(p.lineno(9), 'Mismatched vector size. Expected %i, got %i.' % (boundlist[0].size, len(remaining)))
            return False    # It's wrong. :-(

        result = True
        for row in remaining:
            result = result and check_bound(boundlist[1:], row)
            if not result:
                return False

        return True

    if p[8] is None:
        p[0] = None
        return

    if check_bound(p[4].next, p[8]):
        entry = SYMBOL_TABLE.make_arraydecl(p[2], p.lineno(2), p[6], p[4], default_value = p[8])

    p[0] = None


def p_bound_list(p):
    ''' bound_list : bound
    '''
    p[0] = make_bound_list(p[1])


def p_bound_list_bound(p):
    ''' bound_list : bound_list COMMA bound
    '''
    p[0] = make_bound_list(p[1], p[3])


def p_bound(p):
    ''' bound : expr
    '''
    if not is_number(p[1]):
        syntax_error(p.lexer.lineno, 'Array bound must be a constant expression.')
        p[0] = None

    p[0] = make_bound(Tree.makenode(SymbolNUMBER(OPTIONS.array_base.value, lineno = p.lineno(1))), p[1], p.lexer.lineno)


def p_bound_to_bound(p):
    ''' bound : expr TO expr
    '''
    if not is_number(p[1], p[3]):
        syntax_error(p.lineno(2), 'Array bound must be a constant expression.')
        p[0] = None

    p[0] = make_bound(p[1], p[3], p.lineno(2))


def p_const_vector(p):
    ''' const_vector : LBRACE const_vector_list RBRACE
                     | LBRACE const_number_list RBRACE
    '''
    p[0] = p[2]


def p_const_vector_elem_list(p):
    ''' const_number_list : expr
    '''
    if not is_number(p[1]):
        syntax_error_not_constant(p.lexer.lineno)
        p[0] = None
        return

    p[0] = [p[1]]


def p_const_vector_elem_list_list(p):
    ''' const_number_list : const_number_list COMMA expr
    '''
    if not is_number(p[3]):
        syntax_error_not_constant(p.lineno(2))
        p[0] = None
        return

    p[0] = p[1] + [p[3]]


def p_const_vector_list(p):
    ''' const_vector_list : const_vector
    '''
    p[0] = [p[1]]


def p_const_vector_vector_list(p):
    ''' const_vector_list : const_vector_list COMMA const_vector
    '''
    if len(p[3]) != len(p[1][0]):
        syntax_error(p.lineno(2), "All rows must have the same number of elements")
        p[0] = None
        return

    p[0] = p[1] + [p[3]]



def p_empty_statement(p):
    ''' statement : NEWLINE
                  | CO
    '''
    p[0] = None


def p_staement_func_decl(p):
    ''' statement : function_declaration
    '''
    p[0] = p[1]


def p_statement_border(p):
    ''' statement : BORDER expr NEWLINE
                  | BORDER expr CO
    '''
    p[0] = make_sentence('BORDER', make_typecast('u8', p[2]))


def p_statement_plot(p):
    ''' statement : PLOT expr COMMA expr NEWLINE
                  | PLOT expr COMMA expr CO
    '''
    p[0] = make_sentence('PLOT', make_typecast('u8', p[2]), make_typecast('u8', p[4]))


def p_statement_plot_attr(p):
    ''' statement : PLOT attr_list expr COMMA expr NEWLINE
                  | PLOT attr_list expr COMMA expr CO
    '''
    p[0] = make_sentence('PLOT', make_typecast('u8', p[3]), make_typecast('u8', p[5]), p[2])


def p_statement_draw3(p):
    ''' statement : DRAW expr COMMA expr COMMA expr NEWLINE
                  | DRAW expr COMMA expr COMMA expr CO
    '''
    p[0] = make_sentence('DRAW3', make_typecast('i16', p[2]), make_typecast('i16', p[4]), make_typecast('float', p[6]))


def p_statement_draw3_attr(p):
    ''' statement : DRAW attr_list expr COMMA expr COMMA expr NEWLINE
                  | DRAW attr_list expr COMMA expr COMMA expr CO
    '''
    p[0] = make_sentence('DRAW3', make_typecast('i16', p[3]), make_typecast('i16', p[5]), make_typecast('float', p[7]), p[2])


def p_statement_draw(p):
    ''' statement : DRAW expr COMMA expr NEWLINE
                  | DRAW expr COMMA expr CO
    '''
    p[0] = make_sentence('DRAW', make_typecast('i16', p[2]), make_typecast('i16', p[4]))


def p_statement_draw_attr(p):
    ''' statement : DRAW attr_list expr COMMA expr NEWLINE
                  | DRAW attr_list expr COMMA expr CO
    '''
    p[0] = make_sentence('DRAW', make_typecast('i16', p[3]), make_typecast('i16', p[5]), p[2])


def p_statement_circle(p):
    ''' statement : CIRCLE expr COMMA expr COMMA expr NEWLINE
                  | CIRCLE expr COMMA expr COMMA expr CO
    '''
    p[0] = make_sentence('CIRCLE', make_typecast('u8', p[2]), make_typecast('u8', p[4]), make_typecast('u8', p[6]))


def p_statement_circle_attr(p):
    ''' statement : CIRCLE attr_list expr COMMA expr COMMA expr NEWLINE
                  | CIRCLE attr_list expr COMMA expr COMMA expr CO
    '''
    p[0] = make_sentence('CIRCLE', make_typecast('u8', p[3]), make_typecast('u8', p[5]), make_typecast('u8', p[7]), p[2])


def p_statement_cls(p):
    ''' statement : CLS NEWLINE
                  | CLS CO
    '''
    p[0] = make_sentence('CLS')


def p_statement_asm(p):
    ''' statement : ASM NEWLINE
                  | ASM CO
    '''
    p[0] = make_asm_sentence(p[1], p.lineno(1))


def p_statement_randomize(p):
    ''' statement : RANDOMIZE NEWLINE
                  | RANDOMIZE CO
    '''
    p[0] = make_sentence('RANDOMIZE', Tree.makenode(SymbolNUMBER(0, _type = 'u32', lineno = p.lineno(1))))


def p_statement_randomize_expr(p):
    ''' statement : RANDOMIZE expr NEWLINE
                  | RANDOMIZE expr CO
    '''
    p[0] = make_sentence('RANDOMIZE', make_typecast('u32', p[2]))


def p_statement_beep(p):
    ''' statement : BEEP expr COMMA expr NEWLINE
                  | BEEP expr COMMA expr CO
    '''
    p[0] = make_sentence('BEEP', make_typecast('float', p[2]), make_typecast('float', p[4]))


def p_statement_call(p):
    ''' statement : ID arg_list NEWLINE
                  | ID arg_list CO
    '''
    p[0] = make_proc_call(p[1], p.lineno(1), p[2])


def p_assignment(p):
    ''' statement : lexpr expr CO
                  | lexpr expr NEWLINE
    '''
    global LET_ASSIGNEMENT

    LET_ASSIGNEMENT = False # Mark we're no longer using LET
    p[0] = None
    q = p[1:]
    i = 2

    if q[1] is None: return

    variable = SYMBOL_TABLE.get_id_entry(q[0])
    if variable is None:
        variable = SYMBOL_TABLE.make_var(q[0], p.lineno(i), q[1]._type)
    if variable is None: return

    q1_class = q[1]._class if hasattr(q[1], '_class') else None

    if variable._class == 'var' and q1_class == 'array':
        syntax_error(p.lineno(i), 'Cannot assign an array to an escalar variable')
        return

    if variable._class == 'array':
        if q1_class != variable._class:
            syntax_error(p.lineno(i), 'Cannot assign an escalar to an array variable')
            return

        if q[1]._type != variable._type:
            syntax_error(p.lineno(i), 'Arrays must have the same element type')
            return

        if variable.total_size != q[1].symbol.total_size:
            syntax_error(p.lineno(i), "Arrays '%s' and '%s' must have the same size" % (variable.id, q[1].symbol.id))
            return

        if variable.count != q[1].symbol.count:
            warning(p.lineno(i), "Arrays '%s' and '%s' don't have the same number of dimensions" % (variable.id, q[1].symbol.id))
        else:
            for b1, b2 in zip(variable.bounds.next, q[1].symbol.bounds.next):
                if b1.symbol.lower != b2.symbol.lower or b1.symbol.upper != b2.symbol.upper:
                    warning(p.lineno(i), "Arrays '%s' and '%s' don't have the same dimensions" % (variable.id, q[1].symbol.id))
                    break

        # Array copy
        p[0] = make_sentence('ARRAYCOPY',  Tree.makenode(variable), q[1])
        return

    expr = make_typecast(variable._type, q[1])
    p[0] = make_sentence('LET', Tree.makenode(variable), expr)


def p_lexpr(p):
    ''' lexpr : ID EQ
              | LET ID EQ
    '''
    global LET_ASSIGNEMENT

    LET_ASSIGNEMENT = True # Mark we're about to start a LET sentence

    if p[1] == 'LET':
        p[0] = p[2]
    else:
        p[0] = p[1]


def p_arr_assignment(p):
    ''' statement : ID arg_list EQ expr CO
                  | ID arg_list EQ expr NEWLINE
                  | LET ID arg_list EQ expr CO
                  | LET ID arg_list EQ expr NEWLINE
    '''
    q = p[1:]
    i = 2
    if q[0].upper() == 'LET':
        q = q[1:]
        i = 3

    p[0] = None
    arr = make_array_access(q[0], p.lineno(i), q[1])
    if arr is None: return

    (variable, arr, offset) = arr
    if variable is None: return

    expr = make_typecast(variable._type, q[3])
    if offset is not None:
        offset = make_typecast('u16', Tree.makenode(SymbolNUMBER(offset, lineno = p.lineno(1))))

    p[0] = make_sentence('LETARRAY', arr, expr, offset)


def p_str_assign(p):
    ''' statement : ID substr EQ expr CO
                  | ID substr EQ expr NEWLINE
                  | LET ID substr EQ expr CO
                  | LET ID substr EQ expr NEWLINE
    '''
    q = p[1]
    r = p[4]
    s = p[2]
    lineno = p.lineno(3)

    if q is not None and q.upper() == 'LET':
        q = p[2]
        r = p[5]
        s = p[3]
        lineno = p.lineno(4)

    if q is None or s is None:
        p[0] = None
        return

    if r._type != 'string':
        syntax_error_expected_string(lineno, r._type)

    id = Tree.makenode(SYMBOL_TABLE.make_var(q, lineno, 'string'))
    p[0] = make_sentence('LETSUBSTR', id, s[0], s[1], r)


def p_goto(p):
    ''' statement : goto NUMBER CO
                  | goto NUMBER NEWLINE
                  | goto ID CO
                  | goto ID NEWLINE
    '''
    if isinstance(p[2], float):
        if p[2] == int(p[2]):
            id = str(int(p[2]))
        else:
            syntax_error(p.lineno(1), 'Line numbers must be integers.')
            p[0] = None
            return
    else:
        id = p[2]

    entry = SYMBOL_TABLE.make_label(id, p.lineno(2))
    if entry is not None:
        p[0] = make_sentence(p[1].upper(), Tree.makenode(entry))
    else:
        p[0] = None


def p_go(p):
    ''' goto : GO TO
             | GO SUB
             | GOTO
             | GOSUB
    '''
    p[0] = p[1]
    if p[0] == 'GO':
        p[0] += p[2]


def p_endif(p):
    ''' endif : END IF
              | LABEL END IF
    '''
    if p[1] == 'END':
        p[0] = None
    else:
        p[0] = make_label(p[1], p.lineno(1))


def p_if_sentence(p):
    ''' statement : IF expr THEN program endif CO
                  | IF expr THEN program endif NEWLINE
    '''
    if p[4] is None:
        warning(p.lineno(1), 'Useless empty IF ignored')
        p[0] = None
        return

    if is_number(p[2]) and p[2].value == 0:
        warning_condition_is_always(p.lineno(1))
        if OPTIONS.optimization.value > 0:
            p[0] = None
            return

    p[0] = make_sentence('IF', p[2], make_block(p[4], p[5]))


def p_if_elseif(p):
    ''' statement : IF expr THEN program elseiflist CO
                  | IF expr THEN program elseiflist NEWLINE
    '''
    if is_number(p[2]) and p[2].value == 0:
        warning_condition_is_always(p.lineno(1))
        if OPTIONS.optimization.value > 0:
            p[0] = p[5]
            return

    p[0] = make_sentence('IF', p[2], p[4], p[5])


def p_elseif_list(p):
    ''' elseiflist : ELSEIF expr THEN program endif
                   | LABEL ELSEIF expr THEN program endif
    '''
    if p[1] == 'ELSEIF':
        p1 = None # No label
        p2 = p[2]
        p4 = p[4]
        p5 = p[5]
    else:
        p1 = make_label(p[1], p.lineno(1))
        p2 = p[3]
        p4 = p[5]
        p5 = p[6]

    if is_number(p2) and p2.value == 0:
        warning_condition_is_always(p.lineno(1))
        if OPTIONS.optimization.value > 0:
            p[0] = p1
            return

    p[0] = make_block(p1, make_sentence('IF', p2, make_block(p4, p5)))


def p_elseif_elseiflist(p):
    ''' elseiflist : ELSEIF expr THEN program elseiflist
                   | LABEL ELSEIF expr THEN program elseiflist
    '''
    if p[1] == 'ELSEIF':
        p1 = None
        p2 = p[2]
        p4 = p[4]
        p5 = p[5]
    else:
        p1 = make_label(p[1], p.lineno(1))
        p2 = p[3]
        p4 = p[5]
        p5 = p[6]

    if is_number(p2) and p2.value == 0:
        warning_condition_is_always(p.lineno(1))
        if OPTIONS.optimization.value > 0:
            p[0] = p1
            return

    p[0] = make_block(p1, make_sentence('IF', p2, p4, p5))


def p_else(p):
    ''' else : ELSE
             | LABEL ELSE
    '''
    if p[1] == 'ELSE':
        p[0] = None
    else:
        p[0] = make_label(p[1], p.lineno(1))


def p_if_else(p):
    ''' statement : IF expr THEN program else program endif CO
                  | IF expr THEN program else program endif NEWLINE
    '''
    if p[4] is None and p[6] is None:
        warning(p.lineno(1), 'Useless empty IF ignored')
        p[0] = None
        return

    if is_number(p[2]) and p[2].value == 0:
        warning_condition_is_always(p.lineno(1))
        if OPTIONS.optimization.value > 0:
            p[0] = p[6]
            return

    p[0] = make_sentence('IF', p[2], p[4], make_block(p[5], p[6], p[7]))


def p_if_elseif_else(p):
    ''' statement : IF expr THEN program elseif_elselist program endif CO
                  | IF expr THEN program elseif_elselist program endif NEWLINE
    '''
    if is_number(p[2]) and p[2].value == 0:
        warning_condition_is_always(p.lineno(1))
        if OPTIONS.optimization.value > 0:
            if p[5] is None:
                p[0] = p[6]
                return

            p[5][1].next.append(p[6])
            p[0] = p[5]
            return

    if p[5] is None:
        p[0] = make_sentence('IF', p[2], p[4], make_block(p[6], p[7]))
        return

    p[5][1].next.append(make_block(p[6], p[7]))
    p[0] = make_sentence('IF', p[2], p[4], p[5][0])


def p_elseif_elselist_else(p):
    ''' elseif_elselist : ELSEIF expr THEN program else
                        | LABEL ELSEIF expr THEN program else
    '''
    if p[1] == 'ELSEIF':
        p1 = None
        p2 = p[2]
        p4 = p[4]
        p5 = p[5]
    else:
        p1 = make_label(p[1], p.lineno(1))
        p2 = p[3]
        p4 = p[5]
        p5 = p[6]

    if is_number(p2) and p2.value == 0:
        warning_condition_is_always(p.lineno(1))
        if OPTIONS.optimization.value > 0:
            p[0] = p1
            return

    last = make_block(p1, make_sentence('IF', p2, make_block(p4, p5))) # p[6] must be added in the rule above
    p[0] = (last, last)


def p_elseif_elselist(p):
    ''' elseif_elselist : ELSEIF expr THEN program elseif_elselist
                        | LABEL ELSEIF expr THEN program elseif_elselist
    '''
    if p[1] == 'ELSEIF':
        p1 = None
        p2 = p[2]
        p4 = p[4]
        p5 = p[5]
    else:
        p1 = make_label(p[1], p.lineno(1))
        p2 = p[3]
        p4 = p[5]
        p5 = p[6]

    if is_number(p2) and p2.value == 0:
        warning_condition_is_always(p.lineno(1))
        if OPTIONS.optimization.value > 0:
            last = p5[1]
            p[0] = (make_block(p1, p5[0]), last)
            return

    node = make_sentence('IF', p2, p4, p5[0])
    p[0] = (make_block(p1, node), p5[1])


def p_for_sentence(p):
    ''' statement : for_start program label_next CO
                  | for_start program label_next NEWLINE
    '''
    p[0] = p[1]
    p[1].next.append(make_block(p[2], p[3]))
    LOOPS.pop()


def p_next(p):
    ''' label_next : LABEL NEXT
                   | NEXT 
    '''
    if p[1] == 'NEXT':
        p[0] = None
    else:
        p[0] = make_label(p[1], p.lineno(1))


def p_next1(p):
    ''' label_next : LABEL NEXT ID 
                   | NEXT ID
    '''
    if p[1] == 'NEXT':
        p1 = None
        p3 = p[2]
    else:
        p1 = make_label(p[1], p.lineno(1))
        p3 = p[3]

    if p3 != LOOPS[-1][1]:
        syntax_error_wrong_for_var(p.lineno(2), LOOPS[-1][1], p3)
        p[0] = None
        return

    p[0] = p1


def p_end(p):
    ''' statement : END expr CO
                  | END expr NEWLINE
                  | END CO
                  | END NEWLINE
    '''
    q = p[2]
    if not isinstance(q, Tree):
        q = Tree.makenode(SymbolNUMBER(0, lineno = p.lineno(1)))

    p[0] = make_sentence('END', q)


def p_error_raise(p):
    ''' statement : ERROR expr CO
                  | ERROR expr NEWLINE
    '''
    q = Tree.makenode(SymbolNUMBER(1, lineno = p.lineno(3)))
    r = make_binary(p.lineno(1), 'MINUS', make_typecast('u8', p[2]), q, lambda x, y: x - y)
    p[0] = make_sentence('ERROR', r)


def p_stop_raise(p):
    ''' statement : STOP expr CO
                  | STOP expr NEWLINE
                  | STOP CO
                  | STOP NEWLINE
    '''
    q = p[2]
    if not isinstance(q, Tree):
        q = Tree.makenode(SymbolNUMBER(9, lineno = p.lineno(1)))

    z = Tree.makenode(SymbolNUMBER(1, lineno = p.lineno(1)))
    r = make_binary(p.lineno(1), 'MINUS', make_typecast('u8', q), z, lambda x, y: x - y)
    p[0] = make_sentence('STOP', r)


def p_for_sentence_start(p):
    ''' for_start : FOR ID EQ expr TO expr step
    '''
    LOOPS.append(('FOR', p[2]))
    p[0] = None

    if p[4] is None or p[6] is None or p[7] is None:
        return

    if is_number([p[4], p[6], p[7]]):
        if p[4].value != p[6].value and p[7].value == 0:
            warning(p.lineno(5), 'STEP value is 0 and FOR might loop forever')

        if p[4].value > p[6].value and p[7].value > 0:
            warning(p.lineno(5), 'FOR start value is greater than end. This FOR loop is useless')
            if OPTIONS.optimizations > 0:
                return

        if p[4].value < p[6].value and p[7].value < 0:
            warning(p.lineno(5), 'FOR start value is lower than end. This FOR loop is useless')
            if OPTIONS.optimizations > 0:
                return

    a = make_type(NAME_TYPES[p[4]._type], p.lineno(3))
    b = make_type(NAME_TYPES[p[6]._type], p.lineno(5))
    c = make_type(NAME_TYPES[p[7]._type], p.lexer.lineno)
    d = make_type(NAME_TYPES[common_type(a, b)], p.lineno(5))
    id_type = common_type(c, d)

    variable = Tree.makenode(SYMBOL_TABLE.make_var(p[2], p.lineno(2), default_type = id_type))
    if variable is None:
        return None

    variable.symbol.accessed = True
    expr1 = make_typecast(variable._type, p[4])
    expr2 = make_typecast(variable._type, p[6])
    expr3 = make_typecast(variable._type, p[7])

    p[0] = make_sentence('FOR', variable, expr1, expr2, expr3)
    p[0].t = optemps.new_t()


def p_step(p):
    ''' step :
    '''
    p[0] = Tree.makenode(SymbolNUMBER(1, lineno = p.lexer.lineno))


def p_step_expr(p):
    ''' step : STEP expr
    '''
    p[0] = p[2]


def p_loop(p):
    ''' label_loop : LABEL LOOP 
                   | LOOP 
    '''
    if p[1] == 'LOOP':
        p[0] = None
    else:
        p[0] = make_label(p[1], p.lineno(1))


def p_do_loop(p):
    ''' statement : do_start program label_loop CO
                  | do_start program label_loop NEWLINE
                  | do_start label_loop CO
                  | do_start label_loop NEWLINE
                  | DO label_loop CO
                  | DO label_loop NEWLINE
    '''
    if len(p) > 4:
        q = make_block(p[2], p[3])
    else:
        q = p[2]

    if p[1] == 'DO':
        LOOPS.append(('DO', ))

    if q is None:
        warning(p.lineno(1), 'Infinite empty loop')

    # An infinite loop and no warnings
    p[0] = make_sentence('DO_LOOP', q)
    LOOPS.pop()


def p_do_loop_until(p):
    ''' statement : do_start program label_loop UNTIL expr CO
                  | do_start program label_loop UNTIL expr NEWLINE
                  | do_start label_loop UNTIL expr CO
                  | do_start label_loop UNTIL expr NEWLINE
                  | DO label_loop UNTIL expr NEWLINE
                  | DO label_loop UNTIL expr CO
    '''
    if len(p) > 6:
        q = make_block(p[2], p[3])
        r = p[5]
    else:
        q = p[2]
        r = p[4]

    if p[1] == 'DO':
        LOOPS.append(('DO', ))

    p[0] = make_sentence('DO_UNTIL', r, q)

    LOOPS.pop()
    if is_number(r):
        warning_condition_is_always(p.lineno(3), bool(r.value))
    if q is None:
        warning_empty_loop(p.lineno(3))


def p_do_loop_while(p):
    ''' statement : do_start program LOOP WHILE expr CO
                  | do_start program LOOP WHILE expr NEWLINE
                  | do_start LOOP WHILE expr CO
                  | do_start LOOP WHILE expr NEWLINE
                  | DO LOOP WHILE expr NEWLINE
                  | DO LOOP WHILE expr CO
    '''
    q = p[2]
    r = p[5]

    if q == 'LOOP':
        q = None
        r = p[4]
        LOOPS.append(('DO', ))

    p[0] = make_sentence('DO_WHILE', r, q)
    LOOPS.pop()

    if is_number(r):
        warning_condition_is_always(p.lineno(3), bool(r.value))


def p_do_while_loop(p):
    ''' statement : do_while_start program LOOP CO
                  | do_while_start program LOOP NEWLINE
                  | do_while_start LOOP CO
                  | do_while_start LOOP NEWLINE
    '''
    r = p[1]
    q = p[2]
    if q == 'LOOP':
        q = None

    p[0] = make_sentence('WHILE_DO', r, q)
    LOOPS.pop()

    if is_number(r):
        warning_condition_is_always(p.lineno(2), bool(r.value))


def p_do_until_loop(p):
    ''' statement : do_until_start program LOOP CO
                  | do_until_start program LOOP NEWLINE
                  | do_until_start LOOP CO
                  | do_until_start LOOP NEWLINE
    '''
    r = p[1]
    q = p[2]
    if q == 'LOOP':
        q = None

    p[0] = make_sentence('UNTIL_DO', r, q)
    LOOPS.pop()

    if is_number(r):
        warning_condition_is_always(p.lineno(2), bool(r.value))


def p_do_while_start(p):
    ''' do_while_start : DO WHILE expr CO
                       | DO WHILE expr NEWLINE
    '''
    p[0] = p[3]
    LOOPS.append(('DO', ))


def p_do_until_start(p):
    ''' do_until_start : DO UNTIL expr CO
                       | DO UNTIL expr NEWLINE
    '''
    p[0] = p[3]
    LOOPS.append(('DO', ))


def p_do_start(p):
    ''' do_start : DO CO
                 | DO NEWLINE
    '''
    LOOPS.append(('DO', ))


def p_label_end_while(p):
    ''' label_end_while : LABEL END WHILE CO
                  | LABEL END WHILE NEWLINE
                  | LABEL WEND CO 
                  | LABEL WEND NEWLINE
    '''
    p[0] = make_label(p[1], p.lineno(1))


def p_while_sentence(p):
    ''' statement : while_start program END WHILE CO
                  | while_start program END WHILE NEWLINE
                  | while_start program WEND CO
                  | while_start program WEND NEWLINE
                  | while_start program label_end_while
                  | while_start END WHILE CO
                  | while_start END WHILE NEWLINE
                  | while_start WEND CO
                  | while_start WEND NEWLINE
    '''
    LOOPS.pop()
    q = p[2]

    if q is not None and q in ('WEND', 'END'):
        q = None
    elif p[3] not in ('WEND', 'END'):
        q = make_block(p[2], p[3]) 

    if is_number(p[1]):
        if p[1].value == 0:
            warning_condition_is_always(p[1].lineno)
            if OPTIONS.optimization.value > 0:
                warning(p[1].lineno, "Loop has been ignored")
                p[0] = None
            else:
                p[0] = make_sentence('WHILE', p[1], q)
        else:
            p[0] = make_sentence('WHILE', p[1], q)
            if q is None:
                warning(p[1].lineno, "Condition is always true and leads to an infinite loop.")
            else:
                warning(p[1].lineno, "Condition is always true and might lead to an infinite loop.")
    else:
        p[0] = make_sentence('WHILE', p[1], q)


def p_while_start(p):
    ''' while_start : WHILE expr
    '''
    p[0] = p[2]
    LOOPS.append(('WHILE', ))


def p_exit(p):
    ''' statement : EXIT WHILE CO
                  | EXIT WHILE NEWLINE
                  | EXIT DO CO
                  | EXIT DO NEWLINE
                  | EXIT FOR CO
                  | EXIT FOR NEWLINE
    '''
    q = p[2]
    p[0] = make_sentence('EXIT_%s' % q)

    for i in LOOPS:
        if q == i[0]:
            return

    syntax_error(p.lineno(1), 'Syntax Error: EXIT %s out of loop' % q)


def p_continue(p):
    ''' statement : CONTINUE WHILE CO
                  | CONTINUE WHILE NEWLINE
                  | CONTINUE DO CO
                  | CONTINUE DO NEWLINE
                  | CONTINUE FOR CO
                  | CONTINUE FOR NEWLINE
    '''
    q = p[2]
    p[0] = make_sentence('CONTINUE_%s' % q)

    for i in LOOPS:
        if q == i[0]:
            return

    syntax_error(p.lineno(1), 'Syntax Error: CONTINUE %s out of loop' % q)


def p_print_sentence(p):
    ''' statement : PRINT print_list CO
                  | PRINT print_list NEWLINE
    '''
    global PRINT_IS_USED

    p[0] = p[2]
    PRINT_IS_USED = True


def p_print_list_expr(p):
    ''' print_elem : expr
                   | print_at
                   | print_tab
                   | attr
                   | BOLD expr
                   | ITALIC expr
    '''
    if p[1] in ('BOLD', 'ITALIC'):
        p[0] = make_sentence(p[1] + '_TMP', make_typecast('u8', p[2]))
    else:
        p[0] = p[1]


def p_attr_list(p):
    ''' attr_list : attr SC
    '''
    p[0] = p[1]


def p_attr_list_list(p):
    ''' attr_list : attr_list attr SC
    '''
    p[0] = make_block(p[1], p[2])


def p_attr(p):
    ''' attr : OVER expr
             | INVERSE expr
             | INK expr
             | PAPER expr
             | BRIGHT expr
             | FLASH expr
    '''
    # ATTR_LIST are used by drawing commands: PLOT, DRAW, CIRCLE
    # BOLD and ITALIC are ignored by them, so we put them out of the
    # attr definition so something like DRAW BOLD 1; .... will raise
    # a syntax error
    p[0] = make_sentence(p[1] + '_TMP', make_typecast('u8', p[2]))


def p_print_list_epsilon(p):
    ''' print_elem :
    '''
    p[0] = None


def p_print_list_elem(p):
    ''' print_list : print_elem
    '''
    p[0] = make_sentence('PRINT', p[1])
    p[0].symbol.eol = True


def p_print_list(p):
    ''' print_list : print_list SC print_elem
    '''
    p[0] = p[1]
    p[0].symbol.eol = (p[3] is not None)

    if p[3] is not None:
        p[0].next.append(p[3])


def p_print_list_comma(p):
    ''' print_list : print_list COMMA print_elem
    '''
    p[0] = p[1]
    p[0].symbol.eol = (p[3] is not None)
    p[0].next.append(make_sentence('PRINT_COMMA'))

    if p[3] is not None:
        p[0].next.append(p[3])


def p_print_list_at(p):
    ''' print_at : AT expr COMMA expr
    '''
    p[0] = make_sentence('PRINT_AT', make_typecast('u8', p[2]), make_typecast('u8', p[4]))


def p_print_list_tab(p):
    ''' print_tab : TAB expr
    '''
    p[0] = make_sentence('PRINT_TAB', make_typecast('u8', p[2]))


def p_return(p):
    ''' statement : RETURN CO
                  | RETURN NEWLINE
    '''
    if FUNCTION_LEVEL == []: # At less one level, otherwise, this return is from a GOSUB
        p[0] = make_sentence('RETURN')
        return

    if FUNCTION_LEVEL[-1].kind != 'sub':
        syntax_error(p.lineno(1), 'Syntax Error: Functions must RETURN a value, or use EXIT FUNCTION instead.')
        p[0] = None
        return

    p[0] = make_sentence('RETURN', Tree.makenode(FUNCTION_LEVEL[-1]))


def p_return_expr(p):
    ''' statement : RETURN expr CO
                  | RETURN expr NEWLINE
    '''
    if FUNCTION_LEVEL == []: # At less one level
        syntax_error(p.lineno(1), 'Syntax Error: Returning value out of FUNCTION')
        p[0] = None
        return

    if FUNCTION_LEVEL[-1].kind is None: # This function was not correctly declared.
        p[0] = None
        return

    if FUNCTION_LEVEL[-1].kind != 'function':
        syntax_error(p.lineno(1), 'Syntax Error: SUBs cannot return a value')
        p[0] = None
        return

    if is_numeric(p[2]) and FUNCTION_LEVEL[-1]._type == 'string':
        syntax_error(p.lineno(2), 'Type Error: Function must return a string, not a numeric value')
        p[0] = None
        return

    if not is_numeric(p[2]) and FUNCTION_LEVEL[-1]._type != 'string':
        syntax_error(p.lineno(2), 'Type Error: Function must return a numeric value, not a string')
        p[0] = None
        return

    p[0] = make_sentence('RETURN', Tree.makenode(FUNCTION_LEVEL[-1]), make_typecast(FUNCTION_LEVEL[-1]._type, p[2]))


def p_pause(p):
    ''' statement : PAUSE expr CO
                  | PAUSE expr NEWLINE
    '''
    p[0] = make_sentence('PAUSE', make_typecast('u16', p[2]))


def p_poke(p):
    ''' statement : POKE expr COMMA expr CO
                  | POKE expr COMMA expr NEWLINE
                  | POKE LP expr COMMA expr RP CO
                  | POKE LP expr COMMA expr RP NEWLINE
    '''
    i = 2 if isinstance(p[2], Tree) else 3
    p[0] = make_sentence('POKE', make_typecast('u16', p[i]), make_typecast('u8', p[i + 2]))


def p_poke2(p):
    ''' statement : POKE numbertype expr COMMA expr CO
                  | POKE numbertype expr COMMA expr NEWLINE
                  | POKE LP numbertype expr COMMA expr RP CO
                  | POKE LP numbertype expr COMMA expr RP NEWLINE
    '''
    i = 2 if isinstance(p[2], Tree) else 3
    p[0] = make_sentence('POKE', make_typecast('u16', p[i + 1]), make_typecast(p[i]._type, p[i + 3]))


def p_poke3(p):
    ''' statement : POKE numbertype COMMA expr COMMA expr CO
                  | POKE numbertype COMMA expr COMMA expr NEWLINE
                  | POKE LP numbertype COMMA expr COMMA expr RP CO
                  | POKE LP numbertype COMMA expr COMMA expr RP NEWLINE
    '''
    i = 2 if isinstance(p[2], Tree) else 3
    p[0] = make_sentence('POKE', make_typecast('u16', p[i + 2]), make_typecast(p[i]._type, p[i + 4]))


def p_out(p):
    ''' statement : OUT expr COMMA expr CO
                  | OUT expr COMMA expr NEWLINE
    '''
    p[0] = make_sentence('OUT', make_typecast('u16', p[2]), make_typecast('u8', p[4]))


def p_bold(p):
    ''' statement : BOLD expr CO
                  | BOLD expr NEWLINE
    '''
    p[0] = make_sentence('BOLD', make_typecast('u8', p[2]))


def p_ITALIC(p):
    ''' statement : ITALIC expr CO
                  | ITALIC expr NEWLINE
    '''
    p[0] = make_sentence('ITALIC', make_typecast('u8', p[2]))


def p_ink(p):
    ''' statement : INK expr CO
                  | INK expr NEWLINE
    '''
    p[0] = make_sentence('INK', make_typecast('u8', p[2]))


def p_paper(p):
    ''' statement : PAPER expr CO
                  | PAPER expr NEWLINE
    '''
    p[0] = make_sentence('PAPER', make_typecast('u8', p[2]))


def p_bright(p):
    ''' statement : BRIGHT expr CO
                  | BRIGHT expr NEWLINE
    '''
    p[0] = make_sentence('BRIGHT', make_typecast('u8', p[2]))


def p_flash(p):
    ''' statement : FLASH expr CO
                  | FLASH expr NEWLINE
    '''
    p[0] = make_sentence('FLASH', make_typecast('u8', p[2]))


def p_over(p):
    ''' statement : OVER expr CO
                  | OVER expr NEWLINE
    '''
    p[0] = make_sentence('OVER', make_typecast('u8', p[2]))


def p_inverse(p):
    ''' statement : INVERSE expr CO
                  | INVERSE expr NEWLINE
    '''
    p[0] = make_sentence('INVERSE', make_typecast('u8', p[2]))


def p_save_code(p):
    ''' statement : SAVE expr CODE expr COMMA expr CO
                  | SAVE expr CODE expr COMMA expr NEWLINE
                  | SAVE expr ID NEWLINE
                  | SAVE expr ID CO
    '''
    if p[2]._type != 'string':
        syntax_error_expected_string(p.lineno(1), p[2]._type)

    if len(p) == 5:
        if p[3].upper() not in ('SCREEN', 'SCREEN$'):
            syntax_error(p.lineno(3), 'Unexpected "%s" ID. Expected "SCREEN$" instead' % p[3])
            return None
        else:
            # ZX Spectrum screen start + length
            # This should be stored in a architecture-dependant file
            start = Tree.makenode(SymbolNUMBER(16384, lineno = p.lineno(1)))
            length = Tree.makenode(SymbolNUMBER(6912, lineno = p.lineno(1)))
    else:
        start = p[4]
        length = p[6]

    p[0] = make_sentence(p[1], p[2], start, length)


def p_save_data(p):
    ''' statement : SAVE expr DATA CO
                  | SAVE expr DATA NEWLINE
                  | SAVE expr DATA ID CO
                  | SAVE expr DATA ID NEWLINE
                  | SAVE expr DATA ID LP RP CO
                  | SAVE expr DATA ID LP RP NEWLINE
    '''
    if p[2]._type != 'string':
        syntax_error_expected_string(p.lineno(1), p[2]._type)

    if len(p) != 5:
        entry = SYMBOL_TABLE.make_id(p[4], p.lineno(4))
        if entry is None:
            p[0] = None
            return

        entry.accessed = True
        access = Tree.makenode(entry)
        start = make_unary(p.lineno(4), 'ADDRESS', access, _type = 'u16')

        if entry._class == 'array':
            length = Tree.makenode(SymbolNUMBER(entry.total_size + 1 + 2 * entry.count, lineno = p.lineno(4)))
        else:
            length = Tree.makenode(SymbolNUMBER(TYPE_SIZES[entry._type], lineno = p.lineno(4)))
    else:
        entry = SYMBOL_TABLE.make_id('.ZXBASIC_USER_DATA', p.lineno(4))
        access = Tree.makenode(entry)
        start = make_unary(p.lineno(4), 'ADDRESS', access, _type = 'u16')

        entry = SYMBOL_TABLE.make_id('.ZXBASIC_USER_DATA_LEN', p.lineno(4))
        access = Tree.makenode(entry)
        length = make_unary(p.lineno(4), 'ADDRESS', access, _type = 'u16')

    p[0] = make_sentence(p[1], p[2], start, length)


def p_load_or_verify(p):
    ''' load_or_verify : LOAD
                       | VERIFY
    '''
    p[0] = p[1]


def p_load_code(p):
    ''' statement : load_or_verify expr ID CO
                  | load_or_verify expr CODE CO
                  | load_or_verify expr CODE expr CO
                  | load_or_verify expr CODE expr COMMA expr CO
                  | load_or_verify expr ID NEWLINE
                  | load_or_verify expr CODE NEWLINE
                  | load_or_verify expr CODE expr NEWLINE
                  | load_or_verify expr CODE expr COMMA expr NEWLINE
    '''
    if p[2]._type != 'string':
        syntax_error_expected_string(p.lineno(3), p[2]._type)

    if len(p) == 5:
        if p[3].upper() not in ('SCREEN', 'SCREEN$', 'CODE'):
            syntax_error(p.lineno(3), 'Unexpected "%s" ID. Expected "SCREEN$" instead' % p[3])
            return None
        else:
            if p[3].upper() == 'CODE': # LOAD "..." CODE
                start = Tree.makenode(SymbolNUMBER(0, lineno = p.lineno(3)))
                length = Tree.makenode(SymbolNUMBER(0, lineno = p.lineno(3)))
            else: # SCREEN$
                start = Tree.makenode(SymbolNUMBER(16384, lineno = p.lineno(3)))
                length = Tree.makenode(SymbolNUMBER(6912, lineno = p.lineno(3)))
    else:
        start = make_typecast('u16', p[4])

        if len(p) == 6:
            length = Tree.makenode(SymbolNUMBER(0, lineno = p.lineno(3)))
        else:
            length = make_typecast('u16', p[5])

    p[0] = make_sentence(p[1], p[2], start, length)


def p_load_data(p):
    ''' statement : load_or_verify expr DATA CO
                  | load_or_verify expr DATA NEWLINE
                  | load_or_verify expr DATA ID CO
                  | load_or_verify expr DATA ID NEWLINE
                  | load_or_verify expr DATA ID LP RP CO
                  | load_or_verify expr DATA ID LP RP NEWLINE
    '''
    if p[2]._type != 'string':
        syntax_error_expected_string(p.lineno(1), p[2]._type)

    if len(p) != 5:
        entry = SYMBOL_TABLE.make_id(p[4], p.lineno(4))
        if entry is None:
            p[0] = None
            return

        entry.accessed = True
        access = Tree.makenode(entry)
        start = make_unary(p.lineno(4), 'ADDRESS', access, _type = 'u16')

        if entry._class == 'array':
            length = Tree.makenode(SymbolNUMBER(entry.total_size + 1 + 2 * entry.count, lineno = p.lineno(4)))
        else:
            length = Tree.makenode(SymbolNUMBER(TYPE_SIZES[entry._type], lineno = p.lineno(4)))
    else:
        entry = SYMBOL_TABLE.make_id('.ZXBASIC_USER_DATA', p.lineno(4))
        access = Tree.makenode(entry)
        start = make_unary(p.lineno(4), 'ADDRESS', access, _type = 'u16')

        entry = SYMBOL_TABLE.make_id('.ZXBASIC_USER_DATA_LEN', p.lineno(4))
        access = Tree.makenode(entry)
        length = make_unary(p.lineno(4), 'ADDRESS', access, _type = 'u16')

    p[0] = make_sentence(p[1], p[2], start, length)



def p_numbertype(p):
    ''' numbertype : BYTE
                   | UBYTE
                   | INTEGER
                   | UINTEGER
                   | LONG
                   | ULONG
                   | FIXED
                   | FLOAT
    '''
    p[0] = make_type(p[1], p.lineno(1))



def p_expr_plus_expr(p):
    ''' expr : expr PLUS expr
    '''
    p[0] = make_binary(p.lineno(2), 'PLUS', p[1], p[3], lambda x, y: x + y)


def p_expr_minus_expr(p):
    ''' expr : expr MINUS expr
    '''
    p[0] = make_binary(p.lineno(2), 'MINUS', p[1], p[3], lambda x, y: x - y)


def p_expr_mul_expr(p):
    ''' expr : expr MUL expr
    '''
    p[0] = make_binary(p.lineno(2), 'MUL', p[1], p[3], lambda x, y: x * y)


def p_expr_div_expr(p):
    ''' expr : expr DIV expr
    '''
    p[0] = make_binary(p.lineno(2), 'DIV', p[1], p[3], lambda x, y: x / y)


def p_expr_mod_expr(p):
    ''' expr : expr MOD expr
    '''
    p[0] = make_binary(p.lineno(2), 'MOD', p[1], p[3], lambda x, y: x % y)


def p_expr_pow_expr(p):
    ''' expr : expr POW expr
    '''
    p[0] = make_binary(p.lineno(2), 'POW', make_typecast('float', p[1]), make_typecast('float', p[3]), lambda x, y: x ** y)


def p_expr_shl_expr(p):
    ''' expr : expr SHL expr
    '''
    if p[1] is None or p[3] is None:
        p[0] = None
        return

    if p[1]._type in ('float', 'fixed'):
        p[1] = make_typecast('u32', p[1])

    p[0] = make_binary(p.lineno(2), 'SHL', p[1], make_typecast('u8', p[3]), lambda x, y: x << y)


def p_expr_shr_expr(p):
    ''' expr : expr SHR expr
    '''
    if p[1] is None or p[3] is None:
        p[0] = None
        return

    if p[1]._type in ('float', 'fixed'):
        p[1] = make_typecast('u32', p[1])

    p[0] = make_binary(p.lineno(2), 'SHR', p[1], make_typecast('u8', p[3]), lambda x, y: x >> y)


def p_minus_expr(p):
    ''' expr : MINUS expr %prec UMINUS
    '''
    p[0] = make_unary(p.lineno(1), 'MINUS', p[2], lambda x: -x)


def p_expr_EQ_expr(p):
    ''' expr : expr EQ expr
    '''
    p[0] = make_binary(p.lineno(2), 'EQ', p[1], p[3], lambda x, y: x == y)


def p_expr_LT_expr(p):
    ''' expr : expr LT expr
    '''
    p[0] = make_binary(p.lineno(2), 'LT', p[1], p[3], lambda x, y: x < y)


def p_expr_LE_expr(p):
    ''' expr : expr LE expr
    '''
    p[0] = make_binary(p.lineno(2), 'LE', p[1], p[3], lambda x, y: x <= y)


def p_expr_GT_expr(p):
    ''' expr : expr GT expr
    '''
    p[0] = make_binary(p.lineno(2), 'GT', p[1], p[3], lambda x, y: x > y)


def p_expr_GE_expr(p):
    ''' expr : expr GE expr
    '''
    p[0] = make_binary(p.lineno(2), 'GE', p[1], p[3], lambda x, y: x >= y)


def p_expr_NE_expr(p):
    ''' expr : expr NE expr
    '''
    p[0] = make_binary(p.lineno(2), 'NE', p[1], p[3], lambda x, y: x != y)


def p_expr_OR_expr(p):
    ''' expr : expr OR expr
    '''
    p[0] = make_binary(p.lineno(2), 'OR', p[1], p[3], lambda x, y: x or y)


def p_expr_BOR_expr(p):
    ''' expr : expr BOR expr
    '''
    p[0] = make_binary(p.lineno(2), 'BOR', p[1], p[3], lambda x, y: x | y)


def p_expr_XOR_expr(p):
    ''' expr : expr XOR expr
    '''
    p[0] = make_binary(p.lineno(2), 'XOR', p[1], p[3], lambda x, y: (x and not y) or (not x and y))


def p_expr_BXOR_expr(p):
    ''' expr : expr BXOR expr
    '''
    p[0] = make_binary(p.lineno(2), 'BXOR', p[1], p[3], lambda x, y: x ^ y)


def p_expr_AND_expr(p):
    ''' expr : expr AND expr
    '''
    p[0] = make_binary(p.lineno(2), 'AND', p[1], p[3], lambda x, y: x and y)


def p_expr_BAND_expr(p):
    ''' expr : expr BAND expr
    '''
    p[0] = make_binary(p.lineno(2), 'BAND', p[1], p[3], lambda x, y: x & y)


def p_NOT_expr(p):
    ''' expr : NOT expr
    '''
    p[0] = make_unary(p.lineno(1), 'NOT', p[2], lambda x: not x)


def p_BNOT_expr(p):
    ''' expr : BNOT expr
    '''
    p[0] = make_unary(p.lineno(1), 'BNOT', p[2], lambda x: ~x)


def p_lp_expr_rp(p):
    ''' expr : LP expr RP
    '''
    p[0] = p[2]


def p_cast(p):
    ''' expr : CAST LP numbertype COMMA expr RP
    '''
    p[0] = make_typecast(p[3]._type, p[5])


def p_number_expr(p):
    ''' expr : NUMBER
    '''
    p[0] = Tree.makenode(SymbolNUMBER(p[1], lineno = p.lineno(1)))


def p_expr_PI(p):
    ''' expr : PI
    '''
    p[0] = Tree.makenode(SymbolNUMBER(PI, _type = 'float', lineno = p.lineno(1)))


def p_number_line(p):
    ''' expr : __LINE__
    '''
    p[0] = Tree.makenode(SymbolNUMBER(p.lineno(1), lineno = p.lineno(1)))


def p_expr_string(p):
    ''' expr : string
    '''
    p[0] = p[1]


def p_string_func_call(p):
    ''' string : func_call substr
    '''
    p[0] = make_strslice(p.lineno(1), p[1], p[2][0], p[2][1])


def p_string_str(p):
    ''' string : STRC
    '''
    p[0] = Tree.makenode(SymbolSTRING(p[1], p.lineno(1)))


def p_string_lprp(p):
    ''' string : string LP RP
    '''
    p[0] = p[1]


def p_string_lp_expr_rp(p):
    ''' string : string LP expr RP
    '''
    p[0] = make_strslice(p.lineno(2), p[1], p[3], p[3])


def p_expr_id_substr(p):
    ''' string : ID substr
    '''
    id = Tree.makenode(SYMBOL_TABLE.make_var(p[1], p.lineno(1), 'string'))
    p[0] = None
    if id is None:
        return

    id.symbol.accessed = True
    p[0] = make_strslice(p.lineno(1), id, p[2][0], p[2][1])


def p_string_substr(p):
    ''' string : string substr
    '''
    p[0] = make_strslice(p.lineno(1), p[1], p[2][0], p[2][1])


def p_string_expr_lp(p):
    ''' string : LP expr RP substr
    '''
    if p[1]._type != 'string':
        syntax_error(p.lexer.lineno, "Expected a 'string' type expression. Got '%s' one instead" % NAME_TYPES[p[1]._type])
        p[0] = None
    else:
        p[0] = make_strslice(p.lexer.lineno, p[1], p[2][0], p[2][1])


def p_subind_str(p):
    ''' substr : LP expr TO expr RP
    '''
    p[0] = (make_typecast('u16', p[2]), make_typecast('u16', p[4]))


def p_subind_strTO(p):
    ''' substr : LP TO expr RP
    '''
    p[0] = (make_typecast('u16', Tree.makenode(SymbolNUMBER(0, lineno = p.lineno(2)))), make_typecast('u16', p[3]))


def p_subind_TOstr(p):
    ''' substr : LP expr TO RP
    '''
    p[0] = (make_typecast('u16', p[2]), make_typecast('u16', Tree.makenode(SymbolNUMBER(65535, lineno = p.lineno(4)))))


def p_subind_TO(p):
    ''' substr : LP TO RP
    '''
    p[0] = (make_typecast('u16', Tree.makenode(SymbolNUMBER(0, lineno = p.lineno(2)))), \
            make_typecast('u16', Tree.makenode(SymbolNUMBER(65535, lineno = p.lineno(3)))))


def p_exprstr_file(p):
    ''' expr : __FILE__
    '''
    p[0] = Tree.makenode(SymbolSTRING(FILENAME, p.lineno(1)))


def p_id_expr(p):
    ''' expr : ID
    '''
    entry = SYMBOL_TABLE.get_id_or_make_var(p[1], p.lineno(1))
    if entry is None:
        p[0] = None
        return

    entry.accessed = True
    p[0] = Tree.makenode(entry)

    if p[0]._class == 'array' and not LET_ASSIGNEMENT:
        syntax_error(p.lineno(1), "Variable '%s' is an array and cannot be used in this context" % p[1])
        p[0] = None
    elif p[0].symbol.kind == 'function': # Function call with 0 args
        p[0] = make_call(p[1], p.lineno(1), make_arg_list(None))
    elif p[0].symbol.kind == 'sub': # Forbidden for subs
        syntax_error(p.lineno(1), "'%s' is SUB not a FUNCTION" % p[1])
        p[0] = None


def p_addr_of_id(p):
    ''' expr : ADDRESSOF ID
    '''
    entry = SYMBOL_TABLE.make_id(p[2], p.lineno(2))
    if entry is None:
        p[0] = None
        return

    entry.accessed = True
    access = Tree.makenode(entry)
    result = make_unary(p.lineno(1), 'ADDRESS', access, _type = 'u16')

    if is_dynamic(entry):
        p[0] = result
    else:
        p[0] = make_constexpr(p.lineno(1), result)


def p_expr_funccall(p):
    ''' expr : func_call
    '''
    p[0] = p[1]


def p_idcall_expr(p):
    ''' func_call : ID arg_list
    ''' # This can be a function call, an array call or a string index
    p[0] = make_call(p[1], p.lineno(1), p[2])
    if p[0] is None:
        return

    if p[0].token in ('STRSLICE', 'ID'):
        entry = SYMBOL_TABLE.get_id_or_make_var(p[1], p.lineno(1))
        entry.accessed = True
        return

    # Both array accesses and functions are tagged as functions
    # functions also has the _class attribute set to 'function'
    p[0].symbol.entry.set_kind('function', p.lineno(1))
    p[0].symbol.entry.accessed = True


def p_addr_of_func_call(p):
    ''' expr : ADDRESSOF ID arg_list
    '''
    p[0] = None

    if p[3] is None:
        return

    result = make_array_access(p[2], p.lineno(2), p[3])
    if result is None:
        return

    (variable, access, offset) = result
    variable.accessed = True
    p[0] = make_unary(p.lineno(1), 'ADDRESS', access, _type = 'u16')


def p_arg_list(p):
    ''' arg_list : LP RP
    '''
    p[0] = make_arg_list(None)


def p_arg_list_arg(p):
    ''' arg_list : LP arguments RP
    '''
    p[0] = p[2]


def p_arguments(p):
    ''' arguments : arguments COMMA expr
    '''
    p[0] = make_arg_list(p[1], make_argument(p[3], p.lineno(2)))


def p_argument(p):
    ''' arguments : expr
    '''
    p[0] = make_arg_list(make_argument(p[1], p.lineno(1)))


def p_funcdecl(p):
    ''' function_declaration : function_header function_body
    '''
    if p[1] is None:
        p[0] = None
        return

    p[0] = p[1]
    p[0].symbol.local_symbol_table = SYMBOL_TABLE.table[0]
    p[0].symbol.locals_size = SYMBOL_TABLE.end_function_body()
    FUNCTION_LEVEL.pop()
    p[0].next.append(p[2])

    entry = p[0].symbol.entry
    if entry.forwarded:
        entry.forwarded = False


def p_funcdeclforward(p):
    ''' function_declaration : DECLARE function_header
    '''
    if p[2] is None:
        if FUNCTION_LEVEL:
            FUNCTION_LEVEL.pop()
        return

    if p[2].symbol.entry.forwarded:
        syntax_error(p.lineno(1), "duplicated declaration for function '%s'" % p[2].symbol.entry.id)
    
    p[2].symbol.entry.forwarded = True
    FUNCTION_LEVEL.pop()


def p_function_header(p):
    ''' function_header : function_def param_decl typedef NEWLINE
                        | function_def param_decl typedef CO
    '''
    if p[1] is None or p[2] is None:
        p[0] = None
        return

    forwarded = p[1].symbol.entry.forwarded

    p[0] = p[1]
    p[0].next.append(p[2])
    p[0].symbol.params_size = p[2].size

    previous_type = p[0]._type
    if not p[3].symbol.implicit or p[0].symbol.entry._type is None:
        p[0]._type = p[3]._type

    if forwarded and previous_type != p[0]._type:
        syntax_error_func_type_mismatch(p.lineno(4), p[0].symbol.entry)
        p[0] = None
        return

    if forwarded: # Was predeclared, check parameters match
        p1 = p[0].symbol.entry.params.next # Parameter list previously declared
        p2 = p[2].next

        if len(p1) != len(p2):
            syntax_error_parameter_mismatch(p.lineno(4), p[0].symbol.entry)
            p[0] = None
            return

        for a, b in zip(p1, p2):
            e1 = a.symbol.entry
            e2 = b.symbol.entry

            if e1.id != e2.id:
                warning(p.lineno(4), "Parameter '%s' in function '%s' has been renamed to '%s'" % 
                        (e1.id, p[0].symbol.entry.id, e2.id))

            if e1._type != e2._type or e1.byref != e2.byref:
                syntax_error_parameter_mismatch(p.lineno(4), p[0].symbol.entry)
                p[0] = None
                return

    p[0].symbol.entry.params = p[2]

    if FUNCTION_LEVEL[-1].kind == 'sub' and not p[3].symbol.implicit:
        syntax_error(p.lineno(4), 'SUBs cannot have a return type definition')
        p[0] = None
        return

    if p[0].symbol.entry.convention == '__fastcall__' and p[2].symbol.count > 1:
        kind = 'SUB' if FUNCTION_LEVEL[-1].kind == 'sub' else 'FUNCTION'
        warning(p.lineno(4), "%s '%s' declared as FASTCALL with %i parameters" % (kind, p[0].symbol.entry.id, p[2].symbol.count))


def p_function_error(p):
    ''' function_declaration : function_header program END error NEWLINE
    '''
    p[0] = None
    syntax_error(p.lineno(3), "Unexpected token 'END'. Expected 'END FUNCTION' or 'END SUB' instead.")


def p_function_def(p):
    ''' function_def : FUNCTION convention ID
                     | SUB convention ID
    '''
    p[0] = make_func_declaration(p[3], p.lineno(3))
    SYMBOL_TABLE.start_function_body(p[3])
    FUNCTION_LEVEL.append(SYMBOL_TABLE.get_id_entry(p[3]))
    FUNCTION_LEVEL[-1].convention = p[2]

    if p[0] is not None:
        FUNCTION_LEVEL[-1].set_kind(p[1].lower(), p.lineno(1)) # Must be 'function' or 'sub'


def p_convention(p):
    ''' convention :
                   | STDCALL
    '''
    p[0] = '__stdcall__'


def p_convention2(p):
    ''' convention : FASTCALL
    '''
    p[0] = '__fastcall__'


def p_param_decl_none(p):
    ''' param_decl :
                   | LP RP
    '''
    p[0] = make_param_list(None)


def p_param_decl(p):
    ''' param_decl : LP param_decl_list RP
    '''
    p[0] = p[2]


def p_param_decl_errpr(p):
    ''' param_decl : LP error RP
    '''
    p[0] = None


def p_param_decl_list(p):
    ''' param_decl_list : param_definition
    '''
    p[0] = make_param_list(p[1])


def p_param_decl_list2(p):
    ''' param_decl_list : param_decl_list COMMA param_definition
    '''
    p[0] = make_param_list(p[1], p[3])


def p_param_byref_definition(p):
    ''' param_definition : BYREF param_def
    '''
    p[0] = p[2]

    if p[0] is not None:
        p[0].symbol.byref = p[0].symbol.entry.byref = True


def p_param_byval_definition(p):
    ''' param_definition : BYVAL param_def
    '''
    p[0] = p[2]

    if p[0] is not None:
        p[0].symbol.byref = p[0].symbol.entry.byref = False


def p_param_definition(p):
    ''' param_definition : param_def
    '''
    p[0] = p[1]
    if p[0] is not None:
        p[0].symbol.byref = p[0].symbol.entry.byref = OPTIONS.byref.value


def p_param_def_type(p):
    ''' param_def : ID typedef
    '''
    p[0] = make_param_decl(p[1], p.lineno(1), p[2])


def p_function_body(p):
    ''' function_body : program END FUNCTION
                      | program END SUB
                      | END FUNCTION
                      | END SUB
    '''
    itoken = 2 if p[1] == 'END' else 3

    if len(FUNCTION_LEVEL) == 0:
        syntax_error(p.lineno(3), "Unexpected token 'END %s'. No Function or Sub has been defined." % p[2])
        p[0] = None
        return

    a = FUNCTION_LEVEL[-1].kind
    if a is None: # This function/sub was not correctly declared, so exit now
        p[0] = None
        return

    b = p[itoken].lower()

    if a != b:
        syntax_error(p.lineno(itoken), "Unexpected token 'END %s'. Should be 'END %s'" % (b.upper(), a.upper()))
        p[0] = None
    else:
        p[0] = None if p[1] == 'END' else p[1]


def p_typedef_empty(p):
    ''' typedef :
    ''' # Epsilon. Defaults to float
    p[0] = make_type(DEFAULT_TYPE, p.lexer.lineno, implicit = True)


def p_typedef(p):
    ''' typedef : AS type
    ''' # Epsilon. Defaults to float
    p[0] = make_type(p[2], p.lineno(2), implicit = False)


def p_type(p):
    ''' type : BYTE
             | UBYTE
             | INTEGER
             | UINTEGER
             | LONG
             | ULONG
             | FIXED
             | FLOAT
             | STRING
    '''
    p[0] = p[1]


# Some preprocessor directives
def p_preprocessor_line(p):
    ''' preproc_line : preproc_line_line NEWLINE
    '''

def p_preprocessor_line_line(p):
    ''' preproc_line_line : _LINE INTEGER
    '''
    p.lexer.lineno = int(p[2]) + p.lexer.lineno - p.lineno(2)


def p_preprocessor_line_line_file(p):
    ''' preproc_line_line : _LINE INTEGER STRING
    '''
    global FILENAME

    p.lexer.lineno = int(p[2]) + p.lexer.lineno - p.lineno(3) - 1
    FILENAME = p[3]


def p_preproc_line_init(p):
    ''' preproc_line : _INIT ID
    '''
    INITS.add(p[2])


def p_preproc_line_require(p):
    ''' preproc_line : _REQUIRE STRING
    '''
    REQUIRES.add(p[2])


def p_preproc_line_option(p):
    ''' preproc_line : _PRAGMA ID EQ ID
                     | _PRAGMA ID EQ STRING
                     | _PRAGMA ID EQ INTEGER
    '''
    OPTIONS.option(p[2]).value = p[4]


def p_preproc_line_push(p):
    ''' preproc_line : _PRAGMA _PUSH LP ID RP
    '''
    OPTIONS.option(p[4]).push()


def p_preproc_line_pop(p):
    ''' preproc_line : _PRAGMA _POP LP ID RP
    '''
    OPTIONS.option(p[4]).pop()


# ----------------------------------------
# INTERNAL BASIC Functions
# These will be implemented in the TRADuctor
# module as a CALL to an ASM function
# ----------------------------------------

def p_expr_usr(p):
    ''' expr : USR expr %prec UMINUS
    '''
    if p[2]._type == 'string':
        p[0] = make_unary(p.lineno(1), 'USR_STR', p[2], _type = 'u16')
    else:
        p[0] = make_unary(p.lineno(1), 'USR', make_typecast('u16', p[2]), _type = 'u16')


def p_expr_rnd(p):
    ''' expr : RND
             | RND LP RP
    '''
    p[0] = make_unary(p.lineno(1), 'RND', None, _type = 'float')


def p_expr_peek(p):
    ''' expr : PEEK expr %prec UMINUS
    '''
    p[0] = make_unary(p.lineno(1), 'PEEK', make_typecast('u16', p[2]), _type = 'u8')


def p_expr_peek_type(p):
    ''' expr : PEEK LP numbertype COMMA expr RP
    '''
    p[0] = make_unary(p.lineno(1), 'PEEK', make_typecast('u16', p[5]), _type = p[3]._type)


def p_expr_in(p):
    ''' expr : IN expr %prec UMINUS
    '''
    p[0] = make_unary(p.lineno(1), 'IN', make_typecast('u16', p[2]), _type = 'u8')


def p_len(p):
    ''' expr : LEN expr %prec UMINUS
    '''
    arg = p[2]
    if arg is None:
        p[0] = None
    elif arg._class == 'array':
        p[0] = Tree.makenode(SymbolNUMBER(arg.symbol.bounds.size, lineno = p.lineno(1))) # Do constant folding
    elif arg._type != 'string':
        syntax_error_expected_string(p.lineno(1), NAME_TYPES[arg._type])
        p[0] = None
    elif is_string(arg): # Constant string?
        p[0] = Tree.makenode(SymbolNUMBER(len(arg.text), lineno = p.lineno(1))) # Do constant folding
    else:
        p[0] = make_unary(p.lineno(1), 'LEN', arg, _type = 'u16')


def p_sizeof(p):
    ''' expr : SIZEOF LP type RP
             | SIZEOF LP ID RP
    '''
    if p[3].lower() in TYPE_NAMES.keys():
        p[0] = Tree.makenode(SymbolNUMBER(TYPE_SIZES[TYPE_NAMES[p[3].lower()]], lineno = p.lineno(3)))
    else:
        entry = SYMBOL_TABLE.get_id_or_make_var(p[3], p.lineno(1))
        p[0] = Tree.makenode(SymbolNUMBER(TYPE_SIZES[entry._type], lineno = p.lineno(3)))


def p_str(p):
    ''' string : STR LP expr RP %prec UMINUS
    '''
    if is_number(p[3]): # A constant is converted to string directly
        p[0] = Tree.makenode(SymbolSTRING(str(p[3].value), p.lineno(1)))
    else:
        p[0] = make_unary(p.lineno(1), 'STR', make_typecast('float', p[3]), _type = 'string')


def p_inkey(p):
    ''' string : INKEY
    '''
    p[0] = make_unary(p.lineno(1), 'INKEY', None, _type = 'string')


def p_chr(p):
    ''' string : CHR arg_list
    '''
    if p[2].symbol.count < 1:
        syntax_error(p.lineno(1), "CHR$ function need at less 1 parameter")
        p[0] = None
        return

    is_constant = True
    constant = ''
    for i in range(p[2].symbol.count): # Convert every argument to 8bit unsigned
        p[2].next[i] = make_typecast('u8', p[2].next[i])
        is_constant = is_constant and is_number(p[2].next[i].next[0])
        if is_constant:
            constant += chr(int(p[2].next[i].next[0].value) & 0xFF)

    if is_constant: # Can do constant folding?
        p[0] = Tree.makenode(SymbolSTRING(constant, p.lineno(1)))
    else:
        p[0] = make_unary(p.lineno(1), 'CHR', p[2], _type = 'string')


def p_val(p):
    ''' expr : VAL expr %prec UMINUS
    '''
    def val(s):
        try:
            x = float(s)
        except:
            x = 0
            warning(p.lineno(1), "Invalid string numeric constant '%s' evaluated as 0" % s)
        return x


    if p[2]._type != 'string':
        syntax_error_expected_string(p.lineno(1), NAME_TYPES[p[2]._type])
        p[0] = None
    else:
        p[0] = make_unary(p.lineno(1), 'VAL', p[2], lambda x: val(x), _type = 'float')


def p_code(p):
    ''' expr : CODE expr %prec UMINUS
    '''
    def asc(x):
        if len(x):
            return ord(x[0])

        return 0

    if p[2]._type != 'string':
        syntax_error_expected_string(p.lineno(1), NAME_TYPES[p[2]._type])
        p[0] = None
    else:
        p[0] = make_unary(p.lineno(1), 'CODE', p[2], lambda x: asc(x), _type = 'u8')



def p_sgn(p):
    ''' expr : SGN expr %prec UMINUS
    '''
    def sgn(s):
        if x < 0: return -1
        if x > 0: return 1

        return 0

    if p[2]._type == 'string':
        syntax_error(p.lineno(1), "Expected a numeric expression, got 'string' instead")
        p[0] = None
    else:
        if is_unsigned(p[2]) and not is_number(p[2]):
            warning(p.lineno(1), "Sign of unsigned value is always 0 or 1")

        p[0] = make_unary(p.lineno(1), 'SGN', p[2], lambda x: sgn(x), _type = 'i8')



# ----------------------------------------
# Trigonometrics
# ----------------------------------------
def p_expr_sin(p):
    ''' expr : SIN expr %prec UMINUS
    '''
    p[0] = make_unary(p.lineno(1), 'SIN', make_typecast('float', p[2]), lambda x: math.sin(x), _type = 'float')


def p_expr_cos(p):
    ''' expr : COS expr %prec UMINUS
    '''
    p[0] = make_unary(p.lineno(1), 'COS', make_typecast('float', p[2]), lambda x: math.cos(x), _type = 'float')


def p_expr_tan(p):
    ''' expr : TAN expr %prec UMINUS
    '''
    p[0] = make_unary(p.lineno(1), 'TAN', make_typecast('float', p[2]), lambda x: math.tan(x), _type = 'float')


def p_expr_asin(p):
    ''' expr : ASN expr %prec UMINUS
    '''
    p[0] = make_unary(p.lineno(1), 'ASN', make_typecast('float', p[2]), lambda x: math.asin(x), _type = 'float')


def p_expr_acos(p):
    ''' expr : ACS expr %prec UMINUS
    '''
    p[0] = make_unary(p.lineno(1), 'ACS', make_typecast('float', p[2]), lambda x: math.acos(x), _type = 'float')


def p_expr_atan(p):
    ''' expr : ATN expr %prec UMINUS
    '''
    p[0] = make_unary(p.lineno(1), 'ATN', make_typecast('float', p[2]), lambda x: math.atan(x), _type = 'float')


# ----------------------------------------
# Square root, Exponent and logarithms
# ----------------------------------------
def p_expr_exp(p):
    ''' expr : EXP expr %prec UMINUS
    '''
    p[0] = make_unary(p.lineno(1), 'EXP', make_typecast('float', p[2]), lambda x: math.exp(x), _type = 'float')


def p_expr_logn(p):
    ''' expr : LN expr %prec UMINUS
    '''
    p[0] = make_unary(p.lineno(1), 'LN', make_typecast('float', p[2]), lambda x: math.log(x), _type = 'float')


def p_expr_sqrt(p):
    ''' expr : SQR expr %prec UMINUS
    '''
    p[0] = make_unary(p.lineno(1), 'SQR', make_typecast('float', p[2]), lambda x: math.sqrt(x), _type = 'float')


# ----------------------------------------
# Other important functions
# ----------------------------------------
def p_expr_int(p):
    ''' expr : INT expr %prec UMINUS
    '''
    p[0] = make_typecast('i32', p[2])


def p_abs(p):
    ''' expr : ABS expr %prec UMINUS
    '''
    if is_unsigned(p[2]):
        p[0] = p[2]
        warning(p.lineno(1), "Redundant operation ABS for unsigned value")
        return

    p[0] = make_unary(p.lineno(1), 'ABS', p[2], lambda x: x if x >= 0 else -x)


# ----------------------------------------
# The yyerror function
# ----------------------------------------
def p_error(p):
    global has_errors

    has_errors += 1

    if p is not None:
        if p.type != 'NEWLINE':
            msg = "%s:%i: Syntax Error. Unexpected token '%s' <%s>" % (FILENAME, p.lexer.lineno, p.value, p.type)
        else:
            msg = "%s:%i: Unexpected end of file" % (FILENAME, p.lexer.lineno)
    else:
        #msg = "Unknown internal error. Contact developer(s)"
        import zxblex
        msg = "%s:%i: Unexpected end of file" % (FILENAME, zxblex.lexer.lineno)

    if ERROR_output is None:
        print msg
    else:
        ERROR_output.write("%s\n" % msg)


# ----------------------------------------
# Generic syntax error routine
# ----------------------------------------
def syntax_error(lineno, msg):
    global has_errors

    if has_errors > OPTIONS.max_syntax_errors.value:
        msg = 'Too many errors. Giving up!'

    msg = "%s:%i: %s" % (FILENAME, lineno, msg)
    if ERROR_output is None:
        print msg
    else:
        ERROR_output.write('%s\n' % msg)

    if has_errors > OPTIONS.max_syntax_errors.value:
        sys.exit(1)

    has_errors += 1


# ----------------------------------------
# Generic syntax error routine
# ----------------------------------------
def warning(lineno, msg):
    global has_warnings

    msg = "%s:%i: warning: %s" % (FILENAME, lineno, msg)
    if ERROR_output is None:
        print msg
    else:
        ERROR_output.write('%s\n' % msg)

    has_warnings += 1



# ----------------------------------------
# Syntax error: Expected string instead of
#               numeric expression.
# ----------------------------------------
def syntax_error_expected_string(lineno, _type):
    syntax_error(lineno, "Expected a 'string' type expression, got '%s' instead" % _type)


# ----------------------------------------
# Syntax error: FOR variable should be X
#               instead of Y
# ----------------------------------------
def syntax_error_wrong_for_var(lineno, x, y):
    syntax_error(lineno, "FOR variable should be '%s' instead of '%s'" % (x, y))


# ----------------------------------------
# Syntax error: Initializer expression is
#               not constant
# ----------------------------------------
def syntax_error_not_constant(lineno):
    syntax_error(lineno, "Initializer expression is not constant.")


# ----------------------------------------
# Syntax error: Id is neither an array nor
#               a function
# ----------------------------------------
def syntax_error_not_array_nor_func(lineno, varname):
    syntax_error(lineno, "'%s' is neither an array nor a function." % varname)


# ----------------------------------------
# Syntax error: function redefinition type
#               mismatch
# ----------------------------------------
def syntax_error_func_type_mismatch(lineno, entry):
    syntax_error(lineno, "Function '%s' (previusly declared at %i) type mismatch" % (entry.id, entry.lineno))


# ----------------------------------------
# Syntax error: function redefinition parm.
#               mismatch
# ----------------------------------------
def syntax_error_parameter_mismatch(lineno, entry):
    syntax_error(lineno, "Function '%s' (previously declared at %i) parameter mismatch" % (entry.id, entry.lineno))


# ----------------------------------------
# Warning: Using default implicit type 'x'
# ----------------------------------------
def warning_implicit_type(lineno, id, _type = None):
    if _type is None:
        _type = DEFAULT_TYPE

    warning(lineno, "Using default implicit type '%s' for '%s'" % (_type, id))


# ----------------------------------------
# Warning: Condition is always false/true
# ----------------------------------------
def warning_condition_is_always(lineno, cond = False):
    warning(lineno, "Condition is always %s" % cond)


# ----------------------------------------
# Warning: Conversion may lose significant digits
# ----------------------------------------
def warning_conversion_lose_digits(lineno):
    warning(lineno, 'Conversion may lose significant digits')


# ----------------------------------------
# Warning: Empty loop
# ----------------------------------------
def warning_empty_loop(lineno):
    warning(lineno, 'Empty loop')



# ----------------------------------------
# Initialization
# ----------------------------------------

parser = yacc.yacc(method = 'LALR')
ast = None
data_ast = None # Global Variables AST
optemps = OpcodesTemps()

