import socket

import pytest


@pytest.fixture
def free_ports():
    """Reserva n puertos efimeros y los suelta justo antes de devolverlos.

    Hay una ventana de carrera inevitable entre soltar y que el test los use.
    Es la misma que tiene cualquier test de red y no vale la pena cerrarla.
    """

    def reservar(n):
        socks = []
        for _ in range(n):
            sock = socket.socket()
            sock.bind(("127.0.0.1", 0))
            socks.append(sock)
        numeros = tuple(s.getsockname()[1] for s in socks)
        for sock in socks:
            sock.close()
        return numeros

    return reservar
