"""Interface de test de l'API ANAM (Streamlit) : inscription, connexion et 2FA, profil, rôles, administration,
bulletins, alertes, avis, carte, diffusion, back-office et exploration de la base.

Elle appelle l'API exactement comme le ferait une application : tout ce qui marche ici marchera pour les
développeurs front-end. Lancer l'API d'abord (uvicorn), puis :  streamlit run testui/app.py
"""

from __future__ import annotations

import json
import time
from datetime import datetime

import pyotp
import requests
import streamlit as st

st.set_page_config(page_title="ANAM - test de l'API", page_icon="🌦️", layout="wide")

LEVEL_ICON = {"vert": "🟩 vert", "jaune": "🟨 jaune", "orange": "🟧 orange", "rouge": "🟥 rouge"}
LANGS = {"fr": "Français", "en": "English", "mos": "Mooré"}
ss = st.session_state
ss.setdefault("token", None)
ss.setdefault("refresh", None)
ss.setdefault("me", None)
ss.setdefault("totp", {})  # secrets 2FA créés pendant les tests : {identifiant: secret}

BASE = st.sidebar.text_input("Adresse de l'API", "http://localhost:8000").rstrip("/")


# ============================================================== accès à l'API
def _refresh() -> bool:
    if not ss.refresh:
        return False
    r = requests.post(f"{BASE}/auth/refresh", json={"refresh_token": ss.refresh}, timeout=30)
    if r.ok:
        ss.token, ss.refresh = r.json()["access_token"], r.json()["refresh_token"]
    return r.ok


def api(method: str, path: str, **kw) -> requests.Response:
    for attempt in (1, 2):
        headers = dict(kw.pop("headers", {}))
        if ss.token:
            headers["Authorization"] = f"Bearer {ss.token}"
        try:
            r = requests.request(method, BASE + path, headers=headers, timeout=180, **kw)
        except requests.ConnectionError:
            st.error(f"API injoignable sur {BASE}. Lancez-la : `uvicorn app.main:app --reload` (dossier backend).")
            st.stop()
        if r.status_code == 401 and attempt == 1 and ss.refresh and _refresh():
            continue
        return r
    return r


def detail(r: requests.Response) -> str:
    try:
        d = r.json().get("detail", r.text)
    except Exception:  # noqa: BLE001
        return r.text[:300]
    return json.dumps(d, ensure_ascii=False) if not isinstance(d, str) else d


def result(r: requests.Response, ok_message: str | None = None):
    """Affiche le résultat d'un appel (succès ou erreur) et renvoie le JSON s'il y en a un."""
    if r.ok:
        if ok_message:
            st.success(ok_message)
        try:
            return r.json()
        except Exception:  # noqa: BLE001
            return None
    st.error(f"{r.status_code} - {detail(r)}")
    return None


def fetch_bytes(url: str) -> bytes | None:
    r = api("GET", url if url.startswith("/") else url.replace(BASE, ""))
    return r.content if r.ok else None


def has(perm: str) -> bool:
    return bool(ss.me) and perm in ss.me.get("_permissions", [])


def load_me():
    r = api("GET", "/me")
    if not r.ok:
        ss.me = None
        return
    me = r.json()
    roles = api("GET", "/roles").json()
    me["_permissions"] = next((x["permissions"] for x in roles["roles"] if x["role"] == me["role"]), [])
    ss.me = me


def wait_media(path: str, label: str, timeout: int = 420):
    """Attend la fin de la génération des audios et vidéos (interroge le contenu toutes les 3 s)."""
    with st.status(label, expanded=True) as box:
        t0 = time.time()
        while time.time() - t0 < timeout:
            r = api("GET", path)
            if not r.ok:
                box.update(label=f"Erreur {r.status_code}", state="error")
                return None
            d = r.json()
            if d["media"]["status"] != "processing":
                ok = d["media"]["status"] == "ready"
                box.update(label="Médias prêts" if ok else f"Échec : {d['media']['error']}", state="complete" if ok else "error")
                return d
            box.write(f"En cours… {int(time.time() - t0)} s")
            time.sleep(3)
        box.update(label="Délai dépassé", state="error")
    return None


