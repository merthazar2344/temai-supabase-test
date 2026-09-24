import streamlit as st
from openai import OpenAI
from supabase import create_client, Client
from PIL import Image
import base64
import io
from datetime import datetime

# ================== SUPABASE ==================
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]  # publishable key

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ================== OPENAI ==================
api_key = None
if "OPENAI_API_KEY" in st.secrets:
    api_key = st.secrets["OPENAI_API_KEY"]
else:
    api_key = "BURAYA_KENDI_API_KEYINI_YAZ"

client = (api_key=api_key)
# ============================================

DEFAULT_TITLE = "Yeni Sohbet"

# ================== BELGE OKUMA (PDF / Word) ==================
def extract_pdf_text(file_obj):
    try:
        from pypdf import PdfReader
    except ImportError:
        from PyPDF2 import PdfReader
    reader = PdfReader(file_obj)
    text_parts = []
    for page in reader.pages:
        text_parts.append(page.extract_text() or "")
    return "\n".join(text_parts)


def extract_docx_text(file_obj):
    import docx
    document = docx.Document(file_obj)
    return "\n".join(p.text for p in document.paragraphs)


# ================== VERİTABANI YARDIMCI FONKSİYONLARI ==================
def db_list_chats(user_id):
    res = supabase.table("chats").select("*").eq("user_id", user_id).order("created_at").execute()
    return res.data


def db_create_chat(user_id, title=DEFAULT_TITLE):
    res = supabase.table("chats").insert({"user_id": user_id, "title": title}).execute()
    return res.data[0]


def db_rename_chat(chat_id, new_title):
    supabase.table("chats").update({"title": new_title}).eq("id", chat_id).execute()


def db_delete_chat(chat_id):
    supabase.table("messages").delete().eq("chat_id", chat_id).execute()
    supabase.table("chats").delete().eq("id", chat_id).execute()


def db_update_chat_fields(chat_id, fields: dict):
    supabase.table("chats").update(fields).eq("id", chat_id).execute()


def db_list_messages(chat_id):
    res = supabase.table("messages").select("*").eq("chat_id", chat_id).order("created_at").execute()
    return res.data


def db_add_message(chat_id, role, kind, content, feedback=None):
    supabase.table("messages").insert({
        "chat_id": chat_id, "role": role, "kind": kind, "content": content, "feedback": feedback
    }).execute()


def db_update_message_feedback(message_id, feedback):
    supabase.table("messages").update({"feedback": feedback}).eq("id", message_id).execute()


def format_ts(iso_str):
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.strftime("%H:%M")
    except Exception:
        return ""


st.set_page_config(page_title="Temai", page_icon="🧠", layout="wide")

# ----------------- CSS -----------------
st.markdown("""
<style>
.stApp {
    background: radial-gradient(circle at top left, #1a1a1a 0%, #0f0f0f 60%);
}
section[data-testid="stSidebar"] {
    background-color: #161616;
    border-right: 1px solid #2a2a2a;
}
h1 {
    font-weight: 700 !important;
    letter-spacing: -0.5px;
}
.stChatMessage {
    border-radius: 16px;
    padding: 4px 6px;
}
.temai-toolbar {
    background: #1b1b1b;
    border: 1px solid #2a2a2a;
    border-radius: 14px;
    padding: 12px 16px;
    margin-bottom: 14px;
}
.temai-timestamp {
    font-size: 11px;
    color: #8a8a8a;
    margin-top: -6px;
}
</style>
""", unsafe_allow_html=True)

# ================== "BENİ AÇIK TUT" - TARAYICI COOKIE'Sİ ==================
# Streamlit her sayfa yenilemesinde session_state'i sıfırlayabilir; kalıcı giriş
# için refresh_token'ı tarayıcı cookie'sinde saklıyoruz.
from streamlit_cookies_manager import EncryptedCookieManager

cookies = EncryptedCookieManager(
    prefix="temai/",
    password=st.secrets.get("COOKIES_PASSWORD", "temai-varsayilan-anahtar-bunu-degistir"),
)
if not cookies.ready():
    st.stop()

# 1) Bu oturumda (session_state) zaten giriş bilgisi varsa, supabase client'a bağla.
if st.session_state.get("access_token"):
    try:
        supabase.auth.set_session(
            st.session_state.access_token, st.session_state.refresh_token
        )
    except Exception:
        st.session_state.user = None
        st.session_state.access_token = None
        st.session_state.refresh_token = None

