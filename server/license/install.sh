#!/bin/bash
# تركيب خدمة تراخيص Starbond على سيرفر RouterX (نفس الـ VPS، جنب Gerd بدون ما يلمسه)
#   curl -fsSL https://raw.githubusercontent.com/mmlktahmd4-cmd/starbond-updates/main/server/license/install.sh | sudo bash
set -eu
main() {
SRC="https://raw.githubusercontent.com/mmlktahmd4-cmd/starbond-updates/main/server/license"
DIR=/opt/starbond-license
NGINX_DIR=${NGINX_DIR:-/opt/gerd/nginx}
NGINX_CT=${NGINX_CT:-gerd-nginx}

echo "== 1) الملفات بـ $DIR"
mkdir -p "$DIR/data"
for f in app.py admin.html Dockerfile docker-compose.yml nginx-location.conf; do
	curl -fsSL "$SRC/$f" -o "$DIR/$f"
done

if [ ! -f "$DIR/.env" ]; then
	PW=$(od -An -N15 -tx1 /dev/urandom | tr -d ' \n')
	printf 'ADMIN_PASSWORD=%s\nTRIAL_DAYS=3\n' "$PW" > "$DIR/.env"
	chmod 600 "$DIR/.env"
	NEWPW=$PW
fi

echo "== 2) الحاوية starbond-lic"
docker network inspect gerd_gerd_net >/dev/null 2>&1 || { echo "✗ شبكة gerd_gerd_net مش موجودة — تأكد إن Gerd شغّال"; exit 1; }
cd "$DIR" && docker compose up -d --build
sleep 2
docker exec "$NGINX_CT" wget -qO- http://starbond-lic:8010/health >/dev/null 2>&1 \
	|| docker exec "$NGINX_CT" curl -fsS http://starbond-lic:8010/health >/dev/null 2>&1 \
	|| echo "⚠ nginx لسا ما شاف الخدمة (ممكن تحتاج ثواني)"

echo "== 3) nginx: /starbond-lic/"
if grep -rqs "location /starbond-lic/" "$NGINX_DIR"; then
	echo "• البلوك موجود أصلاً"
else
	CONF=$(grep -rlsE "server_name[^;]*routrx\.com" "$NGINX_DIR" | xargs -r grep -lE "listen[^;]*443" | head -n 1 || true)
	if [ -n "$CONF" ] && [ "$(grep -cE 'listen[^;]*443' "$CONF")" = 1 ]; then
		cp -a "$CONF" "$CONF.bak-starbond"
		# بعد سطر server_name تبع routrx.com بالبلوك اللي فيه 443
		awk -v blk="$(sed 's/^/    /' "$DIR/nginx-location.conf" | grep -v '^    #')" '
			/listen[^;]*443/ { in443=1 }
			{ print }
			in443 && !done && /server_name[^;]*routrx\.com/ { print blk; done=1 }' "$CONF.bak-starbond" > "$CONF"
		if docker exec "$NGINX_CT" nginx -t >/dev/null 2>&1; then
			docker exec "$NGINX_CT" nginx -s reload
			echo "✓ انضاف بـ $CONF (نسخة احتياطية: $CONF.bak-starbond)"
		else
			mv -f "$CONF.bak-starbond" "$CONF"
			echo "✗ nginx -t فشل — رجّعت الملف متل ما كان. ضيف البلوك يدوي من $DIR/nginx-location.conf"
		fi
	else
		echo "⚠ ما قدرت لاقي ملف nginx تبع routrx.com بشكل أكيد بـ $NGINX_DIR"
		echo "  ضيف محتوى $DIR/nginx-location.conf جوّا server { ... 443 ... routrx.com } وبعدين:"
		echo "  docker exec $NGINX_CT nginx -t && docker exec $NGINX_CT nginx -s reload"
	fi
fi

echo
echo "== جاهز"
echo "  فحص:  curl -s https://routrx.com/starbond-lic/health"
echo "  اللوحة: https://routrx.com/starbond-lic/admin"
if [ -n "${NEWPW:-}" ]; then
	echo "  اسم المستخدم: أي شي (مثلاً admin)"
	echo "  كلمة السر:   $NEWPW     ← احفظها هلق (موجودة كمان بـ $DIR/.env)"
fi
echo "  نسخ احتياطي للتراخيص: $DIR/data/licenses.db"
}
main "$@" </dev/null
