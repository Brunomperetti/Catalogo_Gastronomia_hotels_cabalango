from types import SimpleNamespace

from sqlalchemy import create_engine, inspect, text

from app import main


def accommodation(**values):
    defaults = {
        "nombre": "Alojamiento",
        "theme": "alojamiento",
        "subtipo": "Cabaña",
        "capacidad": None,
        "habitaciones": None,
        "banos": None,
        "alojamiento_modalidad": None,
        "alojamiento_detalle_unidades": None,
        "precio_desde": None,
        "destacado": False,
    }
    defaults.update(values)
    return SimpleNamespace(**defaults)


def test_bootstrap_adds_multi_unit_columns_idempotently(monkeypatch):
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE empresas (id INTEGER PRIMARY KEY, nombre VARCHAR)"))
        connection.execute(text("INSERT INTO empresas (nombre) VALUES ('Legacy')"))
    monkeypatch.setattr(main, "engine", engine)

    main.ensure_empresa_media_columns()
    main.ensure_empresa_media_columns()

    columns = {column["name"] for column in inspect(engine).get_columns("empresas")}
    assert {"alojamiento_modalidad", "alojamiento_detalle_unidades"} <= columns
    with engine.connect() as connection:
        row = connection.execute(text("SELECT nombre, alojamiento_modalidad, alojamiento_detalle_unidades FROM empresas")).one()
    assert row == ("Legacy", None, None)


def test_legacy_and_individual_facts_are_unchanged():
    legacy = accommodation(capacidad="4", habitaciones="2", banos="1")
    assert not main.is_alojamiento_complejo(legacy)
    assert main.build_alojamiento_key_facts(legacy) == ["4 personas", "2 habitaciones", "1 baño"]
    assert main.get_alojamiento_card_type(legacy) == "Cabaña"


def test_invalid_modalities_are_safe_and_only_explicit_complex_is_recognized():
    assert main.normalize_alojamiento_modalidad(" individual ") == "individual"
    assert main.normalize_alojamiento_modalidad("COMPLEJO") == "complejo"
    assert main.normalize_alojamiento_modalidad("hotel") is None
    assert not main.is_alojamiento_complejo(accommodation(nombre="Complejo", alojamiento_modalidad="invalid"))
    assert not main.is_alojamiento_complejo(accommodation(theme="servicios", alojamiento_modalidad="complejo"))


def test_complex_card_uses_detail_and_hides_aggregate_room_counts():
    company = accommodation(
        capacidad="6", habitaciones="9", banos="9", alojamiento_modalidad="complejo",
        alojamiento_detalle_unidades="Cabañas para 4 o 6 personas",
    )
    facts = main.build_alojamiento_key_facts(company)
    assert main.get_alojamiento_card_type(company) == "COMPLEJO"
    assert facts == ["Cabañas para 4 o 6 personas"]
    assert "9 habitaciones" not in facts and "9 baños" not in facts


def test_complex_card_falls_back_to_capacity_per_unit():
    company = accommodation(capacidad="6", alojamiento_modalidad="complejo")
    assert main.build_alojamiento_key_facts(company) == ["Hasta 6 personas por unidad"]


def test_capacity_filter_uses_only_maximum_capacity_per_unit():
    companies = [
        accommodation(nombre="A", capacidad="5", alojamiento_modalidad="complejo", alojamiento_detalle_unidades="hasta 50 en total"),
        accommodation(nombre="B", capacidad="6", alojamiento_modalidad="complejo"),
        accommodation(nombre="C", capacidad="8", alojamiento_modalidad="complejo"),
    ]
    result = main.filter_alojamientos(companies, {"capacidad": "7", "tipo": "todos"})
    assert [company.nombre for company in result] == ["C"]


def test_room_filter_excludes_complex_aggregate_counts():
    individual = accommodation(nombre="Individual", habitaciones="3")
    complex_company = accommodation(nombre="Complejo", habitaciones="9", alojamiento_modalidad="complejo")
    result = main.filter_alojamientos([individual, complex_company], {"habitaciones": "3", "tipo": "todos"})
    assert [company.nombre for company in result] == ["Individual"]


def test_complex_type_filter_matches_explicit_modality_despite_subtype():
    company = accommodation(subtipo="Cabaña", alojamiento_modalidad="complejo")
    assert main.filter_alojamientos([company], {"tipo": "complejo"}) == [company]


def test_capacity_order_uses_numeric_capacity_not_detail():
    companies = [
        accommodation(nombre="Five", capacidad="5", alojamiento_detalle_unidades="99", alojamiento_modalidad="complejo"),
        accommodation(nombre="Eight", capacidad="8", alojamiento_detalle_unidades="2", alojamiento_modalidad="complejo"),
        accommodation(nombre="Six", capacidad="6", alojamiento_detalle_unidades="100", alojamiento_modalidad="complejo"),
    ]
    result = main.filter_alojamientos(companies, {"tipo": "todos", "orden": "capacidad_desc"})
    assert [company.capacidad for company in result] == ["8", "6", "5"]


def test_complex_query_normalizes_stale_room_filter():
    from starlette.requests import Request

    request = Request({"type": "http", "query_string": b"tipo=complejo&habitaciones=3"})
    filters = main.get_alojamiento_filters(request)
    company = accommodation(capacidad="6", habitaciones="9", alojamiento_modalidad="complejo")

    assert filters["habitaciones"] == ""
    assert main.filter_alojamientos([company], filters) == [company]


def test_individual_type_room_filter_still_applies():
    house = accommodation(subtipo="Casa", habitaciones="2", alojamiento_modalidad="individual")
    assert main.filter_alojamientos([house], {"tipo": "casa", "habitaciones": "2"}) == [house]
