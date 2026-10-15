from pathlib import Path
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "frontend" / "app.py")


def test_ui_custom_interest_and_feedback():
    at = AppTest.from_file(APP, default_timeout=90).run()
    assert not at.exception
    demo = next(c for c in at.sidebar.checkbox if "Демо" in c.label)
    demo.set_value(True).run()
    ti = next(t for t in at.sidebar.text_input if "Свой интерес" in t.label)
    ti.set_value("Exchange, сетевая безопасность").run()      # новые интересы появляются и выбираются
    ms = next(m for m in at.sidebar.multiselect if m.label == "Интересы")
    assert "Exchange" in ms.value and "сетевая безопасность" in ms.value
    assert not at.exception
    up = next(b for b in at.button if b.label.startswith("👍"))
    up.click().run()                                            # 👍 запоминается
    assert at.session_state["liked"] and not at.exception
