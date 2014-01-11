#!/usr/bin/env python
# -*- coding: utf-8 -*-
# vim: ts=4:et:sw=4:

# ----------------------------------------------------------------------
# Copyleft (K), Jose M. Rodriguez-Rosa (a.k.a. Boriel)
#
# This program is Free Software and is released under the terms of
#                    the GNU General License
# ----------------------------------------------------------------------

from debug import __DEBUG__

from symbols.var import SymbolVAR as VAR
from symbols.vararray import SymbolVARARRAY as VARARRAY
from symbols.typecast import SymbolTYPECAST as TYPECAST
from symbols.type_ import SymbolTYPE as TYPEDEF
from symbols.type_ import SymbolBASICTYPE as BASICTYPE
from symbols.type_ import SymbolTYPEREF as TYPEREF
from symbols.label import SymbolLABEL as LABEL
from symbols.function import SymbolFUNCTION as FUNCTION
from symbols.paramdecl import SymbolPARAMDECL as PARAMDECL
from symbols.symbol_ import Symbol

import global_
from config import OPTIONS

from errmsg import syntax_error
from errmsg import warning_implicit_type
from errmsg import syntax_error_func_type_mismatch
from errmsg import syntax_error_not_array_nor_func

from constants import DEPRECATED_SUFFIXES
from constants import SUFFIX_TYPE
from constants import SCOPE
from constants import CLASS
from constants import TYPE
from constants import PTR_TYPE

from check import is_number
from api.decorator import check_type


# ----------------------------------------------------------------------
# Scope class:
# ----------------------------------------------------------------------

