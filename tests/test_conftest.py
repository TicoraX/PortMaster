"""El reparto de puertos entre workers, que es lo que hace seguro correr en paralelo.

`free_ports` elige un numero al azar, lo bindea para ver si esta libre y lo
suelta antes de devolverlo. Esa ventana entre soltar y usar hoy la disputan los
tests de a uno. Con `pytest -n`, cada worker es un proceso aparte y la disputan
todos a la vez, asi que dos tests pueden recibir el mismo puerto y pelearse por
el. Partir la banda por worker hace que esa carrera no exista, en vez de hacerla
menos probable.

El conftest tambien lo dice: esta clase de intermitente ya costo tres rojos de
CI, y un intermitente que aparece una vez cada veinte corridas es peor que uno
que aparece siempre.
"""

import conftest


def test_sin_xdist_se_usa_la_banda_entera(monkeypatch):
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    monkeypatch.delenv("PYTEST_XDIST_WORKER_COUNT", raising=False)
    assert conftest.banda() == conftest.BANDA


def test_las_franjas_de_los_workers_no_se_pisan(monkeypatch):
    total = 8
    monkeypatch.setenv("PYTEST_XDIST_WORKER_COUNT", str(total))
    franjas = []
    for i in range(total):
        monkeypatch.setenv("PYTEST_XDIST_WORKER", f"gw{i}")
        franjas.append(conftest.banda())

    assert len(set(franjas)) == total, f"hay franjas repetidas: {franjas}"

    ocupados = set()
    for inicio, fin in franjas:
        assert inicio <= fin, f"franja vacia o invertida: {(inicio, fin)}"
        assert conftest.BANDA[0] <= inicio and fin <= conftest.BANDA[1], (
            f"{(inicio, fin)} se sale de {conftest.BANDA}, que esta debajo del "
            "rango efimero a proposito"
        )
        puertos = set(range(inicio, fin + 1))
        assert not (puertos & ocupados), f"{(inicio, fin)} pisa a otro worker"
        ocupados |= puertos

    # Con 200 intentos como tope, una franja chica deja al azar sin donde caer.
    for inicio, fin in franjas:
        assert fin - inicio >= 200, f"franja de {fin - inicio} puertos, muy corta"


def test_un_worker_que_no_se_puede_leer_cae_a_la_banda_entera(monkeypatch):
    """Mejor la banda entera que una franja inventada a partir de basura."""
    monkeypatch.setenv("PYTEST_XDIST_WORKER_COUNT", "4")
    for raro in ("master", "", "gwX", "otro-runner"):
        monkeypatch.setenv("PYTEST_XDIST_WORKER", raro)
        assert conftest.banda() == conftest.BANDA, f"con {raro!r} invento una franja"
