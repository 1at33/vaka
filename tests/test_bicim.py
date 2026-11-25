"""Vaka biçimi: örnek vakalar, alan denetimi, ipucu ve bağlam sızıntısı."""
import json
import re
from pathlib import Path

import pytest
from conftest import ORNEK, mini_vaka

from vaka.bicim import baglam_metni, bicim_hatalari, eksik_alanlar, iskelet, vaka_oku, vaka_yukle
from vaka.yardimci import SIR_KALIPLARI

ORNEKLER = vaka_yukle(ORNEK)


def test_ornek_paketler():
    suitler = [v["suite"] for v in ORNEKLER]
    assert suitler.count("yetenek") == 5
    assert suitler.count("regresyon") == 2
    assert len({v["hata_sinifi"] for v in ORNEKLER}) == 5
    assert all(v.get("ornek") is True for v in ORNEKLER)


@pytest.mark.parametrize("vaka", ORNEKLER, ids=lambda v: v["id"])
def test_ornek_vaka_bicimi_temiz(vaka):
    assert eksik_alanlar(vaka) == []
    assert bicim_hatalari(vaka) == []
    if vaka["suite"] == "yetenek":
        assert baglam_metni(vaka), "yetenek örneği bağlam kolu taşımalı"
        assert vaka["ipucu_yasak"], "yetenek örneği görev metninin kuralı söylemediğini denetlemeli"
    else:
        assert "baglam" not in vaka


@pytest.mark.parametrize("vaka", ORNEKLER, ids=lambda v: v["id"])
def test_ornek_vakada_gercek_sir_ve_yerel_yol_yok(vaka):
    ham = Path(vaka["_dosya"]).read_text(encoding="utf-8")
    assert not any(k.search(ham) for k in SIR_KALIPLARI)
    assert not re.search(r"[A-Za-z]:[\\/]+Users|/home/|/Users/", ham)
    assert not re.search(r"@(?!example\.invalid)[a-z0-9-]+\.[a-z]{2,}", ham)


def test_suite_klasorden_gelir(tmp_path):
    (tmp_path / "regresyon").mkdir()
    v = mini_vaka()
    v.pop("suite")
    v.pop("_dosya")
    (tmp_path / "a.json").write_text(json.dumps(v), encoding="utf-8")
    (tmp_path / "regresyon" / "b.json").write_text(json.dumps(dict(v, id="mini-02")), encoding="utf-8")
    assert [x["suite"] for x in vaka_yukle(tmp_path)] == ["yetenek", "regresyon"]
    assert [x["id"] for x in vaka_yukle(tmp_path, suite="regresyon")] == ["mini-02"]
    assert [x["id"] for x in vaka_yukle(tmp_path, secim={"mini-01"})] == ["mini-01"]


def test_bozuk_json_anlasilir_hata(tmp_path):
    p = tmp_path / "bozuk.json"
    p.write_text("{", encoding="utf-8")
    with pytest.raises(ValueError, match="okunamadı"):
        vaka_oku(p)
    p.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="nesne"):
        vaka_oku(p)


def test_iskelet_dolana_kadar_eksik():
    e = eksik_alanlar(dict(iskelet("yeni-vaka"), _dosya="x.json"))
    for alan in ("kaynak_not", "hata_sinifi", "girdi", "referans_cozum", "negatif", "kontrol.komut"):
        assert alan in e


def test_bilinmeyen_alan_ve_gecersiz_id():
    h = bicim_hatalari(mini_vaka(id="Buyuk Harf", fazladan=1))
    assert any("bilinmeyen alan: fazladan" in x for x in h)
    assert any("id" in x for x in h)
    h = bicim_hatalari(mini_vaka(ortam={"kurulum_betik": [], "bilinmez": 1, "env": {"1AD": "x"}}))
    assert any("bilinmeyen ortam alanı" in x for x in h)
    assert any("ortam.env adı" in x for x in h)
    assert bicim_hatalari(mini_vaka(suite="baska"))


