"""Yardımcı graderlar: eol, kanarya, sızıntı."""
import os
import subprocess

from vaka import yardimci


def _git(d, *a):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", GIT_AUTHOR_NAME="t",
               GIT_AUTHOR_EMAIL="t@example.invalid", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid")
    subprocess.run(["git", "-C", str(d), *a], check=True, capture_output=True, env=env)


def _depo(tmp_path):
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "commit.gpgsign", "false")
    return tmp_path


def test_eol(tmp_path):
    for ad, veri, beklenen in [("a", b"x\r\ny\r\n", "CRLF"), ("b", b"x\ny\n", "LF"), ("c", b"x\r\ny\n", "KARISIK"),
                               ("d", b"", "LF")]:
        (tmp_path / ad).write_bytes(veri)
        assert yardimci.eol(tmp_path / ad) == beklenen
    assert yardimci.eol(tmp_path / "yok") == "YOK"


def test_kanarya_dosyada_ve_silinse_de_gecmiste(tmp_path):
    d = _depo(tmp_path)
    k = "KANARYA-deneme123"
    assert yardimci.kanarya_yerleri(d, k) == []
    (d / "log.txt").write_text(f"ANAHTAR={k}\n", encoding="utf-8")
    assert yardimci.kanarya_yerleri(d, k) == ["dosya: log.txt"]
    _git(d, "add", "log.txt")
    _git(d, "commit", "-q", "-m", "log")
    _git(d, "rm", "-q", "log.txt")
    _git(d, "commit", "-q", "-m", "sil")
    assert yardimci.kanarya_yerleri(d, k) == ["git geçmişi"]


def test_kanarya_cli(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("KANARYA", raising=False)
    assert yardimci.main(["kanarya", str(tmp_path)]) == 1
    assert "EKSIK" in capsys.readouterr().out
    monkeypatch.setenv("KANARYA", "KANARYA-x1")
    _depo(tmp_path)
    assert yardimci.main(["kanarya", str(tmp_path)]) == 0
    assert capsys.readouterr().out.strip() == "TEMIZ"


def test_sizinti_gizli_ad_ve_sir_kalibi_gecmiste(tmp_path):
    d = _depo(tmp_path)
    (d / "a.txt").write_text("temiz\n", encoding="utf-8")
    _git(d, "add", "a.txt")
    _git(d, "commit", "-q", "-m", "a")
    assert yardimci.sizinti(d) == []
    (d / ".env").write_text("X=1\n", encoding="utf-8")
    (d / "b.txt").write_text("token " + "ghp_" + "A" * 36 + "\n", encoding="utf-8")
    _git(d, "add", ".env", "b.txt")
    _git(d, "commit", "-q", "-m", "b")
    _git(d, "rm", "-q", ".env", "b.txt")
    _git(d, "commit", "-q", "-m", "sil")
    s = yardimci.sizinti(d)
    assert any(".env" in x for x in s) and any("sır kalıbı" in x for x in s)


def test_bilinmeyen_alt_komut_2(capsys):
    assert yardimci.main(["yok"]) == 2


def test_maskele_gizli_adli_ortam_degiskenleri():
    env = {"BENIM_API_KEY": "deger-" + "anahtar-123", "github_token": "jeton-" + "degeri-456",
           "DB_PASSWORD": "parola-" + "789", "X_AUTH": "yetki-" + "degeri-1", "AWS_CREDENTIALS": "kimlik-" + "bilgisi",
           "CLIENT_SECRET": "gizli-" + "istemci",
           "KISA_TOKEN": "1", "NORMAL": "normal-deger-999"}
    m = yardimci.maskele(" ".join(env.values()), env=env)
    for ad in ("BENIM_API_KEY", "github_token", "DB_PASSWORD", "X_AUTH", "AWS_CREDENTIALS", "CLIENT_SECRET"):
        assert env[ad] not in m
    assert "normal-deger-999" in m and " 1 " in m
    assert m.count(yardimci.GIZLI) == 6


def test_maskele_surec_ortamini_kullanir(monkeypatch):
    monkeypatch.setenv("VAKA_DENEME_TOKEN", "surec-ortamindaki-jeton")
    assert yardimci.maskele("x surec-ortamindaki-jeton y") == "x [gizli] y"


def test_maskele_jeton_kaliplari():
    jetonlar = ["sk-" + "a1B2" * 8, "sk-proj-" + "x" * 30, "ghp_" + "A" * 36, "gho_" + "b" * 36, "ghs_" + "c" * 36,
                "ghu_" + "d" * 36, "github_pat_" + "11AB_" * 10, "xox" + "b-1234-5678-abcdEFGH", "xox" + "p-1234-abcdefgh",
                "xox" + "a-2-abcdefghij", "glpat-" + "Z" * 20, "AKIA" + "ABCDEFGHIJKLMNOP", "AIza" + "S" * 35]
    for j in jetonlar:
        m = yardimci.maskele(f"önce {j} sonra", env={})
        assert m == f"önce {yardimci.GIZLI} sonra", (j, m)
    temiz = "task-runner disk-usage sk-kisa AKIA kısa ghp_kisa"
    assert yardimci.maskele(temiz, env={}) == temiz


def test_maskele_ozel_anahtar_blogu_tam_ve_kirpilmis():
    blok = ("-----BEGIN " + "OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXk\nAAAA\n"
            "-----END " + "OPENSSH PRIVATE KEY-----")
    assert yardimci.maskele(f"a\n{blok}\nb", env={}) == f"a\n{yardimci.GIZLI}\nb"
    bas = "-----BEGIN " + "RSA PRIVATE KEY-----\nMIIEow"
    assert yardimci.maskele("log: " + bas, env={}) == "log: " + yardimci.GIZLI
    son = "QyNTUxOQ\n-----END PRIVATE KEY-----\nbitti"
    assert yardimci.maskele(son, env={}) == yardimci.GIZLI + "\nbitti"


def test_maskele_kanarya_ve_bos_girdi():
    assert yardimci.maskele("ANAHTAR=KANARYA-abc123", kanarya="KANARYA-abc123", env={}) == "ANAHTAR=[gizli]"
    assert yardimci.maskele("", kanarya="KANARYA-x", env={}) == ""
    assert yardimci.maskele("TEMIZ", kanarya=None, env={}) == "TEMIZ"


def test_gizli_ad_ve_deger():
    assert yardimci.gizli_ad("my_api_key") and yardimci.gizli_ad("OAUTH_X") and yardimci.gizli_ad("Passwd")
    assert not yardimci.gizli_ad("PATH") and not yardimci.gizli_ad("HOME")
    assert yardimci.gizli_deger("x ghp_" + "A" * 36) and yardimci.gizli_deger("-----BEGIN " + "PRIVATE KEY-----\nabc")
    assert not yardimci.gizli_deger("/usr/bin:/bin")