# 2) session_state boşsa (sayfa yenilendi/tarayıcı kapatılıp açıldı), "beni açık tut"
#    ile bırakılmış cookie var mı diye bak, varsa oturumu ondan geri yükle.
elif cookies.get("refresh_token"):
    try:
        res = supabase.auth.refresh_session(cookies.get("refresh_token"))
        st.session_state.user = res.user
        st.session_state.access_token = res.session.access_token
        st.session_state.refresh_token = res.session.refresh_token
        cookies["refresh_token"] = res.session.refresh_token  # Supabase yeni bir refresh_token verebilir
        cookies.save()
    except Exception:
        pass


def save_login_cookie(refresh_token):
    cookies["refresh_token"] = refresh_token
    cookies.save()


def clear_login_cookie():
    try:
        if "refresh_token" in cookies:
            del cookies["refresh_token"]
            cookies.save()
    except Exception:
        pass


def password_is_strong(pw):
    """En az 6 karakter, en az bir harf ve en az bir rakam içermeli."""
    if len(pw) < 6:
        return False, "Şifre en az 6 karakter olmalı."
    if not any(ch.isdigit() for ch in pw):
        return False, "Şifre en az bir rakam içermeli."
    if not any(ch.isalpha() for ch in pw):
        return False, "Şifre en az bir harf içermeli."
    return True, ""


# ================== GİRİŞ / KAYIT EKRANI ==================
if "user" not in st.session_state:
    st.session_state.user = None

if not st.session_state.user:
    st.title("🧠 Temai'ye Hoş Geldin")
    tab_login, tab_signup = st.tabs(["Giriş Yap", "Kayıt Ol"])

    with tab_login:
        login_email = st.text_input("E-posta", key="login_email")
        login_pw = st.text_input("Şifre", type="password", key="login_pw")
        keep_logged_in_login = st.checkbox("🔒 Beni açık tut", value=True, key="keep_login")
        if st.button("Giriş Yap", use_container_width=True):
            try:
                res = supabase.auth.sign_in_with_password(
                    {"email": login_email, "password": login_pw}
                )
                st.session_state.user = res.user
                st.session_state.access_token = res.session.access_token
                st.session_state.refresh_token = res.session.refresh_token
                if keep_logged_in_login:
                    save_login_cookie(res.session.refresh_token)
                st.rerun()
            except Exception as e:
                st.error(f"Giriş başarısız: {e}")

    with tab_signup:
        signup_email = st.text_input("E-posta", key="signup_email")
        signup_pw = st.text_input(
            "Şifre (en az 6 karakter, en az 1 harf ve 1 rakam)",
            type="password", key="signup_pw"
        )
        signup_pw2 = st.text_input("Şifreyi Tekrar Gir", type="password", key="signup_pw2")

        if st.button("Kayıt Ol", use_container_width=True):
            is_strong, strength_msg = password_is_strong(signup_pw)
            if not signup_email.strip():
                st.error("Lütfen bir e-posta adresi gir.")
            elif signup_pw != signup_pw2:
                st.error("Girdiğin iki şifre birbiriyle uyuşmuyor.")
            elif not is_strong:
                st.error(strength_msg)
            else:
                try:
                    res = supabase.auth.sign_up({"email": signup_email, "password": signup_pw})
                    if res.session:
                        # E-posta onayı kapalıysa Supabase burada direkt oturum döndürür,
                        # kullanıcı mail beklemeden içeri girer.
                        st.session_state.user = res.user
                        st.session_state.access_token = res.session.access_token
                        st.session_state.refresh_token = res.session.refresh_token
                        save_login_cookie(res.session.refresh_token)
                        st.rerun()
                    else:
                        st.success(
                            "Kayıt başarılı! E-postana gelen onay linkine tıkla, "
                            "sonra 'Giriş Yap' sekmesinden giriş yap."
                        )
                except Exception as e:
                    st.error(f"Kayıt başarısız: {e}")

    st.stop()  # Giriş yapılmadan uygulamanın geri kalanı hiç çalışmasın.

user = st.session_state.user
user_id = user.id


def db_get_profile(user_id):
    res = supabase.table("profiles").select("*").eq("id", user_id).execute()
    return res.data[0] if res.data else {"id": user_id, "email": user.email, "display_name": None}