# ----------------------------------------------------------------------
# Symbol table. Each id level will push a new symbol table
# ----------------------------------------------------------------------
class SymbolTable(object):
    ''' Implements a symbol table.

    This symbol table stores symbols for types, functions and variables.
    Variables can be in the global or local scope. Each symbol can be
    retrieved by it's name.

    Parameters are treated like local variables, but use a different
    class (PARAMDECL) and has their scope set to SCOPE.parameter.
    Arrays are also a derived class from var. The scope rules above
    also apply for arrays (local, global), except for parameters.

    The symbol table is implemented as a list of Scope instances.
    To get a symbol by its id, just call symboltable.get_id(id, scope).
    If scope is not given, it will search from the current scope to
    the global one, 'un-nesting' them.

    An scope is referenced by a number (it's position in the list).
    Do not use 0 to reference the global scope. Use symboltable.global_scope
    and symboltable.current_scope to get such numbers.

    Accesing symboltable[symboltable.current_scope] returns an Scope object.
    '''

    class Scope(object):
        ''' Implements an Scope.

        An Scope is no more than a dictionary.

        To get a symbol, just access it by it's name. So scope['a'] will
        return the 'a' symbol (e.g. a declared variable 'a') or None
        if nothing is declared in that scope (no KeyError exception is raise
        if the identifier is not defined).

        The caseins dict stores the symbol names in lowercase only if
        the global OPTION ignore case is enabled (True). This is because
        most BASIC dialects are case insensitive. 'caseins' will be used
        as a fallback if the symbol name does not exists.

        On init() the parent mangle can be stored. The mangle is a prefix
        added to every symbol to avoid name collision.

        E.g. for a global var o function, the mangle will be '_'. So
        'a' will be output in asm as '_a'. For nested scopes, the mangled
        is composed as _functionname_varname. So a local variable in function
        myFunct will be output as _myFunct_a.
        '''
        def __init__(self, mangle=''):
            self.symbols = {}
            self.caseins = {}
            self.parent_mangle = mangle

        def __getitem__(self, key):
            return self.symbols.get(key, self.caseins.get(key.lower(), None))

        def __setitem__(self, key, value):
            assert isinstance(value, Symbol)
            self.symbols[key] = value
            if value.caseins:  # Declared with case insensitive option?
                self.caseins[key.lower()] = value

        def __delitem__(self, key):
            symbol = self[key]
            if symbol is None:
                return
            del self.symbols[key]
            del self.caseins[key.lower()]

        def values(self):
            return self.symbols.values()

        def keys(self):
            return self.symbols.keys()


    def __init__(self):
        ''' Initializes the Symbol Table
        '''
        self.mangle = ''      # Prefix for local variables
        self.table = [SymbolTable.Scope(self.mangle)]
        #self.mangles = []    # Mangles stack
        #self.size = 0         # Size (in bytes) of variables
        #self.caseins = [{}]  # Case insensitive identifiers
        self.basic_types = {}

        # Initialize canonical types
        for type_ in TYPE.types:
            self.basic_types[type_] = self.declare_type(BASICTYPE(type_))

    @property
    def current_scope(self):
        return len(self.table) - 1

    @property
    def global_scope(self):
        return 0

    def get_entry(self, id_, scope=None):
        ''' Returns the ID entry stored in self.table, starting
        by the first one. Returns None if not found.
        If scope is not None, only the given scope is searched.
        '''
        if id_[-1] in DEPRECATED_SUFFIXES:
            id_ = id_[:-1]  # Remove it

        if scope is not None:
            assert len(self.table) > scope
            return self[scope][id_]

        for sc in self:
            if sc[id_] is not None:
                return sc[id_]

        '''
        idL = id_.lower()

        if scope is not None:
            if len(self.table) > scope:
                result = self[scope].get(id_, None)
                if result is None:
                    result = self.caseins[scope].get(idL, None)
            return result  # Not found

        # traverses scopes from the most recent to 0 (global)
        for i in range(self.current_scope, -1, -1):
            try:
                return self[i][id_]
            except KeyError:
                pass
            try:
                return self.caseins[i][idL]
            except KeyError:
                pass
        '''

        return None  # Not found

    def declare(self, id_, lineno, entry):
        ''' Check there is no 'id' already declared in the current scope, and
            creates and returns it. Otherwise, returns None,
            and the caller function raises the syntax/semantic error.
            Parameter entry is the SymbolVAR, SymbolVARARRAY, etc. instance
        '''
        id2 = id_
        type_ = entry.type_

        if id2[-1] in DEPRECATED_SUFFIXES:
            id2 = id2[:-1]  # Remove it
            type_ = TYPEREF(self.basic_types[SUFFIX_TYPE[id_[-1]]], lineno)  # Overrides type_

        '''
        # Checks if already declared
        if self[self.current_scope].get(id2, None) is not None:
            return None

        # Checks if already declared (case insensitive)
        if self.caseins[self.current_scope].get(id2.lower(), None):
            return None
        '''

        # Checks if already declared
        if self[self.current_scope][id2] is not None:
            return None

        entry.caseins = OPTIONS.case_insensitive.value
        self[self.current_scope][id2] = entry
        entry.name = id2  # Removes DEPRECATED SUFFIXES if any

        '''
        if entry.caseins:
            self.caseins[self.current_scope][id2.lower()] = entry
        '''

        if isinstance(entry, TYPEDEF):
            return entry  # If it's a type declaration, we're done

        # HINT: The following should be done by the respective callers!
        entry.callable = None  # True if function, strings or arrays
        entry.forwarded = False  # True for a function header
        entry.mangled = '%s_%s' % (self.mangle, entry.name)  # Mangled name
        #entry.class_ = None  # TODO: important
        entry.type_ = type_  # HINT: Nonsense. Must be set at declaration or later

        return entry

    """
    def create_id(self, id_, lineno):
        ''' HINT: DEPRECATED: Use declare_id
        Check there is no 'id' already declared in the current scope.
        If it does exists raises an error. Otherwise creates and returns it.
        '''
        result = self.declare_id(id_, lineno)
        if result is None:
            if id_ not in self.table[self.current_scope].keys(): # is it case insensitive?
                id_ = id_.lower()

            syntax_error(lineno, 'Duplicated identifier "%s" (previous one at %s:%i)' %
                (id_, self.table[self.current_scope][id_].filename,
                 self.table[self.current_scope][id_].lineno))

        return result

    def get_or_create(self, id_, lineno, scope=None):
        ''' HINT: DEPRECATED: use self.access
        Returns the ID entry if stored in self.table,
        otherwise, creates a new one.
        '''
        entry = self.get_entry(id_, scope)
        if entry is not None:
            return entry

        return self.create_id(id_, lineno)
    """

    # -------------------------------------------------------------------------
    # Symbol Table Checks
    # -------------------------------------------------------------------------
    def check_is_declared(self, id_, lineno, classname='identifier',
                          scope=None, show_error=True):
        ''' Checks if the given id is already defined in any scope
            or raises a Syntax Error.

            Note: classname is not the class attribute, but the name of
            the class as it would appear on compiler messages.
        '''
        result = self.get_entry(id_, scope)
        if isinstance(result, TYPEDEF):
            return True

        if result is None or not result.declared:
            if show_error:
                syntax_error(lineno, 'Undeclared %s "%s"' % (classname, id_))
            return False
        return True


    def check_is_undeclared(self, id_, lineno, classname='identifier',
                            scope=None, show_error=False):
        ''' The reverse of the above.

        Check the given identifier is not already declared. Returns True
        if OK, False otherwise.
        '''
        result = self.get_entry(id_, scope)
        if result is None or not result.declared:
            return True

        if scope is None:
            scope = self.current_scope

        if show_error:
            syntax_error(lineno,
                         'Duplicated %s "%s" (previous one at %s:%i)' %
                         (classname, id_, self.table[scope][id_].filename,
                         self.table[scope][id_].lineno))
        return False


    def check_class(self, id_, class_, lineno, scope=None):
        ''' Check the id is either undefined or defined with
        the given class.

        - If the identifier (e.g. variable) does not exists means
        it's undeclared, and returns True (OK).
        - If the identifier exists, but its class_ attribute is
        unknown yet (None), returns also True. This means the
        identifier has been referenced in advanced and it's undeclared.

        Otherwise fails returning False.
        '''
        assert CLASS.is_valid(class_)
        entry = self.get_entry(id_, scope)
        if entry is None or entry.class_ is None:  # Undeclared yet
            return True

        if entry.class_ != class_:
            if entry.class_ == CLASS.array:
                a1 = 'n'
            else:
                a1 = ''
            if class_ == CLASS.array:
                a2 = 'n'
            else:
                a2 = ''
            syntax_error(lineno, "identifier '%s' is a%s %s, not a%s %s" %
                         (id_, a1, entry.class_, a2, class_))
            return False

        return True

    # -------------------------------------------------------------------------
    # Function declaration methods
    # -------------------------------------------------------------------------
    def enter_scope(self, funcname):
        ''' Starts a new variable scope.

        Notice the *IMPORTANT* marked lines. This is the scheme a new
        scope is added, by pushing a new dict at the end (and popped later).
        '''
        self.table.append(SymbolTable.Scope(self.mangle))
        #self.mangles.append(self.mangle)
        self.mangle = '%s_%s' % (self.mangle, funcname)
        #self.table.append({})    # *IMPORTANT* new symbol table
        #self.caseins.append({})  # *IMPORTANT* new caseins dictionary
        global_.META_LOOPS.append(global_.LOOPS)  # saves current LOOPS state
        global_.LOOPS = []  # new LOOPS state

    def leave_scope(self):
        ''' Ends a function body and pops current scope out of the symbol table.
        '''
        def entry_size(entry):
            ''' For local variables and params, returns the real variable or
            local array size in bytes
            '''
            if entry.scope == SCOPE.global_ or \
                    entry.alias is not None:  # aliases or global variables = 0
                return 0

            if entry.class_ != CLASS.array:
                return entry.size

            return entry.memsize

        def sort_entries(entries):
            ''' Sort in-place entries according to it sizes in ascending order
            Sorting ascending is preferable, since this make local arrays,
            for example, to be declared later. This helps using IX+n scheme
            for parameters and leave the heavy HL + NN or IX + NN for arrays.
            '''
            for i in range(len(entries)):
                size = entry_size(entries[i])
                mi = i

                for j in range(i + 1, len(entries)):
                    size1 = entry_size(entries[j])
                    if size > size1:
                        size = size1
                        mi = j

                entries[mi], entries[i] = entries[i], entries[mi]

        entries = self.table[self.current_scope].values()
        sort_entries(entries)
        offset = 0

        for entry in entries:  # Symbols of the current level
            if entry.class_ is None:
                self.move_to_global_scope(entry.id_)

            if entry.class_ == CLASS.function:
                continue

            # Local variables offset
            if entry.class_ == CLASS.var and entry.scope == SCOPE.local:
                if entry.alias is not None:  # alias of another variable?
                    if entry.offset is None:
                        entry.offset = entry.alias.offset
                    else:
                        entry.offset = entry.alias.offset - entry.offset
                else:
                    offset += entry_size(entry)
                    entry.offset = offset

            if entry.class_ == CLASS.array and entry.scope == SCOPE.local:
                entry.offset = entry_size(entry) + offset
                offset = entry.offset

        self.mangle = self[self.current_scope].parent_mangle
        self.table.pop()
        #self.caseins.pop()
        global_.LOOPS = global_.META_LOOPS.pop()

        return offset

    # -------------------------------------------------------------------------
    # Scope Management
    # -------------------------------------------------------------------------
    def move_to_global_scope(self, id_):
        ''' If the given id is in the current scope, and there is more than
        1 scope, move the current id to the global scope and make it global.
        Labels need this.
        '''
        # In the current scope and more than 1 scope?
        if id_ in self.table[self.current_scope].keys() and len(self.table) > 1:
            self.table[self.global_scope][id_] = self.table[self.current_scope][id_]
            self.table[self.global_scope][id_].offset = None
            self.table[self.global_scope][id_].scope = SCOPE.global_
            del self.table[self.current_scope][id_]  # Removes it from the current scope

    def make_static(self, id_):
        ''' The given ID in the current scope is changed to 'global', but the
        variable remains in the current scope, if it's a 'global private'
        variable: A variable private to a function scope, but whose contents
        are not in the stack, not in the global variable area.
        These are called 'static variables' in C.

        A copy of the instance, but mangled, is also allocated in the global
        symbol table.
        '''
        entry = self.table[self.current_scope][id_]
        entry.scope = SCOPE.global_
        self.table[self.global_scope][entry.mangled_] = entry

    # -------------------------------------------------------------------------
    # Identifier Declaration (e.g DIM, FUNCTION, SUB, etc.)
    # -------------------------------------------------------------------------
    """
    def make_var(self, id_, lineno, default_type=None, scope=None):  # TODO: Deprecated. Removal pending
        '''
        Checks whether the id exist or not.
        If it exists, it must be a variable (not a function, array, constant,
        or label)
        '''
        if not self.check_class(id_, CLASS.var, lineno, scope):
            return None
        entry = self.get_or_create(id_, lineno, scope)
        if entry.declared:
            return entry
        entry.class_ = CLASS.var  # Make it a variable
        entry.callable = False
        entry.scope = SCOPE.local if len(self.table) > 1 else SCOPE.global_
        '''
        if entry.scope == SCOPE.global_:  # ***
            entry.t = entry.mangled
        else:  # local scope
            entry.t = global_.optemps.new_t()
            if entry._type == TYPE.string:
                entry.t = '$' + entry.t
        '''
        if entry.type_ is None:  # First time used?
            if default_type is None:
                default_type = global_.DEFAULT_TYPE
                warning(lineno, "Variable '%s' declared as '%s'" %
                        (id_, default_type))

            entry.type_ = default_type  # Default type is unknown
        return entry
    """

    def access_var(self, id_, lineno, scope=None, default_type=None, default_value=None):
        '''
        Since ZX BASIC allows access to undeclared variables, we must allow
        them, and *implicitly* declare them if they are not declared already.
        This function just checks if the id_ exists and returns its entry so.
        Otherwise, creates an implicit declared variable entry and returns it.
        '''
        result = self.get_entry(id_, scope)
        if result is None:
            if default_type is None:
                default_type = TYPEREF(self.basic_types[global_.DEFAULT_TYPE], lineno, implicit=True)

            return self.declare_variable(id_, lineno, default_type, default_value)

        if not self.check_class(id_, CLASS.var, lineno, scope):
            return None

        return result


    def access_func(self, id_, lineno, scope=None, default_type=None):
        '''
        Since ZX BASIC allows access to undeclared functions, we must allow
        them, and *implicitly* declare them if they are not declared already.
        This function just checks if the id_ exists and returns its entry so.
        Otherwise, creates an implicit declared variable entry and returns it.
        '''
        assert default_type is None or isinstance(default_type, TYPEREF)

        result = self.get_entry(id_, scope)
        if result is None:
            if default_type is None:
                default_type = TYPEREF(self.basic_types[global_.DEFAULT_TYPE], lineno, implicit=True)

            return self.declare_func(id_, lineno, default_type)

        if not self.check_class(id_, CLASS.function, lineno, scope):
            return None

        return result


    def access_call(self, id_, lineno):
        ''' Creates a func/array/string call. Checks if id is callable or not.
        An identifier is "callable" if it can be followed by a list of para-
        meters.
        This does not mean the id_ is a function, but that it allows the same
        syntax a function does:

        For example:
           - MyFunction(a, "hello", 5) is a Function so MyFuncion is callable
           - MyArray(5, 3.7, VAL("32")) makes MyArray identifier "callable".
           - MyString(5 TO 7) or MyString(5) is a "callable" string.
        '''
        entry = self.get_entry(id_)
        if entry is None:
            return self.access_func(id_, lineno)

        if entry.callable is False:  # Is it NOT callable?
            if entry.type_ != self.basic_types[TYPE.string]:
                syntax_error_not_array_nor_func(lineno, id_)
                return None
            else:
                # Ok, it is a string slice if it has 0 or 1 parameters
                return entry

        if entry.callable is None and entry.type_ == self.basic_types[TYPE.string]:
            # Ok, it is a string slice if it has 0 or 1 parameters
            entry.callable = False
            return entry

        # Mangled name (functions always has _name as mangled)
        # entry.mangled = '_%s' % entry.name
        # entry.callable = True  # HINT: must be true already
        return entry


    def declare_variable(self, id_, lineno, type_, default_value=None):
        ''' Like the above, but checks that entry.declared is False.
        Otherwise raises an error.

        Parameter default_value specifies an initialized variable, if set.
        '''
        assert isinstance(type_, TYPEREF)
        if not self.check_is_undeclared(id_, lineno, scope=self.current_scope, show_error=False):
            entry = self.get_entry(id_)
            if entry.scope == SCOPE.parameter:
                syntax_error(lineno,
                             "Variable '%s' already declared as a parameter "
                             "at %s:%i" % (id_, entry.filename, entry.lineno))
            else:
                syntax_error(lineno, "Variable '%s' already declared at "
                             "%s:%i" % (id_, entry.filename, entry.lineno))
            return None

        if not self.check_class(id_, CLASS.var, lineno):
            return None

        entry = (self.get_entry(id_, scope=self.current_scope) or
                 self.declare(id_, lineno, VAR(id_, lineno,
                                               class_=CLASS.var)))
        __DEBUG__("Entry %s declared with class %s at scope %i" % (entry.name, entry.class_, self.current_scope))

        if entry.type_ is None:
            entry.type_ = type_

        if entry.type_ != type_:
            if not type_.implicit and entry.type_ is not None:
                syntax_error(lineno,
                             "'%s' suffix is for type '%s' but it was "
                             "declared as '%s'" %
                             (id_, entry.type_, type_))
                return None
            # type_ = entry.type_  # TODO: Unused??

        entry.scope = SCOPE.global_ if self.current_scope == self.global_scope else SCOPE.local
        entry.callable = False
        #entry.class_ = CLASS.var  # Make it a variable
        entry.declared = True  # marks it as declared

        if entry.type_.implicit:
            warning_implicit_type(lineno, id_, entry.type_.name)

        if default_value is not None and entry.type_ != default_value.type_:
            if is_number(default_value):
                default_value = TYPECAST.make_node(entry.type_, default_value,
                                                   lineno)
                if default_value is None:
                    return None
            else:
                syntax_error(lineno,
                             "Variable '%s' declared as '%s' but initialized "
                             "with a '%s' value" %
                             (id_, entry.type_, default_value.type_))
                return None

        # HINT: Parameters and local variables must have it's .t member as '$name'
        if entry.scope != SCOPE.global_ and entry.type_ == self.basic_types[TYPE.string]:
            if entry.t[0] != '$':
                entry.t = '$' + entry.t

        if default_value is not None:
            if default_value.token != 'CONST':
                default_value = default_value.value

        entry.default_value = default_value
        return entry


    def declare_type(self, type_):
        ''' Declares a type.
        Checks its name is not already used in the current scope,
        and that it's not a basic type.

        Returns the given type_ Symbol, or None on error.
        '''
        assert isinstance(type_, TYPEDEF)
        # Checks it's not a basic type
        if not type_.is_basic and type_.name.lower() in TYPE.TYPE_NAMES.values():
            syntax_error(type_.lineno, "'%s' is a basic type and cannot be redefined" %
                         type_.name)
            return None

        if not self.check_is_undeclared(type_.name, type_.lineno, scope=self.current_scope, show_error=True):
            return None

        entry = self.declare(type_.name, type_.lineno, type_)
        return entry


    def declare_const(self, id_, lineno, type_, default_value):
        ''' Similar to the above. But declares a Constant.
        '''
        if not self.check_is_undeclared(id_, scope=self.current_scope, show_error=False):
            entry = self.get_entry(id_)
            if entry.scope == SCOPE.parameter:
                syntax_error(lineno,
                             "Constant '%s' already declared as a parameter "
                             "at %s:%i" % (id_, entry.filename, entry.lineno))
            else:
                syntax_error(lineno, "Constant '%s' already declared at "
                             "%s:%i" % (id_, entry.filename, entry.lineno))
            return None

        entry = self.declare_variable(id_, lineno, type_, default_value,
                                      'constant')
        if entry is None:
            return None

        entry.class_ = CLASS.const
        entry.value = default_value
        return entry


    def declare_label(self, id_, lineno):
        ''' Declares a label (line numbers are also labels).
            Unlike variables, labels are always global.
        '''
        # TODO: consider to make labels private
        id_ = str(id_)
        if not self.check_is_undeclared(id_, lineno, 'label'):
            entry = self.get_entry(id_)
            syntax_error(lineno, "Label '%s' already declared at %s:%i" %
                         (id_, entry.filename, entry.lineno))
            return entry

        entry = self.declare(id_, lineno, LABEL(id_, lineno))
        if entry is None:
            return None

        if entry.declared:
            if entry.is_line_number:
                syntax_error(lineno, "Duplicated line number '%s'. "
                             "Previous was at %i" % (entry.name, entry.lineno))
            else:
                syntax_error(lineno, "Label '%s' already declared at line %i" %
                             (id_, entry.lineno))
            return None

        if id_[0] == '.':
            id_ = id_[1:]
            # HINT: ??? Mangled name. Just the label, 'cause it starts with '.'
            entry.mangled = '%s' % id_
        else:
            # HINT: Mangled name. Labels are __LABEL__
            entry.mangled = '__LABEL__%s' % entry.name

        entry.is_line_number = isinstance(id_, int)
        self.move_to_global_scope(id_)  # Labels are always global # TODO: not in the future
        entry.declared = True
        entry.type_ = self.basic_types[PTR_TYPE]
        return entry


    def declare_param(self, id_, lineno, type_=None):
        ''' Declares a parameter
        Check if entry.declared is False. Otherwise raises an error.
        '''
        if not self.check_is_undeclared(id_, lineno, classname='parameter',
                                        scope=self.current_scope, show_error=True):
            return None

        '''
            syntax_error(lineno, "Parameter '%s' already declared at %s:%i" %
                         (id_, entry.filename, entry.lineno))
            return None
        '''

        entry = self.declare(id_, lineno, PARAMDECL(id_, lineno, type_))
        if entry is None:
            return
        entry.declared = True
        if entry.type_ == self.basic_types[TYPE.string] and entry.t[0] != '$':
            entry.t = '$' + entry.t  # FIXME: This must be worked out

        return entry


    def declare_array(self, id_, lineno, type_, bounds, default_value=None):
        ''' Declares an array in the symbol table (VARARRAY). Error if already
        exists.
        '''
        if not self.check_class(id_, CLASS.array, lineno, scope=self.current_scope):
            return None

        entry = self.get_entry(id_, self.current_scope)
        if entry is None:
            entry = self.declare(id_, lineno, VARARRAY(id_, bounds, lineno))

        #if entry.declared:  # ???
        #    return entry

        if not entry.declared:
            if entry.callable:
                syntax_error(lineno,
                             "Array '%s' must be declared before use. "
                             "First used at line %i" %
                             (id_, entry.lineno))
                return None
        else:
            if entry.scope == SCOPE.parameter:
                syntax_error(lineno, "variable '%s' already declared as a "
                             "parameter at line %i" % (id_, entry.lineno))
            else:
                syntax_error(lineno, "variable '%s' already declared at "
                             "line %i" % (id_, entry.lineno))
            return None

        if entry.type_ is not None and entry.type_ != type_:
            if not type_.implicit:
                syntax_error(lineno, "Array suffix for '%s' is for type '%s' "
                             "but declared as '%s'" %
                             (entry.name, entry.type_, type_))
                return None

            type_.implicit = False
            type_ = entry.type_

        if type_.implicit:
            warning_implicit_type(lineno, id_)

        entry.declared = True
        entry.type_ = type_
        entry.scope = SCOPE.global_ if self.current_scope == self.global_scope else SCOPE.local
        entry.default_value = default_value
        entry.callable = True
        entry.lbound_used = entry.ubound_used = False  # Flag to true when LBOUND/UBOUND used somewhere in the code

        return entry

    def declare_func(self, id_, lineno, type_=None):
        ''' Declares a function in the current scope.
        Checks whether the id exist or not (error if exists).
        And creates the entry at the symbol table.
        '''
        if not self.check_class(id_, 'function', lineno):
            entry = self.get_id_entry(id_)  # Must not exist, or, if created, hav _class = None or Function and declared = False
            an = 'an' if entry.class_.lower()[0] in 'aeio' else 'a'
            syntax_error(lineno, "'%s' already declared as %s %s at %i" % (id_, an, entry.class_, entry.lineno))
            return None

        entry = self.get_entry(id_)  # Must not exist, or, if created, hav _class = None or Function and declared = False
        if entry is not None:
            if entry.declared and not entry.forwarded:
                syntax_error(lineno, "Duplicate function name '%s', previously defined at %i" % (id_, entry.lineno))
                return None

            if entry.callable is False:
                syntax_error_not_array_nor_func(lineno, id_)
                return None

            if id_[-1] in DEPRECATED_SUFFIXES and entry.type_ != SUFFIX_TYPE[id_[-1]]:
                syntax_error_func_type_mismatch(lineno, entry)
        else:
            entry = self.declare(id_, lineno, FUNCTION(id_, lineno, type_=type_))

        if entry.forwarded:
            old_type = entry.type_  # Remembers the old type
            old_params_size = entry.params_size  # TODO: Check this is really still needed

            if entry.type_ is not None:
                if entry.type_ != old_type:
                    syntax_error_func_type_mismatch(lineno, entry)
            else:
                entry.type_ = old_type

        # entry.class_ = CLASS.function
        # Mangled name (functions always has _name as mangled)
        # entry.mangled = '_%s' % entry.id_
        # entry.callable = True
        entry.locals_size = 0  # Size of local variables
        entry.local_symbol_table = None  # Will be set by the parser on END FUNCTION

        if not entry.forwarded:  # TODO: Check this is really still needed
            entry.params_size = 0  # Size of parameters
        else:
            entry.params_size = old_params_size  # Size of parameters
        return entry


    def check_labels(self):
        ''' Checks if all the labels has been declared
        '''
        for entry in self.labels:
            self.check_is_declared(entry.name, entry.lineno, CLASS.label)


    # TIP: DEPRECATED?. Not used.
    def check_classes(self, scope=-1):
        ''' Check if pending identifiers are defined or not. If not,
        returns a syntax error. If no scope is given, the current
        one is checked.
        '''
        for entry in self[scope].values():
            if entry.class_ is None:
                syntax_error(entry.lineno, "Unknown identifier '%s'" %
                             entry.name)

    # -------------------------------------------------------------------------
    # Properties
    # -------------------------------------------------------------------------
    @property
    def vars_(self):
        ''' Returns symbol instances corresponding to variables
        of the current scope.
        '''
        return [x for x in self[self.current_scope].values() if x.class_ == CLASS.var]

    @property
    def labels(self):
        ''' Returns symbol instances corresponding to labels
        in the current scope.
        '''
        return [x for x in self[self.current_scope].values() if x.class_ == CLASS.label]

    @property
    def types(self):
        ''' Returns symbol instances corresponding to type declarations
        within the current scope.
        '''
        return [x for x in self[self.current_scope].values() if isinstance(x, TYPEDEF)]

    @property
    def arrays(self):
        ''' Returns symbol instances corresponding to arrays
        of the current scope.
        '''
        return [x for x in self[self.current_scope].values() if x.class_ == CLASS.array]

    @property
    def functions(self):
        ''' Returns symbol instances corresponding to functions
        of the current scope.
        '''
        return [x for x in self[self.current_scope].values() if x.class_ in
                (CLASS.function, CLASS.sub)]

    @property
    def aliases(self):
        ''' Returns symbol instances corresponding to aliased vars.
        '''
        return [x for x in self[self.current_scope].values() if x.is_aliased]

    def __getitem__(self, level):
        ''' Returns the SYMBOL TABLE for the given scope
        '''
        return self.table[level]

    def __iter__(self):
        ''' Iterates through scopes, from current one (innermost) to global
        (outermost)
        '''
        for i in range(self.current_scope, -1, -1):
            yield self.table[i]
