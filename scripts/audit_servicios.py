"""Read-only audit of the historical services taxonomy.

Render shell: python scripts/audit_servicios.py
"""
from app.database import SessionLocal
from app.models import Empresa


def main() -> None:
    db = SessionLocal()
    try:
        rows = db.query(Empresa).filter(Empresa.theme == "servicios").order_by(Empresa.id).all()
        print("id\tnombre\tslug\tsubgrupo\tsubtipo\tactivo")
        for row in rows:
            print(f"{row.id}\t{row.nombre}\t{row.slug}\t{row.subgrupo or ''}\t{row.subtipo or ''}\t{row.activo}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
