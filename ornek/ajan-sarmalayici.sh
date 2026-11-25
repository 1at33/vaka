#!/usr/bin/env bash
# Örnek ajan sarmalayıcısı. Kendi ajan CLI'ını AJAN_CLI ile ver; bu betik yalnız sözleşmeyi gösterir.
#
#   $1  görev metni dosyası      $2  bağlam dosyası ('' ise bağlamsız kol)
#
# Çalışma klasörü kum havuzunun calisma/ deposudur. Son stdout satırı JSON ise `maliyet_usd` bütçeye yazılır;
# ajanın maliyeti bildirilmezse her koşu `tahmini_kosu_usd` sayılır.
set -euo pipefail
girdi_dosyasi=$1
baglam_dosyasi=${2:-}
: "${AJAN_CLI:?AJAN_CLI ortam değişkeni ajan komutunu vermeli (ör. --ajan-env AJAN_CLI=...)}"

istem=$(cat "$girdi_dosyasi")
if [ -n "$baglam_dosyasi" ]; then
  istem="$(cat "$baglam_dosyasi")"$'\n\n'"$istem"
fi

# Ajanın kendi çıktısı stderr'e gitsin; stdout'un son satırı JSON özet olsun.
$AJAN_CLI "$istem" >&2
echo '{"maliyet_usd": null}'
