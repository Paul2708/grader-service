# Copyright (c) 2022, TU Wien
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.
import json
from http import HTTPStatus

import pytest
from tornado.httpclient import HTTPClientError

from grader_service.api.models.assignment import Assignment
from grader_service.api.models.assignment_settings import AssignmentSettings
from grader_service.api.models.lecture import Lecture
from grader_service.server import GraderServer

from .db_util import insert_assignments, insert_submission


async def test_get_lectures(
    app: GraderServer,
    service_base_url,
    http_server_client,
    default_token,
    default_roles,
    default_user_login,
):
    url = service_base_url + "lectures"

    response = await http_server_client.fetch(
        url, method="GET", headers={"Authorization": f"Token {default_token}"}
    )
    assert response.code == 200
    lectures = json.loads(response.body.decode())
    assert isinstance(lectures, list)
    assert lectures
    [Lecture.from_dict(lec) for lec in lectures]  # assert no errors


async def test_get_lectures_with_some_parameter(
    app: GraderServer,
    service_base_url,
    http_server_client,
    default_user,
    default_token,
    default_roles,
    default_user_login,
):
    url = service_base_url + "lectures?some_param=WS21"
    with pytest.raises(HTTPClientError) as exc_info:
        await http_server_client.fetch(
            url, method="GET", headers={"Authorization": f"Token {default_token}"}
        )
    e = exc_info.value
    assert e.code == 400


async def test_post_lectures(
    app: GraderServer,
    service_base_url,
    http_server_client,
    default_user,
    default_token,
    default_roles,
    default_user_login,
):
    url = service_base_url + "lectures"

    get_response = await http_server_client.fetch(
        url, method="GET", headers={"Authorization": f"Token {default_token}"}
    )
    assert get_response.code == 200
    lectures = json.loads(get_response.body.decode())
    assert isinstance(lectures, list)
    assert len(lectures) == 3
    orig_len = len(lectures)

    # same code as in group of user
    pre_lecture = Lecture(id=-1, name="pytest_lecture", code="20wle2", complete=False)
    post_response = await http_server_client.fetch(
        url,
        method="POST",
        headers={"Authorization": f"Token {default_token}"},
        body=json.dumps(pre_lecture.to_dict()),
    )
    assert post_response.code == 201
    post_lecture = Lecture.from_dict(json.loads(post_response.body.decode()))
    assert post_lecture.id != pre_lecture.id
    assert post_lecture.name == pre_lecture.name
    assert post_lecture.code == pre_lecture.code
    assert not post_lecture.complete

    get_response = await http_server_client.fetch(
        url, method="GET", headers={"Authorization": f"Token {default_token}"}
    )
    assert get_response.code == 200
    lectures = json.loads(get_response.body.decode())
    assert len(lectures) == orig_len


async def test_post_not_found(
    app: GraderServer,
    service_base_url,
    http_server_client,
    default_user,
    default_token,
    default_roles,
    default_user_login,
):
    url = service_base_url + "lectures"

    pre_lecture = Lecture(id=-1, name="pytest_lecture", code="abc", complete=False)

    with pytest.raises(HTTPClientError) as exc_info:
        await http_server_client.fetch(
            url,
            method="POST",
            headers={"Authorization": f"Token {default_token}"},
            body=json.dumps(pre_lecture.to_dict()),
        )
    e = exc_info.value
    print(e.response.error)
    assert e.code == HTTPStatus.NOT_FOUND


async def test_post_unknown_parameter(
    app: GraderServer,
    service_base_url,
    http_server_client,
    default_user,
    default_token,
    default_roles,
    default_user_login,
):
    url = service_base_url + "lectures?some_param=asdf"
    # same code not in user groups
    pre_lecture = Lecture(id=-1, name="pytest_lecture", code="20wle2", complete=False)
    with pytest.raises(HTTPClientError) as exc_info:
        await http_server_client.fetch(
            url,
            method="POST",
            headers={"Authorization": f"Token {default_token}"},
            body=json.dumps(pre_lecture.to_dict()),
        )
    e = exc_info.value
    assert e.code == 400


async def test_put_lecture(
    app: GraderServer,
    service_base_url,
    http_server_client,
    default_user,
    default_token,
    default_roles,
    default_user_login,
):
    url = service_base_url + "lectures/3"

    get_response = await http_server_client.fetch(
        url, method="GET", headers={"Authorization": f"Token {default_token}"}
    )
    assert get_response.code == 200
    lecture = Lecture.from_dict(json.loads(get_response.body.decode()))
    lecture.name = "new name"
    lecture.complete = not lecture.complete
    # lecture code will not be updated
    lecture.code = "some"

    put_response = await http_server_client.fetch(
        url,
        method="PUT",
        headers={"Authorization": f"Token {default_token}"},
        body=json.dumps(lecture.to_dict()),
    )

    assert put_response.code == 200
    put_lecture = Lecture.from_dict(json.loads(put_response.body.decode()))
    assert put_lecture.name == lecture.name
    assert put_lecture.complete == lecture.complete
    assert put_lecture.code != lecture.code


