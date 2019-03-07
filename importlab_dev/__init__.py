#!/usr/bin/env python3
# -*- coding: utf-8 -*-


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


def ensure_files(*files):
	path = pathlib.Path(files[0] or '.')


def make_graph(*files):
	args = Namespace(inputs=files, trim = True, python_version = "3.7",pythonpath= os.environ['PYTHONPATH'])
	source_files = utils.expand_source_files(args.inputs)
	env = environment.create_from_args(args)
	import_graph = graph.ImportGraph.create(env, args.inputs, args.trim)
	return import_graph



# i = utils.expand_source_files(args.inputs)
# e = importlab.environment.create_from_args(args)
# import_graph = importlab.graph.ImportGraph.create(e, args.inputs, args.trim)
# output.inspect_graph(import_graph)
# output.format_file_node
#module_name



