"""Bütçe defteri: toplam, uçuştaki rezerv, bildirilmeyen maliyet, paralel süreçler."""
import os
import subprocess
import sys
import textwrap

import pytest
from conftest import SRC

from vaka.butce import Butce


def test_toplar_ve_sinirda_durur(tmp_path):
    b = Butce(0.03, tmp_path / "d.txt", tahmini_kosu_usd=0.01)
    for _ in range(3):
        k = b.baslat()
        assert k
        b.bitir(k, 0.01)
    assert b.harcanan() == pytest.approx(0.03)
    assert b.baslat() is None


def test_ucustaki_kosu_rezerv_alir(tmp_path):
    b = Butce(0.015, tmp_path / "d.txt", tahmini_kosu_usd=0.01)
    k1 = b.baslat()
    assert k1 and b.ucustaki() == 1
    assert b.baslat() is None  # 0.01 rezerv + 0.01 tahmin > 0.015
    b.bitir(k1, 0.001)
    assert b.ucustaki() == 0
    assert b.baslat()  # artık tahmin gözlenen ortalama (0.001): 0.001 + 0.001 <= 0.015


def test_tahmin_gozlenen_ortalama(tmp_path):
    b = Butce(1, tmp_path / "d.txt", tahmini_kosu_usd=0.5)
    assert b.tahmin() == 0.5
    k = b.baslat()
    b.bitir(k, 0.02)
    assert b.tahmin() == pytest.approx(0.02)


def test_bildirilmeyen_maliyet_tahminle_sayilir_iptal_sayilmaz(tmp_path):
    b = Butce(0.025, tmp_path / "d.txt", tahmini_kosu_usd=0.01)
    k = b.baslat()
    b.bitir(k, None)
    assert b.harcanan() == pytest.approx(0.01)
    assert b.tahmin() == 0.01  # tahminle sayılan ortalamaya girmez
    k = b.baslat()
    b.iptal(k)
    assert b.harcanan() == pytest.approx(0.01) and b.ucustaki() == 0
    b.bitir(b.baslat(), None)
    assert b.baslat() is None


def test_negatif_sinir_reddedilir(tmp_path):
    with pytest.raises(ValueError):
        Butce(-1, tmp_path / "d.txt")


def test_paralel_surecler_siniri_asmaz(tmp_path):
    defter = tmp_path / "ortak.txt"
    kod = textwrap.dedent(f"""
        from vaka.butce import Butce
        b = Butce(0.1, {str(defter)!r}, tahmini_kosu_usd=0.01)
        n = 0
        while True:
            k = b.baslat()
            if k is None:
                break
            b.bitir(k, 0.01)
            n += 1
        print(n)
    """)
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(filter(None, [SRC, os.environ.get("PYTHONPATH")])))
    ps = [subprocess.Popen([sys.executable, "-c", kod], stdout=subprocess.PIPE, text=True, env=env) for _ in range(4)]
    toplam = sum(int(p.communicate()[0].strip()) for p in ps)
    assert toplam == 10
    assert Butce(0.1, defter).harcanan() == pytest.approx(0.1)
