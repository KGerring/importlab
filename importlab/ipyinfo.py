from IPython.core import oinspect
from IPython.core.oinspect import object_info, compress_user, _get_wrapped
from IPython.core.oinspect import Inspector
import inspect
INFO_FIELDS = frozenset(oinspect.info_fields)

from IPython.core.oinspect import find_file
from IPython.core.oinspect import find_source_lines
from IPython.core.oinspect import getdoc
from IPython.core.oinspect import getsource
from IPython.core.oinspect import object_info
from IPython.core.oinspect import typestr2type, safe_hasattr, pretty
from IPython.lib import pretty as _pretty
from numpy.lib._datasource import DataSource
from numpy.lib._datasource import Repository

INSPECTOR = I = Inspector(scheme='NoColor', str_detail_level=1)
_getdef = I._getdef

info = I.info

from functools import update_wrapper
from itertools import filterfalse
from boltons.funcutils import dir_dict
from toolz import complement, keyfilter
from devplugins.utils import AttributeDict

def _is_dunder(name):
    """Returns True if a __dunder__ name, False otherwise."""
    return (name[:2] == name[-2:] == '__' and
            name[2:3] != '_' and
            name[-3:-2] != '_' and
            len(name) > 4)

def dictfilter(d=None, *, factory = AttributeDict, **kw):
    """Remove all keys from dict ``d`` whose value is :const:`None`."""
    d = kw if d is None else (dict(d, **kw) if kw else d)
    res = {k: v for k, v in d.items() if v is not None}
    return factory(res)

def clean_dir_info(obj):
	"""
	If needing to display a dictionary of some class that doesnt have __dict__, the boltons.dir_dict
	will work, but this cleans it up for serializing

	"""
	try:
		d = dir_dict(obj)
	except Exception:
		d = dict()
	d1 = keyfilter(complement(_is_dunder), d)
	return dictfilter(d1, factory = AttributeDict)



from IPython.display import Pretty, HTML, Markdown, TextDisplayObject, JSON, Code, DisplayHandle
#_display_mimetype('application/json', objs, **kwargs)
from IPython.core.display import _display_mimetype, display_html, display_json, display_markdown, display_pretty

JSON_FMT = get_ipython().display_formatter.formatters['application/json']
text_markdown = get_ipython().display_formatter.formatters['text/markdown']
text_plain = get_ipython().display_formatter.formatters['text/plain']

def get_info(obj, oname='', formatter=None, info=None, detail_level=2):
	pre = I._get_info(obj, oname, formatter, info, detail_level)
	return pre.get('text/plain')

def has_parent(obj):
	"""has __objclass__ or __self__
	can also try inspect.ismethoddescriptor; hasattr(obj, '__objclass__')

	"""
	return getattr(obj, '__qualname__', str(obj)) != getattr(obj, '__name__')


#qual = fully_qualified_name
from hypothesis.internal.reflection import fully_qualified_name,  fully_qualified_name as qual  

def cls_obj(obj):
	getdef = INSPECTOR._getdef
	out = dict()
	if inspect.isclass(obj) and not obj.__base__ == type:
		out['bases'] = list(map(qual, obj.__bases__))
		out['mro'] = list(map(qual, obj.__mro__))
		#static_mro = inspect._static_getmro(obj)
		try:
			out['subclasses'] = list(map(qual, type.__subclasses__(obj))). ##TODO fix
		except TypeError:
			out['subclasses'] = []
		out['base'] = qual(obj.__base__)
		
		if hasattr(obj, '__slots__'):
			out['slots'] = list(getattr(obj, '__slots__'))
		
		if hasattr(obj, '__slotnames__'):
			out['slotnames'] = list(getattr(obj, '__slotnames__'))
			
		
		
		#call_docstring
		#out['call_docstring'] = inspect.getdoc(obj.__call__)
		#call_def
		obj_call = getdef(obj.__call__)
		
		obj_cls = qual(obj.__class__)
		#class_docstring
		class_docstring = inspect.getdoc(obj.__class__)
		
		#init_definition
		obj_init = qual(obj.__init__)
		#init_docstring
		init_docstring = inspect.getdoc(obj.__init__)
		
		return out

def more_info(obj, fields: dict = {}):

	info = fields.copy()
	info['type_name'] = type(obj).__name__
	bclass = obj.__class__.__qualname__

	mro = obj.__class__.__mro__
	out['base_class'] = str(bclass)


	info['module'] = getattr(obj, '__module__', None)
	if hasattr(obj, '__self__'):
		selfname = fully_qualified_name(getattr(obj, "__self__"))
		info['parent'] = selfname

	if info.get('found'):
		info.pop('found')
		info.pop('isalias')
		#info.pop('isclass')
		info.pop('ismagic')
		info.pop('length')

	if 'argspec' in info:
		argspec = info.get('argspec', dict())
		if argspec:
			if 'args' in argspec:
				args = argspec.get('args', None)
				if args:
					info['args'] = args[:]
	else:
		info['args'] = []
	info.pop('argspec')
	info['tags'] = info.get('name')
	cleaned_info = {k:v for k,v in info.items() if v}
	return 
		cleaned_info

def object_description(object: "Any") -> str:
    import re
    memory_address_re = re.compile(
        r" at 0x[0-9a-f]{8,16}(?=>)", re.IGNORECASE | re.UNICODE)
    try:
        s = repr(object)
    except Exception:
        raise ValueError
    s = memory_address_re.sub("", s)
    return s.replace("\n", " ")



import ast
_all_nodes = frozenset(filter(lambda x: isinstance(x, type) and
                              issubclass(x, ast.AST),
                              (getattr(ast, node) for node in dir(ast))))
def _filter_nodes(superclass, all_nodes=_all_nodes):
    """Filter out AST nodes that are subclasses of ``superclass``."""
    node_names = (node.__name__ for node in all_nodes
                  if issubclass(node, superclass))
    return frozenset(node_names)
_stmt_nodes = _filter_nodes(ast.stmt)
_all_node_names = frozenset(map(lambda x: x.__name__, _all_nodes))
_expr_context_nodes = _filter_nodes(ast.expr_context)
_handler_nodes = _filter_nodes(ast.excepthandler)
_arguments_nodes = _filter_nodes(ast.arguments)
_keyword_nodes = _filter_nodes(ast.keyword)
_alias_nodes = _filter_nodes(ast.alias)

class RewriteName(NodeTransformer):
	def visit_Name(self, node):
		return copy_location(
				Subscript(
				value=Name(id='data', ctx=Load()),
				slice=Index(value=Str(s=node.id)),
				ctx=node.ctx),
				
				node)
	
import ast

class RewriteLambda(ast.NodeTransformer):
	def visit_Lambda(self, node):
		return ast.copy_location(
			ast.FunctionDef(name='func', args =node.args,
	            body = ast.Return(value=node.body),
	            decorator_list = [],
	            returns=None,
	            type_comment=None),
			node)
	
def exec_node(node):
	temp = {}
	exec(compile(node, '', 'exec'), temp, temp)
	temp[func.__name__].__code__
	return temp[func.__name__]




