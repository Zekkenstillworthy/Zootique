from urllib.parse import urlparse

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from werkzeug.datastructures import FileStorage
from werkzeug.security import generate_password_hash

from models import EstablishmentRegistration, Zoo, User, EstablishmentType, db
from services.storage import save_uploaded_document

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

REGISTRATION_DOCUMENTS = {
    'business_permit': ('Business/Establishment Permit', 'business_permit_url'),
    'wildlife_license': ('Zoo or Wildlife Exhibition License', 'wildlife_license_url'),
    'proof_of_address': ('Proof of Address', 'proof_of_address_url'),
    'representative_id': ('Authorized Representative ID', 'representative_id_url'),
}
ALLOWED_DOCUMENT_EXTENSIONS = {'.pdf', '.jpg', '.jpeg', '.png'}
MAX_DOCUMENT_SIZE = 8 * 1024 * 1024


def _valid_registration_document(file_storage: FileStorage | None) -> bool:
    if not file_storage or not file_storage.filename:
        return False
    filename = file_storage.filename.lower()
    if not any(filename.endswith(extension) for extension in ALLOWED_DOCUMENT_EXTENSIONS):
        return False
    if file_storage.content_length and file_storage.content_length > MAX_DOCUMENT_SIZE:
        return False
    return True


def _validate_password_policy(password: str) -> str | None:
    if len(password or '') < PASSWORD_MIN_LENGTH:
        return f'Password must be at least {PASSWORD_MIN_LENGTH} characters.'
    return None


def _set_auth_session(user: User):
    session.permanent = True
    # Store a role-specific login state so users can be logged into multiple
    # modules (roles) at the same time without clobbering each other.
    auth_by_role = session.get("auth_by_role")
    if not isinstance(auth_by_role, dict):
        auth_by_role = {}
    auth_by_role[str(user.role)] = {
        "user_id": int(user.id),
        "full_name": user.full_name,
    }
    session["auth_by_role"] = auth_by_role

    # Maintain legacy top-level keys for existing code paths/templates.
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
    """registration selection (Visitor vs Zoo Admin only)."""
    return render_template('auth/register_selection.html')


@auth_bp.get('/login-selection')
def login_selection():
    """login selection (Visitor, Zoo Admin, Staff, Super Admin)."""
    return render_template('auth/login_selection.html')

