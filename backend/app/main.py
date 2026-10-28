import secrets
import hashlib
from datetime import datetime, timedelta, timezone
import requests

import os
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal
from urllib.parse import quote_plus
from typing import Optional

import jwt
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer, OAuth2PasswordRequestForm
from pwdlib import PasswordHash
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError


load_dotenv()

DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT = os.getenv("DB_PORT", "3306")
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_NAME = os.getenv("DB_NAME", "pharmacy_inventory")

if not DB_PASSWORD:
    raise RuntimeError("DB_PASSWORD is missing from backend/.env")

DATABASE_URL = (
    f"mysql+pymysql://{DB_USER}:{quote_plus(DB_PASSWORD)}"
    f"@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)

DB_SSL = os.getenv("DB_SSL", "false").lower() == "true"

connect_args = {}
if DB_SSL:
    connect_args["ssl"] = {"ssl": True}

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    connect_args=connect_args,
)

JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")
BREVO_API_KEY = os.getenv("BREVO_API_KEY")
BREVO_SENDER_EMAIL = os.getenv("BREVO_SENDER_EMAIL")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")

if not JWT_SECRET_KEY:
    raise RuntimeError("JWT_SECRET_KEY is missing from backend/.env")

password_hash = PasswordHash.recommended()
oauth2_scheme = HTTPBearer()
ACCESS_TOKEN_EXPIRE_MINUTES = 60
DEMO_PHARMACY_ID = 5


app = FastAPI(
    title="Pharmacy Inventory API",
    description="API for managing pharmacy inventory",
    version="1.0.0",
)

frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173")

allowed_origins = [
    frontend_url.rstrip("/"),
    "https://pharmacy-inventory-eight-theta.vercel.app",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5174",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class PharmacyRegister(BaseModel):
    store_name: str = Field(min_length=2, max_length=150)
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=1)
    new_password: str = Field(min_length=12, max_length=128)


class MedicationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    strength: str = Field(min_length=1, max_length=50)
    dosage_form: str = Field(min_length=1, max_length=50)
    ndc: str | None = Field(default=None, max_length=20)
    quantity: Decimal = Field(default=Decimal("0"), ge=0, decimal_places=3)
    reorder_level: Decimal = Field(default=Decimal("10"), ge=0, decimal_places=3)
    unit_price: Decimal | None = Field(default=None, ge=0)
    expiration_date: date | None = None
    supplier: str | None = Field(default=None, max_length=150)
    package_size: Optional[int] = Field(default=None, gt=0)
    package_price: Optional[Decimal] = Field(default=None, ge=0, decimal_places=2)


class MedicationUpdate(MedicationCreate):
    pass



class StockMovementCreate(BaseModel):
    medication_id: int = Field(gt=0)
    movement_type: Literal["received", "removed", "adjustment"]
    quantity: Decimal = Field(ge=0, decimal_places=3)
    reason: str | None = Field(default=None, max_length=255)


def serialize_value(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def medication_dict(row):
    return {
        key: serialize_value(value)
        for key, value in row.items()
    }



def create_access_token(user_id: int, pharmacy_id: int) -> str:
    now = datetime.now(timezone.utc)

    payload = {
        "sub": str(user_id),
        "pharmacy_id": pharmacy_id,
        "iat": now,
        "exp": now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    }

    return jwt.encode(payload, JWT_SECRET_KEY, algorithm="HS256")


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(oauth2_scheme)
):
    token = credentials.credentials

    try:
        payload = jwt.decode(
            token,
            JWT_SECRET_KEY,
            algorithms=["HS256"],
        )

        user_id = int(payload["sub"])
        pharmacy_id = int(payload["pharmacy_id"])
    except (jwt.InvalidTokenError, KeyError, TypeError, ValueError):
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired login token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        with engine.connect() as connection:
            user = connection.execute(
                text("""
                    SELECT id, pharmacy_id, email
                    FROM users
                    WHERE id = :user_id
                      AND pharmacy_id = :pharmacy_id
                """),
                {
                    "user_id": user_id,
                    "pharmacy_id": pharmacy_id,
                },
            ).mappings().first()

        if not user:
            raise HTTPException(
                status_code=401,
                detail="Account not found",
                headers={"WWW-Authenticate": "Bearer"},
            )

        return dict(user)

    except SQLAlchemyError:
        raise HTTPException(
            status_code=500,
            detail="Could not verify account",
        )


