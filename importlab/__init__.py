#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations, absolute_import
import os
import sys
from . import utils
from . import environment
from . import graph
from . import output
from . import fs
from . import import_finder
from . import parsepy
from . import resolve
from argparse import Namespace
import pathlib
import click

def ensure_files(*files):
	path = pathlib.Path(files[0] or '.')
	return path


def make_graph(*files):
	args = Namespace(inputs=files, trim = True, python_version = "3.8", pythonpath= os.environ.get('PYTHONPATH', None))
	args.inputs = utils.expand_source_files(args.inputs)
	env = environment.create_from_args(args)
	import_graph = graph.ImportGraph.create(env, args.inputs, args.trim)
	return import_graph

def main(*files):
	igraph = make_graph(*files)
	output.print_tree(igraph)
	
	
#forward()

#callback(ctx, param, value)

def do_test(path):
	from click.testing import CliRunner
	runner = CliRunner()
	return runner.invoke(path, 'run')
	

# i = utils.expand_source_files(args.inputs)
# e = importlab.environment.create_from_args(args)
# import_graph = importlab.graph.ImportGraph.create(e, args.inputs, args.trim)
# output.inspect_graph(import_graph)
# output.format_file_node
#module_name



if __name__ == '__main__':
	run()