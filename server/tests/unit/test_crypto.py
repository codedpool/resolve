from app.core.crypto import (
    KeyDestroyed,
    TamperError,
    decode_master_key,
    encode_master_key,
    generate_key,
    open_text,
    seal_text,
    unwrap_data_key,
    wrap_data_key,
)
from app.core.objects import EncryptedObjectStore


def test_round_trip_and_distinct_case_keys():
    master = generate_key()
    first = generate_key()
    second = generate_key()
    assert first != second
    wrapped_first = wrap_data_key(first, master)
    wrapped_second = wrap_data_key(second, master)
    assert unwrap_data_key(wrapped_first, master) == first
    left = seal_text("around 1200", first)
    right = seal_text("around 1200", second)
    assert left != right
    assert open_text(left, first) == "around 1200"
    assert open_text(right, second) == "around 1200"


def test_tamper_is_detected():
    key = generate_key()
    blob = bytearray(seal_text("secret", key))
    blob[-1] ^= 0x01
    try:
        open_text(bytes(blob), key)
    except TamperError:
        return
    raise AssertionError("tampered ciphertext was accepted")


def test_missing_wrapper_is_destroyed():
    master = generate_key()
    try:
        unwrap_data_key(None, master)
    except KeyDestroyed:
        return
    raise AssertionError("missing key was unwrapped")


def test_encrypted_column_round_trip():
    from sqlalchemy import String, create_engine
    from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

    from app.core.crypto import EncryptedText, data_key_context

    class Base(DeclarativeBase):
        pass

    class Note(Base):
        __tablename__ = "notes"
        id: Mapped[str] = mapped_column(String, primary_key=True)
        body: Mapped[str] = mapped_column(EncryptedText)

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    key = generate_key()
    token = data_key_context.set(key)
    try:
        with Session(engine) as session:
            session.add(Note(id="1", body="around 1200"))
            session.commit()
        with Session(engine) as session:
            assert session.get(Note, "1").body == "around 1200"
    finally:
        data_key_context.reset(token)
    raw = generate_key()
    assert decode_master_key(encode_master_key(raw)) == raw


def test_object_store_round_trip_and_wipe(tmp_path):
    store = EncryptedObjectStore(tmp_path)
    key = generate_key()
    store.put("case-1", "note.bin", b"hello", key)
    assert store.get("case-1", "note.bin", key) == b"hello"
    store.wipe("case-1")
    missing = False
    try:
        store.get("case-1", "note.bin", key)
    except Exception:
        missing = True
    assert missing
