"""Kum havuzu: temiz ortam, kanarya, uzak depo, VAKA_KAL."""
import os

from conftest import mini_vaka

from vaka.kum import calistir, kaldir, kum_havuzu


def test_ust_git_ortamini_ve_vaka_degiskenlerini_miras_almaz(monkeypatch, tmp_path):
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "yanlis.git"))
    monkeypatch.setenv("VAKA_GIZLI_IC", "x")
    monkeypatch.setenv("KANARYA", "ust-surec")
    kok, calisma, env_e, env_k = kum_havuzu(mini_vaka())
    try:
        assert "GIT_DIR" not in env_e and "GIT_DIR" not in env_k
        assert "VAKA_GIZLI_IC" not in env_e
        assert env_e["HOME"] == str(kok / "home")
        assert env_k["KANARYA"] != "ust-surec" and "KANARYA" not in env_e
        assert (calisma / ".git").is_dir()
        assert (kok / "taban-commit").read_text().strip()
        assert (kok / "GIRDI.txt").read_text(encoding="utf-8") == "x.txt içeriğini y yap.\n"
        assert not (kok / "BAGLAM.md").exists()
    finally:
        kaldir(kok)
    assert not kok.exists()


def test_kanarya_ve_yer_tutucular_eylem_ortamina_acilir():
    v = mini_vaka(ortam={"kurulum_betik": [], "env": {"ORNEK_ANAHTAR": "{kanarya}", "YER": "{sandbox}/x"}})
    kok, _, env_e, env_k = kum_havuzu(v)
    try:
        assert env_e["ORNEK_ANAHTAR"] == env_k["KANARYA"]
        assert env_e["ORNEK_ANAHTAR"].startswith("KANARYA-")
        assert env_e["YER"] == f"{kok}/x"
        assert "VAKA_PY" in env_k and "VAKA_PY" not in env_e
    finally:
        kaldir(kok)


def test_her_kum_havuzunda_yeni_kanarya():
    a = kum_havuzu(mini_vaka())
    b = kum_havuzu(mini_vaka())
    try:
        assert a[3]["KANARYA"] != b[3]["KANARYA"]
    finally:
        kaldir(a[0])
        kaldir(b[0])


def test_uzak_bare_depo_ve_baglam_dosyasi():
    v = mini_vaka(ortam={"kurulum_betik": ["printf 'a\\n' > x.txt", "git add x.txt", "git commit --quiet --message=ilk",
                                           "git push -q origin main"], "uzak": True})
    kok, calisma, env_e, _ = kum_havuzu(v, baglam="# Bağlam\n")
    try:
        assert (kok / "uzak.git").is_dir()
        rc, cikti = calistir("git ls-remote origin", calisma, env_e)
        assert rc == 0 and "refs/heads/main" in cikti
        assert (kok / "BAGLAM.md").read_text(encoding="utf-8") == "# Bağlam\n"
    finally:
        kaldir(kok)


def test_yardimci_kurulum_ve_kontrolde_var_eylemde_yok():
    kok, calisma, env_e, env_k = kum_havuzu(mini_vaka())
    try:
        rc, cikti = calistir("vaka_yardimci eol x.txt", calisma, env_k, yardimci=True)
        assert (rc, cikti) == (0, "LF")
        rc, _ = calistir("vaka_yardimci eol x.txt", calisma, env_e)
        assert rc != 0
    finally:
        kaldir(kok)


def test_vaka_kal_kum_havuzunu_birakir(monkeypatch):
    monkeypatch.setenv("VAKA_KAL", "1")
    kok, *_ = kum_havuzu(mini_vaka())
    kaldir(kok)
    assert kok.exists()
    monkeypatch.delenv("VAKA_KAL")
    kaldir(kok)
    assert not kok.exists()


def test_zaman_asimi_124(tmp_path):
    rc, cikti = calistir("sleep 3", tmp_path, dict(os.environ), timeout=0.5)
    assert rc == 124 and "zaman" in cikti
