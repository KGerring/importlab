#!/usr/bin/env python
# -*- coding: utf-8 -*-
# filename = __main__
# author=KGerring
# date = 2019-08-14
# project modularities
# docs root 
"""
 modularities  

"""

__all__ = []
from __future__ import annotations, absolute_import
import sys  # isort:skip
import os  # isort:skip
import re  # isort:skip
import click
from types import SimpleNamespace as Namespace
from importlab.utils import expand_source_files
from importlab.environment import create_from_args
from importlab.graph import DependencyGraph, ImportGraph
from importlab.output import print_tree
from importlab import output

#import_graph = graph.ImportGraph.create(env, args.inputs, args.trim)



def callback_ensure_file(value):
	"""

	:param ctx:
	:type ctx:
	:param param:
	:type param:
	:param value:
	:type value:
	:return:
	:rtype:
	"""
	container = Namespace(files=[], cwd=None)
	pref = []
	if not os.path.exists(value):
		value = os.getcwd()
		container.files.append(value)
		container.cwd = value
	
	elif isinstance(value, (list, tuple, set)):
		container.files = value
	
	elif os.path.isdir(value):
		container.files.append(value)
	try:
		source_files = expand_source_files(container.files, cwd=container.cwd)
	except (TypeError, FileNotFoundError) as exc:
		click.echo('the `file` input couldnt resolve; passing [] as last-ditch.')
		source_files = []
	return source_files

@click.command('run_main')
@click.option('-f', '--files', 'files',
              help="""The path/files to analyze. Path/list[Files]""",
              required=True, type=click.Path(exists=True),
              multiple=True)
@click.option('-t', '--trim', help='trim the output', default=True, required=False)
@click.option('-v', '--pyver', help="The python version to use", default='3.8', required=False)
def main(files, trim=True, pyver="3.8"):
	pythonpath = os.getenv("PYTHONPATH", "")
	files= expand_source_files(files)
	#files = callback_ensure_file(files)
	args = Namespace(python_version=pyver, pythonpath=pythonpath)
	env = create_from_args(args)
	import_graph = graph.ImportGraph.create(env, files, trim)
	output.print_tree(import_graph)
	return import_graph

#result = runner.invoke(cli, ['--debug', 'sync'])


if __name__ == '__main__':
	main()


