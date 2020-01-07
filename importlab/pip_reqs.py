#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pipreqs - Generate pip requirements.txt file based on imports

Usage:
	pipreqs [GLOBAL_OPTIONS] <path>

Options:
	--use-local           Use ONLY local package info instead of querying PyPI
	--pypi-server <url>   Use custom PyPi server
	--proxy <url>         Use Proxy, parameter will be passed to requests library. You can also just set the
						  environments parameter in your terminal:
						  $ export HTTP_PROXY="http://10.10.1.10:3128"
						  $ export HTTPS_PROXY="https://10.10.1.10:1080"
	--debug               Print debug information
	--ignore <dirs>...    Ignore extra directories, each separated by a comma
	--encoding <charset>  Use encoding parameter for file open
	--savepath <file>     Save the list of requirements in the given file
	--print               Output the list of requirements in the standard output
	--force               Overwrite existing requirements.txt
	--diff <file>         Compare modules in requirements.txt to project imports.
	--clean <file>        Clean up requirements.txt by removing modules that are not imported in project.
"""
from __future__ import annotations
import os
import sys
import re
import logging
import codecs
import ast
import traceback
from docopt import docopt, parse_defaults
import requests
from yarg import json2package
from yarg.exceptions import HTTPError
import click
import typing
from kombu.abstract import Object
from collections import defaultdict
import functools

logger = logging.getLogger(__name__)
STDLIB = "/Library/Frameworks/Python.framework/Versions/3.7/lib/python3.7/site-packages/pipenv/vendor/pipreqs/stdlib"
MAPPING = "/Library/Frameworks/Python.framework/Versions/3.7/lib/python3.7/site-packages/pipenv/vendor/pipreqs/mapping"
THISDIR = os.path.dirname(__file__)
try:
    from pipreqs import __version__
except Exception:
    __version__ = "0.4.9"

REGEXP = [
    re.compile(r"^import (.+)$"),
    re.compile(r"^from ((?!\.+).*?) import (?:.*)$"),
]

if sys.version_info[0] > 2:
    open_func = open
    py2 = False
    py2_exclude = None
else:
    open_func = codecs.open
    py2 = True
    py2_exclude = ["concurrent", "concurrent.futures"]


def join(f):
    return os.path.join(os.path.dirname(__file__), f)


def make_data():
    global data
    with open(join(STDLIB), "r") as f:
        data = [x.strip() for x in f.readlines()]
        data = [x for x in data if x not in py2_exclude] if py2 else data
    return data


def make_mapping():
    with open(join(MAPPING), "r") as f:
        data = [x.strip().split(":") for x in f.readlines()]
    return data


candidates = None  # typing.List[typing.Any]
imports = None  # Set[str]
raw_imports = None  # Set[str]
packages = None
trees = None
asts = None

Resource = typing.Union[str, os.PathLike]


class AbstractImport(Object):
    attrs = (["name", str], ["version", str])

    def __init__(self, name, version=None):
        self.name = name
        self.version = version


class Container(Object):
    """Object that enables you to modify attributes."""

    attrs = [
        ("path", str),
        ("imports", None),
        ("raw_imports", None),
        ("candidates", None),
        ("ignore_errors", None),
        ("ignore_dirs", None),
        ("packages", None),
        ("result", None),
        ("extra_ignore_dirs", None),
        ("encoding", None),
    ]

    @classmethod
    def set_attrs(cls, **opts):
        _attrs = [(name, type_) for name, type_ in opts.items()]
        setattr(cls, "attrs", tuple(_attrs))

    def __repr__(self):
        return "<%s: %r>" % (type(self).__name__, ", ".join(self.as_dict()))
        # __copy__


def parse_requirements(file_: Resource):
    """Parse a requirements formatted file.

	Traverse a string until a delimiter is detected, then split at said
	delimiter, get module name by element index, create a dict consisting of
	module:version, and add dict to list of parsed modules.

	Args:
		file_: File to parse.

	Raises:
		OSerror: If there's any issues accessing the file.

	Returns:
		tuple: The contents of the file, excluding comments.
	"""
    modules = []
    delim = [
        "<",
        ">",
        "=",
        "!",
        "~",
    ]  # https://www.python.org/dev/peps/pep-0508/#complete-grammar
    try:
        f = open_func(file_, "r")
    except OSError:
        logging.error("Failed on file: {}".format(file_))
        raise
    else:
        data = [x.strip() for x in f.readlines() if x != "\n"]
    finally:
        f.close()

    data = [x for x in data if x[0].isalpha()]

    for x in data:
        if not any([y in x for y in delim]):  # Check for modules w/o a specifier.
            modules.append({"name": x, "version": None})
        for y in x:
            if y in delim:
                module = x.split(y)
                module_name = module[0]
                module_version = module[-1].replace("=", "")
                module = {"name": module_name, "version": module_version}

                if module not in modules:
                    modules.append(module)

                break

    return modules


def _get_all_imports(path, **kwargs):
    kwargs = {}
    kwargs["ignore_dirs"] = [
        ".hg",
        ".svn",
        ".git",
        ".tox",
        "__pycache__",
        "env",
        "venv",
    ]
    kwargs["encoding"] = "utf-8"
    kwargs["ignore_errors"] = False
    kwargs["candidates"] = []
    kwargs["imports"] = set()
    kwargs["raw_imports"] = set()
    kwargs["packages"] = packages = set()
    kwargs["data"] = None
    c = Container()
    return c, kwargs


def get_all_imports(path, encoding="utf-8", extra_ignore_dirs=None):
    global candidates, imports, raw_imports, trees, asts
    imports = set()
    raw_imports = set()
    candidates = []
    ignore_errors = False
    trees = defaultdict(set)
    asts = dict()

    ###########
    ignore_dirs = [".hg", ".svn", ".git", ".tox", "__pycache__", "env", "venv"]
    if extra_ignore_dirs:
        ignore_dirs_parsed = []
        for e in extra_ignore_dirs:
            ignore_dirs_parsed.append(os.path.basename(os.path.realpath(e)))
        ignore_dirs.extend(ignore_dirs_parsed)

    #######################
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d not in ignore_dirs]
        candidates.append(os.path.basename(root))
        files = [fn for fn in files if os.path.splitext(fn)[1] == ".py"]
        candidates += [os.path.splitext(fn)[0] for fn in files]
        for file_name in files:
            with open_func(os.path.join(root, file_name), "r", encoding=encoding) as f:
                contents = f.read()
                try:
                    tree = ast.parse(contents, filename=f.name)
                    asts[f.name] = tree
                    subtree = trees[f.name]
                    for node in ast.walk(tree):
                        if isinstance(node, ast.Import):
                            for subnode in node.names:
                                raw_imports.add(subnode.name)
                                subtree.add(subnode.name)
                        elif isinstance(node, ast.ImportFrom):
                            raw_imports.add(node.module)
                            subtree.add(node.module)
                except Exception as exc:
                    if ignore_errors:
                        traceback.print_exc(exc)
                        logging.warn(
                            "Failed on file: %s" % os.path.join(root, file_name)
                        )
                        continue
                    else:
                        logging.error(
                            "Failed on file: %s" % os.path.join(root, file_name)
                        )
                        raise exc

                # Clean up imports
    for name in [n for n in raw_imports if n]:
        # Sanity check: Name could have been None if the import statement was as from . import X
        # Cleanup: We only want to first part of the import.
        # Ex: from django.conf --> django.conf. But we only want django as an import
        cleaned_name, _, _ = name.partition(".")
        imports.add(cleaned_name)
    global packages
    packages = set(imports) - set(set(candidates) & set(imports))
    logging.debug("Found packages: {0}".format(packages))
    data = make_data()
    return sorted(list(set(packages) - set(data)))
    # with open(join(STDLIB), "r") as f:
    # 	data = [x.strip() for x in f.readlines()]
    # 	data = [x for x in data if x not in py2_exclude] if py2 else data


def filter_line(l):
    return len(l) > 0 and l[0] != "#"


def generate_requirements_file(path: Resource, imports: dict):
    with open(path, "w") as out_file:
        logging.debug(
            "Writing {num} requirements: {imports} to {file}".format(
                num=len(imports),
                file=path,
                imports=", ".join([x["name"] for x in imports]),
            )
        )
        fmt = "{name}=={version}"
        out_file.write(
            "\n".join(
                fmt.format(**item) if item["version"] else "{name}".format(**item)
                for item in imports
            )
            + "\n"
        )


def output_requirements(imports: dict):
    logging.debug(
        "Writing {num} requirements: {imports} to stdout".format(
            num=len(imports), imports=", ".join([x["name"] for x in imports])
        )
    )
    fmt = "{name}=={version}"
    print(
        "\n".join(
            fmt.format(**item) if item["version"] else "{name}".format(**item)
            for item in imports
        )
    )


@functools.lru_cache()
def get_imports_info(imports, pypi_server="https://pypi.python.org/pypi/", proxy=None):
    result = []
    for item in imports:
        try:
            response = requests.get(
                "{0}{1}/json".format(pypi_server, item), proxies=proxy
            )
            if response.status_code == 200:
                if hasattr(response.content, "decode"):
                    data = json2package(response.content.decode())
                else:
                    data = json2package(response.content)
            elif response.status_code >= 300:
                raise HTTPError(
                    status_code=response.status_code, reason=response.reason
                )
        except HTTPError:
            logging.debug("Package %s does not exist or network problems", item)
            continue
        result.append({"name": item, "version": data.latest_release_id})
    return result


@functools.lru_cache()
def get_locally_installed_packages(encoding=None, *, paths=sys.path):
    packages = {}
    ignore = ["tests", "_tests", "egg", "EGG", "info"]
    paths = paths if paths else sys.path[:]
    for path in paths:
        for root, dirs, files in os.walk(path):
            for item in files:
                if "top_level" in item:
                    with open_func(
                        os.path.join(root, item), "r", encoding=encoding
                    ) as f:
                        package = root.split(os.sep)[-1].split("-")
                        try:
                            package_import = f.read().strip().split("\n")
                        except:
                            continue
                        for i_item in package_import:
                            if (i_item not in ignore) and (package[0] not in ignore):
                                version = None
                                if len(package) > 1:
                                    version = (
                                        package[1]
                                        .replace(".dist", "")
                                        .replace(".egg", "")
                                    )

                                packages[i_item] = {
                                    "version": version,
                                    "name": package[0],
                                }
    return packages


def get_import_local(imports, encoding=None):
    local = get_locally_installed_packages()
    result = []
    for item in imports:
        if item.lower() in local:
            result.append(local[item.lower()])

            # removing duplicates of package/version
    result_unique = [dict(t) for t in set([tuple(d.items()) for d in result])]
    return result_unique


def get_pkg_names(pkgs):
    result = []
    with open(join(MAPPING), "r") as f:
        data = [x.strip().split(":") for x in f.readlines()]
        data = make_mapping()
        for pkg in pkgs:
            toappend = pkg
            for item in data:
                if item[0] == pkg:
                    toappend = item[1]
                    break
            if toappend not in result:
                result.append(toappend)
    return result


def get_name_without_alias(name):
    if "import " in name:
        match = REGEXP[0].match(name.strip())
        if match:
            name = match.groups(0)[0]
    return name.partition(" as ")[0].partition(".")[0].strip()


def compare_modules(file_: Resource, imports: dict):
    """Compare modules in a file to imported modules in a project.

	Args:
		file_ (str): File to parse for modules to be compared.
		imports (tuple): Modules being imported in the project.

	Returns:
		tuple: The modules not imported in the project, but do exist in the
			   specified file.
	"""
    modules = parse_requirements(file_)
    imports = [imports[i]["name"] for i in range(len(imports))]
    modules = [modules[i]["name"] for i in range(len(modules))]
    modules_not_imported = set(modules) - set(imports)
    return modules_not_imported


def diff(file_: Resource, imports: dict):
    """Display the difference between modules in a file and imported modules."""
    modules_not_imported = compare_modules(file_, imports)
    logging.info(
        "The following modules are in {} but do not seem to be imported: \n"
        "{}".format(file_, ", ".join(x for x in modules_not_imported))
    )


def clean(file_: Resource, imports: dict):
    """Remove modules that aren't imported in project from file."""
    modules_not_imported = compare_modules(file_, imports)
    re_remove = re.compile("|".join(modules_not_imported))
    to_write = []

    try:
        f = open_func(file_, "r+")
    except OSError:
        logging.error("Failed on file: {}".format(file_))
        raise
    else:
        for i in f.readlines():
            if re_remove.match(i) is None:
                to_write.append(i)
        f.seek(0)
        f.truncate()

        for i in to_write:
            f.write(i)
    finally:
        f.close()

    logging.info("Successfully cleaned up requirements in " + file_)


