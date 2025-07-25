import pytest
from nbformat.v4 import new_notebook

from grader_service.convert.preprocessors import DeduplicateIds

from .. import create_grade_cell, create_locked_cell, create_solution_cell
from .base import BaseTestPreprocessor


@pytest.fixture
def preprocessor():
    pp = DeduplicateIds()
    return pp


class TestDeduplicateIds(BaseTestPreprocessor):
    def test_duplicate_grade_cell(self, preprocessor):
        cell1 = create_grade_cell("hello", "code", "foo", 2)
        cell2 = create_grade_cell("goodbye", "code", "foo", 2)
        nb = new_notebook()
        nb.cells.append(cell1)
        nb.cells.append(cell2)

        nb, resources = preprocessor.preprocess(nb, {})

        assert nb.cells[0].metadata != {}
        assert nb.cells[1].metadata == {}

    def test_duplicate_solution_cell(self, preprocessor):
        cell1 = create_solution_cell("hello", "code", "foo")
        cell2 = create_solution_cell("goodbye", "code", "foo")
        nb = new_notebook()
        nb.cells.append(cell1)
        nb.cells.append(cell2)

        nb, resources = preprocessor.preprocess(nb, {})

        assert nb.cells[0].metadata != {}
        assert nb.cells[1].metadata == {}

    def test_duplicate_locked_cell(self, preprocessor):
        cell1 = create_locked_cell("hello", "code", "foo")
        cell2 = create_locked_cell("goodbye", "code", "foo")
        nb = new_notebook()
        nb.cells.append(cell1)
        nb.cells.append(cell2)

        nb, resources = preprocessor.preprocess(nb, {})

        assert nb.cells[0].metadata != {}
        assert nb.cells[1].metadata == {}
