from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from data.models import SessionLocal, Product, Store
from pydantic import BaseModel
from typing import List, Optional

router = APIRouter()

# Schema for creating a new product
class ProductCreate(BaseModel):
    name: str
    url: str
    store_id: str
    custom_interval: Optional[int] = None
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

@router.post("/products")
def add_new_product(prod: ProductCreate, db: Session = Depends(get_db)):
    # Checks if the store exists before adding the product
    store = db.query(Store).filter(Store.id == prod.store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found. Please register the store or run the scraper once.")
    
    db_product = Product(**prod.dict())
    db.add(db_product)
    db.commit()
    return {"message": "Product added successfully", "product_id": db_product.id}