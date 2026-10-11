from acxes.output_guard import guard_text


def test_la_guardia_elimina_marcas_citas_inventadas_y_pii():
    result = guard_text(
        "Dato <<<DATOS chunk_id=c-1>>> [c-1] [c-999] "
        "correo usuario@example.com CC 1234567890 <<<FIN DATOS>>>",
        ("c-1",),
    )

    assert result.text == "Dato [c-1] correo [redactado] CC [redactado]"
    assert result.redactions == 2
    assert result.invalid_citations == 1


def test_la_guardia_no_inventa_una_cita_si_no_hay_chunks():
    result = guard_text("Respuesta sin fuente [c-1].", ())

    assert result.text == "Respuesta sin fuente."
    assert result.invalid_citations == 1


def test_la_guardia_no_redacta_fechas_ni_montos():
    result = guard_text(
        "Fecha 2026-09-21, vigencia 15-03-2026 a 15/04/2026. "
        "Salario 3 500 000, 3.500.000 y $3,500,000.",
        (),
    )
    assert result.redactions == 0
    assert "2026-09-21" in result.text and "$3,500,000" in result.text


def test_la_guardia_redacta_telefonos_y_conserva_citas_validas():
    result = guard_text(
        "Llámame al 3001234567 o al +57 300 123 4567, correo a@b.co [c-1].",
        ("c-1",),
    )
    assert result.text.count("[redactado]") == 3
    assert "[c-1]" in result.text
