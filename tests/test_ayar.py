"""ayar.toml: varsayılan boş, VAKA_AYAR, XDG, doğrulama."""
import pytest

from vaka.ayar import AjanAyari, ajan_ayari, ayikla, varsayilan_dosya


def test_ayar_yoksa_ajan_yok(tmp_path):
    assert ajan_ayari(env={}, ev=tmp_path) == AjanAyari()
    assert AjanAyari().komut == ""


def test_xdg_varsayilan_dosya(tmp_path):
    env = {"XDG_CONFIG_HOME": str(tmp_path), "APPDATA": str(tmp_path)}
    yol = varsayilan_dosya(tmp_path, env)
    yol.parent.mkdir(parents=True)
    yol.write_text('[ajan]\nkomut = "ajanim {girdi_dosyasi}"\n', encoding="utf-8")
    assert ajan_ayari(env=env, ev=tmp_path).komut == "ajanim {girdi_dosyasi}"


def test_vaka_ayar_yolu(tmp_path):
    p = tmp_path / "a.toml"
    p.write_text('[ajan]\nkomut = "x"\nzaman_asimi_sn = 30\nkendi_ev = true\ntahmini_kosu_usd = 0.2\n',
                 encoding="utf-8")
    a = ajan_ayari(env={"VAKA_AYAR": str(p)}, ev=tmp_path)
    assert a == AjanAyari("x", 30, True, 0.2)
    with pytest.raises(ValueError, match="boş"):
        ajan_ayari(env={"VAKA_AYAR": " "}, ev=tmp_path)
    with pytest.raises(ValueError, match="yok"):
        ajan_ayari(env={"VAKA_AYAR": str(tmp_path / "yok.toml")}, ev=tmp_path)


def test_bozuk_toml(tmp_path):
    p = tmp_path / "a.toml"
    p.write_text("[ajan\n", encoding="utf-8")
    with pytest.raises(ValueError, match="bozuk"):
        ajan_ayari(p)


@pytest.mark.parametrize("veri, mesaj", [
    ({"baska": {}}, "bilinmeyen ayar"),
    ({"ajan": {"model": "x"}}, "bilinmeyen \\[ajan\\]"),
    ({"ajan": {"komut": 1}}, "metin"),
    ({"ajan": {"zaman_asimi_sn": 0}}, "pozitif"),
    ({"ajan": {"zaman_asimi_sn": True}}, "pozitif"),
    ({"ajan": {"kendi_ev": "evet"}}, "true ya da false"),
    ({"ajan": {"tahmini_kosu_usd": -1}}, "pozitif"),
    ({"ajan": []}, "tablo"),
])
def test_gecersiz_ayar(veri, mesaj):
    with pytest.raises(ValueError, match=mesaj):
        ayikla(veri)


def test_ornek_ayar_dosyasi_gecerli():
    from conftest import KOK
    a = ajan_ayari(KOK / "ornek" / "ayar.ornek.toml")
    assert "{girdi_dosyasi}" in a.komut and a.kendi_ev is False


def test_ortam_izin(tmp_path):
    p = tmp_path / "a.toml"
    p.write_text('[ajan]\nkomut = "x"\nortam_izin = ["AJAN_API_KEY", "AJAN_API_KEY", "B"]\n', encoding="utf-8")
    assert ajan_ayari(p).ortam_izin == ("AJAN_API_KEY", "B")
    assert AjanAyari().ortam_izin == ()
    for kotu in ("AJAN_API_KEY", ["1AD"], [1]):
        with pytest.raises(ValueError, match="ortam_izin"):
            ayikla({"ajan": {"ortam_izin": kotu}})
