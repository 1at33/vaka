"""Olay günlüğü: kanonik JSON, özet zinciri, nesne deposu, kurcalama tespiti, CRLF, `vaka kos --gunluk`."""
import hashlib
import json
import os
import unicodedata

import pytest
from conftest import mini_vaka

from vaka import cli
from vaka.cli import main
from vaka.gunluk import (
    BASLADI,
    BITTI,
    OLAY_DOSYASI,
    Gunluk,
    GunlukHatasi,
    gunluk_dogrula,
    indirge,
    kanonik_json,
    nesne_oku,
    olay_ozeti,
    ozet_json,
    ozet_satirlari,
)


def _saat():
    n = {"i": 0}

    def saat():
        n["i"] += 1
        return f"2026-01-01T00:00:{n['i']:02d}Z"
    return saat


def _ornek(dizin, kosu="kosu-1"):
    """Belirlenimci günlük: 1 basladi, 2 vaka, 3-4 senaryo (nesneli), 5 bitti."""
    g = Gunluk(dizin, kosu, _saat())
    g.ekle(BASLADI, {"arac": "deneme", "not": "ğüşıöç İ ✓ 😀"})
    g.ekle("vaka.yuklendi", {"id": "v1", "dosya": g.nesne(b'{"id": "v1"}\n')})
    g.ekle("kosu.senaryo", {"vaka": "v1", "kol": None, "senaryo": "ana", "deneme": 1, "gecti": True,
                            "atlandi_butce": False, "maliyet_usd": 0.1, "ajan_cikti": g.nesne("satır1\r\nsatır2")})
    g.ekle("kosu.senaryo", {"vaka": "v1", "kol": None, "senaryo": "ana", "deneme": 2, "gecti": False,
                            "atlandi_butce": False, "maliyet_usd": 0.2, "ajan_cikti": g.nesne("")})
    g.kapat({"cikis_kodu": 2})
    return g


def _satirlar(dizin):
    return (dizin / OLAY_DOSYASI).read_bytes().split(b"\n")[:-1]


def _yaz(dizin, satirlar):
    (dizin / OLAY_DOSYASI).write_bytes(b"".join(s + b"\n" for s in satirlar))


def _sorunlar(dizin, **k):
    d = gunluk_dogrula(dizin, **k)
    assert d.gecerli is False
    return "\n".join(d.sorunlar)


# --- kanonik JSON --------------------------------------------------------------------------------------------

def test_kanonik_json_sirasiz_bosluksuz_unicode_kacissiz():
    assert kanonik_json({"b": 1, "a": "ç", "c": [1, {"z": None, "y": True}]}) == \
        '{"a":"ç","b":1,"c":[1,{"y":true,"z":null}]}'.encode()
    assert kanonik_json({"x": 1, "y": 2}) == kanonik_json(dict(reversed(list({"x": 1, "y": 2}.items()))))
    assert kanonik_json(("a", 1)) == kanonik_json(["a", 1])
    b = kanonik_json({"m": "İstanbul ğ 😀 \u200b"})
    assert b"\\u" not in b and "😀".encode() in b and "İ".encode() in b
    assert ozet_json({"a": "ç"}) == "sha256:" + hashlib.sha256('{"a":"ç"}'.encode()).hexdigest()


def test_kanonik_json_normallestirmez_tur_ayirir():
    nfc, nfd = unicodedata.normalize("NFC", "şçö"), unicodedata.normalize("NFD", "şçö")
    assert nfc != nfd and ozet_json(nfc) != ozet_json(nfd)  # farklı bayt, farklı özet
    assert ozet_json(True) != ozet_json(1) and ozet_json(1) != ozet_json(1.0) and ozet_json("1") != ozet_json(1)
    assert kanonik_json(0.1 + 0.2) == b"0.30000000000000004"  # repr tabanlı, kararlı
    assert json.loads(kanonik_json({"f": 0.1 + 0.2}))["f"] == 0.1 + 0.2


@pytest.mark.parametrize("bozuk", [float("nan"), {"a": float("inf")}, {1: "a"}, {"a": b"x"}, "\ud800",
                                   {"\udc00": 1}, {"a": {1, 2}}])
def test_kanonik_json_reddeder(bozuk):
    with pytest.raises(GunlukHatasi):
        kanonik_json(bozuk)


