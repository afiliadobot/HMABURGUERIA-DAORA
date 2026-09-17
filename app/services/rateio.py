"""
Rateio com resíduo determinístico — padrão já estabelecido e reutilizado em
várias partes do sistema (rateio de custo fixo, rateio de taxa fixa por pedido,
e agora rateio de frete entre itens de uma compra).

Regra: divide um total (inteiro) proporcionalmente a uma lista de pesos; se a
divisão não fechar exata, o centavo (ou milicentavo, etc.) que sobra vai
inteiro para o item de MAIOR peso — nunca se perde, nunca se duplica.
"""


def ratear_com_residuo(total: int, pesos: list[int]) -> list[int]:
    """Retorna uma lista de mesmo tamanho que `pesos`, cuja soma é EXATAMENTE
    `total`. Se `pesos` somar zero (nenhum peso), o total inteiro vai para o
    primeiro item — caso de borda raro, mas nunca deve ficar indefinido."""
    soma_pesos = sum(pesos)
    if soma_pesos == 0:
        resultado = [0] * len(pesos)
        if resultado:
            resultado[0] = total
        return resultado

    brutos = [(total * peso) / soma_pesos for peso in pesos]
    floors = [int(b) for b in brutos]
    residuo = total - sum(floors)

    idx_maior_peso = max(range(len(pesos)), key=lambda i: pesos[i])
    floors[idx_maior_peso] += residuo
    return floors
