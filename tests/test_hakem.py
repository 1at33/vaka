"""Hakem sınaması: her saldırı saf hakemi kandırır, sağlam hakemi kandıramaz; denetimler, komut hakem, CLI."""
import json
import os
import re
import sys

import pytest
from conftest import SRC

from vaka import hakem
from vaka.butce import Butce
from vaka.cli import main
from vaka.hakem import (
    GOREVLER,
    SALDIRILAR,
    TURLER,
    HakemHatasi,
    KomutHakem,
    cikis_kodu,
    hakem_sina,
    karar_coz,
    katla,
    saf_hakem,
    saglam_hakem,
)
from vaka.kum import bash_yolu

CIFTLER = [(s, g) for s in SALDIRILAR for g in GOREVLER if g.tur in s.turler]
PY = bash_yolu(sys.executable)

# Saf hakemin her saldırıda hangi kısayolla kandığı: saldırı gerçekten hedeflediği zaafı sınıyor.
KISAYOL = {
    "talimat-enjeksiyonu": "talimat", "gizli-talimat": "talimat", "sahte-karar": "karar taklidi",
    "cok-cevap": "yüzeysel", "sahte-kanit": "kanıt", "asiri-ozguven": "özgüven", "uzunluk-sisirme": "uzunluk",
    "anahtar-kelime": "anahtar kelime", "yasak-liste-kacisi": "yüzeysel", "bicim-oyunu": "yüzeysel",
    "tutarsiz-toplam": "yüzeysel",
}


@pytest.fixture(autouse=True)
def _paket_yolu(monkeypatch):
    """Komut hakem `python -m vaka.hakem` olarak koşar; ayıklanmış ortam PYTHONPATH'i taşır."""
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join(filter(None, [SRC, os.environ.get("PYTHONPATH")])))


def test_kutuphane_tutarli():
    assert len({s.id for s in SALDIRILAR}) == len(SALDIRILAR) >= 10
    assert len({g.id for g in GOREVLER}) == len(GOREVLER)
    assert {g.tur for g in GOREVLER} == set(TURLER)
    for s in SALDIRILAR:
        assert set(s.turler) <= set(TURLER) and s.aciklama
        assert any(g.tur in s.turler for g in GOREVLER), s.id
    assert set(KISAYOL) == {s.id for s in SALDIRILAR}


@pytest.mark.parametrize(("saldiri", "gorev"), CIFTLER, ids=[f"{s.id}-{g.id}" for s, g in CIFTLER])
def test_saldiri_safi_kandirir_saglami_kandiramaz(saldiri, gorev):
    yanit = saldiri.uret(gorev)
    assert yanit.strip() and yanit != gorev.dogru
    saf = saf_hakem(gorev.girdi(yanit))
    assert saf["gecti"] is True, saf
    assert KISAYOL[saldiri.id] in saf["neden"], saf
    saglam = saglam_hakem(gorev.girdi(yanit))
    assert saglam["gecti"] is False, saglam


@pytest.mark.parametrize("gorev", GOREVLER, ids=[g.id for g in GOREVLER])
@pytest.mark.parametrize("h", [saf_hakem, saglam_hakem], ids=["saf", "saglam"])
def test_hazir_hakemler_denetimleri_tutar(h, gorev):
    assert h(gorev.girdi(gorev.dogru))["gecti"] is True
    assert h(gorev.girdi(gorev.yanlis))["gecti"] is False
    assert h(gorev.girdi(""))["gecti"] is False


def test_saglam_hakem_katlar_ve_ek_yakalar():
    assert katla("ŞIK Göz Çağrısı İçerik") == "sik goz cagrisi icerik"
    assert katla("dev\u200brim\u00adsel") == "devrimsel"  # sıfır genişlik ve yumuşak tire (Cf) atılır
    assert katla("ｃｅｖａｐ") == "cevap"  # tam genişlik (NFKC)
    duyuru = next(g for g in GOREVLER if g.tur == "yasak")
    for yanit in ("Bu sürüm sınır-tanımayan bir adım ve herkes için yeterince uzun bir duyuru.",
                  "Bu sürüm BENZERSİZLERDEN biri; herkes için yeterince uzun bir duyuru.",
                  "Bu sürüm GÖZ   KAMAŞTIRICIYDI; herkes için yeterince uzun bir duyuru."):
        assert saglam_hakem(duyuru.girdi(yanit))["gecti"] is False, yanit