@click.command()
@click.option(
    "-p",
    "--path",
    help="The path to walk",
    nargs=1,
    type=click.Path(),
    required=True,
    default=THISDIR,
)
@click.option(
    "--local",
    is_flag=True,
    help="Use ONLY local package info instead of querying PyPI",
    default=False,
)
@click.option("-v", "--debug", is_flag=True, help="print debug info", default=False)
@click.option(
    "-i",
    "--ignore",
    help="Ignore extra directories, each separated by a comma",
    default=None,
)
@click.option(
    "-o",
    "--savepath",
    help="Save the list of requirements in the given file",
    type=click.Path(),
)
@click.option(
    "-d",
    "--stdout",
    is_flag=True,
    help="Output the list of requirements in the standard output",
    default=True,
)
@click.option(
    "-f",
    "--force",
    is_flag=True,
    help="Overwrite existing requirements.txt",
    default=False,
)
@click.option(
    "-d",
    "--diffonly",
    help="Compare modules in requirements.txt to project imports.",
    type=click.Path(),
)
@click.option(
    "-c",
    "--cleanup",
    help="Clean up requirements.txt by removing modules that are not imported in project.",
    type=click.Path(),
)
@click.pass_context
def run_main(
    ctx,
    path=THISDIR,
    local=False,
    debug=True,
    ignore=None,
    savepath=None,
    stdout=True,
    force=False,
    diffonly=None,
    cleanup=None,
):

    proxy = None
    encoding = None
    extra_ignore_dirs = []
    if ignore:
        extra_ignore_dirs = extra_ignore_dirs.split(",")
    candidates = get_all_imports(
        path, encoding=encoding, extra_ignore_dirs=extra_ignore_dirs
    )
    candidates = get_pkg_names(candidates)
    if debug:
        click.echo("Found imports: ")
        click.secho(", ".join(candidates), color=True, fg="blue")
    pypi_server = "https://pypi.python.org/pypi/"
    if local:
        click.secho(
            "Getting package information ONLY from local installation.",
            color=True,
            fg="magenta",
        )
        imports = get_import_local(candidates, encoding=encoding)

    else:
        click.secho(
            "Getting packages information from Local/PyPI", color=True, fg="green"
        )
        local = get_import_local(candidates, encoding=encoding)
        difference = [
            x for x in candidates if x.lower() not in [z["name"].lower() for z in local]
        ]
        imports = local + get_imports_info(
            difference, proxy=proxy, pypi_server=pypi_server
        )

    if savepath:
        fpath = savepath
    else:
        fpath = os.path.join(path, "requirements.txt")

    if diffonly:
        diff(diffonly, imports)
        return

    if cleanup:
        clean(cleanup, imports)
        return

    if not stdout and not savepath and not force and os.path.exists(fpath):
        click.echo("Requirements.txt already exists, " "use --force to overwrite it")
        return

    if stdout:
        output_requirements(imports)
        click.secho("Successfully output requirements", color=True, fg="blue")
    else:
        generate_requirements_file(path, imports)
        click.secho(
            "Successfully saved requirements file in " + fpath, color=True, fg="blue"
        )


