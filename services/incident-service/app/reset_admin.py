"""Development-only admin recovery command.

Run inside the container: python -m app.reset_admin
"""
import os

from sqlalchemy.orm import Session

from app.main import Base, User, UserRole, engine, passwords


def main() -> None:
    Base.metadata.create_all(engine)
    email = os.getenv("BOOTSTRAP_ADMIN_EMAIL", "admin@opspulse.local")
    password = os.getenv("BOOTSTRAP_ADMIN_PASSWORD", "ChangeMe123!")
    with Session(engine) as session:
        user = session.query(User).filter_by(email=email).first()
        if user is None:
            user = User(email=email, password_hash=passwords.hash(password), role=UserRole.ADMIN)
            session.add(user)
        else:
            user.password_hash = passwords.hash(password)
            user.role = UserRole.ADMIN
        session.commit()
    print(f"Admin password reset for {email}")


if __name__ == "__main__":
    main()