# --- yazma ve doğrulama ---------------------------------------------------------------------------------------

def test_gecerli_gunluk_ve_belirlenimcilik(tmp_path):
    g = _ornek(tmp_path / "a")
    d = gunluk_dogrula(tmp_path / "a")
    assert d.gecerli and d.sorunlar == [] and d.tamam and d.kosu == "kosu-1" and d.satir_sonu == "LF"
    assert len(d.olaylar) == 5 and d.bas_ozet == g.bas_ozet == d.olaylar[-1]["ozet"]
    assert [o["sira"] for o in d.olaylar] == [1, 2, 3, 4, 5]
    assert d.olaylar[0]["onceki"] is None and d.olaylar[1]["onceki"] == d.olaylar[0]["ozet"]
    assert all(o["ozet"] == olay_ozeti(o) for o in d.olaylar)
    ham = (tmp_path / "a" / OLAY_DOSYASI).read_bytes()
    assert b"\r" not in ham and ham.endswith(b"\n")
    _ornek(tmp_path / "b")  # aynı olaylar, aynı saat, aynı koşu kimliği -> bayt bayt aynı günlük
    assert (tmp_path / "b" / OLAY_DOSYASI).read_bytes() == ham
    assert gunluk_dogrula(tmp_path / "a", beklenen_bas=g.bas_ozet).gecerli


def test_nesne_deposu_bayt_bayt(tmp_path):
    g = Gunluk.ac(tmp_path)
    ref = g.nesne("a\r\nb\n")
    yol = tmp_path / "nesneler" / "sha256" / ref["nesne"].removeprefix("sha256:")
    assert yol.read_bytes() == b"a\r\nb\n" and ref["boyut"] == 5
    assert g.nesne(b"a\r\nb\n") == ref  # aynı içerik tek dosya
    assert nesne_oku(tmp_path, ref) == b"a\r\nb\n"
    assert [p.name for p in yol.parent.iterdir()] == [yol.name]  # geçici dosya kalmaz
    yol.write_bytes(b"baska")
    with pytest.raises(GunlukHatasi, match="farklı içerik"):
        g.nesne(b"a\r\nb\n")
    with pytest.raises(GunlukHatasi, match="geçersiz nesne"):
        nesne_oku(tmp_path, {"nesne": "sha256:../../etc/passwd", "boyut": 1})


@pytest.mark.skipif(os.name == "nt", reason="POSIX izinleri")
def test_gunluk_dosyalari_yalniz_sahibine_acik(tmp_path):
    g = _ornek(tmp_path)
    assert ((tmp_path / OLAY_DOSYASI).stat().st_mode & 0o777) == 0o600
    ref = g.olaylar[2]["veri"]["ajan_cikti"]["nesne"].removeprefix("sha256:")
    assert ((tmp_path / "nesneler" / "sha256" / ref).stat().st_mode & 0o777) == 0o600


def test_yazici_kurallari(tmp_path):
    g = Gunluk.ac(tmp_path, {"a": 1})
    with pytest.raises(GunlukHatasi, match="zaten var"):
        Gunluk.ac(tmp_path)
    with pytest.raises(GunlukHatasi):
        g.ekle(BASLADI, {})
    for tur, veri in (("", {}), ("x", []), ("x", {"f": float("nan")})):
        with pytest.raises(GunlukHatasi):
            g.ekle(tur, veri)
    assert len(_satirlar(tmp_path)) == 1  # reddedilen olay dosyaya yazılmaz
    veri = {"liste": [1]}
    g.ekle("x", veri)
    veri["liste"].append(2)  # sonradan değişen sözlük kaydı etkilemez
    g.kapat()
    assert g.kapali and gunluk_dogrula(tmp_path).gecerli
    with pytest.raises(GunlukHatasi, match="kapanmış"):
        g.ekle("x", {})
    with pytest.raises(GunlukHatasi):
        Gunluk(tmp_path / "yeni", "k").ekle("x", {})  # ilk olay basladi olmalı


# --- kurcalama ------------------------------------------------------------------------------------------------

