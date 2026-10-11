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