def media_players(media: dict, key: str):
    files = media.get("files") or {}
    if not files:
        st.caption(f"Médias : {media.get('status')}")
        return
    cols = st.columns(3)
    for col, lang in zip(cols, ["fr", "en", "mos"]):
        f = files.get(lang)
        if not f:
            continue
        with col:
            st.markdown(f"**{LANGS[lang]}**")
            video = fetch_bytes(f["video"]) if f.get("video") else None
            if video:
                st.video(video, format="video/mp4")
            audio = fetch_bytes(f["audio"]) if f.get("audio") else None
            if audio:
                st.audio(audio, format="audio/wav" if f["audio"].endswith(".wav") else "audio/mpeg")


# ============================================================== pages
def page_auth():
    st.header("Inscription et connexion")
    left, right = st.columns(2)

    with left:
        st.subheader("Inscription")
        method = st.radio("Méthode", ["phone", "email", "local"], horizontal=True,
                          format_func={"phone": "Téléphone (SMS)", "email": "E-mail", "local": "Compte local"}.get)
        body = {"method": method}
        if method == "phone":
            body["phone"] = st.text_input("Téléphone", "70123456", help="8 chiffres burkinabè ou format international")
        elif method == "email":
            body["email"] = st.text_input("E-mail", "test@example.com")
        else:
            body["username"] = st.text_input("Identifiant", "agent_test")
        body["password"] = st.text_input("Mot de passe (8 caractères min.)", "MotDePasse1", type="password", key="reg_pw")
        commune = st.selectbox("Commune", [""] + ["Kaya", "Ziniaré", "Zitenga", "Absouya", "Korsimoro"])
        body["language"] = st.selectbox("Langue", list(LANGS), format_func=LANGS.get)
        if commune:
            body["commune"] = commune
        if st.button("S'inscrire", type="primary"):
            data = result(api("POST", "/auth/register", json=body))
            if data:
                st.info(data["message"])
                ss["last_register"] = body.get("phone") or body.get("email")

        st.markdown("**Validation du code**")
        ident = st.text_input("Numéro ou e-mail", ss.get("last_register", ""), key="verify_ident")
        code = st.text_input("Code à 6 chiffres", key="verify_code")
        c1, c2, c3 = st.columns(3)
        if c1.button("Récupérer le code (mode test)"):
            d = result(api("GET", "/dev/verification-code", params={"identifier": ident}))
            if d:
                st.code(d["code"])
        if c2.button("Valider"):
            result(api("POST", "/auth/verify", json={"identifier": ident, "code": code}), "Compte activé.")
        if c3.button("Renvoyer un code"):
            result(api("POST", "/auth/resend-code", json={"identifier": ident}))

    with right:
        st.subheader("Connexion")
        if ss.me:
            me = ss.me
            st.success(f"Connecté : {me.get('full_name') or me.get('email') or me.get('phone') or me.get('username')}")
            st.write({k: me[k] for k in ("role", "status", "commune", "language", "notification_channels", "totp_enabled")})
            c1, c2 = st.columns(2)
            if c1.button("Déconnexion"):
                api("POST", "/auth/logout", json={"refresh_token": ss.refresh})
                ss.token = ss.refresh = ss.me = None
                st.rerun()
            if c2.button("Déconnexion de tous les appareils"):
                api("POST", "/auth/logout-all")
                ss.token = ss.refresh = ss.me = None
                st.rerun()
            return
        identifier = st.text_input("Identifiant (téléphone, e-mail ou identifiant local)", key="login_id")
        password = st.text_input("Mot de passe", type="password", key="login_pw")
        if st.button("Se connecter", type="primary"):
            r = api("POST", "/auth/login", json={"identifier": identifier, "password": password})
            data = result(r)
            if data:
                ss.pending = {"identifier": identifier, **data}
                if data.get("tokens"):
                    _finish_login(data["tokens"])
        pending = ss.get("pending")
        if pending and not ss.me:
            if pending.get("requires_2fa"):
                st.warning("Ce compte est protégé par la 2FA.")
                secret = ss.totp.get(pending["identifier"])
                if secret:
                    code = st.text_input("Code 2FA", value=pyotp.TOTP(secret).now(), key="c2fa")
                    st.caption("Code pré-rempli avec le secret conservé lors de la configuration de test.")
                    if st.button("Valider la 2FA"):
                        data = result(api("POST", "/auth/2fa/verify", json={"challenge_token": pending["challenge_token"], "code": code}))
                        if data:
                            _finish_login(data)
                else:
                    st.info("Secret 2FA inconnu de cette session (perdu à la fermeture de la page, ou configuré "
                            "ailleurs) : impossible de calculer le code sans une vraie application d'authentification.")
                    if st.button("Réinitialiser la 2FA de ce compte (mode test uniquement)", type="primary"):
                        d = result(api("POST", "/dev/reset-2fa", params={"identifier": pending["identifier"]}))
                        if d:
                            st.success(d["message"])
                            ss.pending = None
                            st.rerun()
            elif pending.get("requires_2fa_setup"):
                st.warning("Ce rôle exige la 2FA : configuration à faire.")
                hdr = {"Authorization": f"Bearer {pending['setup_token']}"}
                if st.button("Générer le secret 2FA"):
                    d = result(api("POST", "/auth/2fa/setup", headers=hdr))
                    if d:
                        ss.totp[pending["identifier"]] = d["secret"]
                        ss.setup_uri = d["otpauth_uri"]
                secret = ss.totp.get(pending["identifier"])
                if secret:
                    st.code(secret)
                    st.caption(f"URI pour un QR code : {ss.get('setup_uri')}")
                    st.caption("En vrai, l'utilisateur le scanne avec une application d'authentification. "
                               "Ici le code est calculé pour vous.")
                    code = st.text_input("Code 2FA", pyotp.TOTP(secret).now(), key="c2fa_setup")
                    if st.button("Activer la 2FA et se connecter"):
                        data = result(api("POST", "/auth/2fa/enable", headers=hdr, json={"code": code}))
                        if data:
                            _finish_login(data)


