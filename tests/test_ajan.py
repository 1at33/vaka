"""Ajan koşucusu: komut şablonu, kollar, gizlenen kontrol dosyaları, bütçe."""
import json
import os

import pytest
from conftest import ORNEK, mini_vaka

from vaka.ajan import ajan_kos, kollar, komut_ac, son_satir_json
from vaka.ayar import AjanAyari
from vaka.bicim import vaka_oku
from vaka.butce import Butce

REF = "echo y > x.txt"


def ayar(komut, **ek):
    return AjanAyari(komut=komut, **ek)


def test_dogru_davranan_ajan_gecer_hicbir_sey_yapmayan_kalir():
    v = mini_vaka()
    assert ajan_kos(v, ayar(REF))["gecti"] is True
    s = ajan_kos(v, ayar("true"))
    assert s["gecti"] is False and s["gecen"] == 0 and s["kosu"] == 1


def test_ajan_komutu_yoksa_kosmaz():
    with pytest.raises(ValueError, match="ajan komutu yok"):
        ajan_kos(mini_vaka(), AjanAyari())


def test_kollar():
    assert kollar(mini_vaka()) == [None]
    v = mini_vaka(baglam={"metin": "- kural"})
    assert kollar(v) == ["baglam", "baglamsiz"]
    assert kollar(v, "baglam") == ["baglam"]
    assert kollar(dict(v, suite="regresyon")) == [None]


def test_baglam_yalniz_baglam_kolunda_kontrol_dosyalari_gizli(tmp_path):
    v = mini_vaka(baglam={"metin": "- x.txt her zaman y olmalı"}, ortam={
        "kurulum_betik": ["printf 'a\\n' > x.txt", "git add x.txt", "git commit --quiet --message=ilk", "mkdir ../ek-klasor"],
        "gorunur": ["ek-klasor"]})
    komut = ('f={baglam_dosyasi}; [ -n "$f" ] && cp "$f" "$CIKTI/$KOL-baglam.md"; '
             'ls .. | sort > "$CIKTI/$KOL-kok.txt"; printf "%s" "$VAKA_GIRDI" > "$CIKTI/$KOL-girdi.txt"; '
             'cp {girdi_dosyasi} "$CIKTI/$KOL-girdi-dosyasi.txt"; ' + REF)
    for kol in ("baglam", "baglamsiz"):
        s = ajan_kos(v, ayar(komut), kol=kol, ek_env={"CIKTI": str(tmp_path), "KOL": kol})
        assert s["gecti"] is True, s  # kontrol taban-commit dosyasını geri bulur
        kok = (tmp_path / f"{kol}-kok.txt").read_text().split()
        assert "taban-commit" not in kok
        assert "calisma" in kok and "GIRDI.txt" in kok and "ek-klasor" in kok
        assert (tmp_path / f"{kol}-girdi.txt").read_text(encoding="utf-8") == v["girdi"]
        assert (tmp_path / f"{kol}-girdi-dosyasi.txt").read_text(encoding="utf-8").strip() == v["girdi"]
        assert s["senaryolar"][0]["baglam_dosyasi"] is (kol == "baglam")
    assert "x.txt her zaman y" in (tmp_path / "baglam-baglam.md").read_text(encoding="utf-8")
    assert not (tmp_path / "baglamsiz-baglam.md").exists()
    assert "BAGLAM.md" in (tmp_path / "baglam-kok.txt").read_text()


def test_ajan_ortaminda_harness_degiskeni_yok(tmp_path):
    komut = 'env > "$CIKTI/env.txt"; ' + REF
    ajan_kos(mini_vaka(), ayar(komut), ek_env={"CIKTI": str(tmp_path)})
    env = (tmp_path / "env.txt").read_text(encoding="utf-8", errors="replace")
    assert "KANARYA=" not in env and "VAKA_PY=" not in env


def test_kendi_ev_ayari_home_u_korur(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "gercek-ev"))
    # HOME'u ajanın kendisi gibi yerel bir süreç okur: Git Bash kabuk içinde HOME'u /c/... biçimine çevirir,
    # Windows programlarına ise özgün yolu geri verir.
    komut = 'python3 -c "import os, sys; sys.stdout.write(os.environ[\'HOME\'])" > "$CIKTI/ev.txt"; ' + REF
    ajan_kos(mini_vaka(), ayar(komut), ek_env={"CIKTI": str(tmp_path)})
    assert (tmp_path / "ev.txt").read_text().endswith("home")
    ajan_kos(mini_vaka(), ayar(komut, kendi_ev=True), ek_env={"CIKTI": str(tmp_path)})
    assert (tmp_path / "ev.txt").read_text() == str(tmp_path / "gercek-ev")


def test_tekrar_varyant_tekrar_ve_maliyet():
    v = mini_vaka(varyantlar=[{"ad": "b", "kurulum_ek": ["printf 'b\\n' > x.txt"]}])
    komut = REF + '; echo \'{"maliyet_usd": 0.002}\''
    s = ajan_kos(v, ayar(komut), tekrar=3, varyant_tekrar=1)
    assert s["kosu"] == 4 and s["gecen"] == 4
    assert [x["senaryo"] for x in s["senaryolar"]] == ["ana"] * 3 + ["b"]
    assert all(x["maliyet_usd"] == 0.002 for x in s["senaryolar"])