def require_write_access(current_user=Depends(get_current_user)):
    if current_user["pharmacy_id"] == DEMO_PHARMACY_ID:
        raise HTTPException(
            status_code=403,
            detail="Demo mode is read-only. Changes are disabled.",
        )

    return current_user


@app.post("/auth/register", status_code=201)
def register_pharmacy(account: PharmacyRegister):
    email = account.email.lower()

    try:
        with engine.begin() as connection:
            existing_user = connection.execute(
                text("SELECT id FROM users WHERE email = :email"),
                {"email": email},
            ).first()

            if existing_user:
                raise HTTPException(
                    status_code=409,
                    detail="An account with this email already exists",
                )

            pharmacy_result = connection.execute(
                text("""
                    INSERT INTO pharmacies (store_name, contact_email)
                    VALUES (:store_name, :email)
                """),
                {
                    "store_name": account.store_name.strip(),
                    "email": email,
                },
            )

            pharmacy_id = pharmacy_result.lastrowid

            user_result = connection.execute(
                text("""
                    INSERT INTO users (pharmacy_id, email, password_hash)
                    VALUES (:pharmacy_id, :email, :password_hash)
                """),
                {
                    "pharmacy_id": pharmacy_id,
                    "email": email,
                    "password_hash": password_hash.hash(account.password),
                },
            )

            user_id = user_result.lastrowid

        return {
            "message": "Pharmacy account created successfully",
            "user_id": user_id,
            "pharmacy_id": pharmacy_id,
            "store_name": account.store_name.strip(),
            "email": email,
        }

    except HTTPException:
        raise
    except SQLAlchemyError:
        raise HTTPException(
            status_code=500,
            detail="Could not create pharmacy account",
        )


@app.post("/auth/forgot-password")
def forgot_password(request: ForgotPasswordRequest):
    email = request.email.lower()

    # Always return the same message to avoid revealing
    # whether an account exists for this email.
    response_message = {
        "message": (
            "If an account exists for that email, "
            "a password reset link has been sent."
        )
    }

    try:
        with engine.connect() as connection:
            user = connection.execute(
                text("""
                    SELECT id
                    FROM users
                    WHERE email = :email
                """),
                {"email": email},
            ).mappings().first()

        if not user:
            return response_message

        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(
            raw_token.encode("utf-8")
        ).hexdigest()

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        expires_at = now + timedelta(minutes=30)

        with engine.begin() as connection:
            # Invalidate previous unused reset tokens.
            connection.execute(
                text("""
                    UPDATE password_reset_tokens
                    SET used_at = :now
                    WHERE user_id = :user_id
                      AND used_at IS NULL
                """),
                {
                    "now": now,
                    "user_id": user["id"],
                },
            )

            connection.execute(
                text("""
                    INSERT INTO password_reset_tokens
                    (user_id, token_hash, expires_at)
                    VALUES (:user_id, :token_hash, :expires_at)
                """),
                {
                    "user_id": user["id"],
                    "token_hash": token_hash,
                    "expires_at": expires_at,
                },
            )

        reset_link = (
            f"{FRONTEND_URL}/#reset-token={raw_token}"
        )

        email_payload = {
            "sender": {
                "name": "MedStock",
                "email": BREVO_SENDER_EMAIL,
            },
            "to": [{"email": email}],
            "subject": "Reset your MedStock password",
            "textContent": (
                "We received a request to reset your MedStock password. "
                "Open this link within 30 minutes to choose a new password:\n\n"
                f"{reset_link}\n\n"
                "If you did not request this, you can ignore this email."
            ),
            "htmlContent": (
                "<p>We received a request to reset your MedStock password.</p>"
                "<p>This link expires in 30 minutes.</p>"
                f'<p><a href="{reset_link}">Reset your password</a></p>'
                "<p>If you did not request this, you can ignore this email.</p>"
            ),
        }

        try:
            email_response = requests.post(
                "https://api.brevo.com/v3/smtp/email",
                headers={
                    "api-key": BREVO_API_KEY or "",
                    "accept": "application/json",
                    "content-type": "application/json",
                },
                json=email_payload,
                timeout=10,
            )
            email_response.raise_for_status()

        except requests.RequestException:
            # Invalidate the token if the email could not be sent.
            with engine.begin() as connection:
                connection.execute(
                    text("""
                        UPDATE password_reset_tokens
                        SET used_at = :now
                        WHERE token_hash = :token_hash
                    """),
                    {
                        "now": datetime.now(timezone.utc).replace(
                            tzinfo=None
                        ),
                        "token_hash": token_hash,
                    },
                )

            raise HTTPException(
                status_code=502,
                detail="Could not send the password reset email. Please try again.",
            )

        return response_message

    except HTTPException:
        raise
    except SQLAlchemyError:
        raise HTTPException(
            status_code=500,
            detail="Could not process the password reset request.",
        )