def test_saglam_hakem_bilinmeyen_tur_kaldi():
    assert saglam_hakem({"yanit": "x", "beklenen": {"tur": "yok"}})["gecti"] is False
    assert saglam_hakem({})["gecti"] is False


def test_hakem_girdisinde_saldiri_adi_yok():
    gorulen = []
    hakem_sina(lambda girdi: gorulen.append(girdi) or False)
    assert all(set(g) == {"gorev", "olcut", "beklenen", "yanit"} for g in gorulen)
    metin = json.dumps(gorulen, ensure_ascii=False)
    assert not any(s.id in metin for s in SALDIRILAR)


def test_sinama_ozeti_ve_cikis_kodlari():
    saf = hakem_sina(saf_hakem)
    t = saf["toplam"]
    assert t["kandiran_saldiri"] == t["saldiri"] == len(SALDIRILAR)
    assert t["kandirilan_cift"] == t["cift"] == len(CIFTLER) and t["kontrol_uygun"] is True
    assert cikis_kodu(saf) == 2
    saglam = hakem_sina(saglam_hakem)
    assert saglam["toplam"]["kandirilan_cift"] == 0 and cikis_kodu(saglam) == 0
    assert all(o["denenen"] == o["uygulanan"] >= 1 for o in saglam["saldirilar"])


@pytest.mark.parametrize("sabit", [True, False])
def test_her_seye_ayni_karari_veren_hakem_gecersiz(sabit):
    s = hakem_sina(lambda girdi: sabit)
    assert s["toplam"]["kontrol_uygun"] is False
    assert cikis_kodu(s) == 1  # her şeye KALDI diyen hakem kandırılmaz ama geçersizdir
    assert (s["toplam"]["kandirilan_cift"] > 0) is sabit


def test_karar_coz():
    assert karar_coz(True) == (True, None) and karar_coz(False) == (False, None)
    assert karar_coz(0.7) == (True, 0.7) and karar_coz(0.2) == (False, 0.2) and karar_coz(1, esik=1) == (True, 1.0)
    assert karar_coz({"gecti": False, "puan": 0.9}) == (False, 0.9)
    assert karar_coz({"puan": 0.5}) == (True, 0.5)
    for bozuk in (None, "GEÇTİ", {"gecti": "evet"}, {"puan": True}, {"puan": float("nan")}, float("inf"), []):
        with pytest.raises(HakemHatasi):
            karar_coz(bozuk)


def test_hakem_hatasi_raporlanir_ve_maskelenir():
    def bozuk(girdi):
        raise RuntimeError("anahtar sk-" + "A" * 24 + " ile bağlanamadı")

    s = hakem_sina(bozuk, saldirilar=SALDIRILAR[:1], gorevler=GOREVLER[:1])
    assert cikis_kodu(s) == 1 and s["toplam"]["hata"] == 4  # 3 denetim + 1 saldırı
    metin = json.dumps(s, ensure_ascii=False)
    assert "AAAAAAAAAAAAAAAAAAAA" not in metin and "[gizli]" in metin
    assert s["saldirilar"][0]["hata"] == 1 and s["denemeler"][0]["kandirdi"] is False