def _finish_login(tokens: dict):
    ss.token, ss.refresh = tokens["access_token"], tokens["refresh_token"]
    ss.pending = None
    load_me()
    if ss.me and tokens.get("must_change_password"):
        st.warning("Ce compte doit changer son mot de passe (onglet Profil).")
    st.rerun()


def need_login() -> bool:
    if not ss.me:
        st.info("Connectez-vous d'abord (page « Inscription et connexion »).")
        return True
    return False


def page_profile():
    st.header("Profil")
    if need_login():
        return
    load_me()
    me = ss.me
    st.json({k: v for k, v in me.items() if not k.startswith("_")}, expanded=False)
    with st.form("profile"):
        communes = ["", "Kaya", "Ziniaré", "Zitenga", "Absouya", "Korsimoro"]
        commune = st.selectbox("Commune", communes, index=communes.index(me["commune"]) if me["commune"] in communes else 0)
        language = st.selectbox("Langue préférée", list(LANGS), index=list(LANGS).index(me["language"]), format_func=LANGS.get)
        channels = st.multiselect("Réception des alertes", ["push", "sms", "email"], default=me["notification_channels"])
        if st.form_submit_button("Enregistrer", type="primary"):
            body = {"language": language, "notification_channels": channels}
            if commune:
                body["commune"] = commune
            if result(api("PATCH", "/me", json=body), "Profil mis à jour."):
                load_me()
    with st.expander("Changer le mot de passe"):
        cur = st.text_input("Mot de passe actuel", type="password")
        new = st.text_input("Nouveau mot de passe", type="password")
        if st.button("Changer"):
            if result(api("POST", "/me/password", json={"current_password": cur, "new_password": new}), "Modifié. Reconnectez-vous."):
                ss.token = ss.refresh = ss.me = None
                st.rerun()
    with st.expander("Notifications push : enregistrer un appareil (faux jeton)"):
        tok = st.text_input("Jeton FCM de test", f"fcm-test-{int(time.time())}")
        if st.button("Enregistrer l'appareil"):
            result(api("POST", "/me/devices", json={"token": tok, "platform": "android"}), "Appareil enregistré.")


