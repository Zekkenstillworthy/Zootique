from urllib.parse import urlparse

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from models import Zoo, User, db

auth_bp = Blueprint('auth', __name__)

PASSWORD_MIN_LENGTH = 8

ROLES = {
    'zootique_admin': 'Zootique Admin Database',
    'zoo_admin': 'Animal Farm Admin Module',
    'zoo_staff': 'Animal Farm Staff Module',
    'visitor': 'Visitors Module'
}

EST_TYPE_LABELS = {
    'zoo': 'Zoo Park',
    'wildlife': 'Wildlife Park',
    'farm': 'Farm Attraction',
}


def _validate_password_policy(password: str) -> str | None:
    if len(password or '') < PASSWORD_MIN_LENGTH:
        return f'Password must be at least {PASSWORD_MIN_LENGTH} characters.'
    return None


def _set_auth_session(user: User):
    session['user_id'] = user.id
    session['role'] = user.role
    session['full_name'] = user.full_name


def _role_home(user: User):
    if user.role == 'zootique_admin':
        return redirect(url_for('zootique_admin.dashboard'))
    if user.role == 'zoo_admin':
        return redirect(url_for('animal_farm_admin.dashboard'))
    if user.role == 'zoo_staff':
        return redirect(url_for('animal_farm_staff.dashboard'))
    return redirect(url_for('visitor.home'))


def _safe_next_redirect(next_url: str | None):
    if not next_url:
        return None
    parsed = urlparse(next_url)
    if parsed.scheme == '' and parsed.netloc == '' and parsed.path.startswith('/'):
        return redirect(next_url)
    return None

@auth_bp.route('/portal')
@auth_bp.route('/role-selection')
def portal():
    """Role-selection hub for authentication modules."""
    return render_template('auth/portal.html', roles=ROLES)


@auth_bp.get('/register-selection')
def register_selection():
    """MVP: registration selection (Visitor vs Zoo Admin only)."""
    return render_template('auth/register_selection.html')


@auth_bp.get('/login-selection')
def login_selection():
    """MVP: login selection (Visitor, Zoo Admin, Staff, Super Admin)."""
    return render_template('auth/login_selection.html')

@auth_bp.route('/admin-login', defaults={'module_name': None}, methods=['GET', 'POST'])
@auth_bp.route('/login', defaults={'module_name': None}, methods=['GET', 'POST'])
@auth_bp.route('/login/<module_name>', methods=['GET', 'POST'])
def login(module_name):
    # Generic admin login page used by auth/login.html
    if module_name is None:
        if request.method == 'POST':
            email = (request.form.get('email') or '').strip().lower()
            password = request.form.get('password') or ''

            user = User.query.filter_by(email=email, role='zootique_admin').first()
            if user and user.check_password(password):
                if getattr(user, 'status', 'active') != 'active':
                    flash('Your account is suspended. Please contact support.', 'error')
                    return render_template('auth/login.html')

                _set_auth_session(user)
                return redirect(url_for('zootique_admin.dashboard'))

            flash('Invalid administrator credentials.', 'error')

        return render_template('auth/login.html')

    if module_name not in ROLES:
        return redirect(url_for('auth.portal'))

    next_url = request.args.get('next') or request.form.get('next')

    if request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()
        password = request.form.get('password')

        # We explicitly enforce that you are logging into your specific module
        user = User.query.filter_by(email=email, role=module_name).first()
        if user and user.check_password(password):
            if getattr(user, 'status', 'active') != 'active':
                flash('Your account is suspended. Please contact an administrator.', 'error')
                return render_template('auth/login_module.html', module_name=module_name, module_title=ROLES[module_name])

            _set_auth_session(user)

            # MVP: Visitors must pick a Zoo after login.
            if module_name == 'visitor':
                if next_url:
                    parsed = urlparse(next_url)
                    if parsed.scheme == '' and parsed.netloc == '' and parsed.path.startswith('/'):
                        session['post_login_next'] = next_url
                return redirect(url_for('visitor.choose_zoo'))

            maybe_next = _safe_next_redirect(next_url)
            if maybe_next:
                return maybe_next

            return _role_home(user)

        flash(f'Invalid email or password access for {ROLES[module_name]}', 'error')

    return render_template('auth/login_module.html', module_name=module_name, module_title=ROLES[module_name])