def init(args):
    encoding = args.get("--encoding")
    extra_ignore_dirs = args.get("--ignore")

    if extra_ignore_dirs:
        extra_ignore_dirs = extra_ignore_dirs.split(",")

    candidates = get_all_imports(
        args["<path>"], encoding=encoding, extra_ignore_dirs=extra_ignore_dirs
    )
    candidates = get_pkg_names(candidates)
    logging.debug("Found imports: " + ", ".join(candidates))
    pypi_server = "https://pypi.python.org/pypi/"
    proxy = None
    if args["--pypi-server"]:
        pypi_server = args["--pypi-server"]

    if args["--proxy"]:
        proxy = {"http": args["--proxy"], "https": args["--proxy"]}

    if args["--use-local"]:
        logging.debug("Getting package information ONLY from local installation.")
        imports = get_import_local(candidates, encoding=encoding)
    else:
        logging.debug("Getting packages information from Local/PyPI")
        local = get_import_local(candidates, encoding=encoding)
        # Get packages that were not found locally
        difference = [
            x for x in candidates if x.lower() not in [z["name"].lower() for z in local]
        ]
        imports = local + get_imports_info(
            difference, proxy=proxy, pypi_server=pypi_server
        )

    path = (
        args["--savepath"]
        if args["--savepath"]
        else os.path.join(args["<path>"], "requirements.txt")
    )

    if args["--diff"]:
        diff(args["--diff"], imports)
        return

    if args["--clean"]:
        clean(args["--clean"], imports)
        return

    if (
        not args["--print"]
        and not args["--savepath"]
        and not args["--force"]
        and os.path.exists(path)
    ):
        logging.warning(
            "Requirements.txt already exists, " "use --force to overwrite it"
        )
        return

    if args["--print"]:
        output_requirements(imports)
        logging.info("Successfully output requirements")
    else:
        generate_requirements_file(path, imports)
        logging.info("Successfully saved requirements file in " + path)


def _main():  # pragma: no cover
    args = docopt(__doc__, version=__version__)
    log_level = logging.DEBUG if args["--debug"] else logging.INFO
    logging.basicConfig(level=log_level, format="%(levelname)s: %(message)s")
    try:
        init(args)
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    run_main()  # pragma: no cover
