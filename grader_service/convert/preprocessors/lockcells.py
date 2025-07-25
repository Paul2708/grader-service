from typing import Tuple

from nbconvert.exporters.exporter import ResourcesDict
from nbformat.notebooknode import NotebookNode
from traitlets import Bool

from grader_service.convert import utils
from grader_service.convert.preprocessors.base import NbGraderPreprocessor


class LockCells(NbGraderPreprocessor):
    """A preprocessor for making cells undeletable."""

    lock_solution_cells = Bool(
        True, help="Whether solution cells are locked (non-deletable and non-editable)"
    ).tag(config=True)

    lock_grade_cells = Bool(True, help="Whether grade cells are locked (non-deletable)").tag(
        config=True
    )

    lock_readonly_cells = Bool(
        True, help="Whether readonly cells are locked (non-deletable and non-editable)"
    ).tag(config=True)

    lock_all_cells = Bool(
        False, help="Whether all assignment cells are locked (non-deletable and non-editable)"
    ).tag(config=True)

    def preprocess_cell(
        self, cell: NotebookNode, resources: ResourcesDict, cell_index: int
    ) -> Tuple[NotebookNode, ResourcesDict]:
        if (
            (self.lock_solution_cells or self.lock_grade_cells)
            and utils.is_solution(cell)
            and utils.is_grade(cell)
        ):
            cell.metadata["deletable"] = False
        elif self.lock_solution_cells and utils.is_solution(cell):
            cell.metadata["deletable"] = False
        elif self.lock_grade_cells and utils.is_grade(cell):
            cell.metadata["deletable"] = False
            cell.metadata["editable"] = False
        elif self.lock_readonly_cells and utils.is_locked(cell):
            cell.metadata["deletable"] = False
            cell.metadata["editable"] = False
        elif self.lock_all_cells:
            cell.metadata["deletable"] = False
            cell.metadata["editable"] = False
        return cell, resources
