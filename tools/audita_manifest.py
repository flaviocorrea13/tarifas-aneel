# Auditoria: braces, manifest, strings e traduções.
import json
import pathlib

RAIZ = pathlib.Path(
    "D:/Documentos/Documents/GitHub/tarifas-aneel/custom_components/tarifas_aneel"
)
falhas = 0


def ok(msg):
    print("OK    :", msg)


def falha(msg):
    global falhas
    falhas += 1
    print("FALHA :", msg)


def chaves_de(obj):
    saida = set()
    if isinstance(obj, dict):
        for chave, val in obj.items():
            saida.add(chave)
            saida |= chaves_de(val)
    elif isinstance(obj, list):
        for item in obj:
            saida |= chaves_de(item)
    return saida


dados = (RAIZ / "manifest.json").read_bytes()
bom = dados.startswith(b"\xef\xbb\xbf")
try:
    manifest = json.loads(dados.decode("utf-8"))
    ok("manifest.json JSON válido (BOM=%s)" % bom)
except Exception as err:
    falha("manifest.json: %s" % err)
    manifest = {}

if manifest:
    for exigida in (
        "domain",
        "name",
        "version",
        "config_flow",
        "documentation",
        "issue_tracker",
        "codeowners",
        "iot_class",
        "integration_type",
    ):
        if exigida not in manifest:
            falha("manifest sem chave '%s'" % exigida)
        else:
            ok("manifest tem '%s'" % exigida)
    ordem = list(manifest)
    if ordem[0] == "domain" and ordem[1] == "name" and ordem[2:] == sorted(ordem[2:]):
        ok("ordem das chaves correta")

print()
print("TOTAL FALHAS:", falhas)
