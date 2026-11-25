"""Paket ve örnekler taşınabilir: yerel yol, sys.path oyunu, gömülü model/sağlayıcı adı yok."""
import re
from pathlib import Path

from conftest import KOK

KAYNAK = sorted((KOK / "src" / "vaka").glob("*.py"))
ORNEKLER = sorted((KOK / "ornek").rglob("*.*"))
MODEL_ADI = re.compile(r"(?i)\b(claude|gpt-?\d|gemini|haiku|sonnet|opus|llama|mistral|openai|anthropic)\b")
YEREL_YOL = re.compile(r"[A-Za-z]:[\\/]+Users|/home/|/Users/")


def oku(p):
    return Path(p).read_text(encoding="utf-8")


def test_kaynak_dosyalari_var():
    assert {p.name for p in KAYNAK} >= {"cli.py", "bicim.py", "kum.py", "dogrula.py", "ajan.py", "butce.py"}
    assert ORNEKLER


def test_kaynakta_yerel_yol_ve_sys_path_yok():
    for p in KAYNAK:
        metin = oku(p)
        assert not YEREL_YOL.search(metin), p.name
        assert "sys.path" not in metin, p.name


def test_kaynakta_ve_orneklerde_model_adi_yok():
    for p in KAYNAK + ORNEKLER:
        assert not MODEL_ADI.search(oku(p)), p.name
