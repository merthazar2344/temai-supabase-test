import streamlit as st
from openai import OpenAI
from PIL import Image
import base64
import io
import json
import os
from datetime import datetime

# ================== OPENAI ==================
api_key = None
if "OPENAI_API_KEY" in st.secrets:
    api_key = st.secrets["OPENAI_API_KEY"]
else:
    api_key = "BURAYA_KENDI_API_KEYINI_YAZ"

client = OpenAI(api_key=api_key)
# ============================================

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


# ================== KALICI KAYIT (JSON dosyası) ==================
CHATS_FILE = "temai_chats.json"

def default_chat():
    return {"messages": [], "document_name": None, "document_text": "", "last_response_id": None}

def load_chats():
    if os.path.exists(CHATS_FILE):
        try:
            with open(CHATS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if data:
                    return data
        except Exception:
            pass
    return {"Sohbet 1": default_chat()}

def save_chats():
    try:
        with open(CHATS_FILE, "w", encoding="utf-8") as f:
            json.dump(st.session_state.chats, f, ensure_ascii=False)
    except Exception as e:
        st.warning(f"Sohbetler kaydedilemedi: {e}")


st.set_page_config(page_title="Temai", page_icon="🧠", layout="wide")

# ----------------- CSS (genel görünüm cilası) -----------------
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

# ----------------- SIDEBAR: SADECE SOHBET LİSTESİ -----------------
st.sidebar.title("💬 Sohbetler")

if "chats" not in st.session_state:
    st.session_state.chats = load_chats()
    st.session_state.active_chat = list(st.session_state.chats.keys())[0]

if st.sidebar.button("➕ Yeni Sohbet Ekle", use_container_width=True):
    n = len(st.session_state.chats) + 1
    name = f"Sohbet {n}"
    while name in st.session_state.chats:  # aynı isimde bir sohbet zaten varsa üzerine yazma
        n += 1
        name = f"Sohbet {n}"
    st.session_state.chats[name] = default_chat()
    st.session_state.active_chat = name
    save_chats()
    st.rerun()

st.sidebar.markdown("---")

if "renaming_chat" not in st.session_state:
    st.session_state.renaming_chat = None

for chat in list(st.session_state.chats.keys()):
    if st.session_state.renaming_chat == chat:
        new_name = st.sidebar.text_input(
            "Yeni isim", value=chat, key=f"rename_input_{chat}", label_visibility="collapsed"
        )
        col_ok, col_cancel = st.sidebar.columns(2)
        with col_ok:
            if st.button("✅ Kaydet", key=f"rename_save_{chat}", use_container_width=True):
                new_name = new_name.strip()
                if new_name and (new_name == chat or new_name not in st.session_state.chats):
                    reordered = {}
                    for k, v in st.session_state.chats.items():
                        reordered[new_name if k == chat else k] = v
                    st.session_state.chats = reordered
                    if st.session_state.active_chat == chat:
                        st.session_state.active_chat = new_name
                else:
                    st.sidebar.warning("Bu isim boş olamaz veya zaten kullanılıyor.")
                st.session_state.renaming_chat = None
                save_chats()
                st.rerun()
        with col_cancel:
            if st.button("✖ Vazgeç", key=f"rename_cancel_{chat}", use_container_width=True):
                st.session_state.renaming_chat = None
                st.rerun()
    else:
        col_a, col_b, col_c = st.sidebar.columns([3, 1, 1])
        with col_a:
            label = f"🟢 {chat}" if chat == st.session_state.active_chat else chat
            if st.button(label, key=f"select_{chat}", use_container_width=True):
                st.session_state.active_chat = chat
                st.rerun()
        with col_b:
            if st.button("✏️", key=f"ren_{chat}"):
                st.session_state.renaming_chat = chat
                st.rerun()
        with col_c:
            if len(st.session_state.chats) > 1 and st.button("🗑️", key=f"del_{chat}"):
                del st.session_state.chats[chat]
                if st.session_state.active_chat == chat:
                    st.session_state.active_chat = list(st.session_state.chats.keys())[0]
                save_chats()
                st.rerun()

# ----------------- MAIN -----------------
st.title("🧠 Temai")

active_data = st.session_state.chats[st.session_state.active_chat]

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
        if active_data.get("document_name"):
            doc_col1, doc_col2 = st.columns([3, 1])
            with doc_col1:
                st.markdown(f"📄 **{active_data['document_name']}**")
            with doc_col2:
                if st.button("🗑️", key="remove_doc"):
                    active_data["document_name"] = None
                    active_data["document_text"] = ""
                    save_chats()
                    st.rerun()
        else:
            st.caption("📄 Belge eklenmedi")

    st.markdown('</div>', unsafe_allow_html=True)

# ----------------- SOHBET GEÇMİŞİ -----------------
messages = active_data["messages"]

for idx, msg in enumerate(messages):
    role = msg[0]
    kind = msg[1]
    content = msg[2]
    ts = msg[3] if len(msg) > 3 else ""
    feedback = msg[4] if len(msg) > 4 else None

    display_role = "user" if role == "user" else "assistant"
    avatar = "🙂" if role == "user" else "🧠"

    with st.chat_message(display_role, avatar=avatar):
        if kind == "image":
            st.image(io.BytesIO(base64.b64decode(content)))
        else:
            st.markdown(content)
        if ts:
            st.markdown(f'<div class="temai-timestamp">{ts}</div>', unsafe_allow_html=True)

        # Sadece bot'un yazı cevaplarına geri bildirim butonu koyuyoruz.
        if role == "bot" and kind == "text":
            if feedback:
                icon = "👍" if feedback == "up" else "👎"
                st.caption(f"Geri bildirimin: {icon}")
            else:
                fb_col1, fb_col2, _ = st.columns([1, 1, 10])
                with fb_col1:
                    if st.button("👍", key=f"fbup_{st.session_state.active_chat}_{idx}"):
                        while len(messages[idx]) < 5:
                            messages[idx].append(None)
                        messages[idx][4] = "up"
                        save_chats()
                        st.rerun()
                with fb_col2:
                    if st.button("👎", key=f"fbdown_{st.session_state.active_chat}_{idx}"):
                        while len(messages[idx]) < 5:
                            messages[idx].append(None)
                        messages[idx][4] = "down"
                        save_chats()
                        st.rerun()

# ----------------- KAMERA (ayrı, çünkü canlı çekim chat kutusunun içine gömülemiyor) -----------------
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
# accept_file=True, chat_input'un içine bu sohbetteki gibi bir ataç/artı ikonu ekler.
# (Bu özellik Streamlit'in yeni sürümlerinde var; eski sürümde hata verirse haber ver.)
user_message = st.chat_input(
    "sohbete başlamak için bir şey yazın...",
    accept_file=True,
    file_type=["png", "jpg", "jpeg", "pdf", "docx"],
)

def system_prompt(mode):
    if mode == "😁 Troll":
        base = "Sen Temai adlı TROLL bir asistansın. Mantıklı görünen ama yanlış cevaplar ver."
    elif mode == "📖 Akademik":
        base = "Sen Temai adlı akademik ve ciddi bir asistansın. Daha resmi ve bilgisel cevaplar ver."
    else:
        base = "Sen Temai adlı chatgpt ve openai ile hicbir alakası olmayan yardımcı bir asistansın."

    doc_text = active_data.get("document_text", "")
    if doc_text:
        base += (
            "\n\nKullanıcı aşağıdaki belgeyi yükledi. Sorularını mümkün olduğunca "
            "bu belgeye dayanarak cevapla, belgede olmayan bir şey soruluyorsa bunu belirt.\n\n"
            f"--- BELGE İÇERİĞİ ---\n{doc_text[:12000]}\n--- BELGE SONU ---"
        )
    return base


def auto_title_chat(chat_key, first_user_message):
    """İlk mesaja bakıp sohbete kısa, akıllı bir başlık verir (hâlâ varsayılan isimdeyse)."""
    if not chat_key.startswith("Sohbet "):
        return  # Kullanıcı zaten kendi ismini vermiş, dokunma.
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
        if new_title and new_title not in st.session_state.chats:
            reordered = {}
            for k, v in st.session_state.chats.items():
                reordered[new_title if k == chat_key else k] = v
            st.session_state.chats = reordered
            if st.session_state.active_chat == chat_key:
                st.session_state.active_chat = new_title
    except Exception:
        pass  # Başlık üretilemezse sorun değil, varsayılan isim kalır.


def extract_generated_image(final_response):
    """Responses API'nin image_generation aracı ile ürettiği görseli (varsa) base64 olarak döndürür."""
    try:
        for item in getattr(final_response, "output", []) or []:
            item_type = getattr(item, "type", None)
            if item_type == "image_generation_call":
                result = getattr(item, "result", None)
                if result:
                    return result  # zaten base64 string
    except Exception:
        pass
    return None


def ask_temai(user_content, instructions, previous_response_id, max_tokens, placeholder):
    full_text = ""
    new_response_id = None
    generated_image_b64 = None
    # image_generation: model, kullanıcı görsel isterse kendisi resim üretebilsin diye.
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
        # tools/image_generation bu kütüphane sürümünde desteklenmiyor olabilir; onsuz dene.
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


# chat_input hem yazı hem dosya taşıyabilir; kamera fotoğrafı ayrı bir widget'tan geliyor.
if user_message or camera_file is not None:
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
                    active_data["document_name"] = attached_file.name
                    active_data["document_text"] = extracted_text
                    doc_just_uploaded = attached_file.name
                else:
                    st.warning("Belgeden metin çıkarılamadı (taranmış/görsel bir PDF olabilir).")
            except Exception as e:
                st.error(
                    f"Belge okunamadı: {e}\n\n"
                    "Gerekli kütüphaneler yüklü mü kontrol et: pip install pypdf python-docx"
                )

    # Kullanıcı sadece dosya gönderip yazı yazmadıysa, mantıklı bir varsayılan mesaj kullan.
    if not user_text:
        if image_base64:
            user_text = "Bu resmi incele ve açıkla."
        elif doc_just_uploaded:
            user_text = f"'{doc_just_uploaded}' belgesini yükledim, içeriğini özetler misin?"

    if user_text:
        now_str = datetime.now().strftime("%H:%M")

        if image_base64:
            messages.append(["user", "image", image_base64, now_str])
            with st.chat_message("user", avatar="🙂"):
                st.image(io.BytesIO(base64.b64decode(image_base64)))
        messages.append(["user", "text", user_text, now_str])
        with st.chat_message("user", avatar="🙂"):
            st.markdown(user_text)
        save_chats()

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

                reply, resp_id, generated_image_b64 = ask_temai(
                    user_content=content,
                    instructions=system_prompt(mode),
                    previous_response_id=active_data.get("last_response_id"),
                    max_tokens=max_tokens,
                    placeholder=placeholder,
                )
                if resp_id:
                    active_data["last_response_id"] = resp_id

            except Exception as e:
                reply = f"❌ Hata: {e}"
                placeholder.markdown(reply)

            if generated_image_b64:
                st.image(io.BytesIO(base64.b64decode(generated_image_b64)))

        reply_ts = datetime.now().strftime("%H:%M")
        if reply:
            messages.append(["bot", "text", reply, reply_ts])
        if generated_image_b64:
            messages.append(["bot", "image", generated_image_b64, reply_ts])
        save_chats()

        # İlk kullanıcı-bot alışverişinden sonra, hâlâ varsayılan isimdeyse başlığı otomatik koy.
        if st.session_state.active_chat.startswith("Sohbet ") and len(messages) <= 3:
            auto_title_chat(st.session_state.active_chat, user_text)
            save_chats()

        st.session_state.upload_key += 1
        st.session_state.camera_open = False
        st.rerun()