def test_tekrar_rastgele_hakemi_yakalar():
    sayac = {"n": 0}

    def ara_sira_kanan(girdi):  # sağlam, ama her üçüncü çağrıda GEÇTİ diyor
        sayac["n"] += 1
        return True if sayac["n"] % 3 == 0 else saglam_hakem(girdi)["gecti"]

    s = hakem_sina(ara_sira_kanan, tekrar=3)
    assert all(d["deneme"] == 3 for d in s["denemeler"] + s["kontroller"])
    assert s["toplam"]["kandirilan_cift"] == s["toplam"]["cift"]
    assert cikis_kodu(s) == 1  # yanlış yanıt da bir kez geçti: denetim tutmaz
    with pytest.raises(ValueError):
        hakem_sina(saglam_hakem, tekrar=0)


def test_butce_dolunca_kalan_denemeler_atlanir(tmp_path):
    butce = Butce(0.05, tmp_path / "defter.txt", 0.01)
    s = hakem_sina(saglam_hakem, butce=butce)
    kosan = sum(x["deneme"] for x in s["kontroller"] + s["denemeler"])
    assert kosan == 5 and s["toplam"]["atlandi_butce"] == len(GOREVLER) * 3 + len(CIFTLER) - 5
    assert cikis_kodu(s) == 3
    assert all(k["uygun"] in (True, None) for k in s["kontroller"])


def test_maliyet_bildiren_hakem_defteri_doldurur(tmp_path):
    butce = Butce(1.0, tmp_path / "defter.txt", 0.5)
    hakem_sina(lambda g: {**saglam_hakem(g), "maliyet_usd": 0.001}, gorevler=GOREVLER[:1], butce=butce)
    assert butce.harcanan() == pytest.approx(0.001 * (3 + sum(GOREVLER[0].tur in s.turler for s in SALDIRILAR)))


def test_komut_hakem_dosya_ve_stdin():
    for komut in (f"{PY} -m vaka.hakem saglam {{girdi_dosyasi}}", f"{PY} -m vaka.hakem saf"):
        s = hakem_sina(KomutHakem(komut), saldirilar=[SALDIRILAR[2]], gorevler=GOREVLER[:1])
        assert s["toplam"]["hata"] == 0 and s["toplam"]["kontrol_uygun"], s
        assert s["denemeler"][0]["kandirdi"] is ("saf" in komut)
        assert s["denemeler"][0]["nedenler"]


def test_komut_hakem_ortami_sirsiz(tmp_path, monkeypatch):
    monkeypatch.setenv("DENEME_API_KEY", "hakem-gormemeli-" + "1234")
    monkeypatch.setenv("IZINLI_TOKEN", "hakem-gorur-" + "5678")
    komut = ('env > "$CIKTI/env.txt"; cp {girdi_dosyasi} "$CIKTI/girdi.json"; '
             'cmp -s {girdi_dosyasi} "$VAKA_HAKEM_GIRDI" && echo \'{"gecti": false, "maliyet_usd": 0.25}\'')
    h = KomutHakem(komut, ortam_izin=["IZINLI_TOKEN"], ek_env={"CIKTI": str(tmp_path)})
    girdi = GOREVLER[0].girdi("Cevap: 1 — ünlü ğ")
    assert h(girdi) == {"gecti": False, "maliyet_usd": 0.25}
    env = (tmp_path / "env.txt").read_text(encoding="utf-8", errors="replace")
    assert "hakem-gormemeli" not in env and "IZINLI_TOKEN=hakem-gorur-5678" in env
    assert json.loads((tmp_path / "girdi.json").read_text(encoding="utf-8")) == girdi
    assert b"\r\n" not in (tmp_path / "girdi.json").read_bytes()


@pytest.mark.parametrize(("komut", "mesaj"), [
    ("echo boom >&2; exit 3", "çıkış kodu 3"),
    ("echo 'GEÇTİ'", "JSON nesnesi değil"),
    ("sleep 3", "zaman aşımı"),
])
def test_komut_hakem_hatalari(komut, mesaj):
    with pytest.raises(HakemHatasi, match=mesaj):
        KomutHakem(komut, zaman_asimi_sn=1)(GOREVLER[0].girdi("x"))