@app.post("/auth/reset-password")
def reset_password(request: ResetPasswordRequest):
    token_hash = hashlib.sha256(
        request.token.encode("utf-8")
    ).hexdigest()

    now = datetime.now(timezone.utc).replace(tzinfo=None)

    try:
        with engine.begin() as connection:
            reset_record = connection.execute(
                text("""
                    SELECT user_id
                    FROM password_reset_tokens
                    WHERE token_hash = :token_hash
                      AND used_at IS NULL
                      AND expires_at > :now
                """),
                {
                    "token_hash": token_hash,
                    "now": now,
                },
            ).mappings().first()

            if not reset_record:
                raise HTTPException(
                    status_code=400,
                    detail="This reset link is invalid or has expired.",
                )

            connection.execute(
                text("""
                    UPDATE users
                    SET password_hash = :password_hash
                    WHERE id = :user_id
                """),
                {
                    "password_hash": password_hash.hash(
                        request.new_password
                    ),
                    "user_id": reset_record["user_id"],
                },
            )

            # Mark this token used and invalidate other reset links.
            connection.execute(
                text("""
                    UPDATE password_reset_tokens
                    SET used_at = :now
                    WHERE user_id = :user_id
                      AND used_at IS NULL
                """),
                {
                    "now": now,
                    "user_id": reset_record["user_id"],
                },
            )

        return {
            "message": "Password reset successfully. You can now log in."
        }

    except HTTPException:
        raise
    except SQLAlchemyError:
        raise HTTPException(
            status_code=500,
            detail="Could not reset the password. Please try again.",
        )
    

@app.post("/auth/demo")
def demo_login():
    try:
        with engine.connect() as connection:
            demo_user = connection.execute(
                text("""
                    SELECT id, pharmacy_id
                    FROM users
                    WHERE pharmacy_id = :pharmacy_id
                    LIMIT 1
                """),
                {"pharmacy_id": DEMO_PHARMACY_ID},
            ).mappings().first()

    except SQLAlchemyError:
        raise HTTPException(
            status_code=500,
            detail="Could not access demo account",
        )

    if not demo_user:
        raise HTTPException(
            status_code=503,
            detail="Demo account is not configured yet",
        )

    token = create_access_token(
        user_id=demo_user["id"],
        pharmacy_id=demo_user["pharmacy_id"],
    )

    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    }


@app.post("/auth/login")
def login(form_data: OAuth2PasswordRequestForm = Depends()):
    email = form_data.username.lower()

    try:
        with engine.connect() as connection:
            user = connection.execute(
                text("""
                    SELECT
                        u.id,
                        u.pharmacy_id,
                        u.email,
                        u.password_hash,
                        p.store_name
                    FROM users u
                    JOIN pharmacies p ON p.id = u.pharmacy_id
                    WHERE u.email = :email
                """),
                {"email": email},
            ).mappings().first()

    except SQLAlchemyError:
        raise HTTPException(
            status_code=500,
            detail="Could not access account",
        )

    if not user or not password_hash.verify(
        form_data.password, user["password_hash"]
    ):
        raise HTTPException(
            status_code=401,
            detail="Incorrect email or password",
        )

    token = create_access_token(
        user_id=user["id"],
        pharmacy_id=user["pharmacy_id"],
    )

    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    }