def test_butce_dolunca_kalan_kosular_atlanir_kaldi_sayilmaz(tmp_path):
    butce = Butce(0.025, tmp_path / "defter.txt", tahmini_kosu_usd=0.01)
    s = ajan_kos(mini_vaka(), ayar(REF + '; echo \'{"maliyet_usd": 0.01}\''), tekrar=5, butce=butce)
    assert s["kosu"] == 2 and s["atlandi_butce"] == 3 and s["gecti"] is True
    assert butce.harcanan() == pytest.approx(0.02)
    assert butce.ucustaki() == 0


def test_butce_bastan_doluysa_hic_kosu_yok(tmp_path):
    s = ajan_kos(mini_vaka(), ayar(REF), tekrar=2, butce=Butce(0, tmp_path / "d.txt"))
    assert s["kosu"] == 0 and s["gecti"] is None and s["atlandi_butce"] == 2


def test_kurulum_hatasinda_rezerv_sizmaz(tmp_path):
    butce = Butce(1, tmp_path / "d.txt")
    with pytest.raises(RuntimeError):
        ajan_kos(mini_vaka(ortam={"kurulum_betik": ["false"]}), ayar(REF), butce=butce)
    assert butce.ucustaki() == 0 and butce.harcanan() == 0


def test_zaman_asimi():
    s = ajan_kos(mini_vaka(), ayar("sleep 5", zaman_asimi_sn=1))
    assert s["senaryolar"][0]["ajan_cikis"] == 124 and s["gecti"] is False


def test_ornek_vaka_referansi_ajan_olarak_gecer():
    v = vaka_oku(ORNEK / "ornek-crlf-yazimi.json")
    betik = "\n".join(v["referans_cozum"])
    s = ajan_kos(v, ayar(betik), kol="baglamsiz")
    assert s["gecti"] is True, s
    neg = ajan_kos(v, ayar("\n".join(v["negatif"])), kol="baglam")
    assert neg["gecti"] is False


def test_komut_sablonu_ve_son_satir_json(tmp_path):
    k = komut_ac("ajan {girdi_dosyasi} {baglam_dosyasi} {calisma}", tmp_path, False)
    assert "GIRDI.txt" in k and "''" in k and "calisma" in k
    assert "BAGLAM.md" in komut_ac("{baglam_dosyasi}", tmp_path, True)
    assert son_satir_json('x\n{"maliyet_usd": 1}\n') == {"maliyet_usd": 1}
    assert son_satir_json("yok") is None
    assert son_satir_json(json.dumps([1])) is None
    assert son_satir_json("") is None


def test_windows_disinda_onek_bos():
    from vaka.kum import WIN_ONEK
    assert (WIN_ONEK == "") is (os.name != "nt")


def test_ajan_ve_kontrol_ciktisi_maskelenir(monkeypatch):
    monkeypatch.setenv("DENEME_SECRET", "surec-sirri-degeri-7")
    komut = ('echo "env=$DENEME_SECRET ek=$BENIM_TOKEN"; echo "sk-' + "q" * 30 + '" >&2; ' + REF)
    k = dict(mini_vaka()["kontrol"])
    k["komut"] = ["echo \"kanarya=$KANARYA\""] + k["komut"]
    s = ajan_kos(mini_vaka(kontrol=k), ayar(komut, ortam_izin=("DENEME_SECRET",)),
                 ek_env={"BENIM_TOKEN": "ek-ortam-jetonu-1"})
    sn = s["senaryolar"][0]
    assert s["gecti"] is True, s
    assert "env=[gizli] ek=[gizli]" in sn["ajan_cikti"] and "sk-" not in sn["ajan_cikti"]
    assert "kanarya=[gizli]" in sn["kontrol_cikti"] and "KANARYA-" not in sn["kontrol_cikti"]


def test_sirlar_ajana_gecmez_izinli_ad_yalniz_ajana_gecer(tmp_path, monkeypatch):
    monkeypatch.setenv("DENEME_AJAN_API_KEY", "ajanin-kendi-anahtari")
    monkeypatch.setenv("DIGER_TOKEN", "baska-bir-jeton-degeri")
    monkeypatch.setenv("SIRADAN_DEGISKEN", "ghp_" + "Z" * 36)
    komut = ('printf "%s|%s|%s" "${DENEME_AJAN_API_KEY-YOK}" "${DIGER_TOKEN-YOK}" "${SIRADAN_DEGISKEN-YOK}" '
             '> "$CIKTI/ajan.txt"; ' + REF)
    k = dict(mini_vaka()["kontrol"])
    k["komut"] = ['test -z "${DENEME_AJAN_API_KEY+x}${DIGER_TOKEN+x}${SIRADAN_DEGISKEN+x}" || exit 7'] + k["komut"]
    v = mini_vaka(kontrol=k)
    s = ajan_kos(v, ayar(komut), ek_env={"CIKTI": str(tmp_path)})
    assert s["gecti"] is True, s
    assert (tmp_path / "ajan.txt").read_text() == "YOK|YOK|YOK"
    s = ajan_kos(v, ayar(komut, ortam_izin=("DENEME_AJAN_API_KEY",)), ek_env={"CIKTI": str(tmp_path)})
    assert s["gecti"] is True, s  # kontrol betiği izinli değişkeni de görmez
    assert (tmp_path / "ajan.txt").read_text() == "ajanin-kendi-anahtari|YOK|YOK"