@auth_bp.route('/register', defaults={'module_name': None}, methods=['GET', 'POST'])
@auth_bp.route('/register/<module_name>', methods=['GET', 'POST'])
def register(module_name):
    allowed_public_roles = {"visitor", "zoo_admin"}

    # Generic register page used by auth/register.html
    if module_name is None:
        if request.method == 'POST':
            full_name = (request.form.get('full_name') or '').strip()
            email = (request.form.get('email') or '').strip().lower()
            password = request.form.get('password') or ''
            role = (request.form.get('role') or 'visitor').strip()

            if role not in allowed_public_roles:
                flash('Only Visitor and Zoo Admin registration are available.', 'error')
                return redirect(url_for('auth.portal'))

            if role == 'zoo_admin':
                flash('Admin accounts require establishment setup. Continue to registration step 1.', 'success')
                return redirect(url_for('auth.register_admin_step1'))

            if not full_name or not email or not password:
                flash('Full name, email, and password are required.', 'error')
                return redirect(url_for('auth.register'))

            password_error = _validate_password_policy(password)
            if password_error:
                flash(password_error, 'error')
                return redirect(url_for('auth.register'))

            if User.query.filter_by(email=email).first():
                flash('Email already registered.', 'error')
                return redirect(url_for('auth.register'))

            new_user = User(email=email, full_name=full_name, role=role)
            new_user.set_password(password)

            db.session.add(new_user)
            db.session.commit()

            flash(f'Successfully registered access to {ROLES[role]}!', 'success')
            return redirect(url_for('auth.registration_success', role=role))

        return render_template('auth/register.html')

    if module_name not in allowed_public_roles:
        flash('Registration for that account type is not available.', 'error')
        return redirect(url_for('auth.portal'))

    if module_name == 'zoo_admin':
        return redirect(url_for('auth.register_admin_step1'))

    if request.method == 'POST':
        full_name = (request.form.get('full_name') or '').strip()
        email = (request.form.get('email') or '').strip().lower()
        password = request.form.get('password')

        if not full_name or not email or not password:
            flash('Full name, email, and password are required.', 'error')
            return redirect(url_for('auth.register', module_name=module_name))

        password_error = _validate_password_policy(password)
        if password_error:
            flash(password_error, 'error')
            return redirect(url_for('auth.register', module_name=module_name))

        if User.query.filter_by(email=email).first():
            flash('Email already registered universally', 'error')
            return redirect(url_for('auth.register', module_name=module_name))

        new_user = User(email=email, full_name=full_name, role=module_name)
        new_user.set_password(password)

        db.session.add(new_user)
        db.session.commit()

        flash(f'Successfully registered access to {ROLES[module_name]}!', 'success')
        return redirect(url_for('auth.registration_success', role=module_name))

    return render_template('auth/register_module.html', module_name=module_name, module_title=ROLES[module_name])


@auth_bp.route('/register-step-1', methods=['GET', 'POST'])
@auth_bp.route('/register-admin-step1', methods=['GET', 'POST'])
def register_admin_step1():
    if request.method == 'POST':
        zoo_name = (request.form.get('zoo_name') or '').strip()
        zoo_type = (request.form.get('zoo_type') or '').strip() or 'Zoo Park'
        zoo_location = (request.form.get('zoo_location') or '').strip()

        if not zoo_name or not zoo_location:
            flash('Please complete all required establishment details.', 'error')
            return redirect(url_for('auth.register_admin_step1'))

        session['reg_zoo_name'] = zoo_name
        session['reg_zoo_type'] = zoo_type
        session['reg_zoo_location'] = zoo_location
        return redirect(url_for('auth.register_admin_step2'))

    return render_template('auth/register_admin_step1.html')


@auth_bp.route('/register-step-2', methods=['GET', 'POST'])
@auth_bp.route('/register-admin-step2', methods=['GET', 'POST'])
def register_admin_step2():
    zoo_name = (session.get('reg_zoo_name') or '').strip()
    zoo_type = (session.get('reg_zoo_type') or 'Zoo Park').strip()
    zoo_location = (session.get('reg_zoo_location') or '').strip()

    if not zoo_name or not zoo_location:
        flash('Please complete establishment details first.', 'error')
        return redirect(url_for('auth.register_admin_step1'))

    if request.method == 'POST':
        full_name = (request.form.get('full_name') or '').strip()
        email = (request.form.get('email') or '').strip().lower()
        password = request.form.get('password') or ''

        if not full_name or not email or not password:
            flash('Please complete all admin account fields.', 'error')
            return redirect(url_for('auth.register_admin_step2'))

        password_error = _validate_password_policy(password)
        if password_error:
            flash(password_error, 'error')
            return redirect(url_for('auth.register_admin_step2'))

        if User.query.filter_by(email=email).first():
            flash('Email already registered universally', 'error')
            return redirect(url_for('auth.register_admin_step2'))

        new_zoo = Zoo(name=zoo_name, type=zoo_type, location=zoo_location)
        db.session.add(new_zoo)
        db.session.flush()

        new_user = User(email=email, full_name=full_name, role='zoo_admin', zoo_id=new_zoo.id)
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()

        session.pop('reg_zoo_name', None)
        session.pop('reg_zoo_type', None)
        session.pop('reg_zoo_location', None)

        flash('Zoo admin account created successfully.', 'success')
        return redirect(url_for('auth.registration_success', role='zoo_admin'))

    return render_template('auth/register_admin_step2.html')


@auth_bp.get('/establishment-selection')
def establishment_selection():
    # MVP: Staff should not self-register. Keep this page non-public.
    if session.get('role') != 'zoo_admin':
        flash('Staff accounts are created by Zoo Admins.', 'error')
        return redirect(url_for('auth.login_selection'))

    zoos = Zoo.query.order_by(Zoo.name.asc()).all()
    return render_template('auth/establishment_selection.html', zoos=zoos)


@auth_bp.post('/register-staff-select-zoo')
def register_staff_select_zoo():
    if session.get('role') != 'zoo_admin':
        flash('Staff accounts are created by Zoo Admins.', 'error')
        return redirect(url_for('auth.login_selection'))

    zoo_id = request.form.get('zoo_id')
    if not zoo_id or not str(zoo_id).isdigit():
        flash('Please select an establishment.', 'error')
        return redirect(url_for('auth.establishment_selection'))

    zoo = db.session.get(Zoo, int(zoo_id))
    if not zoo:
        flash('Selected establishment was not found.', 'error')
        return redirect(url_for('auth.establishment_selection'))

    session['reg_staff_zoo_id'] = zoo.id
    flash(f'Establishment selected: {zoo.name}. Continue registration.', 'success')
    return redirect(url_for('auth.register', module_name='zoo_staff'))


@auth_bp.get('/registration-success')
def registration_success():
    role = (request.args.get('role') or 'visitor').strip()
    if role not in ROLES:
        role = 'visitor'
    return render_template('auth/registration_success.html', role=role)

@auth_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('visitor.home'))
