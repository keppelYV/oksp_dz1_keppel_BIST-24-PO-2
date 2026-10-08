def test_unauthorized_is_401(client):
    assert client.get('/api/tickets').status_code == 401


def test_bad_credentials(client):
    assert client.get('/api/summary', auth=('demo', 'bad')).status_code == 401


def test_list_contract(client, auth):
    r = client.get('/api/tickets?page=1&size=20', auth=auth)
    assert r.status_code == 200
    assert r.json()['total'] == 1
    assert {'items', 'total', 'page', 'size'} <= r.json().keys()


def test_invalid_page_is_422(client, auth):
    assert client.get('/api/tickets?page=0', auth=auth).status_code == 422


def test_detail_has_comments(client, auth):
    r = client.get('/api/tickets/1', auth=auth)
    assert r.status_code == 200
    assert {'comments', 'sla_minutes', 'sla_breached', 'owner', 'category'} <= r.json().keys()


def test_create_ticket_success(client, auth):
    payload = {'user_id': 2, 'category_id': 1, 'title': 'Не загружается сайт', 'body': 'Ошибка'}
    r = client.post('/api/tickets', json=payload, auth=auth)
    assert r.status_code == 201
    assert r.json()['status'] == 'new'
    assert r.json()['id'] == 2


def test_create_ticket_wrong_category(client, auth):
    payload = {'user_id': 2, 'category_id': 999, 'title': 'Не загружается сайт', 'body': 'Ошибка'}
    assert client.post('/api/tickets', json=payload, auth=auth).status_code == 404


def test_change_status(client, auth):
    r = client.patch('/api/tickets/1/status', json={'status': 'in_progress'}, auth=auth)
    assert r.status_code == 200
    assert r.json()['status'] == 'in_progress'


def test_bad_status_rejected(client, auth):
    r = client.patch('/api/tickets/1/status', json={'status': 'broken'}, auth=auth)
    assert r.status_code == 422


def test_first_staff_comment_records_response(client, auth):
    r = client.post('/api/tickets/1/comments', json={'author_id': 1, 'body': 'Проверяем'}, auth=auth)
    assert r.status_code == 201
    detail = client.get('/api/tickets/1', auth=auth).json()
    assert len(detail['comments']) == 1
    assert detail['first_response_at'] is not None
    assert detail['response_minutes'] is not None


def test_summary_contract(client, auth):
    r = client.get('/api/summary', auth=auth)
    assert r.status_code == 200
    assert r.json()['total_tickets'] == 1
    assert r.json()['categories'][0]['open'] == 1