@auth_bp.route('/admin-login', defaults={'module_name': None}, methods=['GET', 'POST'])
@auth_bp.route('/login', defaults={'module_name': None}, methods=['GET', 'POST'])
@auth_bp.route('/login/<module_name>', methods=['GET', 'POST'])
def login(module_name):
    # Generic admin login page used by auth/login.html
    if module_name is None:
        next_url = request.args.get('next') or request.form.get('next')
        if request.method == 'POST':
            email = (request.form.get('email') or '').strip().lower()
            password = request.form.get('password') or ''

            user = User.query.filter_by(email=email, role='zootique_admin').first()
            if user and user.check_password(password):
                if (getattr(user, 'status', 'active') or 'active').strip().lower() != 'active':
                    flash('Your account is suspended. Please contact support.', 'error')
                    return render_template('auth/login.html')

                _set_auth_session(user)

                maybe_next = _safe_next_redirect(next_url)
                if maybe_next:
                    return maybe_next

                return redirect(url_for('zootique_admin.dashboard'))

            flash('Invalid administrator credentials.', 'error')

        return render_template('auth/login.html')

    if module_name not in ROLES:
        return redirect(url_for('auth.portal'))

    next_url = request.args.get('next') or request.form.get('next')

    if request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()
        password = request.form.get('password') or ''

        try:
            from sqlalchemy.exc import SQLAlchemyError
            # We explicitly enforce that you are logging into your specific module
            user = User.query.filter_by(email=email, role=module_name).first()
        except SQLAlchemyError as e:
            flash(f'Database connection error. Please verify your Vercel DATABASE_URL connection string.', 'error')
            return render_template('auth/login_module.html', module_name=module_name, module_title=ROLES[module_name])
        except Exception as e:
            flash(f'An unexpected error occurred during login. Please try again.', 'error')
            return render_template('auth/login_module.html', module_name=module_name, module_title=ROLES[module_name])

        if user and user.check_password(password):
            if (getattr(user, 'status', 'active') or 'active').strip().lower() != 'active':
                flash('Your account is suspended. Please contact an administrator.', 'error')
                return render_template('auth/login_module.html', module_name=module_name, module_title=ROLES[module_name])

            _set_auth_session(user)

            # Visitors must pick a Zoo after login.
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
    registration = None
    registration_id = session.get('reg_registration_id')
    if registration_id:
        registration = db.session.get(EstablishmentRegistration, registration_id)

    if request.method == 'POST':
        zoo_name = (request.form.get('zoo_name') or '').strip()
        zoo_type = (request.form.get('zoo_type') or '').strip() or 'Zoo Park'
        zoo_location = (request.form.get('zoo_location') or '').strip()

        if not zoo_name or not zoo_location:
            flash('Please complete all required establishment details.', 'error')
            return redirect(url_for('auth.register_admin_step1'))

        if not registration:
            registration = EstablishmentRegistration(
                establishment_name=zoo_name,
                establishment_type=zoo_type,
                location=zoo_location,
                status='draft',
            )
            db.session.add(registration)
            db.session.flush()
        else:
            registration.establishment_name = zoo_name
            registration.establishment_type = zoo_type
            registration.location = zoo_location

        for document_key, (label, column_name) in REGISTRATION_DOCUMENTS.items():
            document = request.files.get(document_key)
            remove_document = request.form.get(f'remove_{document_key}') == '1'
            current_url = getattr(registration, column_name)
            if remove_document:
                setattr(registration, column_name, None)
                current_url = None
            if document and document.filename:
                if not _valid_registration_document(document):
                    db.session.rollback()
                    flash(f'{label} must be a PDF, JPG, or PNG file no larger than 8 MB.', 'error')
                    return redirect(url_for('auth.register_admin_step1'))
                uploaded_url = save_uploaded_document(document, f'establishment_registrations/{registration.id}')
                if not uploaded_url:
                    db.session.rollback()
                    flash(f'Unable to upload {label}. Please try again.', 'error')
                    return redirect(url_for('auth.register_admin_step1'))
                setattr(registration, column_name, uploaded_url)
            elif not current_url:
                db.session.rollback()
                flash('Please attach all four required establishment documents.', 'error')
                return redirect(url_for('auth.register_admin_step1'))

        db.session.commit()
        session['reg_registration_id'] = registration.id

        session['reg_zoo_name'] = zoo_name
        session['reg_zoo_type'] = zoo_type
        session['reg_zoo_location'] = zoo_location
        return redirect(url_for('auth.register_admin_step2'))

    types = EstablishmentType.query.filter_by(is_active=True).order_by(EstablishmentType.name.asc()).all()
    return render_template('auth/register_admin_step1.html', establishment_types=types, registration=registration)


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

        registration_id = session.get('reg_registration_id')
        registration = db.session.get(EstablishmentRegistration, registration_id) if registration_id else None
        if not registration:
            flash('Please complete establishment details first.', 'error')
            return redirect(url_for('auth.register_admin_step1'))

        registration.establishment_name = zoo_name
        registration.establishment_type = zoo_type
        registration.location = zoo_location
        registration.admin_full_name = full_name
        registration.admin_email = email
        registration.admin_password_hash = generate_password_hash(password)
        registration.status = 'pending'
        registration.approved_by = None
        registration.approved_at = None
        registration.rejected_by = None
        registration.rejected_at = None
        registration.rejection_note = None
        db.session.commit()

        session.pop('reg_zoo_name', None)
        session.pop('reg_zoo_type', None)
        session.pop('reg_zoo_location', None)
        session.pop('reg_registration_id', None)

        flash('Registration submitted for Super Admin approval.', 'success')
        return redirect(url_for('auth.registration_success', role='zoo_admin'))

    return render_template('auth/register_admin_step2.html')


@auth_bp.get('/establishment-selection')
def establishment_selection():
    # Staff should not self-register. Keep this page non-public.
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
    return redirect(url_for('landing'))