def test_gorev_metni_kurali_ele_verirse_hata():
    v = mini_vaka(ipucu_yasak=["z yazma"], girdi="x.txt içeriğini y yap, z yazma.")
    assert any("ele veriyor" in x for x in bicim_hatalari(v))
    v = mini_vaka(ipucu_yasak=["z yazma"], varyantlar=[{"ad": "v", "girdi": "Z YAZMA"}])
    assert any("ele veriyor" in x for x in bicim_hatalari(v))


def test_baglam_metin_ve_dosyalar(tmp_path):
    (tmp_path / "not.md").write_text("- dosyadaki kural\n", encoding="utf-8")
    v = mini_vaka(baglam={"metin": ["- satır kuralı"], "dosyalar": ["not.md"]}, _dosya=str(tmp_path / "v.json"))
    m = baglam_metni(v)
    assert "- satır kuralı" in m and "- dosyadaki kural" in m
    assert bicim_hatalari(v) == []
    assert baglam_metni(mini_vaka()) is None
    assert baglam_metni(mini_vaka(baglam={"metin": ""})) is None


def test_baglamda_vaka_izi_ve_eksik_dosya_hata(tmp_path):
    assert any("vaka izi" in x for x in bicim_hatalari(mini_vaka(baglam={"metin": "mini-01 için kural"})))
    assert any("vaka izi" in x for x in bicim_hatalari(mini_vaka(baglam={"metin": "çıktı SONUC=uygun olmalı"})))
    v = mini_vaka(baglam={"dosyalar": ["yok.md"]}, _dosya=str(tmp_path / "v.json"))
    assert any("okunamadı" in x for x in bicim_hatalari(v))
    assert any("baglam yalnız" in x for x in bicim_hatalari(mini_vaka(baglam={"baska": 1})))


@pytest.mark.parametrize("yol", ["/etc/passwd", "~/.ssh/id_rsa", "~", "../disari.md", "alt/../../disari.md",
                                 "C:/Windows/win.ini", "C:not.md", "\\\\sunucu\\pay\\a.md", "\\kok.md"])
def test_baglam_dosyasi_vaka_klasoru_disina_cikamaz(tmp_path, yol):
    (tmp_path / "vakalar").mkdir()
    (tmp_path / "disari.md").write_text("- dışarıdaki kural\n", encoding="utf-8")
    v = mini_vaka(baglam={"dosyalar": [yol]}, _dosya=str(tmp_path / "vakalar" / "v.json"))
    with pytest.raises(ValueError, match="baglam.dosyalar"):
        baglam_metni(v)
    h = bicim_hatalari(v)
    assert any("baglam.dosyalar" in x for x in h), h


def test_baglam_dosyasi_klasor_icinde_kalan_goreli_yol_gecer(tmp_path):
    (tmp_path / "notlar").mkdir()
    (tmp_path / "notlar" / "a.md").write_text("- alt klasördeki kural\n", encoding="utf-8")
    v = mini_vaka(baglam={"dosyalar": ["notlar/../notlar/a.md"]}, _dosya=str(tmp_path / "v.json"))
    assert "alt klasördeki kural" in baglam_metni(v)
    assert bicim_hatalari(v) == []


def test_baglam_dosyasi_sembolik_bagla_disari_cikamaz(tmp_path):
    (tmp_path / "vakalar").mkdir()
    disari = tmp_path / "gizli.md"
    disari.write_text("- gizli\n", encoding="utf-8")
    bag = tmp_path / "vakalar" / "bag.md"
    try:
        bag.symlink_to(disari)
    except OSError:
        pytest.skip("sembolik bağ kurulamıyor")
    v = mini_vaka(baglam={"dosyalar": ["bag.md"]}, _dosya=str(tmp_path / "vakalar" / "v.json"))
    assert any("dışına çıkıyor" in x for x in bicim_hatalari(v))


def test_baglam_dosyalar_liste_ve_metin_olmali(tmp_path):
    v = mini_vaka(baglam={"dosyalar": "not.md"}, _dosya=str(tmp_path / "v.json"))
    assert any("liste" in x for x in bicim_hatalari(v))
    v = mini_vaka(baglam={"dosyalar": [1]}, _dosya=str(tmp_path / "v.json"))
    assert any("boş olmayan bir yol" in x for x in bicim_hatalari(v))