def test_degistirilmis_olay(tmp_path):
    _ornek(tmp_path)
    s = _satirlar(tmp_path)
    olay = json.loads(s[2])
    olay["veri"]["gecti"] = False  # özeti bırakıp içeriği değiştir
    s[2] = kanonik_json(olay)
    _yaz(tmp_path, s)
    assert "satır 3: olay özeti tutmuyor" in _sorunlar(tmp_path)


def test_ozeti_yeniden_hesaplanmis_olay_zinciri_koparir(tmp_path):
    _ornek(tmp_path)
    s = _satirlar(tmp_path)
    olay = json.loads(s[2])
    olay["veri"]["gecti"] = False
    olay["ozet"] = olay_ozeti(olay)
    s[2] = kanonik_json(olay)
    _yaz(tmp_path, s)
    sorun = _sorunlar(tmp_path)
    assert "satır 4: zincir kopuk" in sorun and "satır 3" not in sorun


def test_yeniden_siralama_ve_silme(tmp_path):
    _ornek(tmp_path)
    s = _satirlar(tmp_path)
    _yaz(tmp_path, [s[0], s[2], s[1], s[3], s[4]])
    sorun = _sorunlar(tmp_path)
    assert "satır 2: sıra bozuk" in sorun and "zincir kopuk" in sorun
    _yaz(tmp_path, [s[0], s[1], s[3], s[4]])
    sorun = _sorunlar(tmp_path)
    assert "satır 3: sıra bozuk: 2'den sonra 4" in sorun and sorun.count("sıra bozuk") == 1
    _yaz(tmp_path, s[:4])  # sondaki kosu.bitti silindi
    assert "kosu.bitti yok" in _sorunlar(tmp_path)
    yarim = gunluk_dogrula(tmp_path, tamam_sart=False)
    assert yarim.gecerli and not yarim.tamam


def test_yarim_son_satir_ve_bos_satir(tmp_path):
    _ornek(tmp_path)
    ham = (tmp_path / OLAY_DOSYASI).read_bytes()
    (tmp_path / OLAY_DOSYASI).write_bytes(ham[:-20])
    assert "son satır yarım" in _sorunlar(tmp_path)
    (tmp_path / OLAY_DOSYASI).write_bytes(ham + b"\n")
    assert "boş satır" in _sorunlar(tmp_path)
    (tmp_path / OLAY_DOSYASI).write_bytes(b"")
    assert "günlük boş" in _sorunlar(tmp_path)
    assert "okunamadı" in _sorunlar(tmp_path / "yok")


def test_kanonik_olmayan_ve_yinelenen_anahtar(tmp_path):
    _ornek(tmp_path)
    s = _satirlar(tmp_path)
    _yaz(tmp_path, s[:1] + [json.dumps(json.loads(s[1]), indent=1).replace("\n", " ").encode()] + s[2:])
    assert "satır 2: kanonik JSON değil" in _sorunlar(tmp_path)
    ikiz = s[1][:-1] + b',"tur":"vaka.yuklendi"}'  # aynı anahtar iki kez: json.loads sonuncuyu alır
    _yaz(tmp_path, s[:1] + [ikiz] + s[2:])
    assert "satır 2: kanonik JSON değil" in _sorunlar(tmp_path)
    _yaz(tmp_path, s[:1] + [b'{"sira": 2}'] + s[2:])
    assert "satır 2: olay alanları" in _sorunlar(tmp_path)
    _yaz(tmp_path, s[:1] + [b"\xff\xfe"] + s[2:])
    assert "satır 2: JSON okunamadı" in _sorunlar(tmp_path)


def test_baska_kosudan_olay(tmp_path):
    _ornek(tmp_path / "a", "kosu-a")
    _ornek(tmp_path / "b", "kosu-b")
    s = _satirlar(tmp_path / "a")
    s[1] = _satirlar(tmp_path / "b")[1]
    _yaz(tmp_path / "a", s)
    assert "başka bir koşunun olayı (kosu-b)" in _sorunlar(tmp_path / "a")


def test_eksik_ve_degismis_nesne(tmp_path):
    g = _ornek(tmp_path)
    ref = g.olaylar[2]["veri"]["ajan_cikti"]["nesne"]
    yol = tmp_path / "nesneler" / "sha256" / ref.removeprefix("sha256:")
    yol.write_bytes(b"satir1\nsatir2")
    assert f"satır 3: nesne değişmiş: {ref}" in _sorunlar(tmp_path)
    yol.unlink()
    assert f"satır 3: nesne yok: {ref}" in _sorunlar(tmp_path)