def db_update_profile(user_id, fields: dict):
    supabase.table("profiles").update(fields).eq("id", user_id).execute()


profile = db_get_profile(user_id)
display_name = profile.get("display_name") or user.email.split("@")[0]

# ----------------- SIDEBAR: KULLANICI + SOHBET LİSTESİ -----------------
st.sidebar.title("💬 Sohbetler")
st.sidebar.caption(f"👤 {display_name}")

with st.sidebar.expander("⚙️ Profil / Hesap Ayarları"):
    st.caption(f"E-posta: {user.email}")

    # --- İsim değiştir ---
    new_display_name = st.text_input("Görünen isim", value=display_name, key="profile_name")
    if st.button("İsmi Kaydet", key="save_name", use_container_width=True):
        db_update_profile(user_id, {"display_name": new_display_name.strip()})
        st.success("İsim güncellendi.")
        st.rerun()

    st.markdown("---")

    # --- E-posta değiştir ---
    new_email = st.text_input("Yeni e-posta", key="profile_email")
    if st.button("E-postayı Değiştir", key="save_email", use_container_width=True):
        if not new_email.strip():
            st.error("Lütfen bir e-posta adresi gir.")
        else:
            try:
                supabase.auth.update_user({"email": new_email.strip()})
                st.success(
                    "İstek gönderildi. Supabase ayarına göre, yeni adresine gelen "
                    "onay linkine tıklaman gerekebilir."
                )
            except Exception as e:
                st.error(f"E-posta değiştirilemedi: {e}")

    st.markdown("---")

    # --- Şifre değiştir ---
    new_pw = st.text_input(
        "Yeni şifre (en az 6 karakter, 1 harf + 1 rakam)",
        type="password", key="profile_pw"
    )
    new_pw2 = st.text_input("Yeni şifreyi tekrar gir", type="password", key="profile_pw2")
    if st.button("Şifreyi Değiştir", key="save_pw", use_container_width=True):
        is_strong, strength_msg = password_is_strong(new_pw)
        if new_pw != new_pw2:
            st.error("Girdiğin iki şifre birbiriyle uyuşmuyor.")
        elif not is_strong:
            st.error(strength_msg)
        else:
            try:
                supabase.auth.update_user({"password": new_pw})
                st.success("Şifren güncellendi.")
            except Exception as e:
                st.error(f"Şifre değiştirilemedi: {e}")

    st.markdown("---")

    # --- Hesap verilerini sil ---
    st.caption(
        "⚠️ Bu işlem tüm sohbetlerini ve mesajlarını kalıcı olarak siler. "
        "(Not: Bu, sadece Temai'deki verilerini siler; giriş hesabının tamamen "
        "kaldırılması için ek bir adım gerekir, bunu sonra ekleyebiliriz.)"
    )
    confirm_delete = st.checkbox("Verilerimi silmek istediğimi onaylıyorum", key="confirm_delete")
    if st.button("🗑️ Hesap Verilerimi Sil", key="delete_account", use_container_width=True):
        if not confirm_delete:
            st.error("Önce yukarıdaki onay kutusunu işaretle.")
        else:
            try:
                my_chats = db_list_chats(user_id)
                for c in my_chats:
                    db_delete_chat(c["id"])
                supabase.table("profiles").delete().eq("id", user_id).execute()
                supabase.auth.sign_out()
                clear_login_cookie()
                for k in ["user", "access_token", "refresh_token", "active_chat_id", "renaming_chat_id"]:
                    st.session_state.pop(k, None)
                st.rerun()
            except Exception as e:
                st.error(f"Silme işlemi sırasında hata oluştu: {e}")

if st.sidebar.button("🚪 Çıkış Yap", use_container_width=True):
    try:
        supabase.auth.sign_out()
    except Exception:
        pass
    clear_login_cookie()
    for k in ["user", "access_token", "refresh_token", "active_chat_id", "renaming_chat_id"]:
        st.session_state.pop(k, None)
    st.rerun()

st.sidebar.markdown("---")

chats = db_list_chats(user_id)

if st.sidebar.button("➕ Yeni Sohbet Ekle", use_container_width=True):
    new_chat = db_create_chat(user_id)
    st.session_state.active_chat_id = new_chat["id"]
    st.rerun()