@app.get("/")
def home():
    return {"message": "Pharmacy Inventory API is running!"}


@app.get("/health")
def health_check():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return {"status": "healthy", "database": "connected"}
    except SQLAlchemyError:
        raise HTTPException(
            status_code=503, detail="Database connection failed"
        )



@app.get("/medications")
def get_medications(current_user=Depends(get_current_user)):
    try:
        with engine.connect() as connection:
            rows = connection.execute(
                text("""
                    SELECT *
                    FROM medications
                    WHERE pharmacy_id = :pharmacy_id
                    ORDER BY name
                """),
                {"pharmacy_id": current_user["pharmacy_id"]},
            ).mappings().all()

        return [medication_dict(row) for row in rows]

    except SQLAlchemyError:
        raise HTTPException(
            status_code=500,
            detail="Could not retrieve medications",
        )




@app.post("/medications", status_code=201)
def create_medication(
    medication: MedicationCreate,
    current_user=Depends(require_write_access),
):
    data = medication.model_dump()
    data["pharmacy_id"] = current_user["pharmacy_id"]

    try:
        with engine.begin() as connection:
            result = connection.execute(
                text("""
                    INSERT INTO medications
                    (
                        pharmacy_id, name, strength, dosage_form, ndc,
                        quantity, reorder_level, unit_price,
                        expiration_date, supplier, package_size, package_price
                    )
                    VALUES
                    (
                        :pharmacy_id, :name, :strength, :dosage_form, :ndc,
                        :quantity, :reorder_level, :unit_price,
                        :expiration_date, :supplier, :package_size, :package_price
                    )
                """),
                data,
            )

            row = connection.execute(
                text("""
                    SELECT *
                    FROM medications
                    WHERE id = :id
                      AND pharmacy_id = :pharmacy_id
                """),
                {
                    "id": result.lastrowid,
                    "pharmacy_id": current_user["pharmacy_id"],
                },
            ).mappings().one()

        return medication_dict(row)

    except SQLAlchemyError:
        raise HTTPException(
            status_code=500,
            detail="Could not create medication",
        )



@app.put("/medications/{medication_id}")
def update_medication(
    medication_id: int,
    medication: MedicationUpdate,
    current_user=Depends(require_write_access),
):
    data = medication.model_dump()
    data["id"] = medication_id
    data["pharmacy_id"] = current_user["pharmacy_id"]

    try:
        with engine.begin() as connection:
            result = connection.execute(
                text("""
                    UPDATE medications
                    SET name = :name,
                        strength = :strength,
                        dosage_form = :dosage_form,
                        ndc = :ndc,
                        quantity = :quantity,
                        reorder_level = :reorder_level,
                        unit_price = :unit_price,
                        expiration_date = :expiration_date,
                        supplier = :supplier,
                        package_size = :package_size,
                        package_price = :package_price
                    WHERE id = :id
                      AND pharmacy_id = :pharmacy_id
                """),
                data,
            )

            if result.rowcount == 0:
                raise HTTPException(
                    status_code=404,
                    detail="Medication not found",
                )

            row = connection.execute(
                text("""
                    SELECT *
                    FROM medications
                    WHERE id = :id
                      AND pharmacy_id = :pharmacy_id
                """),
                {
                    "id": medication_id,
                    "pharmacy_id": current_user["pharmacy_id"],
                },
            ).mappings().one()

        return medication_dict(row)

    except HTTPException:
        raise
    except SQLAlchemyError:
        raise HTTPException(
            status_code=500,
            detail="Could not update medication",
        )



