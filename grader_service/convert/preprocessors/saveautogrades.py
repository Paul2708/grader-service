from typing import Tuple

from nbconvert.exporters.exporter import ResourcesDict
from nbformat.notebooknode import NotebookNode

from grader_service.convert import utils
from grader_service.convert.gradebook.gradebook import Gradebook
from grader_service.convert.preprocessors.base import NbGraderPreprocessor


class SaveAutoGrades(NbGraderPreprocessor):
    """Preprocessor for saving out the autograder grades into a database"""

    def preprocess(
        self, nb: NotebookNode, resources: ResourcesDict
    ) -> Tuple[NotebookNode, ResourcesDict]:
        # pull information from the resources
        self.notebook_id = resources["unique_key"]
        self.json_path = resources["output_json_path"]
        self.gradebook = Gradebook(self.json_path)

        with self.gradebook:
            # process the cells
            nb, resources = super(SaveAutoGrades, self).preprocess(nb, resources)

        return nb, resources

    def _add_score(self, cell: NotebookNode, resources: ResourcesDict) -> None:
        """Graders can override the autograder grades, and may need to
        manually grade written solutions anyway. This function adds
        score information to the database if it doesn't exist. It does
        NOT override the 'score' field, as this is the manual score
        that might have been provided by a grader.

        """
        # these are the fields by which we will identify the score
        # information
        grade = self.gradebook.find_grade(cell.metadata["nbgrader"]["grade_id"], self.notebook_id)

        # determine what the grade is
        auto_score, _ = utils.determine_grade(cell, self.log)
        grade.auto_score = auto_score

        # if there was previously a manual grade, or if there is no autograder
        # score, then we should mark this as needing review
        if (grade.manual_score is not None) or (grade.auto_score is None):
            grade.needs_manual_grade = True
        else:
            grade.needs_manual_grade = False

        self.gradebook.add_grade(cell.metadata["nbgrader"]["grade_id"], self.notebook_id, grade)

    def _add_comment(self, cell: NotebookNode, resources: ResourcesDict) -> None:
        comment = self.gradebook.find_comment(
            cell.metadata["nbgrader"]["grade_id"], self.notebook_id
        )
        if cell.metadata.nbgrader.get("checksum", None) == utils.compute_checksum(
            cell
        ) and not utils.is_task(cell):
            comment.auto_comment = "No response."
        else:
            comment.auto_comment = None

        self.gradebook.add_comment(cell.metadata["nbgrader"]["grade_id"], self.notebook_id, comment)

    def preprocess_cell(
        self, cell: NotebookNode, resources: ResourcesDict, cell_index: int
    ) -> Tuple[NotebookNode, ResourcesDict]:
        # if it's a grade cell, the add a grade
        if utils.is_grade(cell):
            self._add_score(cell, resources)

        if utils.is_solution(cell):
            self._add_comment(cell, resources)

        if utils.is_task(cell):
            self._add_comment(cell, resources)

        return cell, resources