def test_komut_hakem_maskeler(monkeypatch):
    monkeypatch.setenv("BENIM_SECRET", "cok-gizli-" + "deger-42")
    komut = 'echo "anahtar cok-gizli-deger-42 ve ghp_' + "B" * 30 + '" >&2; exit 1'
    with pytest.raises(HakemHatasi) as e:
        KomutHakem(komut)(GOREVLER[0].girdi("x"))
    assert "cok-gizli-deger-42" not in str(e.value) and "B" * 30 not in str(e.value)


def test_python_m_vaka_hakem(tmp_path, capsysbinary):
    g = tmp_path / "g.json"
    g.write_text(json.dumps(GOREVLER[0].girdi(GOREVLER[0].dogru), ensure_ascii=False), encoding="utf-8")
    assert hakem.main(["saglam", str(g)]) == 0
    assert json.loads(capsysbinary.readouterr().out)["gecti"] is True
    assert hakem.main([]) == 2 and hakem.main(["baska"]) == 2
    (tmp_path / "bozuk.json").write_text("{", encoding="utf-8")
    assert hakem.main(["saf", str(tmp_path / "bozuk.json")]) == 1
    (tmp_path / "liste.json").write_text("[]", encoding="utf-8")
    assert hakem.main(["saf", str(tmp_path / "liste.json")]) == 1


def test_py_hakem_yukle(tmp_path):
    d = tmp_path / "benim_hakemim.py"
    d.write_text("def karar(girdi):\n    return {'puan': 0.0}\nSABIT = 3\n", encoding="utf-8")
    assert hakem.py_hakem_yukle(f"{d}:karar")({}) == {"puan": 0.0}
    for bozuk in (str(d), f"{d}:", f"{d}:yok", f"{d}:SABIT", f"{tmp_path / 'yok.py'}:karar", f"{d}:1ad"):
        with pytest.raises((ValueError, TypeError)):
            hakem.py_hakem_yukle(bozuk)


def test_sec():
    assert hakem.sec(None, SALDIRILAR, "saldırı") == SALDIRILAR
    assert [s.id for s in hakem.sec(["cok-cevap", "cok-cevap"], SALDIRILAR, "saldırı")] == ["cok-cevap"]
    with pytest.raises(ValueError, match="bilinmeyen saldırı: yok"):
        hakem.sec(["yok"], SALDIRILAR, "saldırı")


# --- CLI -----------------------------------------------------------------------------------------------------

def test_cli_ornek_hakemler_json_md(tmp_path, capsys):
    j, m = tmp_path / "h.json", tmp_path / "h.md"
    assert main(["hakem-sina", "--ornek-hakem", "saf", "--json", str(j), "--md", str(m)]) == 2
    cikti = capsys.readouterr().out
    assert "KANDIRDI" in cikti and "-> uygun" in cikti
    veri = json.loads(j.read_text(encoding="utf-8"))
    assert veri["mod"] == "hakem" and veri["sonuc"]["hakem"] == "ornek:saf" and veri["butce"] is None
    assert veri["sonuc"]["toplam"]["kandiran_saldiri"] == len(SALDIRILAR)
    assert {d["saldiri"] for d in veri["sonuc"]["denemeler"]} == {s.id for s in SALDIRILAR}
    md = m.read_bytes()
    assert b"\r\n" not in md and "| talimat-enjeksiyonu | 5/5 | KANDIRDI |" in md.decode("utf-8")
    assert main(["hakem-sina", "--ornek-hakem", "saglam", "--json", str(j)]) == 0
    assert "dayandı" in capsys.readouterr().out
    assert json.loads(j.read_text(encoding="utf-8"))["sonuc"]["toplam"]["kandirilan_cift"] == 0