# Aktif sohbet geçerli değilse (silinmiş, ilk açılış vs.) uygun bir tane seç/oluştur.
if "active_chat_id" not in st.session_state or not any(c["id"] == st.session_state.active_chat_id for c in chats):
    if chats:
        st.session_state.active_chat_id = chats[0]["id"]
    else:
        new_chat = db_create_chat(user_id)
        chats = [new_chat]
        st.session_state.active_chat_id = new_chat["id"]

if "renaming_chat_id" not in st.session_state:
    st.session_state.renaming_chat_id = None

for c in chats:
    cid = c["id"]
    if st.session_state.renaming_chat_id == cid:
        new_name = st.sidebar.text_input(
            "Yeni isim", value=c["title"], key=f"rename_input_{cid}", label_visibility="collapsed"
        )
        col_ok, col_cancel = st.sidebar.columns(2)
        with col_ok:
            if st.button("✅ Kaydet", key=f"rename_save_{cid}", use_container_width=True):
                new_name = new_name.strip()
                if new_name:
                    db_rename_chat(cid, new_name)
                st.session_state.renaming_chat_id = None
                st.rerun()
        with col_cancel:
            if st.button("✖ Vazgeç", key=f"rename_cancel_{cid}", use_container_width=True):
                st.session_state.renaming_chat_id = None
                st.rerun()
    else:
        col_a, col_b, col_c = st.sidebar.columns([3, 1, 1])
        with col_a:
            label = f"🟢 {c['title']}" if cid == st.session_state.active_chat_id else c["title"]
            if st.button(label, key=f"select_{cid}", use_container_width=True):
                st.session_state.active_chat_id = cid
                st.rerun()
        with col_b:
            if st.button("✏️", key=f"ren_{cid}"):
                st.session_state.renaming_chat_id = cid
                st.rerun()
        with col_c:
            if len(chats) > 1 and st.button("🗑️", key=f"del_{cid}"):
                db_delete_chat(cid)
                if st.session_state.active_chat_id == cid:
                    st.session_state.pop("active_chat_id", None)
                st.rerun()

# ----------------- MAIN -----------------
st.title("🧠 Temai")

active_chat = next(c for c in chats if c["id"] == st.session_state.active_chat_id)
active_chat_id = active_chat["id"]

# ----------------- ARAÇ ÇUBUĞU (mod, token, belge) -----------------
with st.container():
    st.markdown('<div class="temai-toolbar">', unsafe_allow_html=True)
    tool_col1, tool_col2, tool_col3 = st.columns([2, 1.4, 2])

    with tool_col1:
        mode = st.radio(
            "Mod:",
            ["Normal", "📖 Akademik", "😁 Troll"],
            horizontal=True,
            label_visibility="collapsed"
        )

    with tool_col2:
        with st.popover("⚙️ Ayarlar"):
            max_tokens = st.slider(
                "Cevap uzunluğu (token)",
                min_value=300,
                max_value=4000,
                value=2000,
                step=100,
                help="Yüksek değer = daha uzun cevap yazabilir, ama daha maliyetli olur."
            )

    with tool_col3:
        if active_chat.get("document_name"):
            doc_col1, doc_col2 = st.columns([3, 1])
            with doc_col1:
                st.markdown(f"📄 **{active_chat['document_name']}**")
            with doc_col2:
                if st.button("🗑️", key="remove_doc"):
                    db_update_chat_fields(active_chat_id, {"document_name": None, "document_text": ""})
                    st.rerun()
        else:
            st.caption("📄 Belge eklenmedi")

    st.markdown('</div>', unsafe_allow_html=True)

# ----------------- SOHBET GEÇMİŞİ -----------------
messages = db_list_messages(active_chat_id)
had_messages_before = len(messages) > 0

for m in messages:
    role = m["role"]
    kind = m["kind"]
    content = m["content"]
    ts = format_ts(m.get("created_at", ""))
    feedback = m.get("feedback")

    display_role = "user" if role == "user" else "assistant"
    avatar = "🙂" if role == "user" else "🧠"

    with st.chat_message(display_role, avatar=avatar):
        if kind == "image":
            st.image(io.BytesIO(base64.b64decode(content)))
        else:
            st.markdown(content)
        if ts:
            st.markdown(f'<div class="temai-timestamp">{ts}</div>', unsafe_allow_html=True)

        if role == "bot" and kind == "text":
            if feedback:
                icon = "👍" if feedback == "up" else "👎"
                st.caption(f"Geri bildirimin: {icon}")
            else:
                fb_col1, fb_col2, _ = st.columns([1, 1, 10])
                with fb_col1:
                    if st.button("👍", key=f"fbup_{m['id']}"):
                        db_update_message_feedback(m["id"], "up")
                        st.rerun()
                with fb_col2:
                    if st.button("👎", key=f"fbdown_{m['id']}"):
                        db_update_message_feedback(m["id"], "down")
                        st.rerun()

