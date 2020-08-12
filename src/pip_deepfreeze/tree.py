from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import typer
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from .compat import NormalizedName
from .installed_dist import InstalledDistribution
from .pip import pip_list
from .project_name import get_project_name

NodeKey = Tuple[NormalizedName, Tuple[NormalizedName, ...]]


class Node:
    def __init__(self, req: Requirement, dist: Optional[InstalledDistribution]):
        self.req = req
        self.dist = dist
        self.children = []  # type: List[Node]

    @staticmethod
    def key(req: Requirement) -> NodeKey:
        return (
            canonicalize_name(req.name),
            tuple(sorted(canonicalize_name(e) for e in req.extras)),
        )

    def print(self) -> None:
        seen = set()  # type: Set[Node]

        def _print(indent: List[str], node: Node) -> None:
            # inspired by https://stackoverflow.com/a/59109706
            SPACE = "    "
            BRANCH = "│   "
            TEE = "├── "
            LAST = "└── "
            typer.echo(f"{''.join(indent)}{node.req}", nl=False)
            if node in seen:
                typer.secho(" ⬆", dim=True)
                return
            typer.secho(f" ({node.sversion})", dim=True)
            seen.add(node)
            if not node.children:
                return
            pointers = [TEE] * (len(node.children) - 1) + [LAST]
            for pointer, child in zip(
                pointers, sorted(node.children, key=lambda n: str(n.req))
            ):
                if indent:
                    if indent[-1] == TEE:
                        _print(indent[:-1] + [BRANCH, pointer], child)
                    else:
                        assert indent[-1] == LAST
                        _print(indent[:-1] + [SPACE, pointer], child)
                else:
                    _print([pointer], child)

        _print([], self)

    @property
    def sversion(self) -> str:
        if not self.dist:
            version = typer.style("✘ not installed", fg=typer.colors.RED)
        else:
            version = self.dist.version
            if self.dist.direct_url:
                version += f" @ {self.dist.direct_url}"
        return version


def tree(python: str, project_root: Path, extras: List[NormalizedName]) -> None:
    installed_dists = pip_list(python)
    nodes = {}  # type: Dict[NodeKey, Node]

    def add(req: Requirement) -> Node:
        key = Node.key(req)
        if key in nodes:
            return nodes[key]
        dist = installed_dists.get(canonicalize_name(req.name))
        node = Node(req, dist)
        nodes[key] = node
        if not dist:
            # not installed
            return node
        for dep_req in dist.requires:
            node.children.append(add(dep_req))
        for extra in req.extras:
            for dep_req in dist.extra_requires.get(extra, []):
                node.children.append(add(dep_req))
        return node

    project_name_with_extras = str(get_project_name(python, project_root))
    if extras:
        project_name_with_extras += "[" + ",".join(extras) + "]"
    add(Requirement(project_name_with_extras)).print()