def test_bas_ozeti_ve_oynatma(tmp_path):
    _ornek(tmp_path)
    assert "baş özeti beklenenden farklı" in _sorunlar(tmp_path, beklenen_bas="sha256:" + "0" * 64)
    s = _satirlar(tmp_path)
    son = json.loads(s[-1])
    son["veri"]["durum_ozeti"] = "sha256:" + "1" * 64
    son["ozet"] = olay_ozeti(son)
    _yaz(tmp_path, s[:-1] + [kanonik_json(son)])
    assert "oynatma tutmuyor" in _sorunlar(tmp_path)


def test_bitti_sonrasi_olay(tmp_path):
    g = _ornek(tmp_path)
    fazla = {"surum": "vaka-gunluk/1", "kosu": "kosu-1", "sira": 6, "tur": "x", "zaman": "z", "veri": {},
             "onceki": g.bas_ozet}
    fazla["ozet"] = olay_ozeti(fazla)
    _yaz(tmp_path, _satirlar(tmp_path) + [kanonik_json(fazla)])
    assert "kosu.bitti sonrasında olay" in _sorunlar(tmp_path)


def test_crlf_cevrilmis_gunluk_gecerli(tmp_path):
    g = _ornek(tmp_path)
    ham = (tmp_path / OLAY_DOSYASI).read_bytes()
    (tmp_path / OLAY_DOSYASI).write_bytes(ham.replace(b"\n", b"\r\n"))
    d = gunluk_dogrula(tmp_path)
    assert d.gecerli and d.satir_sonu == "CRLF" and d.bas_ozet == g.bas_ozet
    s = ham.split(b"\n")
    (tmp_path / OLAY_DOSYASI).write_bytes(b"\r\n".join(s[:2]) + b"\n" + b"\n".join(s[2:]))
    d = gunluk_dogrula(tmp_path)
    assert d.gecerli and d.satir_sonu == "KARISIK"


def test_indirge_ve_ozet(tmp_path):
    g = _ornek(tmp_path)
    d = indirge(g.olaylar)
    assert d["olay"] == 4 and d["turler"]["kosu.senaryo"] == 2 and list(d["vakalar"]) == ["v1"]
    assert ozet_satirlari(g.olaylar) == [["v1", "-", "1/2", 0, "0.3000"]]
    assert g.olaylar[-1]["tur"] == BITTI and g.olaylar[-1]["veri"]["durum_ozeti"] == ozet_json(d)


# --- vaka kos --gunluk ve dogrula-gunluk ---------------------------------------------------------------------

def _vaka_dizini(tmp_path, **ek):
    d = tmp_path / "vakalar"
    d.mkdir(exist_ok=True)
    v = mini_vaka(**ek)
    v.pop("_dosya")
    (d / f"{v['id']}.json").write_text(json.dumps(v, ensure_ascii=False), encoding="utf-8")
    return d