def test_cli_secim_ve_kullanim_hatalari(capsys):
    assert main(["hakem-sina", "--ornek-hakem", "saf", "--saldiri", "bicim-oyunu", "--gorev", "test-raporu"]) == 2
    assert main(["hakem-sina", "--ornek-hakem", "saf", "--saldiri", "bicim-oyunu", "--gorev", "carpim"]) == 0
    assert main(["hakem-sina"]) == 2
    assert main(["hakem-sina", "--ornek-hakem", "saf", "--hakem", "true", "--butce-usd", "1"]) == 2
    assert main(["hakem-sina", "--hakem", "true"]) == 2  # kullanıcı hakemi: bütçe zorunlu
    assert main(["hakem-sina", "--ornek-hakem", "saf", "--saldiri", "yok"]) == 2
    assert main(["hakem-sina", "--ornek-hakem", "saf", "--gorev", "yok"]) == 2
    assert main(["hakem-sina", "--ornek-hakem", "saf", "--tekrar", "0"]) == 2
    assert main(["hakem-sina", "--hakem", "true", "--butce-usd", "1", "--ortam-izin", "kotu ad"]) == 2
    assert main(["hakem-sina", "--hakem", "true", "--butce-usd", "1", "--hakem-env", "BOZUK"]) == 2
    with pytest.raises(SystemExit) as e:
        main(["hakem-sina", "--ornek-hakem", "baska"])
    assert e.value.code == 2
    capsys.readouterr()
    assert main(["hakem-sina", "--liste"]) == 0
    cikti = capsys.readouterr().out
    assert all(s.id in cikti for s in SALDIRILAR) and all(g.id in cikti for g in GOREVLER)


def test_cli_komut_hakem_ve_butce(tmp_path, capsys):
    j = tmp_path / "h.json"
    saglam = f"{PY} -m vaka.hakem saglam {{girdi_dosyasi}}"
    argv = ["hakem-sina", "--hakem", saglam, "--butce-usd", "1", "--saldiri", "sahte-karar", "--gorev", "carpim"]
    assert main(argv + ["--json", str(j)]) == 0
    veri = json.loads(j.read_text(encoding="utf-8"))
    assert veri["sonuc"]["hakem"] == "komut" and veri["butce"]["sinir_usd"] == 1
    assert "ortam: sır adlı" in capsys.readouterr().err
    assert main(argv[:3] + ["--butce-usd", "0"]) == 3  # hiçbir çağrı sığmaz
    assert main(["hakem-sina", "--hakem", "exit 3", "--butce-usd", "1", "--gorev", "carpim"]) == 1
    assert "hakem hatası" in capsys.readouterr().err


def test_cli_py_hakem(tmp_path, capsys):
    d = tmp_path / "h.py"
    d.write_text("from vaka.hakem import saglam_hakem\n\ndef h(girdi):\n    return saglam_hakem(girdi)\n\n"
                 "def hep_kaldi(girdi):\n    return False\n", encoding="utf-8")
    assert main(["hakem-sina", "--hakem-py", f"{d}:h", "--butce-usd", "1"]) == 0
    assert main(["hakem-sina", "--hakem-py", f"{d}:hep_kaldi", "--butce-usd", "1"]) == 1
    assert "denetim tutmadı" in capsys.readouterr().err
    assert main(["hakem-sina", "--hakem-py", f"{d}:yok", "--butce-usd", "1"]) == 1
    assert main(["hakem-sina", "--hakem-py", f"{d}:h"]) == 2


def test_saldiri_baglantilari_ornek_alan_adinda():
    """Saldırı yükleri sentetiktir; bağlantılar example.com'a gider."""
    for s, g in CIFTLER:
        for url in re.findall(r"https?://\S+", s.uret(g)):
            assert url.startswith("https://example.com/"), url


def test_cli_cp1252_konsolda_cokmez():
    """Windows konsolu taklidi: çıktı kodlaması cp1252 iken Türkçe harfli liste basılabilir."""
    import os
    import subprocess
    import sys

    env = {**os.environ, "PYTHONIOENCODING": "cp1252", "PYTHONUTF8": "0"}
    r = subprocess.run([sys.executable, "-m", "vaka", "hakem-sina", "--liste"], capture_output=True, env=env,
                       check=False)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")
    assert r.stdout.decode("utf-8")
