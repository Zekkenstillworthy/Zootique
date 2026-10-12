"""Seed review-page scenarios for Super Admin testing.

Creates one pending application with four local demo documents, one pending
application with missing documents, and normalizes the migrated Lyger Zoo record.
"""

from pathlib import Path
from datetime import datetime
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app
from models import EstablishmentRegistration, RegistrationEmailAttempt, User, Zoo, db
from werkzeug.security import generate_password_hash


DOCUMENTS = {
    "business_permit_url": "business-permit.pdf",
    "wildlife_license_url": "wildlife-license.pdf",
    "proof_of_address_url": "proof-of-address.pdf",
    "representative_id_url": "representative-id.pdf",
}


def ensure_demo_document(upload_root: Path, name: str) -> str:
    folder = upload_root / "establishment_registrations" / "demo-review"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    if not path.exists():
        path.write_bytes(b"%PDF-1.4\n% Zootique demo registration document\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n")
    return f"/uploads/establishment_registrations/demo-review/{name}"


def upsert(name: str, email: str, missing: bool, upload_root: Path, status: str = "pending"):
    registration = EstablishmentRegistration.query.filter_by(admin_email=email).first()
    if not registration:
        registration = EstablishmentRegistration(
            establishment_name=name,
            establishment_type="Zoo Park",
            location="Demo City",
            admin_full_name=f"{name} Applicant",
            admin_email=email,
            establishment_contact_name=f"{name} Contact",
            establishment_contact_email=f"contact@{email.split('@')[-1]}",
            establishment_contact_phone="+63 900 000 0000",
            admin_phone="+63 911 111 1111",
            admin_password_hash=generate_password_hash("Password123"),
            status="pending",
        )
        db.session.add(registration)
    if registration.zoo_id:
        demo_user = User.query.filter_by(email=email).first()
        if demo_user:
            db.session.delete(demo_user)
        demo_zoo = db.session.get(Zoo, registration.zoo_id)
        if demo_zoo:
            db.session.delete(demo_zoo)
        registration.zoo_id = None
    for attempt in RegistrationEmailAttempt.query.filter_by(registration_id=registration.id).all():
        db.session.delete(attempt)
    registration.status = status
    registration.is_legacy_migration = False
    if not registration.admin_password_hash:
        registration.admin_password_hash = generate_password_hash("Password123")
    registration.acknowledgement_email_status = "pending"
    registration.confirmation_email_status = "pending"
    registration.approved_by = None
    registration.approved_at = None
    registration.rejected_by = None
    registration.rejected_at = None
    registration.rejection_note = None
    registration.reviewer_note = None
    registration.activation_token_hash = None
    registration.activation_expires_at = None
    if missing:
        for field in DOCUMENTS:
            setattr(registration, field, None)
    else:
        for field, filename in DOCUMENTS.items():
            setattr(registration, field, ensure_demo_document(upload_root, filename))
        registration.document_reviews = {}
    if status == "approved":
        registration.approved_at = datetime.utcnow()
        registration.reviewer_note = "Approved demo application."
    elif status == "rejected":
        registration.rejected_at = datetime.utcnow()
        registration.rejection_note = "Documents Incomplete: Rejected demo application."
    registration.created_at = registration.created_at or datetime.utcnow()
    registration.updated_at = datetime.utcnow()


with create_app().app_context():
    upload_root = Path("uploads")
    with db.session.begin():
        upsert("Demo Verified Wildlife Park", "demo.verified@zootique.test", missing=False, upload_root=Path("uploads"))
        upsert("Demo Missing Documents Park", "demo.missing@zootique.test", missing=True, upload_root=Path("uploads"))
        upsert("Demo Approved Wildlife Park", "demo.approved@zootique.test", missing=False, upload_root=Path("uploads"), status="approved")
        upsert("Demo Rejected Wildlife Park", "demo.rejected@zootique.test", missing=True, upload_root=Path("uploads"), status="rejected")
        legacy = EstablishmentRegistration.query.filter_by(establishment_name="Lyger Zoo").first()
        if legacy:
            legacy.is_legacy_migration = True
            legacy.status = "approved_legacy"
    print("Registration review demo scenarios seeded.")