def page_roles():
    st.header("Rôles et permissions")
    data = api("GET", "/roles").json()
    perms = data["permissions"]
    rows = [{"Rôle": r["label"], "2FA": "oui" if r["requires_2fa"] else "", **{p: ("✔" if p in r["permissions"] else "") for p in perms}}
            for r in data["roles"]]
    st.dataframe(rows, width="stretch", hide_index=True)
    st.caption("Signification des permissions : " + " · ".join(f"**{k}** = {v}" for k, v in perms.items()))
    st.subheader("Ce que MON compte peut faire")
    if need_login():
        return
    st.write(f"Rôle : **{ss.me['role']}**")
    probes = [("GET", "/admin/users", "users:read"), ("GET", "/admin/stats/communes", "stats:read"),
              ("GET", "/backoffice/dashboard", "stats:read"), ("GET", "/backoffice/settings", "config:manage"),
              ("GET", "/alerts?status=draft", "content:manage"), ("GET", "/bulletins?status=draft", "content:manage")]
    if st.button("Tester mes accès sur l'API"):
        table = []
        for method, path, perm in probes:
            r = api(method, path)
            table.append({"Route": f"{method} {path}", "Permission requise": perm, "Résultat": "✅ autorisé" if r.ok else f"⛔ {r.status_code}"})
        st.dataframe(table, width="stretch", hide_index=True)


def page_admin():
    st.header("Administration des comptes")
    if need_login():
        return
    if not has("users:read"):
        st.warning("Votre rôle n'a pas la permission users:read.")
        return
    c1, c2, c3, c4 = st.columns(4)
    status = c1.selectbox("Statut", ["", "pending", "active", "disabled"])
    role = c2.selectbox("Rôle", ["", "grand_public", "observateur", "responsable_communal", "agent_anam", "administrateur"])
    commune = c3.selectbox("Commune", ["", "Kaya", "Ziniaré", "Zitenga", "Absouya", "Korsimoro"])
    q = c4.text_input("Recherche")
    params = {k: v for k, v in {"status": status, "role": role, "commune": commune, "q": q, "limit": 200}.items() if v}
    data = result(api("GET", "/admin/users", params=params))
    if data:
        st.caption(f"{data['total']} compte(s)")
        st.dataframe([{k: u[k] for k in ("id", "email", "phone", "username", "role", "status", "commune", "language", "totp_enabled")}
                      for u in data["items"]], width="stretch", hide_index=True)
        users = {f"{u['email'] or u['phone'] or u['username']} ({u['role']}, {u['status']})": u["id"] for u in data["items"]}
    else:
        users = {}
    st.subheader("Actions sur un compte")
    if users and has("users:manage"):
        target = users[st.selectbox("Compte", list(users))]
        a1, a2, a3, a4 = st.columns(4)
        if a1.button("Activer"):
            result(api("POST", f"/admin/users/{target}/activate"), "Activé.")
        if a2.button("Désactiver"):
            result(api("POST", f"/admin/users/{target}/disable"), "Désactivé (sessions fermées).")
        if a3.button("Réinitialiser la 2FA"):
            result(api("POST", f"/admin/users/{target}/reset-2fa"), "2FA réinitialisée.")
        new_role = a4.selectbox("Nouveau rôle", ["grand_public", "observateur", "responsable_communal", "agent_anam", "administrateur"])
        if a4.button("Attribuer ce rôle"):
            result(api("PATCH", f"/admin/users/{target}/role", json={"role": new_role}), "Rôle modifié.")
    with st.expander("Créer un compte interne (agent, administrateur, responsable…)"):
        with st.form("internal"):
            ident = st.text_input("E-mail (ou laisser vide et remplir l'identifiant)")
            username = st.text_input("Identifiant local")
            pw = st.text_input("Mot de passe initial", "MdpInitial123")
            role = st.selectbox("Rôle", ["agent_anam", "administrateur", "responsable_communal", "observateur", "grand_public"])
            name = st.text_input("Nom")
            if st.form_submit_button("Créer"):
                body = {"password": pw, "role": role, "full_name": name or None}
                if ident:
                    body["email"] = ident
                if username:
                    body["username"] = username
                result(api("POST", "/admin/users", json=body), "Compte créé (mot de passe à changer à la 1re connexion).")
    if has("stats:read"):
        st.subheader("Répartition par commune")
        d = api("GET", "/admin/stats/communes")
        if d.ok:
            st.bar_chart({x["commune"]: x["users"] for x in d.json()})


def _zones():
    return {z["name"]: z["id"] for z in api("GET", "/zones").json()}


