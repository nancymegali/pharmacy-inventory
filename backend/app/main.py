
from fastapi import FastAPI

app = FastAPI(
    title="Pharmacy Inventory API",
    description="API for managing pharmacy inventory",
    version="1.0.0",
)


@app.get("/")
def home():
    return {
        "message": "Pharmacy Inventory API is running!"
    }


@app.get("/health")
def health_check():
    return {"status": "healthy"}
