"""Kum havuzu: her senaryo için geçici bir git deposu, temiz ortam ve bash çalıştırıcı.

Düzen (kök, geçici bir dizindir; adlar köke göreli):

    calisma    git deposu; kurulum, eylem ve kontrol burada çalışır
    home       HOME
    uzak.git   `ortam.uzak: true` ise yerel bare depo (origin)
    taban-commit  kurulum bittiğindeki commit kimliği (kurulumda commit yoksa dosya yok)
    GIRDI.txt  görev metni
    BAGLAM.md  yalnız `baglam` kolunda
"""
import os
import secrets
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

from vaka.bicim import metin
from vaka.yardimci import gizli_ad, gizli_deger, maskele

PAKET_KOKU = str(Path(__file__).resolve().parents[1])
KANARYA_ONEK = "KANARYA-"
TABAN_DOSYASI = "taban-commit"


def _py_yolu():
    return sys.executable.replace("\\", "/")


# Windows (Git Bash) farkları vaka betikleri için Linux'a eşitlenir; Linux/macOS'ta önek boştur:
# - `python3` çoğu zaman Microsoft Store kısayoludur -> bu süreçteki yorumlayıcı;
# - MSYS `sed` metin kipinde CR'yi siler -> `sed -b` (GNU sed'de de geçerli bayrak).
WIN_ONEK = ('python3() { "' + _py_yolu() + '" "$@"; }\nexport -f python3\n'
            'sed() { command sed -b "$@"; }\nexport -f sed\n') if os.name == "nt" else ""
# Kurulum ve kontrol betiklerinde yardımcı graderlar: `vaka_yardimci eol dosya` gibi. Ajan ortamında yoktur.
YARDIMCI_ONEK = 'vaka_yardimci() { "$VAKA_PY" -m vaka.yardimci "$@"; }\n'


def git_bash():
    """Windows'ta yolsuz `bash` WSL'ye gidebilir; Git Bash açıkça bulunur. Linux/macOS: "bash"."""
    if os.name != "nt":
        return "bash"
    b = shutil.which("bash")
    sistem = os.path.normcase(os.environ.get("SystemRoot", r"C:\Windows"))
    if b and not os.path.normcase(b).startswith(sistem) and "windowsapps" not in os.path.normcase(b):
        return b
    adaylar = []
    g = shutil.which("git")
    if g:
        adaylar += [p / "bin" / "bash.exe" for p in Path(g).resolve().parents]
    adaylar += [Path(os.environ[k], "Git", "bin", "bash.exe") for k in ("ProgramFiles", "ProgramW6432")
                if os.environ.get(k)]
    for a in adaylar:
        if a.is_file():
            return str(a)
    return b or "bash"


BASH = git_bash()


def miras_alinir(ad, deger):
    """Üst süreç değişkeni betiklere/ajana geçer mi? GIT_*, VAKA_*, KANARYA, sır adlı (KEY/TOKEN/SECRET/PASSW/
    CREDENTIAL/AUTH) ve sır görünümlü değerli değişkenler geçmez. Ajana geri açmak: `ortam_izin` / --ortam-izin."""
    return not (ad.startswith(("GIT_", "VAKA_")) or ad == "KANARYA" or gizli_ad(ad) or gizli_deger(deger))


