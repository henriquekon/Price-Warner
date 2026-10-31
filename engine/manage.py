"""Create the initial private administrator and optionally claim legacy monitors."""
import argparse
import getpass
from sqlalchemy import select
from data.models import Monitoring, SessionLocal, User
from engine.auth import hash_password
from engine.migrations import upgrade


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("create-admin", choices=["create-admin"])
    parser.add_argument("--email", required=True)
    parser.add_argument("--claim-local", action="store_true")
    args = parser.parse_args()
    upgrade()
    password = getpass.getpass("Password (12 or more characters): ")
    with SessionLocal.begin() as db:
        if db.scalar(select(User).where(User.email == args.email.strip().lower())):
            parser.error("Account already exists")
        user = User(email=args.email.strip().lower(), password_hash=hash_password(password), is_admin=True)
        db.add(user)
        db.flush()
        if args.claim_local:
            local = db.scalar(select(User).where(User.email == "local@price-warner.invalid"))
            if local:
                for monitoring in db.scalars(select(Monitoring).where(Monitoring.user_id == local.id)).all():
                    db.add(Monitoring(user_id=user.id, product_id=monitoring.product_id,
                                      interval=monitoring.interval,
                                      target_drop_percentage=monitoring.target_drop_percentage,
                                      is_active=monitoring.is_active))
    print("Administrator created")


if __name__ == "__main__":
    main()