def test_kos_gunluk_yazar_dogrula_gunluk_okur(tmp_path, capsys):
    d = _vaka_dizini(tmp_path, varyantlar=[{"ad": "b", "kurulum_ek": ["printf 'b\\n' > x.txt"]}])
    g, j, m = tmp_path / "kayit", tmp_path / "k.json", tmp_path / "k.md"
    argv = ["kos", "--vakalar", str(d), "--ajan", 'echo y > x.txt; echo "{\\"maliyet_usd\\": 0.01}"',
            "--butce-usd", "0.015", "--tahmini-kosu-usd", "0.01", "--gunluk", str(g), "--json", str(j), "--md", str(m)]
    assert main(argv) == 3  # ana koşu sığar, varyant koşusu bütçeden atlanır
    veri = json.loads(j.read_text(encoding="utf-8"))
    bas = veri["gunluk"]["bas_ozet"]
    assert veri["gunluk"]["dizin"] == str(g) and bas in capsys.readouterr().out and bas in m.read_text("utf-8")
    dog = gunluk_dogrula(g, beklenen_bas=bas)
    assert dog.gecerli, dog.sorunlar
    turler = [o["tur"] for o in dog.olaylar]
    assert turler == ["kosu.basladi", "vaka.yuklendi", "kosu.senaryo", "kosu.senaryo", "kosu.bitti"]
    basladi, vaka, s1, s2, bitti = (o["veri"] for o in dog.olaylar)
    assert basladi["komut_ozeti"].startswith("sha256:") and "echo" not in json.dumps(basladi)
    assert nesne_oku(g, vaka["dosya"]) == (d / "mini-01.json").read_bytes()
    assert s1["gecti"] is True and s1["maliyet_usd"] == 0.01 and nesne_oku(g, s1["kontrol_cikti"])
    assert s2["atlandi_butce"] is True and s2["senaryo"] == "b"
    assert bitti["cikis_kodu"] == 3 and bitti["sinir_usd"] == 0.015
    capsys.readouterr()
    jg = tmp_path / "g.json"
    assert main(["dogrula-gunluk", str(g), "--beklenen-bas", bas, "--olaylar", "--json", str(jg)]) == 0
    cikti = capsys.readouterr().out
    assert "GEÇERLİ: 5 olay" in cikti and "mini-01" in cikti and "kosu.senaryo" in cikti
    gv = json.loads(jg.read_text(encoding="utf-8"))
    assert gv["mod"] == "gunluk" and gv["sonuc"]["gecerli"] and gv["sonuc"]["ozet"][0][:4] == ["mini-01", "-", "1/1", 1]
    assert main(["dogrula-gunluk", str(g), "--beklenen-bas", "sha256:" + "0" * 64]) == 1
    # kurcala: ajan çıktısı nesnesini sil
    (g / "nesneler" / "sha256" / s1["ajan_cikti"]["nesne"].removeprefix("sha256:")).unlink()
    capsys.readouterr()
    assert main(["dogrula-gunluk", str(g), "--json", str(jg)]) == 1
    hata = capsys.readouterr()
    assert "GEÇERSİZ" in hata.out and "nesne yok" in hata.err
    assert json.loads(jg.read_text(encoding="utf-8"))["sonuc"]["ozet"] is None


def test_kos_var_olan_gunluge_yazmaz_ajan_kosmaz(tmp_path, capsys):
    d = _vaka_dizini(tmp_path)
    g = tmp_path / "kayit"
    _ornek(g)
    isaret = tmp_path / "kostu"
    assert main(["kos", "--vakalar", str(d), "--ajan", f"touch {isaret}", "--butce-usd", "1", "--gunluk", str(g)]) == 1
    assert "günlük açılamadı" in capsys.readouterr().err and not isaret.exists()


def test_kos_gunluksuz_json_degismez(tmp_path):
    d = _vaka_dizini(tmp_path)
    j = tmp_path / "k.json"
    assert main(["kos", "--vakalar", str(d), "--ajan", "echo y > x.txt", "--butce-usd", "1", "--json", str(j)]) == 0
    assert set(json.loads(j.read_text(encoding="utf-8"))) == {"mod", "sonuc", "butce"}


def test_kesilen_kos_gunlugu_kapatir(tmp_path, monkeypatch):
    d = _vaka_dizini(tmp_path)
    g = tmp_path / "kayit"

    def patlar(*a, **k):
        raise RuntimeError("kesildi")

    monkeypatch.setattr(cli, "ajan_kos", patlar)
    with pytest.raises(RuntimeError):
        main(["kos", "--vakalar", str(d), "--ajan", "true", "--butce-usd", "1", "--gunluk", str(g)])
    dog = gunluk_dogrula(g)
    assert dog.gecerli and dog.olaylar[-1]["veri"]["kesildi"] == "RuntimeError"


def test_dogrula_gunluk_yarim_kabul(tmp_path, capsys):
    g = Gunluk.ac(tmp_path / "kayit", {"a": 1})
    g.ekle("x", {})
    assert main(["dogrula-gunluk", str(tmp_path / "kayit")]) == 1
    assert "kosu.bitti yok" in capsys.readouterr().err
    assert main(["dogrula-gunluk", str(tmp_path / "kayit"), "--yarim-kabul"]) == 0
    assert "YARIM" in capsys.readouterr().out
    assert main(["dogrula-gunluk", str(tmp_path / "yok")]) == 1