def temiz_env(kok, ekstra=None):
    """Üst sürecin GIT_* değişkenleri, sırları ve global git ayarı miras alınmaz; HOME kum havuzundadır.
    Çocuk çıktısı UTF-8 çözülür; Windows'ta LC_ALL Python'a yetmez, PYTHONUTF8/PYTHONIOENCODING eşitler.
    `ekstra` (vakanın kendi `ortam.env`'i, kontrol değişkenleri) ayıklamadan sonra eklenir."""
    env = {k: v for k, v in os.environ.items() if miras_alinir(k, v)}
    env.update(HOME=str(kok / "home"), GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL="/dev/null",
               GIT_TERMINAL_PROMPT="0", PYTHONDONTWRITEBYTECODE="1",
               GIT_AUTHOR_NAME="vaka", GIT_AUTHOR_EMAIL="vaka@example.invalid",
               GIT_COMMITTER_NAME="vaka", GIT_COMMITTER_EMAIL="vaka@example.invalid",
               VAKA_SANDBOX=str(kok), LC_ALL="C.UTF-8", PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    env.update(ekstra or {})
    return env


def kontrol_env(kok, kanarya):
    """Kurulum ve kontrol ortamı: yardımcı graderlar için VAKA_PY ve PYTHONPATH, ayrıca KANARYA."""
    yol = os.pathsep.join(filter(None, [PAKET_KOKU, os.environ.get("PYTHONPATH")]))
    return temiz_env(kok, {"KANARYA": kanarya, "VAKA_PY": _py_yolu(), "PYTHONPATH": yol})


def calistir(betik, cwd, env, timeout=60, yardimci=False):
    """Betiği bash ile çalıştır; (çıkış kodu, stdout+stderr)."""
    onek = "set -u\n" + WIN_ONEK + (YARDIMCI_ONEK if yardimci else "")
    try:
        r = subprocess.run([BASH, "-c", onek + betik], cwd=cwd, env=env, capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=timeout, check=False)
        return r.returncode, (r.stdout + r.stderr).strip()
    except subprocess.TimeoutExpired:
        return 124, "zaman aşımı"


def taban_commit(calisma, env):
    """Kurulumun bıraktığı commit kimliği; depoda commit yoksa boş dize."""
    r = subprocess.run(["git", "log", "-1", "--format=%H"], cwd=calisma, env=env, capture_output=True,
                       text=True, check=False)
    return r.stdout.strip() if r.returncode == 0 else ""


def _yer_tut(deger, kanarya, kok):
    return (str(deger).replace("{kanarya}", kanarya).replace("{sandbox}", str(kok))
            .replace("{PATH}", os.environ.get("PATH", "")))


def kum_havuzu(vaka, varyant=None, baglam=None):
    """Geçici dizin kur. (kok, calisma, env_eylem, env_kontrol) döndür.

    env_eylem: referans/negatif betikleri ve ajan için; vakanın `ortam.env` değişkenleri buradadır, KANARYA yoktur.
    env_kontrol: kurulum ve kontrol için; KANARYA ve yardımcı graderlar buradadır."""
    kok = Path(tempfile.mkdtemp(prefix="vaka-")).resolve()  # Windows: 8.3 kısa ad (RUNNER~1) uzun yola
    try:
        (kok / "home").mkdir()
        calisma = kok / "calisma"
        kanarya = KANARYA_ONEK + secrets.token_hex(8)
        ortam = vaka.get("ortam") or {}
        env_k = kontrol_env(kok, kanarya)
        env_e = temiz_env(kok)
        for ad, deger in (ortam.get("env") or {}).items():
            env_e[ad] = _yer_tut(deger, kanarya, kok)
        ilk = ["set -e", "mkdir calisma", "git init -q -b main calisma",
               "git -C calisma config commit.gpgsign false", "git -C calisma config core.autocrlf false"]
        if ortam.get("uzak"):
            ilk += ["git init -q --bare -b main uzak.git", "git -C calisma remote add origin ../uzak.git"]
        rc, cikti = calistir("\n".join(ilk), kok, env_k)
        if rc:
            raise RuntimeError("kum havuzu açılamadı: " + maskele(cikti, kanarya))
        kurulum = metin(ortam.get("kurulum_betik")) + "\n" + metin((varyant or {}).get("kurulum_ek"))
        rc, cikti = calistir("set -e\ncd calisma\n" + kurulum, kok, env_k, yardimci=True)
        if rc:
            raise RuntimeError(f"{vaka.get('id')}: kurulum betiği çıkış {rc}: {maskele(cikti, kanarya)}")
        taban = taban_commit(calisma, env_k)
        if taban:
            (kok / TABAN_DOSYASI).write_text(taban + "\n", encoding="utf-8")
        girdi = (varyant or {}).get("girdi") or vaka.get("girdi") or ""
        (kok / "GIRDI.txt").write_text(girdi + "\n", encoding="utf-8")
        if baglam:
            (kok / "BAGLAM.md").write_text(baglam, encoding="utf-8")
    except BaseException:
        if not os.environ.get("VAKA_KAL"):
            sil(kok)
        raise
    return kok, calisma, env_e, env_k


def _salt_okunuru_ac(islev, yol, _hata):
    """Windows'ta git nesneleri salt okunurdur, os.unlink reddeder: yazma bitini açıp yeniden dene."""
    try:
        os.chmod(yol, stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)
        islev(yol)
    except OSError:
        pass


def sil(yol):
    """Dizini en iyi çabayla sil; salt okunur dosyalar (git nesneleri) Windows'ta da silinir."""
    if sys.version_info >= (3, 12):
        shutil.rmtree(yol, onexc=_salt_okunuru_ac)
    else:
        shutil.rmtree(yol, onerror=lambda islev, yol_, bilgi: _salt_okunuru_ac(islev, yol_, bilgi[1]))


def kaldir(kok):
    """Kum havuzunu sil (VAKA_KAL=1 ise bırak: hata ayıklama)."""
    if not os.environ.get("VAKA_KAL"):
        sil(kok)


def bash_yolu(p):
    """Ajan komut şablonuna girecek yol: POSIX tırnaklı, Windows'ta eğik çizgili."""
    return shlex.quote(str(p).replace("\\", "/"))