def page_bulletins():
    st.header("Bulletins")
    tab_list, tab_import = st.tabs(["Liste et détail", "Importer un PDF"])
    with tab_import:
        if need_login():
            return
        pdf = st.file_uploader("Bulletin PDF de l'ANAM", type="pdf")
        if pdf and st.button("Importer", type="primary"):
            d = result(api("POST", "/bulletins", files={"file": (pdf.name, pdf.getvalue(), "application/pdf")}), "Importé : génération en cours.")
            if d:
                ss.bulletin_id = d["id"]
                wait_media(f"/bulletins/{d['id']}", "Génération des audios et vidéos (1 à 3 min)…")
    with tab_list:
        scope = st.selectbox("Afficher", ["published", "draft", "archived", "all"], format_func={"published": "Publiés", "draft": "Brouillons", "archived": "Archivés", "all": "Tous"}.get)
        data = result(api("GET", "/bulletins", params={"status": scope, "limit": 50}))
        if not data or not data["items"]:
            st.info("Aucun bulletin.")
            return
        labels = {f"{b['title']} [{b['status']}]": b for b in data["items"]}
        b = labels[st.selectbox("Bulletin", list(labels), key="bsel")]
        st.write(f"**Statut** : {b['status']} · **Médias** : {b['media']['status']}" + (f" ({b['media']['error']})" if b["media"]["error"] else ""))
        cols = st.columns(5)
        if has("content:publish"):
            if cols[0].button("Publier + diffuser"):
                result(api("POST", f"/bulletins/{b['id']}/publish"), "Publié.")
            if cols[1].button("Publier sans diffuser"):
                result(api("POST", f"/bulletins/{b['id']}/publish", params={"broadcast": False}), "Publié.")
            if cols[2].button("Dépublier"):
                result(api("POST", f"/bulletins/{b['id']}/unpublish"), "Archivé.")
            if cols[3].button("Rediffuser"):
                result(api("POST", f"/bulletins/{b['id']}/broadcast"), "Diffusion lancée (voir « Diffusion et back-office »).")
        if has("content:manage") and cols[4].button("Régénérer les médias"):
            api("POST", f"/bulletins/{b['id']}/media")
            wait_media(f"/bulletins/{b['id']}", "Régénération…")
        if b["parsed"]:
            with st.expander("Texte extrait du PDF"):
                st.json(b["parsed"])
        media_players(b["media"], b["id"])
        if b["texts"]:
            with st.expander("Texte lu, par langue (à relire)"):
                for lang, text in b["texts"].items():
                    st.markdown(f"**{LANGS[lang]}**")
                    st.write(text)
        if has("content:manage"):
            kit = api("GET", f"/bulletins/{b['id']}/share-kit")
            if kit.ok:
                with st.expander("Texte WhatsApp prêt à copier"):
                    lang = st.radio("Langue", list(LANGS), format_func=LANGS.get, horizontal=True, key=f"kitlang{b['id']}")
                    st.code(kit.json()["text"][lang], language=None)