@app.delete("/medications/{medication_id}")
def delete_medication(
    medication_id: int,
    current_user=Depends(require_write_access),
):
    try:
        with engine.begin() as connection:
            result = connection.execute(
                text("""
                    DELETE FROM medications
                    WHERE id = :id
                      AND pharmacy_id = :pharmacy_id
                """),
                {
                    "id": medication_id,
                    "pharmacy_id": current_user["pharmacy_id"],
                },
            )

            if result.rowcount == 0:
                raise HTTPException(
                    status_code=404,
                    detail="Medication not found",
                )

        return {"message": "Medication deleted successfully"}

    except HTTPException:
        raise
    except SQLAlchemyError:
        raise HTTPException(
            status_code=500,
            detail="Could not delete medication",
        )

    

@app.post("/stock-movements", status_code=201)
def create_stock_movement(
    movement: StockMovementCreate,
    current_user=Depends(require_write_access),
):
    pharmacy_id = current_user["pharmacy_id"]
    if movement.movement_type != "adjustment" and movement.quantity <= 0:
        raise HTTPException(
            status_code=422,
            detail="Quantity must be greater than 0 for received or removed stock",
        )

    try:
        with engine.begin() as connection:
            # Lock only a medication belonging to this pharmacy.
            medication = connection.execute(
                text("""
                    SELECT id, quantity
                    FROM medications
                    WHERE id = :id
                      AND pharmacy_id = :pharmacy_id
                    FOR UPDATE
                """),
                {
                    "id": movement.medication_id,
                    "pharmacy_id": pharmacy_id,
                },
            ).mappings().first()

            if not medication:
                raise HTTPException(
                    status_code=404,
                    detail="Medication not found",
                )

            current_quantity = medication["quantity"]

            if movement.movement_type == "received":
                change = movement.quantity
            elif movement.movement_type == "removed":
                change = -movement.quantity
            else:
                # Adjustment sets stock to the requested quantity.
                change = movement.quantity - current_quantity

            new_quantity = current_quantity + change

            if new_quantity < 0:
                raise HTTPException(
                    status_code=400,
                    detail="Insufficient stock for this removal",
                )

            connection.execute(
                text("""
                    UPDATE medications
                    SET quantity = :quantity
                    WHERE id = :id
                      AND pharmacy_id = :pharmacy_id
                """),
                {
                    "quantity": new_quantity,
                    "id": movement.medication_id,
                    "pharmacy_id": pharmacy_id,
                },
            )

            result = connection.execute(
                text("""
                    INSERT INTO stock_movements
                    (medication_id, movement_type, quantity_change, reason)
                    VALUES (:medication_id, :movement_type, :quantity_change, :reason)
                """),
                {
                    "medication_id": movement.medication_id,
                    "movement_type": movement.movement_type,
                    "quantity_change": change,
                    "reason": movement.reason,
                },
            )

            row = connection.execute(
                text("""
                    SELECT id, medication_id, movement_type,
                           quantity_change, reason, created_at
                    FROM stock_movements
                    WHERE id = :id
                """),
                {"id": result.lastrowid},
            ).mappings().one()

        return medication_dict(row)

    except HTTPException:
        raise
    except SQLAlchemyError:
        raise HTTPException(
            status_code=500,
            detail="Could not record stock movement",
        )



@app.get("/stock-movements")
def get_stock_movements(current_user=Depends(get_current_user)):
    pharmacy_id = current_user["pharmacy_id"]

    try:
        with engine.connect() as connection:
            rows = connection.execute(
                text("""
                    SELECT
                        sm.id,
                        sm.medication_id,
                        m.name AS medication_name,
                        sm.movement_type,
                        sm.quantity_change,
                        sm.reason,
                        sm.created_at
                    FROM stock_movements sm
                    JOIN medications m ON m.id = sm.medication_id
                    WHERE m.pharmacy_id = :pharmacy_id
                    ORDER BY sm.created_at DESC, sm.id DESC
                """),
                {"pharmacy_id": pharmacy_id},
            ).mappings().all()

        return [medication_dict(row) for row in rows]

    except SQLAlchemyError:
        raise HTTPException(
            status_code=500,
            detail="Could not retrieve stock movement history",
        )
