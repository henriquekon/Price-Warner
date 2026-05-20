from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Query, Session
from data.models import SessionLocal, Product, Store
from pydantic import BaseModel, Field
from typing import List, Optional

router = APIRouter()

# Schema for creating a new product
class ProductCreate(BaseModel):
    name: str
    url: str
    store_id: str
    interval: Optional[int] = Field(default=30, description="Interval in minutes")
    target_drop_percentage: Optional[float] = 10.0

# Dependency to get DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.get("/products")
def get_all_products(db: Session = Depends(get_db)):
    return db.query(Product).all()

# Search by name
@router.get("/products/search")
def search_products(q: str = Query(..., min_length=1), db: Session = Depends(get_db)):
    results = db.query(Product).filter(Product.name.ilike(f"%{q}%")).all()
    return results

@router.post("/products")
def add_new_product(prod: ProductCreate, db: Session = Depends(get_db)):
    # Checks if the store exists before adding the product
    store = db.query(Store).filter(Store.id == prod.store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found. Please register the store or run the scraper once.")
    
    data = prod.dict()
    if data.get("interval") is None:
        data["interval"] = 30

    db_product = Product(**data)
    db.add(db_product)
    db.commit()
    db.refresh(db_product)
    
    return {"message": "Product added successfully", "product_id": db_product.id}