def page_alerts():
    st.header("Alertes")
    tab_list, tab_new = st.tabs(["Liste et détail", "Nouvelle alerte"])
    with tab_new:
        if need_login():
            return
        types = {t["label_fr"]: t["id"] for t in api("GET", "/alert-types").json()}
        zones = _zones()
        c1, c2 = st.columns(2)
        with c1:
            t = st.selectbox("Type d'alerte", list(types))
            level = st.selectbox("Niveau", ["jaune", "orange", "rouge"])
            zsel = st.multiselect("Zones concernées (vide = tout le territoire)", list(zones))
            until = st.checkbox("Fixer la fin de validité (sinon : durée par défaut)")
            valid_until = None
            if until:
                d = st.date_input("Date de fin")
                h = st.time_input("Heure de fin (UTC)")
                valid_until = datetime.combine(d, h).isoformat()
            image = st.file_uploader("Image de l'alerte (radar, satellite…)", type=["jpg", "jpeg", "png"])
        with c2:
            raw = st.text_area("Texte de l'alerte (coller le message WhatsApp tel quel)", height=330, key="alert_raw")
        if raw.strip() and st.button("Voir comment le texte est découpé"):
            st.json(result(api("POST", "/alerts/preview", json={"raw_text": raw})))
        if st.button("Créer, générer les médias", type="primary", disabled=not (raw.strip() and image)):
            body = {"alert_type_id": types[t], "level": level, "raw_text": raw, "zone_ids": [zones[z] for z in zsel]}
            if valid_until:
                body["valid_until"] = valid_until
            d = result(api("POST", "/alerts", json=body))
            if d and result(api("PUT", f"/alerts/{d['id']}/image", files={"file": (image.name, image.getvalue(), "image/jpeg")})):
                if result(api("POST", f"/alerts/{d['id']}/media")):
                    wait_media(f"/alerts/{d['id']}", "Génération des audios et vidéos (1 à 3 min)…")
                    st.success("Alerte créée en brouillon : allez dans « Liste et détail » pour la publier.")
    with tab_list:
        scope = st.selectbox("Afficher", ["published", "draft", "cancelled", "all"], format_func={"published": "Publiées", "draft": "Brouillons", "cancelled": "Annulées", "all": "Toutes"}.get)
        data = result(api("GET", "/alerts", params={"status": scope, "limit": 50}))
        if not data or not data["items"]:
            st.info("Aucune alerte.")
            return
        labels = {f"{a['title']} · {', '.join(z['name'] for z in a['zones']) or 'national'} [{a['status']}]": a for a in data["items"]}
        a = labels[st.selectbox("Alerte", list(labels), key="asel")]
        st.write(f"**Niveau** {LEVEL_ICON[a['level']]} · **Statut** {a['status']} · **Active** {'oui' if a['is_active'] else 'non'} · "
                 f"**Validité** {a['valid_until']} · **Médias** {a['media']['status']}")
        cols = st.columns(5)
        if has("content:publish"):
            if cols[0].button("Publier + diffuser", key="apub"):
                result(api("POST", f"/alerts/{a['id']}/publish"), "Publiée.")
            if cols[1].button("Publier sans diffuser", key="apub2"):
                result(api("POST", f"/alerts/{a['id']}/publish", params={"broadcast": False}), "Publiée.")
            if cols[2].button("Annuler", key="acancel"):
                result(api("POST", f"/alerts/{a['id']}/cancel"), "Annulée.")
            if cols[3].button("Rediffuser", key="abc"):
                result(api("POST", f"/alerts/{a['id']}/broadcast"), "Diffusion lancée.")
        if has("content:manage") and cols[4].button("Supprimer", key="adel"):
            result(api("DELETE", f"/alerts/{a['id']}"), "Supprimée.")
        if a["image_url"]:
            img = fetch_bytes(a["image_url"])
            if img:
                st.image(img, width=420)
        media_players(a["media"], a["id"])
        with st.expander("Message de prévention associé"):
            for p in a["prevention"]:
                st.write("- " + p["text_fr"])
        if a["parsed"]:
            with st.expander("Texte reconnu"):
                st.json(a["parsed"])
        if a["texts"]:
            with st.expander("Texte lu, par langue (à relire)"):
                for lang, text in a["texts"].items():
                    st.markdown(f"**{LANGS[lang]}**")
                    st.write(text)
        if has("content:manage"):
            kit = api("GET", f"/alerts/{a['id']}/share-kit")
            if kit.ok:
                with st.expander("Texte WhatsApp prêt à copier (diffusion manuelle de secours)"):
                    lang = st.radio("Langue", list(LANGS), format_func=LANGS.get, horizontal=True, key=f"akit{a['id']}")
                    st.code(kit.json()["text"][lang], language=None)


