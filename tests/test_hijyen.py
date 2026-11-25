"""Paket ve örnekler taşınabilir: yerel yol, sys.path oyunu, gömülü model/sağlayıcı adı yok."""
import re
from pathlib import Path

from conftest import KOK

KAYNAK = sorted((KOK / "src" / "vaka").glob("*.py"))
ORNEKLER = sorted((KOK / "ornek").rglob("*.*"))
# Model seçimi kullanıcının ajan komutundadır: kaynakta ve örneklerde sabit model değeri ya da --model bayrağı olmaz.
MODEL_SECIMI = re.compile(r"""(?i)(--model\b|\bmodel(_adi|_id)?\s*[=:]\s*["'][^"']+["'])""")
YEREL_YOL = re.compile(r"[A-Za-z]:[\\/]+Users|/home/|/Users/")


def oku(p):
    return Path(p).read_text(encoding="utf-8")


def test_kaynak_dosyalari_var():
    assert {p.name for p in KAYNAK} >= {"cli.py", "bicim.py", "kum.py", "dogrula.py", "ajan.py", "butce.py", "hakem.py",
                                        "gunluk.py"}
    assert ORNEKLER


def test_kaynakta_yerel_yol_ve_sys_path_yok():
    for p in KAYNAK:
        metin = oku(p)
        assert not YEREL_YOL.search(metin), p.name
        assert "sys.path" not in metin, p.name


def test_kaynakta_ve_orneklerde_sabit_model_secimi_yok():
    for p in KAYNAK + ORNEKLER:
        assert not MODEL_SECIMI.search(oku(p)), p.name


def test_model_secimi_deseni_yakalar():
    assert MODEL_SECIMI.search('model = "ornek-model-1"') and MODEL_SECIMI.search("ajan --model x")
    assert not MODEL_SECIMI.search("vaka dogrula model çağırmaz")
