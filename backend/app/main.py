
import os
from fastapi.middleware.cors import CORSMiddleware
from datetime import date, datetime
from decimal import Decimal
from urllib.parse import quote_plus
from typing import Literal


from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
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

engine = create_engine(DATABASE_URL, pool_pre_ping=True)

app = FastAPI(
    title="Pharmacy Inventory API",
    description="API for managing pharmacy inventory",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

class MedicationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    strength: str = Field(min_length=1, max_length=50)
    dosage_form: str = Field(min_length=1, max_length=50)
    ndc: str | None = Field(default=None, max_length=20)
    quantity: int = Field(default=0, ge=0)
    reorder_level: int = Field(default=10, ge=0)
    unit_price: Decimal | None = Field(default=None, ge=0)
    expiration_date: date | None = None
    supplier: str | None = Field(default=None, max_length=150)


class MedicationUpdate(MedicationCreate):
    pass



class StockMovementCreate(BaseModel):
    medication_id: int = Field(gt=0)
    movement_type: Literal["received", "removed", "adjustment"]
    quantity: int = Field(gt=0)
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
def get_medications():
    try:
        with engine.connect() as connection:
            rows = connection.execute(
                text("SELECT * FROM medications ORDER BY name")
            ).mappings().all()
        return [medication_dict(row) for row in rows]
    except SQLAlchemyError:
        raise HTTPException(
            status_code=500, detail="Could not retrieve medications"
        )


@app.post("/medications", status_code=201)
def create_medication(medication: MedicationCreate):
    data = medication.model_dump()
    try:
        with engine.begin() as connection:
            result = connection.execute(
                text("""
                    INSERT INTO medications
                    (name, strength, dosage_form, ndc, quantity, reorder_level,
                    unit_price, expiration_date, supplier)
                    VALUES
                    (:name, :strength, :dosage_form, :ndc, :quantity, :reorder_level,
                    :unit_price, :expiration_date, :supplier)
                """),
                data,
            )
            new_id = result.lastrowid
            row = connection.execute(
                text("SELECT * FROM medications WHERE id = :id"),
                {"id": new_id},
            ).mappings().one()
        return medication_dict(row)
    except SQLAlchemyError:
        raise HTTPException(
            status_code=500, detail="Could not create medication"
        )


@app.put("/medications/{medication_id}")
def update_medication(
    medication_id: int, medication: MedicationUpdate
):
    data = medication.model_dump()
    data["id"] = medication_id
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
                        supplier = :supplier
                    WHERE id = :id
                """),
                data,
            )
            if result.rowcount == 0:
                exists = connection.execute(
                    text("SELECT id FROM medications WHERE id = :id"),
                    {"id": medication_id},
                ).first()
                if not exists:
                    raise HTTPException(
                        status_code=404, detail="Medication not found"
                    )
            row = connection.execute(
                text("SELECT * FROM medications WHERE id = :id"),
                {"id": medication_id},
            ).mappings().one()
        return medication_dict(row)
    except SQLAlchemyError:
        raise HTTPException(
            status_code=500, detail="Could not update medication"
        )


@app.delete("/medications/{medication_id}")
def delete_medication(medication_id: int):
    try:
        with engine.begin() as connection:
            result = connection.execute(
                text("DELETE FROM medications WHERE id = :id"),
                {"id": medication_id},
            )
            if result.rowcount == 0:
                raise HTTPException(
                    status_code=404, detail="Medication not found"
                )
        return {"message": "Medication deleted successfully"}
    except SQLAlchemyError:
        raise HTTPException(
            status_code=500, detail="Could not delete medication"
        )
    

@app.post("/stock-movements", status_code=201)
def create_stock_movement(movement: StockMovementCreate):
    try:
        with engine.begin() as connection:
            # Lock the medication row while processing this movement.
            medication = connection.execute(
                text("""
                    SELECT id, quantity
                    FROM medications
                    WHERE id = :id
                    FOR UPDATE
                """),
                {"id": movement.medication_id},
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
                # Adjustment sets the stock to the requested quantity.
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
                """),
                {
                    "quantity": new_quantity,
                    "id": movement.medication_id,
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
def get_stock_movements():
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
                    ORDER BY sm.created_at DESC, sm.id DESC
                """)
            ).mappings().all()

        return [medication_dict(row) for row in rows]

    except SQLAlchemyError:
        raise HTTPException(
            status_code=500,
            detail="Could not retrieve stock movement history",
        )

