"""Vaka doğrulaması: referans geçer, negatif kalır, boş durum geçmez."""
import pytest
from conftest import ORNEK, mini_vaka

from vaka.bicim import vaka_yukle
from vaka.dogrula import vaka_dogrula


@pytest.mark.parametrize("vaka", vaka_yukle(ORNEK), ids=lambda v: v["id"])
def test_ornek_vaka_gecerli(vaka):
    s = vaka_dogrula(vaka)
    assert s["gecerli"], s["sorunlar"]
    for sn in s["senaryolar"]:
        assert "IHLAL" in sn["negatif"]["kontrol_cikti"] or "EKSIK" in sn["negatif"]["kontrol_cikti"]


def test_mini_vaka_gecerli():
    s = vaka_dogrula(mini_vaka())
    assert s["gecerli"], s["sorunlar"]
    assert s["senaryolar"][0]["referans"]["gecti"] is True
    assert s["senaryolar"][0]["negatif"]["gecti"] is False
    assert s["senaryolar"][0]["bos_gecti"] is False


def test_ihlali_yakalamayan_kontrol_gecersiz():
    s = vaka_dogrula(mini_vaka(kontrol={"komut": ["echo TEMIZ"], "gecer_cikti": "TEMIZ"}))
    assert not s["gecerli"]
    assert any("negatif" in p for p in s["sorunlar"])
    assert any("ücretsiz yol" in p for p in s["sorunlar"])


def test_referansi_bozuk_vaka_gecersiz():
    s = vaka_dogrula(mini_vaka(referans_cozum=["echo q > x.txt"]))
    assert not s["gecerli"]
    assert any("referans" in p for p in s["sorunlar"])


def test_cikis_kodu_ve_gecer_cikti_birlikte_gerekir():
    v = mini_vaka(kontrol={"komut": ["grep -qx y x.txt || exit 1", "echo BASKA"], "gecer_cikti": "TEMIZ"})
    s = vaka_dogrula(v)
    assert not s["gecerli"]


def test_bos_durum_gecebilir_isaretliyse_ucretsiz_yol_sorun_degil():
    k = {"komut": ["! grep -qx z x.txt || exit 1", "echo TEMIZ"], "gecer_cikti": "TEMIZ"}
    assert not vaka_dogrula(mini_vaka(kontrol=k))["gecerli"]
    assert vaka_dogrula(mini_vaka(kontrol=k, bos_durum_gecebilir=True))["gecerli"]


def test_varyant_kendi_referansi_ve_negatifiyle():
    var = {"ad": "baslangic-b", "kurulum_ek": ["printf 'b\\n' > x.txt"],
           "negatif": ["echo w > x.txt"]}
    s = vaka_dogrula(mini_vaka(varyantlar=[var]))
    assert s["gecerli"], s["sorunlar"]
    assert [sn["senaryo"] for sn in s["senaryolar"]] == ["ana", "baslangic-b"]


def test_eksik_alanli_vaka_kosmadan_gecersiz():
    v = mini_vaka()
    v.pop("negatif")
    s = vaka_dogrula(v)
    assert not s["gecerli"] and s["senaryolar"] == []
    assert "negatif" in s["sorunlar"][0]


def test_kurulumu_bozuk_vaka_gecersiz():
    s = vaka_dogrula(mini_vaka(ortam={"kurulum_betik": ["false"]}))
    assert not s["gecerli"]
    assert "kurulum" in s["sorunlar"][0]


def test_rapora_giren_kontrol_ciktisi_maskelenir(monkeypatch):
    monkeypatch.setenv("VAKA_TEST_API_KEY", "surec-api-" + "anahtari-42")
    k = {"komut": ["echo \"k=$KANARYA s=surec-api-anahtari-42 j=ghp_" + "A" * 36 + "\"",
                   "test \"$(cat x.txt)\" = y || exit 4", "echo SONUC=uygun"], "gecer_cikti": "SONUC=uygun"}
    s = vaka_dogrula(mini_vaka(kontrol=k))
    assert s["gecerli"], s["sorunlar"]
    cikti = s["senaryolar"][0]["referans"]["kontrol_cikti"]
    assert "k=[gizli] s=[gizli] j=[gizli]" in cikti
    assert "KANARYA-" not in cikti and "surec-api" not in cikti and "ghp_" not in cikti


def test_kurulum_hatasi_mesaji_maskelenir():
    s = vaka_dogrula(mini_vaka(ortam={"kurulum_betik": ["echo \"kanarya=$KANARYA\"", "false"]}))
    assert not s["gecerli"]
    assert "kanarya=[gizli]" in s["sorunlar"][0] and "KANARYA-" not in s["sorunlar"][0]


def test_vaka_betikleri_sir_adli_ve_sir_gorunumlu_degiskenleri_gormez(monkeypatch):
    monkeypatch.setenv("DENEME_API_KEY", "gizli-" + "anahtar-degeri")
    monkeypatch.setenv("db_Password", "parola-" + "degeri-123")
    monkeypatch.setenv("SIRADAN_DEGISKEN", "sk-" + "a" * 30)
    monkeypatch.setenv("NORMAL_DEGISKEN", "gorunur-deger")
    yok = 'test -z "${DENEME_API_KEY+x}${db_Password+x}${SIRADAN_DEGISKEN+x}"'
    v = mini_vaka(
        ortam={"kurulum_betik": [yok + " || exit 9", 'test "$NORMAL_DEGISKEN" = gorunur-deger || exit 8',
                                 "printf 'a\\n' > x.txt", "git add x.txt", "git commit --quiet --message=ilk"],
               "env": {"VAKA_KENDI_TOKENI": "{kanarya}"}},
        referans_cozum=[yok + " && test -n \"$VAKA_KENDI_TOKENI\" && echo y > x.txt"],
        kontrol=dict(mini_vaka()["kontrol"], komut=[yok + " || exit 6"] + mini_vaka()["kontrol"]["komut"]))
    s = vaka_dogrula(v)
    assert s["gecerli"], s["sorunlar"]