# ----------------- KAMERA -----------------
if "upload_key" not in st.session_state:
    st.session_state.upload_key = 0
if "camera_open" not in st.session_state:
    st.session_state.camera_open = False

camera_file = None
cam_col, _ = st.columns([1, 5])
with cam_col:
    if not st.session_state.camera_open:
        if st.button("📷 Kamera Aç"):
            st.session_state.camera_open = True
            st.rerun()
    else:
        if st.button("✖ Kamerayı Kapat"):
            st.session_state.camera_open = False
            st.rerun()
        camera_file = st.camera_input(
            "Fotoğraf çek",
            key=f"camera_{st.session_state.upload_key}",
            label_visibility="collapsed"
        )

# ----------------- MESAJ KUTUSU + GÖMÜLÜ '+' DOSYA BUTONU -----------------
user_message = st.chat_input(
    "sohbete başlamak için bir şey yazın...",
    accept_file=True,
    file_type=["png", "jpg", "jpeg", "pdf", "docx"],
)


def system_prompt(mode, doc_text):
    if mode == "😁 Troll":
        base = "Sen Temai adlı TROLL bir asistansın. Mantıklı görünen ama yanlış cevaplar ver."
    elif mode == "📖 Akademik":
        base = "Sen Temai adlı akademik ve ciddi bir asistansın. Daha resmi ve bilgisel cevaplar ver."
    else:
        base = "Sen Temai adlı chatgpt ve openai ile hicbir alakası olmayan yardımcı bir asistansın."

    if doc_text:
        base += (
            "\n\nKullanıcı aşağıdaki belgeyi yükledi. Sorularını mümkün olduğunca "
            "bu belgeye dayanarak cevapla, belgede olmayan bir şey soruluyorsa bunu belirt.\n\n"
            f"--- BELGE İÇERİĞİ ---\n{doc_text[:12000]}\n--- BELGE SONU ---"
        )
    return base


def extract_generated_image(final_response):
    try:
        for item in getattr(final_response, "output", []) or []:
            if getattr(item, "type", None) == "image_generation_call":
                result = getattr(item, "result", None)
                if result:
                    return result
    except Exception:
        pass
    return None


def ask_temai(user_content, instructions, previous_response_id, max_tokens, placeholder):
    full_text = ""
    new_response_id = None
    generated_image_b64 = None
    tools = [{"type": "image_generation"}]
    try:
        with client.responses.stream(
            model="gpt-4.1-mini",
            input=[{"role": "user", "content": user_content}],
            instructions=instructions,
            previous_response_id=previous_response_id,
            max_output_tokens=max_tokens,
            tools=tools,
        ) as stream:
            for event in stream:
                if event.type == "response.output_text.delta":
                    full_text += event.delta
                    placeholder.markdown(full_text + "▌")
            final_response = stream.get_final_response()
            new_response_id = final_response.id
            if not full_text:
                full_text = final_response.output_text
            generated_image_b64 = extract_generated_image(final_response)
    except AttributeError:
        response = client.responses.create(
            model="gpt-4.1-mini",
            input=[{"role": "user", "content": user_content}],
            instructions=instructions,
            previous_response_id=previous_response_id,
            max_output_tokens=max_tokens,
            tools=tools,
        )
        full_text = response.output_text
        new_response_id = response.id
        generated_image_b64 = extract_generated_image(response)
    except TypeError:
        response = client.responses.create(
            model="gpt-4.1-mini",
            input=[{"role": "user", "content": user_content}],
            instructions=instructions,
            previous_response_id=previous_response_id,
            max_output_tokens=max_tokens,
        )
        full_text = response.output_text
        new_response_id = response.id

    placeholder.markdown(full_text if full_text else "")
    return full_text, new_response_id, generated_image_b64


