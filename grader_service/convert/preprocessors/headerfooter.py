# -*- coding: utf-8 -*-

import io
from typing import Tuple

from nbconvert.exporters.exporter import ResourcesDict
from nbformat import current_nbformat
from nbformat.notebooknode import NotebookNode
from traitlets import Unicode

from grader_service.convert.nbgraderformat import read as read_nb
from grader_service.convert.preprocessors.base import NbGraderPreprocessor


class IncludeHeaderFooter(NbGraderPreprocessor):
    """A preprocessor for adding header and/or footer cells to a notebook."""

    header = Unicode(
        "", help="Path to header notebook, relative to the root of the course directory"
    ).tag(config=True)
    footer = Unicode(
        "", help="Path to footer notebook, relative to the root of the course directory"
    ).tag(config=True)

    def preprocess(
        self, nb: NotebookNode, resources: ResourcesDict
    ) -> Tuple[NotebookNode, ResourcesDict]:
        """Concatenates the cells from the header and footer notebooks to the
        given cells.

        """
        new_cells = []

        # header
        if self.header:
            with io.open(self.header, encoding="utf-8") as fh:
                header_nb = read_nb(fh, as_version=current_nbformat)
            new_cells.extend(header_nb.cells)

        # body
        new_cells.extend(nb.cells)

        # footer
        if self.footer:
            with io.open(self.footer, encoding="utf-8") as fh:
                footer_nb = read_nb(fh, as_version=current_nbformat)
            new_cells.extend(footer_nb.cells)

        nb.cells = new_cells
        super(IncludeHeaderFooter, self).preprocess(nb, resources)

        return nb, resources

    def preprocess_cell(
        self, cell: NotebookNode, resources: ResourcesDict, cell_index: int
    ) -> Tuple[NotebookNode, ResourcesDict]:
        return cell, resources
