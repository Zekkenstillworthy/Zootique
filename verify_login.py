from app import app

client = app.test_client()
paths = [
    ('superadmin', '/auth/login/zootique_admin', 'admin@zootique.com', 'Password123'),
    ('staff', '/auth/login/zoo_staff', 'staff1_1@manilazoo.com', 'Password123'),
    ('visitor', '/auth/login/visitor', 'visitor1@gmail.com', 'Password123'),
    ('zoo_admin', '/auth/login/zoo_admin', 'admin1@lygerzoo.com', '5Ci7IGyRqxJR'),
]
for name, path, email, password in paths:
    resp = client.post(path, data={'email': email, 'password': password}, follow_redirects=False)
    print(name, 'STATUS', resp.status_code, 'LOCATION', resp.headers.get('Location'))
