import urllib.request
import urllib.parse
import http.cookiejar
import re

BASE_URL = "http://127.0.0.1:5000"

roles = [
    ('superadmin', '/auth/login/zootique_admin', 'admin@zootique.com', 'Password123', [
        '/zootique-admin/',
        '/zootique-admin/user-management',
        '/zootique-admin/establishment-types',
        '/zootique-admin/subscriptions/directory',
        '/zootique-admin/subscriptions/pricing-tiers',
        '/zootique-admin/reports',
        '/zootique-admin/feedback',
        '/zootique-admin/settings',
        '/zootique-admin/layout-manager',
    ]),
    ('admin', '/auth/login/zoo_admin', 'admin1@lygerzoo.com', 'Password123', [
        '/animal-farm-admin/',
        '/animal-farm-admin/bookings',
        '/animal-farm-admin/services?tab=add',
        '/animal-farm-admin/services?tab=list',
        '/animal-farm-admin/animals?tab=add',
        '/animal-farm-admin/animals?tab=list',
        '/animal-farm-admin/events?tab=add',
        '/animal-farm-admin/events?tab=list',
        '/animal-farm-admin/promotions?tab=add',
        '/animal-farm-admin/promotions?tab=list',
        '/animal-farm-admin/feedback',
        '/animal-farm-admin/map-zones?tab=add',
        '/animal-farm-admin/map-zones?tab=landing-map',
        '/animal-farm-admin/map-zones?tab=zones',
        '/animal-farm-admin/revenue',
        '/animal-farm-admin/analytics',
        '/animal-farm-admin/system-feedback',
        '/animal-farm-admin/staff-management?tab=assign',
        '/animal-farm-admin/staff-management?tab=accounts',
        '/animal-farm-admin/staff-management?tab=tasks',
        '/animal-farm-admin/settings?section=profile',
        '/animal-farm-admin/settings?section=security',
        '/animal-farm-admin/establishment-profile',
        '/animal-farm-admin/subscriptions',
    ]),
    ('staff', '/auth/login/zoo_staff', 'staff1_1@manilazoo.com', 'Password123', [
        '/animal-farm-staff/',
        '/animal-farm-staff/bookings',
        '/animal-farm-staff/events?tab=add',
        '/animal-farm-staff/events?tab=list',
        '/animal-farm-staff/map-zones',
        '/animal-farm-staff/visitor-feedback',
        '/animal-farm-staff/tasks',
        '/animal-farm-staff/report-incident',
        '/animal-farm-staff/profile',
        '/animal-farm-staff/logout-confirm',
    ]),
    ('visitor', '/auth/login/visitor', 'visitor1@gmail.com', 'Password123', [
        '/visitor/choose-zoo',
        '/visitor/home',
        '/visitor/bookings',
        '/visitor/services',
        '/visitor/animals',
        '/visitor/events',
        '/visitor/promotions',
        '/visitor/feedback',
        '/visitor/park-info',
        '/visitor/profile',
    ]),
]

print("=== STARTING LIVE AUDIT ===")

for role_name, login_path, email, pwd, pages in roles:
    print(f"\n--- Checking role: {role_name} ---")
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    
    # 1. Login
    data = urllib.parse.urlencode({'email': email, 'password': pwd}).encode('utf-8')
    req = urllib.request.Request(BASE_URL + login_path, data=data)
    try:
        res = opener.open(req)
    except Exception as e:
        print(f"  Login failed: {e}")
        continue
        
    if role_name == 'visitor':
        # Select zoo 1
        sel_data = urllib.parse.urlencode({'zoo_id': '1'}).encode('utf-8')
        try:
            opener.open(urllib.request.Request(BASE_URL + '/visitor/select-zoo', data=sel_data))
        except Exception as e:
            print(f"  Select zoo failed: {e}")
    
    for page in pages:
        try:
            resp = opener.open(BASE_URL + page)
            html = resp.read().decode('utf-8', errors='ignore')
        except Exception as e:
            print(f"  [FETCH ERROR] {page}: {e}")
            continue
            
        # Check unwrapped tables
        for m in re.finditer(r'<table\b', html, re.IGNORECASE):
            pre = html[max(0, m.start() - 350):m.start()]
            if 'table-wrap' not in pre and 'table-container' not in pre and 'overflow' not in pre:
                print(f"  [UNWRAPPED TABLE] in {page}")

        # Check for multi-column grids that might not collapse on mobile
        # (e.g., inline grid-template-columns with 3+ columns)
        for m in re.finditer(r'grid-template-columns:\s*([^;"]+)', html):
            val = m.group(1).strip()
            if ('repeat(3' in val or 'repeat(4' in val or 'repeat(5' in val or val.count('1fr') >= 3) and '@media' not in html[max(0, m.start()-100):m.end()+100]:
                print(f"  [MULTI-COL GRID: {val}] in {page}")

print("\n=== AUDIT FINISHED ===")
