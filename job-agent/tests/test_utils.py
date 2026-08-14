from src.utils import clean_html_to_text


def test_clean_html_to_text_returns_human_readable_text() -> None:
    html = """
    <p><strong>THE POSITION<br></strong>Our roster has an opening.</p>
    <ul><li>Build ML systems</li><li>Partner with analysts</li></ul>
    """

    text = clean_html_to_text(html)

    assert "<p>" not in text
    assert "<li>" not in text
    assert "THE POSITION" in text
    assert "Build ML systems" in text
    assert "Partner with analysts" in text
