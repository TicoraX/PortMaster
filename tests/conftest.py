import random
import socket

import pytest

# Debajo del rango efimero de los tres sistemas: Linux reparte desde 32768,
# macOS y Windows desde 49152. Pedir `bind(port 0)` devuelve uno de ahi arriba,
# que es justo el que el SO le esta dando a todo lo demas: entre que la fixture
# lo suelta y el test lo usa, se lo lleva cualquiera. Aca abajo nadie asigna
# nada por su cuenta, asi que la ventana solo la disputan los tests entre si.
#
# No es teorico. Costo tres rojos de CI: un mes buscando un intermitente que
# resulto ser next_free escaneando dentro del rango efimero, y dos "nunca quedo
# listo" en ubuntu 3.10 con el servidor de prueba sin poder bindear.
BANDA = (20000, 30000)


@pytest.fixture
def free_ports():
    """Reserva n puertos libres y los suelta justo antes de devolverlos."""

    def reservar(n):
        socks = []
        numeros = []
        intentos = 0
        while len(numeros) < n:
            intentos += 1
            if intentos > 200:
                raise RuntimeError(f"sin puertos libres en {BANDA} despues de 200 intentos")
            candidato = random.randint(*BANDA)
            if candidato in numeros:
                continue
            sock = socket.socket()
            try:
                sock.bind(("127.0.0.1", candidato))
            except OSError:
                sock.close()
                continue
            socks.append(sock)
            numeros.append(candidato)
        for sock in socks:
            sock.close()
        return tuple(numeros)

    return reservar
