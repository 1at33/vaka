"""Komut satırı: alt komutlar, çıkış kodları, raporlar."""
import json
import os
import subprocess
import sys
import textwrap

import pytest
from conftest import ORNEK, SRC, mini_vaka

from vaka import __version__
from vaka.cli import main


def _vaka_dizini(tmp_path, **ek):
    d = tmp_path / "vakalar"
    d.mkdir(exist_ok=True)
    v = mini_vaka(**ek)
    v.pop("_dosya")
    (d / f"{v['id']}.json").write_text(json.dumps(v, ensure_ascii=False), encoding="utf-8")
    return d


def test_dogrula_ornek_tek_vaka_json_md(tmp_path, capsys):
    j, m = tmp_path / "s.json", tmp_path / "s.md"
    kod = main(["dogrula", "--vakalar", str(ORNEK), "--vaka", "ornek-git-add-hepsi", "--json", str(j), "--md", str(m)])
    assert kod == 0
    assert "GEÇERLİ" in capsys.readouterr().out
    veri = json.loads(j.read_text(encoding="utf-8"))
    assert veri["mod"] == "dogrulama" and veri["sonuc"][0]["gecerli"] is True
    assert b"\r\n" not in m.read_bytes() and "| ornek-git-add-hepsi |" in m.read_text(encoding="utf-8")


def test_dogrula_gecersiz_vaka_cikis_1(tmp_path, capsys):
    d = _vaka_dizini(tmp_path, kontrol={"komut": ["echo TEMIZ"], "gecer_cikti": "TEMIZ"})
    assert main(["dogrula", "--vakalar", str(d)]) == 1
    assert "GEÇERSİZ" in capsys.readouterr().out


def test_vaka_yoksa_cikis_1(tmp_path):
    assert main(["dogrula", "--vakalar", str(tmp_path)]) == 1


def test_yeni_iskelet_doldurulana_kadar_gecersiz(tmp_path, capsys):
    d = tmp_path / "vakalar"
    assert main(["yeni", "benim-olayim", "--vakalar", str(d)]) == 0
    assert (d / "benim-olayim.json").is_file()
    assert main(["yeni", "benim-olayim", "--vakalar", str(d)]) == 1
    assert main(["yeni", "Kotu Ad", "--vakalar", str(d)]) == 2
    assert main(["yeni", "eski-olay", "--vakalar", str(d), "--suite", "regresyon"]) == 0
    assert (d / "regresyon" / "eski-olay.json").is_file()
    capsys.readouterr()
    assert main(["dogrula", "--vakalar", str(d)]) == 1
    assert "eksik alan" in capsys.readouterr().err


def test_liste(capsys):
    assert main(["liste", "--vakalar", str(ORNEK)]) == 0
    cikti = capsys.readouterr().out
    assert "ornek-sir-loga-sizar" in cikti and "regresyon" in cikti


def test_kos_butce_zorunlu(tmp_path):
    with pytest.raises(SystemExit) as e:
        main(["kos", "--vakalar", str(tmp_path), "--ajan", "true"])
    assert e.value.code == 2


def test_kos_ajan_yoksa_kosmaz(tmp_path, capsys):
    d = _vaka_dizini(tmp_path)
    assert main(["kos", "--vakalar", str(d), "--butce-usd", "1"]) == 1
    assert "ajan komutu yok" in capsys.readouterr().err


def test_kos_ayardan_komut_ve_cikis_kodlari(tmp_path, monkeypatch, capsys):
    d = _vaka_dizini(tmp_path, baglam={"metin": "- x.txt y olmalı"})
    ayar = tmp_path / "ayar.toml"
    ayar.write_text('[ajan]\nkomut = "echo y > x.txt"\n', encoding="utf-8")
    monkeypatch.setenv("VAKA_AYAR", str(ayar))
    j, m = tmp_path / "k.json", tmp_path / "k.md"
    assert main(["kos", "--vakalar", str(d), "--butce-usd", "1", "--json", str(j), "--md", str(m)]) == 0
    veri = json.loads(j.read_text(encoding="utf-8"))
    assert {s["kol"] for s in veri["sonuc"]} == {"baglam", "baglamsiz"}
    assert veri["butce"]["sinir_usd"] == 1
    assert "Bağlamın katkısı" in m.read_text(encoding="utf-8")
    capsys.readouterr()
    assert main(["kos", "--vakalar", str(d), "--butce-usd", "1", "--ajan", "true"]) == 2
    assert main(["kos", "--vakalar", str(d), "--butce-usd", "1", "--ajan", "true", "--kol", "baglamsiz"]) == 0
    assert main(["kos", "--vakalar", str(d), "--butce-usd", "0"]) == 3
    assert main(["kos", "--vakalar", str(d), "--butce-usd", "1", "--ajan-env", "BOZUK"]) == 2


def test_kos_bozuk_ayar_cikis_1(tmp_path, monkeypatch, capsys):
    d = _vaka_dizini(tmp_path)
    ayar = tmp_path / "ayar.toml"
    ayar.write_text("[baska]\n", encoding="utf-8")
    monkeypatch.setenv("VAKA_AYAR", str(ayar))
    assert main(["kos", "--vakalar", str(d), "--butce-usd", "1"]) == 1
    assert "ayar hatası" in capsys.readouterr().err


def test_surum(capsys):
    with pytest.raises(SystemExit):
        main(["--version"])
    assert __version__ in capsys.readouterr().out