def page_advisories():
    st.header("Avis et conseils / planification anticipée")
    tab_list, tab_new = st.tabs(["Liste", "Nouvel avis"])
    with tab_new:
        if need_login():
            return
        kind = st.selectbox("Type", ["conseil", "planification"], format_func={"conseil": "Avis et conseils", "planification": "Planification anticipée (saison)"}.get)
        title = st.text_input("Titre (français)")
        body = st.text_area("Texte (français)", height=150)
        if st.button("Créer le brouillon", type="primary", disabled=not (title and body)):
            result(api("POST", "/advisories", json={"kind": kind, "title_fr": title, "body_fr": body}), "Créé en brouillon.")
    with tab_list:
        scope = st.selectbox("Afficher", ["published", "draft", "all"], key="advscope")
        data = result(api("GET", "/advisories", params={"status": scope}))
        for adv in (data or {"items": []})["items"]:
            with st.container(border=True):
                st.markdown(f"**{adv['title_fr']}** — {adv['kind']} · {adv['status']}")
                st.write(adv["body_fr"])
                if adv["title_en"] or adv["title_mos"]:
                    st.caption(f"EN : {adv['title_en']} — MOS : {adv['title_mos']}")
                c = st.columns(4)
                if has("content:manage") and c[0].button("Traduire (EN + mooré)", key=f"tr{adv['id']}"):
                    result(api("POST", f"/advisories/{adv['id']}/translate", json={"langs": ["en", "mos"]}), "Traductions proposées : à relire.")
                if has("content:publish"):
                    if c[1].button("Publier", key=f"pub{adv['id']}"):
                        result(api("POST", f"/advisories/{adv['id']}/publish"), "Publié.")
                    if c[2].button("Retirer", key=f"wd{adv['id']}"):
                        result(api("POST", f"/advisories/{adv['id']}/withdraw"), "Retiré.")
                    if c[3].button("Diffuser", key=f"bc{adv['id']}"):
                        result(api("POST", f"/advisories/{adv['id']}/broadcast"), "Diffusion lancée.")


def page_map():
    st.header("Carte des alertes")
    data = result(api("GET", "/map/alerts"))
    if not data:
        return
    rows = [{"Zone": z["zone"]["name"], "Type": z["zone"]["kind"], "Niveau": LEVEL_ICON[z["level"]],
             "Alertes actives": ", ".join(a["title"] for a in z["alerts"]), "Latitude": z["zone"]["latitude"],
             "Longitude": z["zone"]["longitude"], "Contour": "oui" if z["zone"]["geometry"] else ""} for z in data["zones"]]
    st.dataframe(rows, width="stretch", hide_index=True)
    if data["national_alerts"]:
        st.warning("Alertes sur tout le territoire : " + ", ".join(a["title"] for a in data["national_alerts"]))
    pts = [{"lat": r["Latitude"], "lon": r["Longitude"]} for r in rows if r["Latitude"] is not None]
    if pts:
        st.map(pts)
    else:
        st.caption("Les coordonnées des zones ne sont pas encore renseignées (à charger depuis les fichiers de l'ANAM) : "
                   "la carte s'affichera ici dès qu'elles le seront.")
    st.subheader("Renseigner une zone")
    if has("config:manage"):
        zones = {z["zone"]["name"]: z for z in data["zones"]}
        z = zones[st.selectbox("Zone", list(zones))]["zone"]
        lat = st.number_input("Latitude", value=z["latitude"] or 12.0, format="%.4f")
        lon = st.number_input("Longitude", value=z["longitude"] or -1.5, format="%.4f")
        if st.button("Enregistrer les coordonnées"):
            result(api("PATCH", f"/zones/{z['id']}", json={"latitude": lat, "longitude": lon}), "Enregistré.")
    else:
        st.caption("Réservé aux administrateurs (permission config:manage).")


