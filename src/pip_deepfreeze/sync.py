import tempfile
from pathlib import Path
from typing import Iterator, List, Optional, Sequence

import httpx
import typer

from .compat import NormalizedName
from .pip import pip_freeze_dependencies_by_extra, pip_uninstall, pip_upgrade_project
from .project_name import get_project_name
from .req_file_parser import OptionsLine, parse as parse_req_file
from .req_merge import prepare_frozen_reqs_for_upgrade
from .req_parser import get_req_names
from .utils import (
    log_debug,
    log_info,
    make_project_name_with_extras,
    open_with_rollback,
)


def _make_requirements_path(project_root: Path, extra: Optional[str]) -> Path:
    if extra:
        return project_root / f"requirements-{extra}.txt"
    else:
        return project_root / "requirements.txt"


def _make_requirements_paths(
    project_root: Path, extras: Sequence[str]
) -> Iterator[Path]:
    yield _make_requirements_path(project_root, None)
    for extra in extras:
        yield _make_requirements_path(project_root, extra)


def sync(
    python: str,
    upgrade_all: bool,
    to_upgrade: List[str],
    editable: bool,
    extras: List[NormalizedName],
    uninstall_unneeded: Optional[bool],
    project_root: Path,
    use_pip_constraints: bool,
) -> None:
    project_name = get_project_name(python, project_root)
    project_name_with_extras = make_project_name_with_extras(project_name, extras)
    requirements_in = project_root / "requirements.txt.in"
    # upgrade project and its dependencies, if needed
    with tempfile.NamedTemporaryFile(
        dir=project_root,
        prefix="requirements.",
        suffix=".txt.df",
        mode="w",
        encoding="utf-8",
        delete=False,
    ) as constraints:
        for req_line in prepare_frozen_reqs_for_upgrade(
            _make_requirements_paths(project_root, extras),
            requirements_in,
            upgrade_all,
            to_upgrade,
        ):
            print(req_line, file=constraints)
    constraints_path = Path(constraints.name)
    try:
        pip_upgrade_project(
            python,
            constraints_path,
            project_root,
            editable=editable,
            extras=extras,
            use_pip_constraints=use_pip_constraints,
        )
    finally:
        constraints_path.unlink()
    # freeze dependencies
    frozen_reqs_by_extra, unneeded_reqs = pip_freeze_dependencies_by_extra(
        python, project_root, extras
    )
    for extra, frozen_reqs in frozen_reqs_by_extra.items():
        requirements_frozen_path = _make_requirements_path(project_root, extra)
        log_info(f"Updating {requirements_frozen_path}")
        with open_with_rollback(requirements_frozen_path) as f:
            print("# frozen requirements generated by pip-deepfreeze", file=f)
            # output pip options in main requirements only
            if not extra and requirements_in.exists():
                # TODO can we avoid this second parse of requirements.txt.in?
                for parsed_req_line in parse_req_file(
                    str(requirements_in),
                    reqs_only=False,
                    recurse=True,
                    strict=True,
                    session=httpx.Client(),
                ):
                    if isinstance(parsed_req_line, OptionsLine):
                        print(parsed_req_line.raw_line, file=f)
            # output frozen dependencies of project
            for req_line in frozen_reqs:
                print(req_line, file=f)
    # uninstall unneeded dependencies, if asked to do so
    if unneeded_reqs:
        unneeded_req_names = get_req_names(unneeded_reqs)
        unneeded_reqs_str = ",".join(unneeded_req_names)
        prompted = False
        if uninstall_unneeded is None:
            uninstall_unneeded = typer.confirm(
                typer.style(
                    f"The following distributions "
                    f"that are not dependencies of {project_name_with_extras} "
                    f"are also installed: {unneeded_reqs_str}.\n"
                    f"Do you want to uninstall them?",
                    bold=True,
                ),
                default=False,
                show_default=True,
            )
            prompted = True
        if uninstall_unneeded:
            log_info(f"Uninstalling unneeded distributions: {unneeded_reqs_str}")
            pip_uninstall(python, unneeded_req_names)
        elif not prompted:
            log_debug(
                f"The following distributions "
                f"that are not dependencies of {project_name_with_extras} "
                f"are also installed: {unneeded_reqs_str}"
            )
