import streamlit as st
import pandas as pd
from data.models import SessionLocal, Product, PriceHistory, Store
import plotly.express as px
from sqlalchemy.orm import joinedload

st.set_page_config(page_title="Price-Warner Dashboard", layout="wide")

st.title("Price-Warner Control Panel")

def get_data():
    db = SessionLocal()
    try:
        products = db.query(Product).options(joinedload(Product.history)).all()
        stores = db.query(Store).all()
        history = db.query(PriceHistory).all()
        return products, stores, history
    finally:
        db.close()

products, stores, history = get_data()

# --- Top Metrics ---
col1, col2, col3 = st.columns(3)
col1.metric("Monitored Products", len(products))
col2.metric("Active Stores", len([s for s in stores if s.is_active]))
col3.metric("Price Records", len(history))

st.divider()

# --- Product List & Management ---
st.subheader("Product Inventory")
if products:
    df_prod = pd.DataFrame([{
        "ID": p.id,
        "Name": p.name,
        "Store": p.store_id,
        "Current Price": f"R$ {p.history[-1].price:.2f}" if p.history else "N/A",
        "Last Check": p.last_checked.strftime("%Y-%m-%d %H:%M") if p.last_checked else "Never",
        "Status": "✅ Active" if p.is_active else "❌ Inactive",
        "Target Drop": f"{p.target_drop_percentage}%"
    } for p in products])
    st.dataframe(df_prod, width='stretch')
else:
    st.info("No products found in database.")

# --- Price History Chart ---
st.divider()
st.subheader("Price Evolution")
selected_product = st.selectbox("Select a product to view history", 
                               options=[p.name for p in products] if products else ["None"])

if products and selected_product != "None":
    prod_obj = next(p for p in products if p.name == selected_product)
    
    if prod_obj.history:
        df_hist = pd.DataFrame([{
            "Date": h.fetched_at,
            "Price": h.price
        } for h in prod_obj.history])
        
        fig = px.line(df_hist, x="Date", y="Price", title=f"Price Trend: {selected_product}")
        st.plotly_chart(fig, width='stretch')
    else:
        st.warning("No history available for this product yet.")

# --- System Logs (Simulation) ---
st.divider()
st.subheader("Recent System Events")
if st.button("Refresh Data"):
    st.rerun()