def page_backoffice():
    st.header("Diffusion et back-office")
    if need_login():
        return
    if not has("stats:read"):
        st.warning("Votre rôle n'a pas la permission stats:read.")
        return
    tab_dash, tab_bc, tab_settings, tab_sms = st.tabs(["Tableau de bord", "Diffusions", "Paramètres", "Pilote SMS"])
    with tab_dash:
        d = result(api("GET", "/backoffice/dashboard"))
        if d:
            c = st.columns(4)
            c[0].metric("Comptes", d["users"]["total"])
            c[1].metric("Bulletins publiés", d["content"]["bulletins_published"])
            c[2].metric("Alertes actives", d["content"]["alerts_active"])
            c[3].metric("Médias en échec", d["content"]["media_failed"])
            st.write("Comptes par statut", d["users"]["by_status"])
            st.write("Envois par canal", d["diffusion"]["deliveries_by_channel"])
            st.write("Usage sur 7 jours", d["usage_last_7_days"])
        st.markdown("**Simuler une consultation (événement d'usage)**")
        c1, c2 = st.columns(2)
        cid = c1.text_input("Identifiant du contenu", "test")
        kind = c2.selectbox("Type d'événement", ["view", "play_audio", "play_video", "share"])
        if st.button("Envoyer l'événement"):
            result(api("POST", "/events", json={"content_type": "bulletin", "content_id": cid, "kind": kind, "language": "fr"}), "Enregistré.")
    with tab_bc:
        data = result(api("GET", "/backoffice/broadcasts", params={"limit": 30}))
        items = (data or {"items": []})["items"]
        st.dataframe([{k: b[k] for k in ("created_at", "content_type", "trigger", "status", "target_count", "sent_count", "failed_count")} for b in items],
                     width="stretch", hide_index=True)
        if items:
            choice = st.selectbox("Détail d'une diffusion", [f"{b['created_at']} · {b['content_type']} · {b['status']}" for b in items])
            b = items[[f"{x['created_at']} · {x['content_type']} · {x['status']}" for x in items].index(choice)]
            det = result(api("GET", f"/backoffice/broadcasts/{b['id']}"))
            if det:
                st.write("Par canal :", det["by_channel"])
                st.dataframe(det["deliveries"], width="stretch", hide_index=True)
                st.caption("Statut « simulated » = envoi simulé (mode développement) : rien n'est réellement parti.")
    with tab_settings:
        if not has("config:manage"):
            st.info("Réservé aux administrateurs (permission config:manage).")
        else:
            settings = result(api("GET", "/backoffice/settings")) or {}
            key = st.selectbox("Paramètre", list(settings))
            new = st.text_area("Valeur (JSON)", json.dumps(settings.get(key), ensure_ascii=False, indent=2), height=200, key=f"set_{key}")
            if st.button("Enregistrer le paramètre"):
                try:
                    result(api("PUT", "/backoffice/settings", json={"values": {key: json.loads(new)}}), "Enregistré.")
                except json.JSONDecodeError as exc:
                    st.error(f"JSON invalide : {exc}")
    with tab_sms:
        st.json(result(api("GET", "/backoffice/sms-pilot")) or {})


def page_dev():
    st.header("Base de données et état du système")
    status = api("GET", "/dev/status")
    if not status.ok:
        st.info("Les outils de développement sont désactivés (ENV=prod).")
        return
    s = status.json()
    c = st.columns(4)
    c[0].metric("ffmpeg", "installé" if s["ffmpeg_installed"] else "ABSENT")
    c[1].metric("CITADEL traduction", "configuré" if s["citadel_translation_configured"] else "non configuré")
    c[2].metric("CITADEL voix mooré", "configuré" if s["citadel_speech_configured"] else "non configuré")
    c[3].metric("Environnement", s["env"])
    st.write("Canaux d'envoi actifs (console = simulation) :", s["backends"])
    st.caption(f"Base : {s['database']} · Stockage : {s['storage_dir']} · "
              f"Modèle de traduction FR→mooré : **{s['moore_model_type']}**")

    tab_out, tab_db = st.tabs(["Messages envoyés (simulés)", "Tables de la base"])
    with tab_out:
        st.caption("SMS, e-mails, notifications push et messages WhatsApp « envoyés » par le mode simulation.")
        if st.button("Actualiser", key="outbox_refresh"):
            st.rerun()
        st.dataframe(api("GET", "/dev/outbox", params={"limit": 50}).json(), width="stretch", hide_index=True)
    with tab_db:
        counts = api("GET", "/dev/db").json()
        st.dataframe([{"Table": t, "Lignes": n} for t, n in counts.items()], width="stretch", hide_index=True)
        table = st.selectbox("Voir le contenu d'une table", list(counts))
        rows = api("GET", f"/dev/db/{table}", params={"limit": 100}).json()
        st.caption("Mots de passe hachés, secrets 2FA, codes et jetons sont masqués.")
        st.dataframe(rows["rows"], width="stretch", hide_index=True)


PAGES = {
    "Inscription et connexion": page_auth,
    "Profil": page_profile,
    "Rôles et permissions": page_roles,
    "Administration des comptes": page_admin,
    "Bulletins": page_bulletins,
    "Alertes": page_alerts,
    "Avis et conseils": page_advisories,
    "Carte des alertes": page_map,
    "Diffusion et back-office": page_backoffice,
    "Base de données et état": page_dev,
}
choice = st.sidebar.radio("Page", list(PAGES))
if ss.me:
    st.sidebar.success(f"{ss.me.get('email') or ss.me.get('phone') or ss.me.get('username')}\n\nrôle : {ss.me['role']}")
else:
    st.sidebar.caption("Non connecté (visiteur anonyme)")
PAGES[choice]()
