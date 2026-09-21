"""app.py — interface locale de test du Module 1 (bulletins et alertes).

Lancer :  streamlit run app.py
Ouvre une page dans le navigateur (http://localhost:8501). Réservé aux tests :
la production passera par le backend.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def _load_env(path: Path) -> None:
    # Doit s'exécuter AVANT l'import de moore_client, qui lit os.environ à l'import.
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


_load_env(Path(__file__).with_name(".env"))

import streamlit as st  # noqa: E402

from alert_parser import parse_alert_text  # noqa: E402
from bulletin_parser import parse_bulletin  # noqa: E402
from generate_alert_all import generate_alert_all  # noqa: E402
from generate_bulletin_all import generate_bulletin_all  # noqa: E402

LANGS = {
    "fr": ("Français", "audio/mpeg"),
    "en": ("English", "audio/mpeg"),
    "mos": ("Mooré", "audio/wav"),
}
REQUIRED_ENV = ["CITADEL_API_EMAIL", "CITADEL_API_PASSWORD", "MOORE_API_BASE_URL", "MOORE_API_TOKEN"]

st.set_page_config(page_title="ANAM Module 1 — tests", page_icon="🌦️", layout="wide")
st.title("Module 1 — test bulletins et alertes")
st.caption("Génère l'audio et la vidéo en français, anglais et mooré. Interface de test uniquement.")

missing = [k for k in REQUIRED_ENV if not os.environ.get(k)]
if missing:
    st.error("Variables manquantes dans .env : " + ", ".join(missing))


def _read_results(result: dict, stem: str) -> dict:
    """Charge les fichiers produits en mémoire (ils survivent ainsi aux rechargements de la page)."""
    out = {"stem": stem, "langs": {}}
    for lang in LANGS:
        audio, video = Path(result[f"audio_{lang}"]), Path(result[f"video_{lang}"])
        out["langs"][lang] = {
            "text": result[f"text_{lang}"],
            "audio": audio.read_bytes(), "audio_name": audio.name,
            "video": video.read_bytes(), "video_name": video.name,
        }
    return out


def _show_results(res: dict, key: str) -> None:
    st.subheader("Résultats")
    cols = st.columns(len(LANGS))
    for col, (lang, (label, mime)) in zip(cols, LANGS.items()):
        data = res["langs"][lang]
        with col:
            st.markdown(f"**{label}**")
            st.video(data["video"], format="video/mp4")
            st.audio(data["audio"], format=mime)
            d1, d2 = st.columns(2)
            d1.download_button("Vidéo (mp4)", data["video"], data["video_name"], "video/mp4",
                               key=f"{key}_v_{lang}", width="stretch")
            d2.download_button("Audio", data["audio"], data["audio_name"], mime,
                               key=f"{key}_a_{lang}", width="stretch")
            with st.expander("Texte lu"):
                st.write(data["text"])


@st.cache_data(show_spinner=False)
def _preview_bulletin(name: str, data: bytes) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / name
        path.write_bytes(data)
        b = parse_bulletin(path)
    return {"date": b.date_text, "observed": b.observed, "forecast": b.forecast,
            "advice_intro": b.advice_intro, "advice": b.advice}


tab_bulletin, tab_alert = st.tabs(["Bulletin (PDF)", "Alerte (image + texte)"])

# ---------------------------------------------------------------- Bulletin
with tab_bulletin:
    pdf = st.file_uploader("Bulletin PDF", type="pdf", key="pdf")
    if pdf:
        with st.expander("Texte reconnu dans le PDF (aperçu, sans traduction)"):
            try:
                p = _preview_bulletin(pdf.name, pdf.getvalue())
                st.write("**Date :**", p["date"])
                st.write("**Temps observé :**", p["observed"])
                st.write("**Prévisions :**", p["forecast"])
                if p["advice"]:
                    st.write("**Avis et conseils :**", p["advice_intro"])
                    for item in p["advice"]:
                        st.write("-", item)
                else:
                    st.write("**Avis et conseils :** (absents)")
            except Exception as exc:
                st.warning(f"Lecture du PDF impossible : {exc}")

        if st.button("Générer audios et vidéos", type="primary", key="go_bulletin"):
            try:
                with st.spinner("Traduction, synthèse vocale et montage vidéo en cours (1 à 3 minutes)…"):
                    with tempfile.TemporaryDirectory() as tmp:
                        src = Path(tmp) / pdf.name
                        src.write_bytes(pdf.getvalue())
                        out_dir = Path(tmp) / "out"
                        result = generate_bulletin_all(str(src), str(out_dir))
                        st.session_state["bulletin_res"] = _read_results(result, src.stem)
            except Exception as exc:
                st.session_state.pop("bulletin_res", None)
                st.error(f"Échec de la génération : {exc}")
                st.info("Les services CITADEL sont parfois instables : réessaie dans un instant.")

    if "bulletin_res" in st.session_state:
        _show_results(st.session_state["bulletin_res"], "bulletin")

# ------------------------------------------------------------------ Alerte
with tab_alert:
    left, right = st.columns([1, 2])
    with left:
        image = st.file_uploader("Image de l'alerte", type=["jpg", "jpeg", "png"], key="img")
        if image:
            st.image(image.getvalue(), width="stretch")
    with right:
        text = st.text_area("Texte de l'alerte (coller le message WhatsApp tel quel)", height=320, key="alert_text")

    if text.strip():
        with st.expander("Texte reconnu (aperçu, sans traduction)"):
            a = parse_alert_text(text)
            st.write("**Date :**", a.date_text)
            st.write("**Situation :**", a.situation)
            st.write("**Évolution :**", a.evolution)
            if a.has_risques:
                st.write("**Risques :**")
                for r in a.risques:
                    st.write("-", r)
            st.write("**Conseils :**", a.conseils_intro or "")
            for c in a.conseils:
                st.write("-", c)

    if st.button("Générer audios et vidéos", type="primary", key="go_alert", disabled=not (image and text.strip())):
        try:
            with st.spinner("Traduction, synthèse vocale et montage vidéo en cours (1 à 2 minutes)…"):
                with tempfile.TemporaryDirectory() as tmp:
                    img_path = Path(tmp) / image.name
                    img_path.write_bytes(image.getvalue())
                    txt_path = Path(tmp) / "alerte.txt"
                    txt_path.write_text(text, encoding="utf-8")
                    result = generate_alert_all(str(img_path), str(txt_path), str(Path(tmp) / "out"))
                    st.session_state["alert_res"] = _read_results(result, img_path.stem)
        except Exception as exc:
            st.session_state.pop("alert_res", None)
            st.error(f"Échec de la génération : {exc}")
            st.info("Les services CITADEL sont parfois instables : réessaie dans un instant.")

    if "alert_res" in st.session_state:
        _show_results(st.session_state["alert_res"], "alert")