async def test_put_lecture_unauthorized(
    app: GraderServer,
    service_base_url,
    http_server_client,
    default_token,
    default_roles,
    default_user_login,
):
    #  default user is a student in lecture with lecture_id 1
    url = service_base_url + "lectures/1"

    get_response = await http_server_client.fetch(
        url, method="GET", headers={"Authorization": f"Token {default_token}"}
    )
    assert get_response.code == 200
    lecture = Lecture.from_dict(json.loads(get_response.body.decode()))
    lecture.name = "new name"

    with pytest.raises(HTTPClientError) as exc_info:
        await http_server_client.fetch(
            url,
            method="PUT",
            headers={"Authorization": f"Token {default_token}"},
            body=json.dumps(lecture.to_dict()),
        )

    e = exc_info.value
    assert e.code == 403


async def test_get_lecture(
    app: GraderServer,
    service_base_url,
    http_server_client,
    default_token,
    default_roles,
    default_user_login,
):
    url = service_base_url + "lectures/1"

    get_response = await http_server_client.fetch(
        url, method="GET", headers={"Authorization": f"Token {default_token}"}
    )
    assert get_response.code == 200
    Lecture.from_dict(json.loads(get_response.body.decode()))


async def test_get_lecture_not_found(
    app: GraderServer,
    service_base_url,
    http_server_client,
    default_token,
    default_roles,
    default_user_login,
):
    url = service_base_url + "lectures/999"

    with pytest.raises(HTTPClientError) as exc_info:
        await http_server_client.fetch(
            url, method="GET", headers={"Authorization": f"Token {default_token}"}
        )
    e = exc_info.value
    assert e.code == 403


async def test_delete_lecture(
    app: GraderServer,
    service_base_url,
    http_server_client,
    default_token,
    default_roles,
    default_user_login,
):
    url = service_base_url + "lectures/3"

    delete_response = await http_server_client.fetch(
        url, method="DELETE", headers={"Authorization": f"Token {default_token}"}
    )
    assert delete_response.code == 200

    with pytest.raises(HTTPClientError) as exc_info:
        await http_server_client.fetch(
            url, method="GET", headers={"Authorization": f"Token {default_token}"}
        )
    e = exc_info.value
    assert e.code == 404


async def test_delete_lecture_unauthorized(
    app: GraderServer,
    service_base_url,
    http_server_client,
    default_token,
    default_roles,
    default_user_login,
):
    url = service_base_url + "lectures/1"

    with pytest.raises(HTTPClientError) as exc_info:
        await http_server_client.fetch(
            url, method="DELETE", headers={"Authorization": f"Token {default_token}"}
        )
    e = exc_info.value
    assert e.code == 403


async def test_delete_lecture_assignment_with_submissions(
    app: GraderServer,
    service_base_url,
    http_server_client,
    default_token,
    sql_alchemy_engine,
    default_roles,
    default_user_login,
    default_user,
):
    l_id = 3
    a_id = 2
    url = service_base_url + f"lectures/{l_id}"

    engine = sql_alchemy_engine
    insert_assignments(engine, lecture_id=3)
    insert_submission(engine, assignment_id=a_id, username=default_user.name)

    with pytest.raises(HTTPClientError) as exc_info:
        await http_server_client.fetch(
            url, method="DELETE", headers={"Authorization": f"Token {default_token}"}
        )
    e = exc_info.value
    assert e.code == HTTPStatus.CONFLICT


async def test_delete_lecture_assignment_released(
    app: GraderServer,
    service_base_url,
    http_server_client,
    default_token,
    sql_alchemy_engine,
    default_roles,
    default_user_login,
):
    l_id = 3
    url = service_base_url + f"lectures/{l_id}"

    engine = sql_alchemy_engine
    insert_assignments(engine, lecture_id=3)  # assignment with id 1 is status released

    with pytest.raises(HTTPClientError) as exc_info:
        await http_server_client.fetch(
            url, method="DELETE", headers={"Authorization": f"Token {default_token}"}
        )
    e = exc_info.value
    assert e.code == HTTPStatus.CONFLICT


async def test_delete_lecture_assignment_complete(
    app: GraderServer,
    service_base_url,
    http_server_client,
    default_token,
    default_roles,
    default_user_login,
):
    l_id = 3
    url = service_base_url + f"lectures/{l_id}/assignments"

    pre_assignment = Assignment(
        id=-1,
        name="pytest",
        status="complete",
        settings=AssignmentSettings(autograde_type="unassisted"),
    )
    post_response = await http_server_client.fetch(
        url,
        method="POST",
        headers={"Authorization": f"Token {default_token}"},
        body=json.dumps(pre_assignment.to_dict()),
    )
    assert post_response.code == 201

    url = service_base_url + f"lectures/{l_id}"
    with pytest.raises(HTTPClientError) as exc_info:
        await http_server_client.fetch(
            url, method="DELETE", headers={"Authorization": f"Token {default_token}"}
        )
    e = exc_info.value
    assert e.code == HTTPStatus.CONFLICT


async def test_delete_lecture_not_found(
    app: GraderServer,
    service_base_url,
    http_server_client,
    default_token,
    sql_alchemy_engine,
    default_roles,
    default_user_login,
):
    l_id = -5

    url = service_base_url + f"lectures/{l_id}"
    with pytest.raises(HTTPClientError) as exc_info:
        await http_server_client.fetch(
            url, method="DELETE", headers={"Authorization": f"Token {default_token}"}
        )
    e = exc_info.value
    assert e.code == HTTPStatus.NOT_FOUND