def _py(kod):
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(filter(None, [SRC, os.environ.get("PYTHONPATH")])))
    return subprocess.run([sys.executable, "-c", textwrap.dedent(kod)], check=False, capture_output=True,
                          text=True, encoding="utf-8", env=env)


def test_stringio_stdout_cokmez():
    r = _py(f"""
        import io, sys
        from vaka.cli import main
        sys.stdout = io.StringIO()
        kod = main(["liste", "--vakalar", {str(ORNEK)!r}])
        cikti = sys.stdout.getvalue()
        sys.stdout = sys.__stdout__
        print(kod, "ornek-crlf-yazimi" in cikti)
    """)
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == ["0", "True"]


def test_crlf_sarmalayicida_lf_basar():
    r = _py(f"""
        import io, sys
        from vaka.cli import main
        b = io.BytesIO()
        sys.stdout = io.TextIOWrapper(b, encoding="utf-8", newline="\\r\\n")
        main(["liste", "--vakalar", {str(ORNEK)!r}])
        sys.stdout.flush()
        veri = b.getvalue()
        sys.stdout = sys.__stdout__
        print("CRLF" if b"\\r\\n" in veri else "LF")
    """)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "LF"


def test_python_m_vaka():
    r = _py("""
        import runpy, sys
        sys.argv = ["vaka", "--version"]
        runpy.run_module("vaka", run_name="__main__")
    """)
    assert __version__ in r.stdout


def test_kos_ortak_defter(tmp_path):
    d = _vaka_dizini(tmp_path)
    defter = tmp_path / "defter.txt"
    j = tmp_path / "k.json"
    argv = ["kos", "--vakalar", str(d), "--ajan", "echo y > x.txt", "--butce-usd", "0.025",
            "--butce-defter", str(defter), "--tahmini-kosu-usd", "0.01", "--json", str(j)]
    assert main(argv) == 0
    assert main(argv) == 0
    assert main(argv) == 3  # üçüncü koşu ortak defterde sığmaz
    assert json.loads(j.read_text(encoding="utf-8"))["butce"]["defter"] == str(defter)


@pytest.mark.skipif(os.name == "nt", reason="POSIX izinleri")
def test_rapor_dosyalari_yalniz_sahibine_acik(tmp_path, capsys):
    d = _vaka_dizini(tmp_path)
    j, m = tmp_path / "s.json", tmp_path / "s.md"
    m.write_text("eski\n", encoding="utf-8")
    m.chmod(0o644)
    assert main(["dogrula", "--vakalar", str(d), "--json", str(j), "--md", str(m)]) == 0
    assert (j.stat().st_mode & 0o777) == 0o600
    assert (m.stat().st_mode & 0o777) == 0o600
    assert "| mini-01 |" in m.read_text(encoding="utf-8") and b"\r\n" not in m.read_bytes()
    jk, mk = tmp_path / "k.json", tmp_path / "k.md"
    assert main(["kos", "--vakalar", str(d), "--ajan", "echo y > x.txt", "--butce-usd", "1",
                 "--json", str(jk), "--md", str(mk)]) == 0
    assert (jk.stat().st_mode & 0o777) == 0o600 and (mk.stat().st_mode & 0o777) == 0o600


def test_kos_disari_cikan_baglam_dosyasinda_kosmaz(tmp_path, capsys):
    d = _vaka_dizini(tmp_path, baglam={"dosyalar": ["../disari.md"]})
    (tmp_path / "disari.md").write_text("- dışarıdaki not\n", encoding="utf-8")
    isaret = tmp_path / "kostu"
    assert main(["kos", "--vakalar", str(d), "--ajan", f"touch {isaret}", "--butce-usd", "1"]) == 1
    assert "dışına çıkıyor" in capsys.readouterr().err
    assert not isaret.exists()


def test_kos_ortam_izin_bildirimi_yalniz_adlar(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DENEME_AJAN_API_KEY", "bildirimde-" + "gorunmemeli-1")
    monkeypatch.setenv("AYARDAN_TOKEN", "bildirimde-" + "gorunmemeli-2")
    d = _vaka_dizini(tmp_path)
    ayar = tmp_path / "ayar.toml"
    ayar.write_text('[ajan]\nkomut = "echo y > x.txt"\nortam_izin = ["AYARDAN_TOKEN"]\n', encoding="utf-8")
    monkeypatch.setenv("VAKA_AYAR", str(ayar))
    j = tmp_path / "k.json"
    argv = ["kos", "--vakalar", str(d), "--butce-usd", "1", "--ortam-izin", "DENEME_AJAN_API_KEY",
            "--ortam-izin", "OLMAYAN_KEY", "--ajan-env", "EK_AD=ek-deger-gorunmemeli", "--json", str(j)]
    assert main(argv) == 0
    cikti = capsys.readouterr()
    satir = [s for s in cikti.err.splitlines() if s.startswith("ortam:")]
    assert len(satir) == 1
    assert "AYARDAN_TOKEN, DENEME_AJAN_API_KEY" in satir[0] and "ortamda yok: OLMAYAN_KEY" in satir[0]
    assert "EK_AD" in satir[0]
    hepsi = cikti.out + cikti.err + j.read_text(encoding="utf-8")
    assert "bildirimde-gorunmemeli" not in hepsi and "ek-deger-gorunmemeli" not in hepsi
    assert main(["kos", "--vakalar", str(d), "--butce-usd", "1", "--ortam-izin", "kotu ad"]) == 2