def auto_title_chat(chat_id, current_title, first_user_message):
    if current_title != DEFAULT_TITLE:
        return
    try:
        title_response = client.responses.create(
            model="gpt-4.1-mini",
            input=[{"role": "user", "content": [{"type": "input_text", "text": first_user_message}]}],
            instructions=(
                "Kullanıcının ilk mesajına bakarak bu sohbet için 2-4 kelimelik, "
                "kısa ve açıklayıcı bir Türkçe başlık üret. Sadece başlığı yaz, "
                "tırnak işareti, noktalama veya başka hiçbir şey ekleme."
            ),
            max_output_tokens=20,
        )
        new_title = title_response.output_text.strip().strip('"').strip("'")
        if new_title:
            db_rename_chat(chat_id, new_title)
    except Exception:
        pass


if (user_message or camera_file is not None):
    user_text = (user_message.text.strip() if user_message else "") or ""
    attached_from_input = user_message.files[0] if (user_message and user_message.files) else None
    attached_file = camera_file if camera_file is not None else attached_from_input

    image_base64 = None
    image_mime = "image/png"
    doc_just_uploaded = None

    if attached_file is not None:
        file_name = getattr(attached_file, "name", "kamera.png").lower()
        is_image = camera_file is not None or file_name.endswith((".png", ".jpg", ".jpeg"))

        if is_image:
            image = Image.open(attached_file)
            buf = io.BytesIO()
            image.save(buf, format="PNG")
            image_base64 = base64.b64encode(buf.getvalue()).decode()
        else:
            try:
                if file_name.endswith(".pdf"):
                    extracted_text = extract_pdf_text(attached_file)
                else:
                    extracted_text = extract_docx_text(attached_file)

                if extracted_text.strip():
                    db_update_chat_fields(active_chat_id, {
                        "document_name": attached_file.name,
                        "document_text": extracted_text,
                    })
                    doc_just_uploaded = attached_file.name
                else:
                    st.warning("Belgeden metin çıkarılamadı (taranmış/görsel bir PDF olabilir).")
            except Exception as e:
                st.error(
                    f"Belge okunamadı: {e}\n\n"
                    "Gerekli kütüphaneler yüklü mü kontrol et: pip install pypdf python-docx"
                )

    if not user_text:
        if image_base64:
            user_text = "Bu resmi incele ve açıkla."
        elif doc_just_uploaded:
            user_text = f"'{doc_just_uploaded}' belgesini yükledim, içeriğini özetler misin?"

    if user_text:
        if image_base64:
            db_add_message(active_chat_id, "user", "image", image_base64)
            with st.chat_message("user", avatar="🙂"):
                st.image(io.BytesIO(base64.b64decode(image_base64)))
        db_add_message(active_chat_id, "user", "text", user_text)
        with st.chat_message("user", avatar="🙂"):
            st.markdown(user_text)

        with st.chat_message("assistant", avatar="🧠"):
            placeholder = st.empty()
            placeholder.markdown("✍️ Temai yazıyor...")

            reply = ""
            generated_image_b64 = None
            try:
                content = [{"type": "input_text", "text": user_text}]
                if image_base64:
                    content.append({
                        "type": "input_image",
                        "image_url": f"data:{image_mime};base64,{image_base64}"
                    })

                # En güncel belge metnini veritabanından tazele (az önce yüklenmiş olabilir).
                fresh_chat = supabase.table("chats").select("*").eq("id", active_chat_id).execute().data[0]

                reply, resp_id, generated_image_b64 = ask_temai(
                    user_content=content,
                    instructions=system_prompt(mode, fresh_chat.get("document_text", "")),
                    previous_response_id=fresh_chat.get("last_response_id"),
                    max_tokens=max_tokens,
                    placeholder=placeholder,
                )
                if resp_id:
                    db_update_chat_fields(active_chat_id, {"last_response_id": resp_id})

            except Exception as e:
                reply = f"❌ Hata: {e}"
                placeholder.markdown(reply)

            if generated_image_b64:
                st.image(io.BytesIO(base64.b64decode(generated_image_b64)))

        if reply:
            db_add_message(active_chat_id, "bot", "text", reply)
        if generated_image_b64:
            db_add_message(active_chat_id, "bot", "image", generated_image_b64)

        if not had_messages_before:
            auto_title_chat(active_chat_id, active_chat["title"], user_text)

        st.session_state.upload_key += 1
        st.session_state.camera_open = False
        st.rerun()
